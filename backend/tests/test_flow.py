"""End-to-end checks of the daily workflow against a small made-up street grid."""

import csv
import io

from .conftest import grid_point, zip_for

HOUSES = [
    11,
    12,
    13,
    14,
    21,
    22,
    23,
    24,
    31,
    33,
    41,
    43,
    15,
    16,
    17,
    18,
    25,
    27,
    36,
    38,
    46,
    48,
    56,
    58,
    61,
    62,
    71,
    73,
    82,
    84,
    66,
    67,
    76,
    78,
    86,
    88,
]


def paste_text(houses=HOUSES, unit=""):
    return "".join(f"{n} Grid St\t{unit}\tGridville\tOH\t{zip_for(n)}\n" for n in houses)


def make_driver(client, name, kind="staff", at=(0, 0), **extra):
    lat, lon = grid_point(*at)
    body = {
        "name": name,
        "kind": kind,
        "start_label": "base",
        "start_lat": lat,
        "start_lon": lon,
        "end_label": "base",
        "end_lat": lat,
        "end_lon": lon,
        **extra,
    }
    r = client.post("/api/drivers", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def confirm_all_new(client, plan):
    for s in [s for s in plan["stops"] if s["match_state"] == "new"]:
        cands = client.get(f"/api/stops/{s['id']}/candidates").json()["candidates"]
        assert cands and cands[0]["on_map"] is True
        r = client.post(f"/api/stops/{s['id']}/confirm-location", json={"lat": cands[0]["lat"], "lon": cands[0]["lon"]})
        assert r.status_code == 200, r.text
        plan = r.json()
    return plan


def day(client, date, drivers, houses=HOUSES):
    plan = client.get(f"/api/plans/by-day/{date}").json()
    plan = client.put(f"/api/plans/{plan['id']}", json={"working_driver_ids": [d["id"] for d in drivers]}).json()
    plan = client.post(f"/api/plans/{plan['id']}/paste", json={"text": paste_text(houses)}).json()
    return confirm_all_new(client, plan)


def compute(client, plan):
    r = client.post(f"/api/plans/{plan['id']}/compute")
    assert r.status_code == 200, r.text
    return r.json()


def by_driver(plan):
    out = {}
    for s in plan["stops"]:
        out.setdefault(s["driver_id"], []).append(s)
    return out


def test_new_rows_need_confirming_then_match_next_day(client):
    staff = make_driver(client, "Alex")
    plan = client.get("/api/plans/by-day/2026-01-05").json()
    plan = client.put(f"/api/plans/{plan['id']}", json={"working_driver_ids": [staff["id"]]}).json()
    plan = client.post(f"/api/plans/{plan['id']}/paste", json={"text": paste_text()}).json()
    assert plan["layout"] == ["street", "unit", "city", "state", "zip"]
    assert {s["match_state"] for s in plan["stops"]} == {"new"}
    assert client.post(f"/api/plans/{plan['id']}/compute").status_code == 422  # rows still need attention

    plan = confirm_all_new(client, plan)
    assert {s["match_state"] for s in plan["stops"]} == {"matched"}
    assert all(s["is_new_address"] for s in plan["stops"])

    plan2 = client.get("/api/plans/by-day/2026-01-06").json()
    plan2 = client.post(f"/api/plans/{plan2['id']}/paste", json={"text": paste_text()}).json()
    assert {s["match_state"] for s in plan2["stops"]} == {"matched"}
    assert not any(s["is_new_address"] for s in plan2["stops"])


def test_possible_match_and_alias(client):
    staff = make_driver(client, "Alex")
    day(client, "2026-01-05", [staff], houses=[11, 12])
    plan = client.get("/api/plans/by-day/2026-01-06").json()
    plan = client.post(
        f"/api/plans/{plan['id']}/paste",
        json={"text": "11 Grid Street\t\tGridville\tOH\t43001\n12 Gridd St\t\tGridville\tOH\t43001\n"},
    ).json()
    states = [s["match_state"] for s in plan["stops"]]
    assert states == ["matched", "possible"]  # "Street" tidies to "St"; "Gridd" is a near miss
    assert [c["street"] for c in plan["stops"][1]["candidates"]] == ["12 Grid St"]
    plan = client.post(f"/api/stops/{plan['stops'][1]['id']}/confirm-match", json={}).json()
    assert plan["stops"][1]["match_state"] == "matched"
    # the spelling is remembered
    plan3 = client.get("/api/plans/by-day/2026-01-07").json()
    plan3 = client.post(
        f"/api/plans/{plan3['id']}/paste", json={"text": "12 Gridd St\t\tGridville\tOH\t43001\n"}
    ).json()
    assert plan3["stops"][0]["match_state"] == "matched"


def test_units_are_separate_addresses_sharing_a_building(client):
    staff = make_driver(client, "Alex")
    plan = client.get("/api/plans/by-day/2026-01-05").json()
    plan = client.put(f"/api/plans/{plan['id']}", json={"working_driver_ids": [staff["id"]]}).json()
    text = "22 Grid St\tApt 1\tGridville\tOH\t43001\n22 Grid St\tApt 2\tGridville\tOH\t43001\n22 Grid St\t#1\tGridville\tOH\t43001\n"
    plan = client.post(f"/api/plans/{plan['id']}/paste", json={"text": text}).json()
    assert plan["stops"][2]["duplicate_of_seq"] == 1  # "#1" is the same unit as "Apt 1"
    first = plan["stops"][0]
    cands = client.get(f"/api/stops/{first['id']}/candidates").json()["candidates"]
    plan = client.post(f"/api/stops/{first['id']}/confirm-location", json=cands[0]).json()
    assert [s["match_state"] for s in plan["stops"]] == ["matched", "new", "matched"]
    second = plan["stops"][1]
    cands = client.get(f"/api/stops/{second['id']}/candidates").json()["candidates"]
    assert cands[0]["source"] == "known"  # the building's confirmed pin is offered first
    plan = client.post(f"/api/stops/{second['id']}/confirm-location", json=cands[0]).json()
    assert len(client.get("/api/addresses").json()) == 2
    plan = compute(client, plan)
    assert sorted(s["stop_number"] for s in plan["stops"]) == [1, 2, 3]


def test_location_outside_map_is_rejected(client):
    make_driver(client, "Alex")
    plan = client.get("/api/plans/by-day/2026-01-05").json()
    plan = client.post(f"/api/plans/{plan['id']}/paste", json={"text": "5000 Far Rd\t\tElsewhere\tOH\t43001\n"}).json()
    sid = plan["stops"][0]["id"]
    cands = client.get(f"/api/stops/{sid}/candidates").json()["candidates"]
    assert cands[0]["on_map"] is False
    r = client.post(f"/api/stops/{sid}/confirm-location", json={"lat": cands[0]["lat"], "lon": cands[0]["lon"]})
    assert r.status_code == 400


def test_volunteers_filled_first_within_limits_then_staff(client):
    alex = make_driver(client, "Alex", at=(0, 0))
    blair = make_driver(client, "Blair", at=(9, 9))
    vera = make_driver(client, "Vera", "volunteer", at=(2, 2), max_stops=5, zip_codes=["43001"])
    vic = make_driver(client, "Vic", "volunteer", at=(7, 7), max_route_minutes=12)
    plan = compute(client, day(client, "2026-01-05", [alex, blair, vera, vic]))

    assert all(s["driver_id"] for s in plan["stops"])
    assert not plan["result"]["unassigned"]
    groups = by_driver(plan)
    assert len(groups[vera["id"]]) == 5  # used to the fullest
    assert {s["zip"] for s in groups[vera["id"]]} == {"43001"}
    assert all(s["label"] == "added" for s in groups[vera["id"]])
    routes = {r["driver_id"]: r for r in plan["result"]["routes"]}
    assert 0 < routes[vic["id"]]["time_s"] <= 12 * 60
    assert routes[vic["id"]]["stops"] >= 1
    assert not routes[vera["id"]]["over_limit"] and not routes[vic["id"]]["over_limit"]
    staff_stops = len(groups.get(alex["id"], [])) + len(groups.get(blair["id"], []))
    assert staff_stops == len(HOUSES) - 5 - routes[vic["id"]]["stops"]
    assert all(s["label"] == "staff" for s in groups.get(alex["id"], []) + groups.get(blair["id"], []))
    for r in plan["result"]["routes"]:
        numbers = sorted(s["stop_number"] for s in groups.get(r["driver_id"], []))
        assert numbers == list(range(1, r["stops"] + 1))
        assert not r["stops"] or r["shapes"]


def test_make_usual_then_pinned_and_lock(client):
    alex = make_driver(client, "Alex", at=(0, 0))
    vera = make_driver(client, "Vera", "volunteer", at=(2, 2), max_stops=5)
    plan = compute(client, day(client, "2026-01-05", [alex, vera]))
    extras = [s for s in plan["stops"] if s["driver_id"] == vera["id"]]
    assert len(extras) == 5
    plan = client.post(f"/api/stops/{extras[0]['id']}/make-usual").json()
    assert next(s for s in plan["stops"] if s["id"] == extras[0]["id"])["label"] == "usual"
    plan = client.post(f"/api/plans/{plan['id']}/make-all-usual", json={"driver_id": vera["id"]}).json()
    usual_keys = {(s["street"], s["zip"]) for s in plan["stops"] if s["label"] == "usual"}
    assert len(usual_keys) == 5
    assert next(d for d in client.get("/api/drivers").json() if d["id"] == vera["id"])["usual_stops"] == 5

    # Next day only three of her usual stops are on the list: she keeps those and is filled back up to five.
    todays = [int(k[0].split()[0]) for k in list(usual_keys)[:3]] + [86, 88, 76, 78, 66, 67]
    plan2 = compute(client, day(client, "2026-01-06", [alex, vera], houses=todays))
    hers = [s for s in plan2["stops"] if s["driver_id"] == vera["id"]]
    assert len(hers) == 5
    assert sum(1 for s in hers if s["label"] == "usual") == 3
    assert sum(1 for s in hers if s["label"] == "added") == 2

    # Locked: exactly her usual stops, nothing added, nothing can be moved on or off.
    body = {**vera, "locked": True}
    assert client.put(f"/api/drivers/{vera['id']}", json=body).status_code == 200
    plan2 = compute(client, plan2)
    hers = [s for s in plan2["stops"] if s["driver_id"] == vera["id"]]
    assert len(hers) == 3 and all(s["label"] == "usual" for s in hers)
    other = next(s for s in plan2["stops"] if s["driver_id"] == alex["id"])
    assert client.post(f"/api/stops/{other['id']}/move", json={"driver_id": vera["id"]}).status_code == 400
    assert client.post(f"/api/stops/{hers[0]['id']}/move", json={"driver_id": alex["id"]}).status_code == 400
    assert (
        client.put(
            f"/api/addresses/{hers[0]['address_id']}", json={"set_usual": True, "usual_driver_id": None}
        ).status_code
        == 400
    )


def test_volunteer_off_is_covered_temporarily(client):
    alex = make_driver(client, "Alex", at=(0, 0))
    vera = make_driver(client, "Vera", "volunteer", at=(2, 2), max_stops=4)
    plan = compute(client, day(client, "2026-01-05", [alex, vera]))
    plan = client.post(f"/api/plans/{plan['id']}/make-all-usual", json={"driver_id": vera["id"]}).json()
    usual_ids = {s["address_id"] for s in plan["stops"] if s["label"] == "usual"}
    assert len(usual_ids) == 4

    plan2 = compute(client, day(client, "2026-01-06", [alex]))  # Vera is off
    covered = [s for s in plan2["stops"] if s["address_id"] in usual_ids]
    assert all(
        s["driver_id"] == alex["id"] and s["label"] == "covering" and s["covering_for_id"] == vera["id"]
        for s in covered
    )
    # still hers afterwards
    assert len(client.get(f"/api/addresses?driver_id={vera['id']}").json()) == 4


def test_usual_stops_over_the_limit_overflow_to_staff(client):
    alex = make_driver(client, "Alex", at=(0, 0))
    vera = make_driver(client, "Vera", "volunteer", at=(2, 2), max_stops=6)
    plan = compute(client, day(client, "2026-01-05", [alex, vera]))
    client.post(f"/api/plans/{plan['id']}/make-all-usual", json={"driver_id": vera["id"]})
    client.put(f"/api/drivers/{vera['id']}", json={**vera, "max_stops": 4})
    plan = compute(client, plan)
    hers = [s for s in plan["stops"] if s["driver_id"] == vera["id"]]
    assert len(hers) == 4 and all(s["label"] == "usual" for s in hers)
    moved = [s for s in plan["stops"] if s["label"] == "overflow"]
    assert len(moved) == 2 and all(s["driver_id"] == alex["id"] and s["covering_for_id"] == vera["id"] for s in moved)


def test_manual_move_and_csv(client):
    alex = make_driver(client, "Alex", at=(0, 0))
    blair = make_driver(client, "Blair", at=(9, 9))
    plan = day(client, "2026-01-05", [alex, blair])
    plan = client.put(f"/api/plans/{plan['id']}", json={"objective": "distance"}).json()
    plan = compute(client, plan)
    assert plan["result"]["objective"] == "distance"
    assert all(r["order_mode"] == "optimized" for r in plan["result"]["routes"])

    counts = {r["driver_id"]: r["stops"] for r in plan["result"]["routes"]}
    assert max(counts.values()) <= 22 and min(counts.values()) >= 14  # shared roughly evenly

    target = next(s for s in plan["stops"] if s["driver_id"] == blair["id"])
    plan = client.post(f"/api/stops/{target['id']}/move", json={"driver_id": alex["id"]}).json()
    moved = next(s for s in plan["stops"] if s["id"] == target["id"])
    assert moved["driver_id"] == alex["id"] and moved["label"] == "manual"

    rows = list(csv.reader(io.StringIO(client.get(f"/api/plans/{plan['id']}/export.csv").text)))
    assert rows[0] == [
        "List Order",
        "Street",
        "Unit",
        "City",
        "State",
        "Zip",
        "Driver",
        "Stop Number",
        "Estimated Arrival",
        "Notes",
    ]
    assert [r[1] for r in rows[1:]] == [f"{n} Grid St" for n in HOUSES]  # list order
    assert [int(r[0]) for r in rows[1:]] == list(range(1, len(HOUSES) + 1))  # numbered across the whole paste
    assert all(r[6] in ("Alex", "Blair") and int(r[7]) >= 1 and len(r[8]) == 5 for r in rows[1:])


def test_no_staff_working_leaves_reasons(client):
    vera = make_driver(client, "Vera", "volunteer", at=(2, 2), max_stops=4)
    plan = compute(client, day(client, "2026-01-05", [vera]))
    assert sum(1 for s in plan["stops"] if s["driver_id"] == vera["id"]) == 4
    assert len(plan["result"]["unassigned"]) == len(HOUSES) - 4
    assert "no staff driver is working" in plan["result"]["unassigned"][0]["reason"]


def test_avoid_highways_changes_travel(client, router):
    a, b = grid_point(0, 0), grid_point(0, 9)  # both on the motorway row
    fast, _ = router.matrix([a, b], avoid_highways=False, shortest=False)
    slow, _ = router.matrix([a, b], avoid_highways=True, shortest=False)
    assert slow[0][1] > fast[0][1]


def test_layout_correction_is_remembered(client):
    make_driver(client, "Alex")
    plan = client.get("/api/plans/by-day/2026-01-05").json()
    plan = client.post(f"/api/plans/{plan['id']}/paste", json={"text": paste_text([11, 12])}).json()
    wrong = ["street", "extra", "city", "state", "zip"]
    plan = client.post(f"/api/plans/{plan['id']}/layout", json={"layout": wrong}).json()
    assert plan["layout"] == wrong
    plan2 = client.get("/api/plans/by-day/2026-01-06").json()
    plan2 = client.post(f"/api/plans/{plan2['id']}/paste", json={"text": paste_text([13], unit="Apt 9")}).json()
    assert plan2["layout"] == wrong and plan2["stops"][0]["unit"] == "" and plan2["stops"][0]["extras"] == ["Apt 9"]


def test_staff_sharing_can_be_turned_off(client):
    alex = make_driver(client, "Alex", at=(0, 0))
    blair = make_driver(client, "Blair", at=(9, 9))
    plan = day(client, "2026-01-05", [alex, blair])
    shared = compute(client, plan)["result"]["totals"]["time_s"]
    assert client.put("/api/settings", json={"staff_balance": "off"}).json()["staff_balance"] == "off"
    free = compute(client, plan)["result"]["totals"]["time_s"]
    assert free <= shared  # without sharing only the total matters


def test_locking_undoes_earlier_hand_moves(client):
    """A lock turned on after stops were moved by hand still means exactly the usual stops."""
    alex = make_driver(client, "Alex", at=(0, 0))
    vera = make_driver(client, "Vera", "volunteer", at=(2, 2), max_stops=5)
    plan = compute(client, day(client, "2026-01-05", [alex, vera]))
    plan = client.post(f"/api/plans/{plan['id']}/make-all-usual", json={"driver_id": vera["id"]}).json()
    usual = [s for s in plan["stops"] if s["driver_id"] == vera["id"]]
    assert len(usual) == 5

    # While she is unlocked: one of her usual stops is moved to Alex, and one of his is moved onto her.
    away, extra = usual[0], next(s for s in plan["stops"] if s["driver_id"] == alex["id"])
    assert client.post(f"/api/stops/{away['id']}/move", json={"driver_id": alex["id"]}).status_code == 200
    plan = client.post(f"/api/stops/{extra['id']}/move", json={"driver_id": vera["id"]}).json()
    hers = {s["id"] for s in plan["stops"] if s["driver_id"] == vera["id"]}
    assert extra["id"] in hers and away["id"] not in hers

    assert client.put(f"/api/drivers/{vera['id']}", json={**vera, "locked": True}).status_code == 200
    plan = compute(client, plan)
    hers = [s for s in plan["stops"] if s["driver_id"] == vera["id"]]
    assert {s["id"] for s in hers} == {s["id"] for s in usual}
    assert all(s["label"] == "usual" for s in hers)
    assert next(s for s in plan["stops"] if s["id"] == extra["id"])["driver_id"] == alex["id"]
    assert any("Vera" in w and "locked" in w for w in plan["result"]["warnings"])

    # Unlocked again, the hand moves count once more.
    assert client.put(f"/api/drivers/{vera['id']}", json={**vera, "locked": False}).status_code == 200
    plan = compute(client, plan)
    hers = {s["id"] for s in plan["stops"] if s["driver_id"] == vera["id"]}
    assert extra["id"] in hers and away["id"] not in hers
