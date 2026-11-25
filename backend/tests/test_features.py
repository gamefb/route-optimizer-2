"""Checks for the second round of features: arrival times, reordering, undo, notes, import, backup."""

import csv
import io
import time

from .conftest import grid_point
from .test_flow import compute, day, make_driver, paste_text


def test_staff_sharing_by_driving_time(client):
    alex = make_driver(client, "Alex", at=(0, 0))
    blair = make_driver(client, "Blair", at=(9, 9))
    plan = day(client, "2026-01-05", [alex, blair])
    client.put("/api/settings", json={"staff_balance": "time"})
    result = compute(client, plan)["result"]
    times = [r["time_s"] for r in result["routes"]]
    assert not result["unassigned"] and min(times) > 0
    assert max(times) <= 1.9 * (sum(times) / 2)  # neither driver carries nearly everything


def test_arrival_times_use_start_time_and_minutes_per_stop(client):
    alex = make_driver(client, "Alex", at=(0, 0))
    plan = day(client, "2026-01-05", [alex], houses=[11, 12, 13])
    client.put("/api/settings", json={"minutes_per_stop": 10})
    plan = client.put(f"/api/plans/{plan['id']}", json={"start_time": "08:30"}).json()
    plan = compute(client, plan)
    stops = sorted(plan["stops"], key=lambda s: s["stop_number"])
    etas = [s["eta"] for s in stops]
    assert etas == sorted(etas) and etas[0] >= "08:30"

    def minutes(t):
        return int(t[:2]) * 60 + int(t[3:])

    assert minutes(etas[1]) - minutes(etas[0]) >= 10  # ten minutes at the first stop before driving on
    route = plan["result"]["routes"][0]
    assert route["start_time"] == "08:30" and route["finish_time"] > etas[-1]
    assert client.put(f"/api/plans/{plan['id']}", json={"start_time": "9am"}).status_code == 400


def test_reorder_by_hand_and_reset(client):
    alex = make_driver(client, "Alex", at=(0, 0))
    plan = compute(client, day(client, "2026-01-05", [alex], houses=[11, 12, 13, 14, 21]))
    order = plan["result"]["routes"][0]["stop_ids"]
    plan = client.post(f"/api/stops/{order[2]}/reorder", json={"direction": -1}).json()
    route = plan["result"]["routes"][0]
    assert route["stop_ids"] == [order[0], order[2], order[1], order[3], order[4]]
    assert route["order_mode"] == "manual"
    assert next(s for s in plan["stops"] if s["id"] == order[2])["stop_number"] == 2
    plan = compute(client, plan)  # a rebuild keeps the hand-arranged order
    assert plan["result"]["routes"][0]["stop_ids"][1] == order[2]
    plan = client.post(f"/api/plans/{plan['id']}/reset-order", json={"driver_id": alex["id"]}).json()
    assert plan["result"]["routes"][0]["order_mode"] == "optimized"
    assert plan["result"]["routes"][0]["stop_ids"] == order


def test_undo_make_all_usual(client):
    alex = make_driver(client, "Alex", at=(0, 0))
    vera = make_driver(client, "Vera", "volunteer", at=(2, 2), max_stops=4)
    plan = compute(client, day(client, "2026-01-05", [alex, vera]))
    assert plan["undo_label"] == ""
    plan = client.post(f"/api/plans/{plan['id']}/make-all-usual", json={"driver_id": vera["id"]}).json()
    assert "usual" in plan["undo_label"]
    assert len(client.get(f"/api/addresses?driver_id={vera['id']}").json()) == 4
    plan = client.post(f"/api/plans/{plan['id']}/undo").json()
    assert plan["undo_label"] == ""
    assert len(client.get(f"/api/addresses?driver_id={vera['id']}").json()) == 0
    assert all(s["label"] == "added" for s in plan["stops"] if s["driver_id"] == vera["id"])

    assert client.post(f"/api/plans/{plan['id']}/undo").status_code == 400
    assert client.post(f"/api/plans/{plan['id']}/reshuffle/apply").status_code in (404, 405)  # removed


def test_notes_follow_the_address(client):
    alex = make_driver(client, "Alex", at=(0, 0))
    plan = compute(client, day(client, "2026-01-05", [alex], houses=[11, 12]))
    first = plan["stops"][0]
    r = client.put(f"/api/addresses/{first['address_id']}", json={"notes": "Gate code 4411"})
    assert r.json()["notes"] == "Gate code 4411"
    plan2 = client.get("/api/plans/by-day/2026-01-06").json()
    plan2 = client.post(f"/api/plans/{plan2['id']}/paste", json={"text": paste_text([11])}).json()
    assert plan2["stops"][0]["notes"] == "Gate code 4411"
    rows = list(csv.reader(io.StringIO(client.get(f"/api/plans/{plan['id']}/export.csv").text)))
    assert rows[1][-1] == "Gate code 4411" and rows[1][0] == "1"


def wait_for_import(client):
    for _ in range(200):
        job = client.get("/api/import/status").json()
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("import did not finish")


def row(*cells):
    return "\t".join(cells) + "\n"


def test_bulk_import_saves_confident_addresses_and_parks_the_rest(client):
    make_driver(client, "Alex", at=(0, 0))
    vera = make_driver(client, "Vera", "volunteer", at=(2, 2), max_stops=5)
    text = (
        row("11 Grid St", "", "Gridville", "OH", "43001", "Vera", "Side door")
        + row("12 Grid St", "Apt 3", "Gridville", "OH", "43001", "vera", "")
        + row("13 Grid St", "", "Gridville", "OH", "43001", "", "Call first")
        + row("5000 Far Rd", "", "Elsewhere", "OH", "43001", "Vera", "Blue house")
        + row("14 Grid St", "", "Gridville", "OH", "", "Vera", "")
    )
    preview = client.post("/api/import/preview", json={"text": text}).json()
    assert preview["layout"] == ["street", "unit", "city", "state", "zip", "volunteer", "notes"]
    assert client.post("/api/import/addresses", json={"text": text}).status_code == 200
    job = wait_for_import(client)
    assert job["status"] == "done", job
    assert (job["saved"], job["pending"], job["updated"]) == (3, 1, 0)
    assert len(job["problems"]) == 1 and "Row 5" in job["problems"][0]
    hers = client.get(f"/api/addresses?driver_id={vera['id']}").json()
    assert sorted(a["street"] for a in hers) == ["11 Grid St", "12 Grid St"]
    assert next(a for a in hers if a["street"] == "11 Grid St")["notes"] == "Side door"
    pending = client.get("/api/pending").json()
    assert len(pending) == 1 and pending[0]["street"] == "5000 Far Rd" and pending[0]["reason"]

    # Importing again updates rather than duplicates.
    client.post("/api/import/addresses", json={"text": row("13 Grid St", "", "Gridville", "OH", "43001", "Vera", "Ring bell")})
    job = wait_for_import(client)
    assert (job["saved"], job["updated"]) == (0, 1)
    assert len(client.get("/api/addresses").json()) == 3
    assert len(client.get(f"/api/addresses?driver_id={vera['id']}").json()) == 3

    # A parked address gets its volunteer and notes once its location is confirmed.
    lat, lon = grid_point(5, 5)
    saved = client.post("/api/pending/confirm", json={"key": pending[0]["key"], "lat": lat, "lon": lon}).json()
    assert saved["usual_driver_id"] == vera["id"] and saved["notes"] == "Blue house"
    assert client.get("/api/pending").json() == []

    # The imported addresses match on a day's list with no map check needed.
    plan = client.get("/api/plans/by-day/2026-01-05").json()
    plan = client.post(f"/api/plans/{plan['id']}/paste", json={"text": paste_text([11, 13])}).json()
    assert {s["match_state"] for s in plan["stops"]} == {"matched"}


def test_import_without_auto_save_parks_everything(client):
    make_driver(client, "Vera", "volunteer", at=(2, 2))
    client.post("/api/import/addresses", json={"text": row("11 Grid St", "", "Gridville", "OH", "43001"), "auto_save": False})
    job = wait_for_import(client)
    assert (job["saved"], job["pending"]) == (0, 1)


def test_backup_and_restore_round_trip(client):
    alex = make_driver(client, "Alex", at=(0, 0))
    vera = make_driver(client, "Vera", "volunteer", at=(2, 2), max_stops=3)
    plan = compute(client, day(client, "2026-01-05", [alex, vera], houses=[11, 12, 13, 21, 22]))
    client.post(f"/api/plans/{plan['id']}/make-all-usual", json={"driver_id": vera["id"]})
    client.put("/api/settings", json={"minutes_per_stop": 7, "google_key": "secret-key"})
    assert client.get("/api/settings").json()["has_google_key"] is True
    assert "secret-key" not in client.get("/api/settings").text  # keys are never sent back
    backup = client.get("/api/backup").json()
    assert len(backup["drivers"]) == 2 and len(backup["addresses"]) == 5

    client.delete(f"/api/drivers/{vera['id']}")
    client.put("/api/settings", json={"minutes_per_stop": 1})
    assert client.post("/api/restore", json={"app": "something else"}).status_code == 400
    assert client.post("/api/restore", json=backup).json()["addresses"] == 5
    drivers = client.get("/api/drivers").json()
    new_vera = next(d for d in drivers if d["name"] == "Vera")
    assert new_vera["usual_stops"] == 3 and new_vera["max_stops"] == 3
    assert client.get("/api/settings").json()["minutes_per_stop"] == 7


def test_older_database_gains_new_columns(client):
    """A database made by the first version is upgraded in place, keeping its data."""
    from sqlalchemy import inspect, text

    from app.db import engine, ensure_schema

    make_driver(client, "Alex", at=(0, 0))
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE plans DROP COLUMN start_time"))
        conn.execute(text("ALTER TABLE addresses DROP COLUMN notes"))
    ensure_schema()
    columns = {c["name"] for c in inspect(engine).get_columns("plans")}
    assert "start_time" in columns
    assert "notes" in {c["name"] for c in inspect(engine).get_columns("addresses")}
    assert client.get("/api/drivers").json()[0]["name"] == "Alex"
    assert client.get("/api/plans/by-day/2026-02-01").json()["start_time"] == "09:00"


def test_older_database_loses_retired_columns(client):
    """Columns that nothing reads any more are dropped, so their old "required" rule cannot block new rows."""
    from sqlalchemy import inspect, text

    from app.db import engine, ensure_schema

    alex = make_driver(client, "Alex", at=(0, 0))
    day(client, "2026-01-05", [alex], houses=[12])
    plan = client.get("/api/plans/by-day/2026-01-06").json()
    plan = client.post(f"/api/plans/{plan['id']}/paste", json={"text": paste_text([12]).replace("Grid", "Gridd")}).json()
    stop = plan["stops"][0]
    assert stop["match_state"] == "possible"
    known = stop["candidates"][0]["id"]
    with engine.begin() as conn:  # the shape the first version left behind
        conn.execute(text("ALTER TABLE drivers ADD COLUMN default_working BOOLEAN NOT NULL DEFAULT 1"))
        conn.execute(text("ALTER TABLE plans ADD COLUMN order_modes JSON NOT NULL DEFAULT '{}'"))
        conn.execute(text("ALTER TABLE plan_stops ADD COLUMN candidate_address_id INTEGER"))
        conn.execute(text("UPDATE plan_stops SET candidate_address_id = :known, candidate_address_ids = NULL WHERE id = :id"),
                     {"known": known, "id": stop["id"]})
    ensure_schema()
    columns = {table: {c["name"] for c in inspect(engine).get_columns(table)} for table in ("drivers", "plans", "plan_stops")}
    assert "default_working" not in columns["drivers"]
    assert "order_modes" not in columns["plans"]
    assert "candidate_address_id" not in columns["plan_stops"]
    # The one possible match an old row named is still offered.
    again = client.get("/api/plans/by-day/2026-01-06").json()["stops"][0]
    assert [c["id"] for c in again["candidates"]] == [known]
    # New rows still save.
    make_driver(client, "Blair", at=(9, 9))
    assert client.get("/api/plans/by-day/2026-02-01").json()["stops"] == []


def test_drag_order_driver_start_time_and_backup_folder(client, tmp_path, monkeypatch):
    alex = make_driver(client, "Alex", at=(0, 0), start_time="07:30")
    blair = make_driver(client, "Blair", at=(9, 9))
    plan = day(client, "2026-01-05", [alex, blair], houses=[11, 12, 13, 14, 86, 88])
    plan = client.put(f"/api/plans/{plan['id']}", json={"start_time": "09:00"}).json()
    plan = compute(client, plan)
    routes = {r["driver_id"]: r for r in plan["result"]["routes"]}
    assert routes[alex["id"]]["start_time"] == "07:30"  # his own time
    assert routes[blair["id"]]["start_time"] == "09:00"  # the day's time
    assert all(s["eta"] < "09:00" for s in plan["stops"] if s["driver_id"] == alex["id"])

    order = routes[alex["id"]]["stop_ids"]
    wanted = list(reversed(order))
    plan = client.post(f"/api/plans/{plan['id']}/set-order", json={"driver_id": alex["id"], "stop_ids": wanted}).json()
    route = next(r for r in plan["result"]["routes"] if r["driver_id"] == alex["id"])
    assert route["stop_ids"] == wanted and route["order_mode"] == "manual"
    bad = client.post(f"/api/plans/{plan['id']}/set-order", json={"driver_id": alex["id"], "stop_ids": wanted[:-1]})
    assert bad.status_code == 400

    from app import main

    assert client.get("/api/backup/files").json()["enabled"] is False
    monkeypatch.setattr(main, "BACKUP_DIR", str(tmp_path))
    monkeypatch.setattr(main, "BACKUP_KEEP", 2)
    for old in ("2020-01-01", "2020-01-02", "2020-01-03"):
        (tmp_path / f"route-planner-backup-{old}.json").write_text("{}")
    name = client.post("/api/backup/save").json()["name"]
    files = [f["name"] for f in client.get("/api/backup/files").json()["files"]]
    assert files[0] == name and len(files) == 2  # oldest files dropped
    import json

    saved = json.loads((tmp_path / name).read_text())
    assert saved["app"] == "route-planner" and len(saved["drivers"]) == 2
    assert next(d for d in saved["drivers"] if d["name"] == "Alex")["start_time"] == "07:30"


def test_volunteer_without_limits_shares_like_staff(client):
    alex = make_driver(client, "Alex", at=(0, 0))
    free = make_driver(client, "Fran", "volunteer", at=(9, 9))          # no limits at all
    capped = make_driver(client, "Vera", "volunteer", at=(2, 2), max_stops=4)
    plan = compute(client, day(client, "2026-01-05", [alex, free, capped]))
    counts = {r["driver_id"]: r["stops"] for r in plan["result"]["routes"]}
    assert counts[capped["id"]] == 4                                    # limited volunteer still filled first
    rest = 36 - 4
    assert counts[alex["id"]] + counts[free["id"]] == rest
    assert max(counts[alex["id"]], counts[free["id"]]) <= 20            # shared roughly evenly (16 each, up to 20%)
    assert min(counts[alex["id"]], counts[free["id"]]) >= 12

    # Her usual stops still come to her first, and count toward her share.
    client.post(f"/api/plans/{plan['id']}/make-all-usual", json={"driver_id": free["id"]})
    usual = {a["id"] for a in client.get(f"/api/addresses?driver_id={free['id']}").json()}
    plan = compute(client, plan)
    hers = [s for s in plan["stops"] if s["driver_id"] == free["id"]]
    assert usual <= {s["address_id"] for s in hers} and all(s["label"] == "usual" for s in hers if s["address_id"] in usual)
    assert not plan["result"]["unassigned"]


def test_several_near_matches_are_all_offered(client):
    make_driver(client, "Alex", at=(0, 0))
    plan = client.get("/api/plans/by-day/2026-01-05").json()
    known = row("12 Grid St", "", "Gridville", "OH", "43001") + row("12 Grid Ct", "", "Gridville", "OH", "43001") + row("12 Gridd St", "", "Gridville", "OH", "43001")
    plan = client.post(f"/api/plans/{plan['id']}/paste", json={"text": known}).json()
    while any(s["match_state"] != "matched" for s in plan["stops"]):
        s = next(s for s in plan["stops"] if s["match_state"] != "matched")
        if s["match_state"] == "possible":
            plan = client.post(f"/api/stops/{s['id']}/mark-new").json()  # "Add new"
            continue
        c = client.get(f"/api/stops/{s['id']}/candidates").json()["candidates"][0]
        plan = client.post(f"/api/stops/{s['id']}/confirm-location", json={"lat": c["lat"], "lon": c["lon"]}).json()
    assert len(client.get("/api/addresses").json()) == 3

    plan2 = client.get("/api/plans/by-day/2026-01-06").json()
    plan2 = client.post(f"/api/plans/{plan2['id']}/paste", json={"text": row("12 Gridd Ct", "", "Gridville", "OH", "43001")}).json()
    stop = plan2["stops"][0]
    assert stop["match_state"] == "possible"
    offered = [c["street"] for c in stop["candidates"]]
    assert offered == ["12 Grid Ct", "12 Gridd St"]  # both offered; the different kind of street comes last
    pick = next(c for c in stop["candidates"] if c["street"] == "12 Gridd St")
    plan2 = client.post(f"/api/stops/{stop['id']}/confirm-match", json={"address_id": pick["id"]}).json()
    assert plan2["stops"][0]["match_state"] == "matched" and plan2["stops"][0]["address_id"] == pick["id"]
