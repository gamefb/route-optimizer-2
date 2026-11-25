"""Route Planner API."""

from __future__ import annotations

import copy
import csv
import io
import os
import re
import threading
from contextlib import asynccontextmanager
from datetime import date, datetime

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import geocode as geo
from . import planner
from .db import SessionLocal, ensure_schema, get_db
from .matching import AddressBook, flag_duplicates, match_stop, same_building
from .models import STAFF, VOLUNTEER, Driver, KnownAddress, PendingAddress, Plan, PlanStop, Setting
from .parsing import (
    ROLES, US_STATES, apply_layout, building_key, clean_state, clean_zip, detect_layout,
    norm_key, normalize_unit, row_problem, split_rows,
)
from .routing import RoutingError, get_router

DEFAULT_SETTINGS = {
    "units": "mi",
    "geocoder": "census",
    "tile_url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    "layout": [],
    "staff_balance": "stops",  # stops | time | off
    "minutes_per_stop": 5,
    "default_start_time": "09:00",
    "google_key": "",
    "mapbox_key": "",
    "geocodio_key": "",
}
KEY_SETTINGS = {"google": "google_key", "mapbox": "mapbox_key", "geocodio": "geocodio_key"}
COLORS = ["#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed", "#0891b2", "#db2777", "#4d7c0f", "#b45309", "#475569"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_schema()
    threading.Thread(target=_backup_loop, daemon=True).start()
    router = get_router()
    url = os.environ.get("DEFAULT_REGION_URL", "").strip()
    if url and not router.ready and router.pending is None:
        try:
            router.start_build(os.environ.get("DEFAULT_REGION_NAME", "Default region"), url)
        except RoutingError:
            pass
    yield


app = FastAPI(title="Route Planner", lifespan=lifespan)


def bad(message: str, status: int = 400):
    raise HTTPException(status_code=status, detail=message)


# ------------------------------------------------------------------ settings


def get_settings(db: Session) -> dict:
    out = dict(DEFAULT_SETTINGS)
    stored = {row.key: row.value for row in db.query(Setting).all()}
    out.update(stored)
    if "staff_balance" not in stored and stored.get("balance_staff") is False:
        out["staff_balance"] = "off"  # setting from the first version
    out.pop("balance_staff", None)
    return out


def geocoder_keys(settings: dict) -> dict:
    return {name: settings.get(key) or geo.env_key(name) for name, key in KEY_SETTINGS.items()}


def settings_out(db: Session) -> dict:
    """Settings for the interface. API keys are never sent back, only whether one is saved."""
    out = get_settings(db)
    keys = geocoder_keys(out)
    for name, key in KEY_SETTINGS.items():
        out.pop(key, None)
        out[f"has_{name}_key"] = bool(keys[name])
    return out


def lookup(db: Session, **kwargs) -> list[dict]:
    settings = get_settings(db)
    return geo.geocode(settings["geocoder"], keys=geocoder_keys(settings), **kwargs)


def valid_time(value: str) -> bool:
    return bool(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value or ""))


def set_setting(db: Session, key: str, value) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value


class SettingsIn(BaseModel):
    units: str | None = None
    geocoder: str | None = None
    tile_url: str | None = None
    staff_balance: str | None = None
    minutes_per_stop: int | None = None
    default_start_time: str | None = None
    google_key: str | None = None  # an empty string removes a saved key
    mapbox_key: str | None = None
    geocodio_key: str | None = None


@app.get("/api/settings")
def read_settings(db: Session = Depends(get_db)):
    return settings_out(db)


@app.put("/api/settings")
def write_settings(body: SettingsIn, db: Session = Depends(get_db)):
    if body.units is not None:
        if body.units not in ("mi", "km"):
            bad("Units must be mi or km")
        set_setting(db, "units", body.units)
    if body.geocoder is not None:
        if body.geocoder not in geo.ALL_PROVIDERS:
            bad("Unknown geocoder")
        set_setting(db, "geocoder", body.geocoder)
    for name, key in KEY_SETTINGS.items():
        value = getattr(body, key)
        if value is not None:
            set_setting(db, key, value.strip())
    if body.staff_balance is not None:
        if body.staff_balance not in ("stops", "time", "off"):
            bad("Staff sharing must be stops, time or off")
        set_setting(db, "staff_balance", body.staff_balance)
        _mark_plans_stale(db)
    if body.minutes_per_stop is not None:
        if not 0 <= body.minutes_per_stop <= 120:
            bad("Minutes per stop must be between 0 and 120")
        set_setting(db, "minutes_per_stop", body.minutes_per_stop)
        _mark_plans_stale(db)
    if body.default_start_time is not None:
        if not valid_time(body.default_start_time):
            bad("Start time must look like 09:00")
        set_setting(db, "default_start_time", body.default_start_time)
    if body.tile_url is not None and body.tile_url.strip():
        set_setting(db, "tile_url", body.tile_url.strip())
    db.commit()
    return settings_out(db)


# -------------------------------------------------------------------- region


class RegionIn(BaseModel):
    name: str
    url: str


@app.get("/api/region")
def region_info():
    return get_router().info()


@app.get("/api/region/catalog")
def region_catalog():
    base = "https://download.geofabrik.de/north-america/us"
    items = []
    for code, name in sorted(US_STATES.items(), key=lambda kv: kv[1]):
        slug = name.lower().replace(" ", "-")
        items.append({"name": name.title(), "url": f"{base}/{slug}-latest.osm.pbf"})
    return items


@app.post("/api/region")
def region_build(body: RegionIn):
    url = body.url.strip()
    if not (url.startswith("http://") or url.startswith("https://") or url.startswith("/")):
        bad("Give a link to an .osm.pbf map file, or a path inside the map data folder.")
    try:
        get_router().start_build(body.name.strip() or "Custom region", url)
    except RoutingError as exc:
        bad(str(exc), 409)
    return get_router().info()


# ------------------------------------------------------------------- geocode


class GeocodeIn(BaseModel):
    query: str


def _with_map_check(candidates: list[dict]) -> list[dict]:
    router = get_router()
    for c in candidates:
        c["on_map"] = router.on_map(c["lat"], c["lon"]) if router.ready else None
    return candidates


@app.post("/api/geocode")
def geocode_freeform(body: GeocodeIn, db: Session = Depends(get_db)):
    if not body.query.strip():
        bad("Type an address to look up.")
    try:
        found = lookup(db, freeform=body.query.strip())
    except geo.GeocodeError as exc:
        bad(str(exc), 502)
    return _with_map_check(found)


# ------------------------------------------------------------------- drivers


class DriverIn(BaseModel):
    name: str
    kind: str = STAFF
    color: str | None = None
    start_label: str = ""
    start_lat: float | None = None
    start_lon: float | None = None
    end_label: str = ""
    end_lat: float | None = None
    end_lon: float | None = None
    avoid_highways: bool = False
    start_time: str | None = None
    max_stops: int | None = None
    max_route_minutes: int | None = None
    zip_codes: list[str] = []
    locked: bool = False


def driver_out(d: Driver, usual_count: int = 0) -> dict:
    return {
        "id": d.id, "name": d.name, "kind": d.kind, "color": d.color,
        "start_label": d.start_label, "start_lat": d.start_lat, "start_lon": d.start_lon,
        "end_label": d.end_label, "end_lat": d.end_lat, "end_lon": d.end_lon,
        "avoid_highways": d.avoid_highways,
        "start_time": d.start_time or "",
        "max_stops": d.max_stops, "max_route_minutes": d.max_route_minutes,
        "zip_codes": d.zip_codes or [], "locked": d.is_locked, "usual_stops": usual_count,
    }


def _usual_counts(db: Session) -> dict[int, int]:
    counts: dict[int, int] = {}
    for (driver_id,) in db.query(KnownAddress.usual_driver_id).filter(KnownAddress.usual_driver_id.isnot(None)):
        counts[driver_id] = counts.get(driver_id, 0) + 1
    return counts


def _fill_driver(d: Driver, body: DriverIn) -> None:
    if not body.name.strip():
        bad("A driver needs a name.")
    if body.kind not in (STAFF, VOLUNTEER):
        bad("A driver is either staff or volunteer.")
    for lat, lon, what in ((body.start_lat, body.start_lon, "start"), (body.end_lat, body.end_lon, "end")):
        if lat is not None and lon is not None and get_router().ready and not get_router().on_map(lat, lon):
            bad(f"The {what} location is outside the loaded map region.")
    d.name, d.kind = body.name.strip(), body.kind
    if body.color:
        d.color = body.color
    d.start_label, d.start_lat, d.start_lon = body.start_label, body.start_lat, body.start_lon
    d.end_label, d.end_lat, d.end_lon = body.end_label, body.end_lat, body.end_lon
    d.avoid_highways = body.avoid_highways
    if body.start_time and not valid_time(body.start_time):
        bad("Start time must look like 09:00")
    d.start_time = body.start_time or None
    volunteer = body.kind == VOLUNTEER
    # Limits, zip codes and the lock exist for volunteers only.
    d.max_stops = (body.max_stops or None) if volunteer else None
    d.max_route_minutes = (body.max_route_minutes or None) if volunteer else None
    d.zip_codes = [clean_zip(z)[:5] for z in body.zip_codes if z.strip()] if volunteer else []
    d.locked = body.locked if volunteer else False


def _mark_plans_stale(db: Session) -> None:
    db.query(Plan).filter(Plan.day >= date.today()).update({Plan.stale: True})


@app.get("/api/drivers")
def list_drivers(db: Session = Depends(get_db)):
    counts = _usual_counts(db)
    return [driver_out(d, counts.get(d.id, 0)) for d in db.query(Driver).order_by(Driver.kind, Driver.name)]


@app.post("/api/drivers")
def create_driver(body: DriverIn, db: Session = Depends(get_db)):
    d = Driver()
    _fill_driver(d, body)
    if not body.color:
        d.color = COLORS[db.query(Driver).count() % len(COLORS)]
    db.add(d)
    db.commit()
    return driver_out(d)


@app.put("/api/drivers/{driver_id}")
def update_driver(driver_id: int, body: DriverIn, db: Session = Depends(get_db)):
    d = db.get(Driver, driver_id) or bad("Driver not found", 404)
    was_volunteer = d.is_volunteer
    _fill_driver(d, body)
    if was_volunteer and not d.is_volunteer:
        # Staff have no usual stops.
        db.query(KnownAddress).filter(KnownAddress.usual_driver_id == d.id).update(
            {KnownAddress.usual_driver_id: None}
        )
    _mark_plans_stale(db)
    db.commit()
    return driver_out(d, _usual_counts(db).get(d.id, 0))


@app.delete("/api/drivers/{driver_id}")
def delete_driver(driver_id: int, db: Session = Depends(get_db)):
    d = db.get(Driver, driver_id) or bad("Driver not found", 404)
    # A removed volunteer's stops no longer have a usual driver.
    db.query(KnownAddress).filter(KnownAddress.usual_driver_id == d.id).update(
        {KnownAddress.usual_driver_id: None}
    )
    for plan in db.query(Plan).filter(Plan.day >= date.today()):
        plan.working_driver_ids = [i for i in (plan.working_driver_ids or []) if i != d.id]
        plan.stale = True
    db.query(PlanStop).filter(PlanStop.manual_driver_id == d.id).update({PlanStop.manual_driver_id: None})
    db.delete(d)
    db.commit()
    return {"ok": True}


# ----------------------------------------------------------------- addresses


class AddressIn(BaseModel):
    usual_driver_id: int | None = None
    set_usual: bool = False
    notes: str | None = None
    lat: float | None = None
    lon: float | None = None


def address_out(a: KnownAddress) -> dict:
    return {
        "id": a.id, "street": a.street, "unit": a.unit, "city": a.city, "state": a.state, "zip": a.zip,
        "lat": a.lat, "lon": a.lon, "usual_driver_id": a.usual_driver_id, "notes": a.notes or "",
    }


def _change_usual(db: Session, addr: KnownAddress, new_id: int | None) -> None:
    """Change who an address usually belongs to. Locked volunteers gain and lose nothing."""
    if addr.usual_driver_id == new_id:
        return
    current = db.get(Driver, addr.usual_driver_id) if addr.usual_driver_id else None
    if current is not None and current.is_locked:
        bad(f"{current.name}'s addresses are locked. Turn the lock off to change them.")
    if new_id is not None:
        target = db.get(Driver, new_id) or bad("Driver not found", 404)
        if not target.is_volunteer:
            bad("Only volunteers have usual stops.")
        if target.is_locked:
            bad(f"{target.name}'s addresses are locked. Turn the lock off to change them.")
    addr.usual_driver_id = new_id


@app.get("/api/addresses")
def list_addresses(q: str = "", driver_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(KnownAddress)
    if driver_id is not None:
        query = query.filter(KnownAddress.usual_driver_id == driver_id)
    rows = query.order_by(KnownAddress.zip, KnownAddress.street, KnownAddress.unit).all()
    if q.strip():
        needle = q.strip().lower()
        rows = [a for a in rows if needle in f"{a.street} {a.unit} {a.city} {a.zip} {a.notes or ''}".lower()]
    return [address_out(a) for a in rows]


@app.put("/api/addresses/{address_id}")
def update_address(address_id: int, body: AddressIn, db: Session = Depends(get_db)):
    a = db.get(KnownAddress, address_id) or bad("Address not found", 404)
    if body.notes is not None:
        a.notes = body.notes.strip()  # a note changes nothing about the routes
    if body.set_usual:
        _change_usual(db, a, body.usual_driver_id)
        _mark_plans_stale(db)
    if body.lat is not None and body.lon is not None:
        if get_router().ready and not get_router().on_map(body.lat, body.lon):
            bad("That location is outside the loaded map region.")
        a.lat, a.lon = body.lat, body.lon
        _mark_plans_stale(db)
    db.commit()
    return address_out(a)


@app.delete("/api/addresses/{address_id}")
def delete_address(address_id: int, db: Session = Depends(get_db)):
    a = db.get(KnownAddress, address_id) or bad("Address not found", 404)
    owner = db.get(Driver, a.usual_driver_id) if a.usual_driver_id else None
    if owner is not None and owner.is_locked:
        bad(f"{owner.name}'s addresses are locked. Turn the lock off to change them.")
    for s in db.query(PlanStop).filter(PlanStop.address_id == a.id):
        s.address_id, s.match_state, s.driver_id, s.stop_number = None, "new", None, None
        s.plan.stale = True
    db.delete(a)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------- plans


def stop_out(s: PlanStop, candidates: dict[int, KnownAddress]) -> dict:
    a = s.address
    ids = (s.candidate_address_ids or []) if s.match_state == "possible" else []
    near = [address_out(candidates[i]) for i in ids if i in candidates]
    return {
        "id": s.id, "seq": s.seq, "street": s.street, "unit": s.unit, "city": s.city,
        "state": s.state, "zip": s.zip, "extras": s.extras or [],
        "match_state": s.match_state, "problem": s.problem, "duplicate_of_seq": s.duplicate_of_seq,
        "is_new_address": s.is_new_address, "address_id": s.address_id,
        "lat": a.lat if a else None, "lon": a.lon if a else None,
        "usual_driver_id": a.usual_driver_id if a else None,
        "notes": (a.notes or "") if a else "", "eta": s.eta,
        "candidates": near,
        "manual_driver_id": s.manual_driver_id, "driver_id": s.driver_id, "label": s.label,
        "covering_for_id": s.covering_for_id, "stop_number": s.stop_number,
        "added_time_s": s.added_time_s, "added_distance_m": s.added_distance_m,
    }


def plan_out(db: Session, plan: Plan) -> dict:
    cand_ids = list({i for s in plan.stops for i in (s.candidate_address_ids or [])})
    candidates = {a.id: a for a in db.query(KnownAddress).filter(KnownAddress.id.in_(cand_ids))} if cand_ids else {}
    return {
        "id": plan.id, "day": plan.day.isoformat(), "objective": plan.objective,
        "working_driver_ids": plan.working_driver_ids or [],
        "layout": plan.layout or [], "stale": plan.stale, "result": plan.result,
        "start_time": plan.start_time or "09:00",
        "undo_label": (plan.undo or {}).get("label") or "",
        "sample": next((s.raw for s in plan.stops if s.raw), []),
        "stops": [stop_out(s, candidates) for s in plan.stops],
    }


def get_plan(db: Session, plan_id: int) -> Plan:
    return db.get(Plan, plan_id) or bad("Plan not found", 404)


def get_stop(db: Session, stop_id: int) -> PlanStop:
    return db.get(PlanStop, stop_id) or bad("Stop not found", 404)


@app.get("/api/plans")
def list_plans(db: Session = Depends(get_db)):
    out = []
    for p in db.query(Plan).order_by(Plan.day.desc()).limit(60):
        out.append({"id": p.id, "day": p.day.isoformat(), "stops": len(p.stops), "computed": p.result is not None})
    return out


@app.get("/api/plans/by-day/{day}")
def plan_for_day(day: date, db: Session = Depends(get_db)):
    plan = db.query(Plan).filter(Plan.day == day).first()
    if plan is None:
        # Days that were only looked at (no rows entered) are not worth keeping.
        for empty in db.query(Plan).filter(~Plan.stops.any()).all():
            db.delete(empty)
        db.flush()
        last = db.query(Plan).order_by(Plan.day.desc()).first()
        everyone = [d.id for d in db.query(Driver).all()]
        # Start from the drivers picked on the most recent day; the dispatcher adjusts from there.
        picked = [i for i in (last.working_driver_ids or []) if i in everyone] if last else []
        plan = Plan(
            day=day,
            objective=last.objective if last else "time",
            working_driver_ids=picked or everyone,
            layout=get_settings(db).get("layout") or [],
            start_time=get_settings(db).get("default_start_time") or "09:00",
        )
        db.add(plan)
        db.commit()
    return plan_out(db, plan)


class PlanIn(BaseModel):
    objective: str | None = None
    working_driver_ids: list[int] | None = None
    start_time: str | None = None


@app.put("/api/plans/{plan_id}")
def update_plan(plan_id: int, body: PlanIn, db: Session = Depends(get_db)):
    plan = get_plan(db, plan_id)
    if body.objective is not None:
        if body.objective not in ("time", "distance"):
            bad("Objective must be time or distance")
        plan.objective = body.objective
    if body.working_driver_ids is not None:
        plan.working_driver_ids = body.working_driver_ids
    if body.start_time is not None:
        if not valid_time(body.start_time):
            bad("Start time must look like 09:00")
        plan.start_time = body.start_time
    plan.stale = True
    db.commit()
    return plan_out(db, plan)


# ------------------------------------------------------- pasted rows / table


class PasteIn(BaseModel):
    text: str
    mode: str = "replace"  # replace | append
    layout: list[str] | None = None


class LayoutIn(BaseModel):
    layout: list[str]


class StopIn(BaseModel):
    street: str = ""
    unit: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""


def _set_fields(stop: PlanStop, fields: dict) -> None:
    stop.street, stop.unit, stop.city = fields["street"].strip(), fields["unit"].strip(), fields["city"].strip()
    stop.state, stop.zip = clean_state(fields["state"]), clean_zip(fields["zip"])
    stop.extras = fields.get("extras", stop.extras or [])


def _rematch(db: Session, plan: Plan, only: list[PlanStop] | None = None) -> None:
    book = AddressBook(db)
    for s in only if only is not None else plan.stops:
        match_stop(s, book)
        s.driver_id = s.stop_number = None
        s.label = ""
    flag_duplicates(list(plan.stops))
    plan.stale = True


def _clean_layout(layout: list[str], width: int) -> list[str]:
    out = [(r if r in ROLES else "extra") for r in layout][:width]
    return out + ["extra"] * (width - len(out))


@app.post("/api/plans/{plan_id}/paste")
def paste_rows(plan_id: int, body: PasteIn, db: Session = Depends(get_db)):
    plan = get_plan(db, plan_id)
    rows = split_rows(body.text)
    if not rows:
        bad("Nothing to read. Copy the rows in Excel and paste them here.")
    width = len(rows[0])
    remembered = body.layout or plan.layout or get_settings(db).get("layout") or []
    # Use the remembered layout when the pasted data has the same shape; otherwise look again.
    layout = _clean_layout(remembered, width) if len(remembered) == width else detect_layout(rows)
    if body.mode == "replace":
        plan.stops.clear()
        plan.result, plan.undo, plan.manual_orders = None, None, {}
        db.flush()
        start = 1
    else:
        start = max((s.seq for s in plan.stops), default=0) + 1
    created = []
    for offset, cells in enumerate(rows):
        stop = PlanStop(seq=start + offset, raw=cells)
        _set_fields(stop, apply_layout(cells, layout))
        plan.stops.append(stop)
        created.append(stop)
    plan.layout = layout
    db.flush()
    _rematch(db, plan, created)
    db.commit()
    return plan_out(db, plan)


@app.post("/api/plans/{plan_id}/layout")
def change_layout(plan_id: int, body: LayoutIn, db: Session = Depends(get_db)):
    """The dispatcher corrected which column is which. Re-read every pasted row."""
    plan = get_plan(db, plan_id)
    layout = _clean_layout(body.layout, len(body.layout))
    if not layout:
        bad("Keep at least one column.")
    for s in plan.stops:
        if s.raw:
            _set_fields(s, apply_layout(s.raw, layout))
    plan.layout = layout
    set_setting(db, "layout", layout)  # remembered for the next paste of the same shape
    _rematch(db, plan)
    db.commit()
    return plan_out(db, plan)


@app.post("/api/plans/{plan_id}/stops")
def add_stop(plan_id: int, body: StopIn, db: Session = Depends(get_db)):
    plan = get_plan(db, plan_id)
    stop = PlanStop(seq=max((s.seq for s in plan.stops), default=0) + 1, raw=[])
    _set_fields(stop, {**body.model_dump(), "extras": []})
    plan.stops.append(stop)
    db.flush()
    _rematch(db, plan, [stop])
    db.commit()
    return plan_out(db, plan)


@app.delete("/api/plans/{plan_id}/stops")
def clear_stops(plan_id: int, db: Session = Depends(get_db)):
    plan = get_plan(db, plan_id)
    plan.stops.clear()
    plan.result, plan.stale, plan.undo, plan.manual_orders = None, True, None, {}
    db.commit()
    return plan_out(db, plan)


@app.put("/api/stops/{stop_id}")
def edit_stop(stop_id: int, body: StopIn, db: Session = Depends(get_db)):
    stop = get_stop(db, stop_id)
    _set_fields(stop, {**body.model_dump(), "extras": stop.extras or []})
    _rematch(db, stop.plan, [stop])
    db.commit()
    return plan_out(db, stop.plan)


@app.delete("/api/stops/{stop_id}")
def delete_stop(stop_id: int, db: Session = Depends(get_db)):
    stop = get_stop(db, stop_id)
    plan = stop.plan
    plan.stops.remove(stop)
    db.flush()
    for n, s in enumerate(sorted(plan.stops, key=lambda x: x.seq), start=1):
        s.seq = n
    flag_duplicates(list(plan.stops))
    plan.stale = True
    db.commit()
    return plan_out(db, plan)


class ShiftIn(BaseModel):
    direction: int


@app.post("/api/stops/{stop_id}/shift")
def shift_stop(stop_id: int, body: ShiftIn, db: Session = Depends(get_db)):
    """Move a row up or down in list order."""
    stop = get_stop(db, stop_id)
    plan = stop.plan
    ordered = sorted(plan.stops, key=lambda x: x.seq)
    i = ordered.index(stop)
    j = i + (1 if body.direction > 0 else -1)
    if 0 <= j < len(ordered):
        ordered[i].seq, ordered[j].seq = ordered[j].seq, ordered[i].seq
        flag_duplicates(list(plan.stops))
        plan.stale = True
        db.commit()
        db.refresh(plan)
    return plan_out(db, plan)


class ConfirmMatchIn(BaseModel):
    address_id: int | None = None


@app.post("/api/stops/{stop_id}/confirm-match")
def confirm_match(stop_id: int, body: ConfirmMatchIn, db: Session = Depends(get_db)):
    """Yes, this row is that known address. Remember the spelling for next time."""
    stop = get_stop(db, stop_id)
    closest = (stop.candidate_address_ids or [0])[0]
    target = db.get(KnownAddress, body.address_id or closest) or bad("Address not found", 404)
    key = norm_key(stop.street, stop.unit, stop.zip)
    if key != target.norm_key and key not in (target.aliases or []):
        target.aliases = list(target.aliases or []) + [key]
    db.flush()
    _rematch(db, stop.plan, [s for s in stop.plan.stops if s.match_state != "matched"])
    db.commit()
    return plan_out(db, stop.plan)


@app.post("/api/stops/{stop_id}/mark-new")
def mark_new(stop_id: int, db: Session = Depends(get_db)):
    stop = get_stop(db, stop_id)
    if stop.match_state == "possible":
        stop.match_state, stop.candidate_address_ids = "new", None
        db.commit()
    return plan_out(db, stop.plan)


@app.get("/api/stops/{stop_id}/candidates")
def stop_candidates(stop_id: int, db: Session = Depends(get_db)):
    """Places this new address might be, for the dispatcher to confirm on a map."""
    stop = get_stop(db, stop_id)
    book = AddressBook(db)
    out, error = [], ""
    building = same_building(book, stop.street, stop.zip)
    if building is not None:
        out.append({
            "lat": building.lat, "lon": building.lon, "confidence": "high", "source": "known", "note": "",
            "label": f"Same building as {building.street} {building.unit}".strip() + " (already confirmed)",
        })
    try:
        out += lookup(db, street=stop.street, city=stop.city, state=stop.state, zip_code=stop.zip)
    except geo.GeocodeError as exc:
        error = str(exc)
    out = _with_map_check(out)
    nearby = []
    if out:
        top, unit = out[0], normalize_unit(stop.unit)
        for a in book.by_zip.get(stop.zip[:5], []):
            if normalize_unit(a.unit) == unit and geo.distance_m(top["lat"], top["lon"], a.lat, a.lon) <= 30:
                nearby.append(address_out(a))
    return {"candidates": out, "nearby_known": nearby, "error": error}


def save_address(db: Session, street: str, unit: str, city: str, state: str, zip_code: str,
                 lat: float, lon: float) -> KnownAddress:
    """Save a confirmed location as a known address (or move an existing one)."""
    key = norm_key(street, unit, zip_code)
    addr = db.query(KnownAddress).filter(KnownAddress.norm_key == key).first()
    if addr is None:
        addr = KnownAddress(
            street=street, unit=unit, city=city, state=state, zip=zip_code,
            norm_key=key, building_key=building_key(street, zip_code), aliases=[], lat=lat, lon=lon,
        )
        db.add(addr)
        waiting = db.get(PendingAddress, key)
        if waiting is not None:  # imported earlier; its volunteer and notes were kept for this moment
            owner = db.get(Driver, waiting.usual_driver_id) if waiting.usual_driver_id else None
            if owner is not None and owner.is_volunteer and not owner.is_locked:
                addr.usual_driver_id = owner.id
            addr.notes = waiting.notes
            db.delete(waiting)
    else:
        addr.lat, addr.lon = lat, lon
    db.flush()
    return addr


class LocationIn(BaseModel):
    lat: float
    lon: float


@app.post("/api/stops/{stop_id}/confirm-location")
def confirm_location(stop_id: int, body: LocationIn, db: Session = Depends(get_db)):
    """The dispatcher confirmed where a new address is. Save it as a known address."""
    stop = get_stop(db, stop_id)
    if stop.match_state == "invalid":
        bad("Fix the row first: " + stop.problem)
    router = get_router()
    if router.ready and not router.on_map(body.lat, body.lon):
        bad("That location is outside the loaded map region.")
    addr = save_address(db, stop.street, stop.unit, stop.city, stop.state, stop.zip, body.lat, body.lon)
    plan = stop.plan
    pending = [s for s in plan.stops if s.match_state != "matched"]
    _rematch(db, plan, pending)
    for s in pending:
        if s.address_id == addr.id:
            s.is_new_address = True
    db.commit()
    return plan_out(db, plan)


# ------------------------------------------------------- computing the plan


def _run(db: Session, plan: Plan) -> dict:
    try:
        settings = get_settings(db)
        return planner.compute(
            db, plan, get_router(),
            staff_balance=settings["staff_balance"], minutes_per_stop=int(settings["minutes_per_stop"] or 0),
        )
    except (planner.PlanError, RoutingError) as exc:
        bad(str(exc), 422)


@app.post("/api/plans/{plan_id}/compute")
def compute_plan(plan_id: int, db: Session = Depends(get_db)):
    plan = get_plan(db, plan_id)
    planner.apply_result(plan, _run(db, plan))
    db.commit()
    return plan_out(db, plan)


def _snapshot(plan: Plan, label: str) -> None:
    """Remember what a big change is about to replace, so it can be undone once."""
    plan.undo = {
        "label": label,
        "usual": {str(s.address_id): s.address.usual_driver_id for s in plan.stops if s.address is not None},
        "manual": {str(s.id): s.manual_driver_id for s in plan.stops},
        "manual_orders": plan.manual_orders or {},
        "result": plan.result,
    }


@app.post("/api/plans/{plan_id}/undo")
def undo_last(plan_id: int, db: Session = Depends(get_db)):
    """Put usual stops and the day's routes back to how they were before the last big change."""
    plan = get_plan(db, plan_id)
    saved = plan.undo
    if not saved:
        bad("There is nothing to undo.")
    drivers = {d.id for d in db.query(Driver).all()}
    for s in plan.stops:
        if s.address is not None and str(s.address_id) in saved["usual"]:
            previous = saved["usual"][str(s.address_id)]
            s.address.usual_driver_id = previous if previous in drivers else None
        if str(s.id) in saved["manual"]:
            s.manual_driver_id = saved["manual"][str(s.id)]
    plan.manual_orders = saved.get("manual_orders") or {}
    plan.undo = None
    if saved.get("result"):
        planner.apply_result(plan, saved["result"])
    else:
        plan.stale = True
    db.commit()
    return plan_out(db, plan)


class MoveIn(BaseModel):
    driver_id: int | None = None


@app.post("/api/stops/{stop_id}/move")
def move_stop(stop_id: int, body: MoveIn, db: Session = Depends(get_db)):
    """Send a stop to a chosen driver for the day, or clear that choice."""
    stop = get_stop(db, stop_id)
    plan = stop.plan
    usual = db.get(Driver, stop.address.usual_driver_id) if stop.address and stop.address.usual_driver_id else None
    if usual is not None and usual.is_locked and usual.id in (plan.working_driver_ids or []) and body.driver_id != usual.id:
        bad(f"{usual.name}'s addresses are locked. Turn the lock off to move this stop.")
    if body.driver_id is not None:
        target = db.get(Driver, body.driver_id) or bad("Driver not found", 404)
        if target.id not in (plan.working_driver_ids or []):
            bad(f"{target.name} is not working this day.")
        if target.is_locked and (usual is None or usual.id != target.id):
            bad(f"{target.name}'s addresses are locked. Turn the lock off to add a stop.")
    stop.manual_driver_id = body.driver_id
    plan.stale = True
    db.flush()
    if plan.result is not None:
        planner.apply_result(plan, _run(db, plan))
    db.commit()
    return plan_out(db, plan)


def _make_usual(db: Session, plan: Plan, stop: PlanStop, result: dict) -> None:
    driver = db.get(Driver, stop.driver_id) if stop.driver_id else None
    if driver is None or not driver.is_volunteer:
        bad("Only a stop on a volunteer's route can become a usual stop.")
    if stop.label not in ("added", "manual"):
        bad("This stop already belongs to a volunteer. Change its usual volunteer on the Addresses page.")
    _change_usual(db, stop.address, driver.id)
    stop.label, stop.manual_driver_id = "usual", None
    a = result["assignments"].get(str(stop.id))
    if a:
        a["label"] = "usual"


@app.post("/api/stops/{stop_id}/make-usual")
def make_usual(stop_id: int, db: Session = Depends(get_db)):
    stop = get_stop(db, stop_id)
    plan = stop.plan
    if plan.result is None:
        bad("Build the routes first.")
    result = copy.deepcopy(plan.result)
    _snapshot(plan, "making a stop usual")
    _make_usual(db, plan, stop, result)
    plan.result = result
    db.commit()
    return plan_out(db, plan)


@app.post("/api/plans/{plan_id}/make-all-usual")
def make_all_usual(plan_id: int, body: MoveIn, db: Session = Depends(get_db)):
    plan = get_plan(db, plan_id)
    if plan.result is None:
        bad("Build the routes first.")
    result = copy.deepcopy(plan.result)
    _snapshot(plan, "making all added stops usual")
    for s in plan.stops:
        if s.driver_id == body.driver_id and s.label in ("added", "manual"):
            _make_usual(db, plan, s, result)
    plan.result = result
    db.commit()
    return plan_out(db, plan)


class OrderIn(BaseModel):
    driver_id: int
    stop_ids: list[int]


@app.post("/api/plans/{plan_id}/set-order")
def set_order(plan_id: int, body: OrderIn, db: Session = Depends(get_db)):
    """Set a driver's whole stop order by hand (used by drag and drop)."""
    plan = get_plan(db, plan_id)
    if plan.result is None:
        bad("Build the routes first.")
    route = next((r for r in plan.result["routes"] if r["driver_id"] == body.driver_id), None)
    if route is None or sorted(route["stop_ids"]) != sorted(body.stop_ids):
        bad("The route changed. Rebuild the routes, then try again.")
    plan.manual_orders = {**(plan.manual_orders or {}), str(body.driver_id): body.stop_ids}
    db.flush()
    planner.apply_result(plan, _run(db, plan))
    db.commit()
    return plan_out(db, plan)


class ReorderIn(BaseModel):
    direction: int


@app.post("/api/stops/{stop_id}/reorder")
def reorder_stop(stop_id: int, body: ReorderIn, db: Session = Depends(get_db)):
    """Move a stop one place earlier or later in its driver's route."""
    stop = get_stop(db, stop_id)
    plan = stop.plan
    if plan.result is None or stop.driver_id is None:
        bad("Build the routes first.")
    route = next((r for r in plan.result["routes"] if r["driver_id"] == stop.driver_id), None)
    if route is None or stop.id not in route["stop_ids"]:
        bad("Rebuild the routes, then try again.")
    order = list(route["stop_ids"])
    i = order.index(stop.id)
    j = i + (1 if body.direction > 0 else -1)
    if 0 <= j < len(order):
        order[i], order[j] = order[j], order[i]
        plan.manual_orders = {**(plan.manual_orders or {}), str(stop.driver_id): order}
        db.flush()
        planner.apply_result(plan, _run(db, plan))
        db.commit()
    return plan_out(db, plan)


@app.post("/api/plans/{plan_id}/reset-order")
def reset_order(plan_id: int, body: MoveIn, db: Session = Depends(get_db)):
    """Drop the hand-arranged order for one driver and go back to the automatic one."""
    plan = get_plan(db, plan_id)
    plan.manual_orders = {k: v for k, v in (plan.manual_orders or {}).items() if k != str(body.driver_id)}
    db.flush()
    if plan.result is not None:
        planner.apply_result(plan, _run(db, plan))
    db.commit()
    return plan_out(db, plan)


# -------------------------------------------------------------------- export


@app.get("/api/plans/{plan_id}/export.csv")
def export_csv(plan_id: int, db: Session = Depends(get_db)):
    """One file for the day, in list order, with the driver and stop number."""
    plan = get_plan(db, plan_id)
    names = {d.id: d.name for d in db.query(Driver).all()}
    extra_width = max((len(s.extras or []) for s in plan.stops), default=0)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["List Order", "Street", "Unit", "City", "State", "Zip"]
        + [f"Extra {i + 1}" for i in range(extra_width)]
        + ["Driver", "Stop Number", "Estimated Arrival", "Notes"]
    )
    for s in sorted(plan.stops, key=lambda x: x.seq):
        extras = list(s.extras or []) + [""] * (extra_width - len(s.extras or []))
        writer.writerow(
            [s.seq, s.street, s.unit, s.city, s.state, s.zip] + extras
            + [names.get(s.driver_id, "") if s.driver_id else "", s.stop_number or "",
               s.eta or "", (s.address.notes or "") if s.address else ""]
        )
    return Response(
        content=buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="routes-{plan.day.isoformat()}.csv"'},
    )


# -------------------------------------------------------- bulk address import

IMPORT_ROLES = ["street", "unit", "city", "state", "zip", "volunteer", "notes", "extra"]
_import_job: dict = {"status": "idle"}
_import_lock = threading.Lock()


class ImportIn(BaseModel):
    text: str
    layout: list[str] | None = None
    auto_save: bool = True


def _import_layout(db: Session, rows: list[list[str]]) -> list[str]:
    """Address columns as usual, plus a volunteer-name column and a notes column if present."""
    layout = detect_layout(rows)
    names = {d.name.strip().lower() for d in db.query(Driver).filter(Driver.kind == VOLUNTEER)}
    extras = [i for i, role in enumerate(layout) if role == "extra"]
    for i in extras:
        values = [r[i].strip().lower() for r in rows if i < len(r) and r[i].strip()]
        if values and names and sum(1 for v in values if v in names) / len(values) >= 0.5:
            layout[i] = "volunteer"
            break
    for i in extras:
        if layout[i] == "extra" and any(r[i].strip() for r in rows if i < len(r)):
            layout[i] = "notes"
            break
    return layout


@app.post("/api/import/preview")
def import_preview(body: ImportIn, db: Session = Depends(get_db)):
    rows = split_rows(body.text)
    if not rows:
        bad("Nothing to read. Copy the rows in Excel and paste them here.")
    return {"layout": _import_layout(db, rows), "sample": rows[:5], "rows": len(rows)}


def _import_fields(cells: list[str], layout: list[str]) -> dict:
    address_layout = [r if r in ROLES else "extra" for r in layout]
    fields = apply_layout(cells, address_layout)
    pick = lambda role: " ".join(c.strip() for c, r in zip(cells, layout) if r == role and c.strip())  # noqa: E731
    fields["volunteer"], fields["notes"] = pick("volunteer"), pick("notes")
    return fields


def _run_import(rows: list[list[str]], layout: list[str], auto_save: bool) -> None:
    job = _import_job
    db = SessionLocal()
    try:
        router = get_router()
        volunteers = {d.name.strip().lower(): d for d in db.query(Driver).filter(Driver.kind == VOLUNTEER)}
        book = AddressBook(db)
        for n, cells in enumerate(rows, start=1):
            job["done"] = n - 1
            f = _import_fields(cells, layout)
            problem = row_problem(f)
            if problem:
                job["problems"].append(f"Row {n}: {problem}.")
                continue
            owner = volunteers.get(f["volunteer"].lower()) if f["volunteer"] else None
            if f["volunteer"] and owner is None:
                job["problems"].append(f"Row {n}: no volunteer named \"{f['volunteer']}\". Saved without a usual volunteer.")
            if owner is not None and owner.is_locked:
                job["problems"].append(f"Row {n}: {owner.name} is locked. Saved without a usual volunteer.")
                owner = None
            key = norm_key(f["street"], f["unit"], f["zip"])
            known = book.by_key.get(key)
            if known is not None:
                current = db.get(Driver, known.usual_driver_id) if known.usual_driver_id else None
                if owner is not None and not (current is not None and current.is_locked):
                    known.usual_driver_id = owner.id
                if f["notes"]:
                    known.notes = f["notes"]
                job["updated"] += 1
                db.commit()
                continue
            spot, reason = None, ""
            if not auto_save:
                reason = "Waiting for a map check"
            elif not router.ready:
                reason = "No map region was loaded during the import"
            else:
                building = same_building(book, f["street"], f["zip"])
                if building is not None:
                    spot = (building.lat, building.lon)
                else:
                    try:
                        found = lookup(db, street=f["street"], city=f["city"], state=f["state"], zip_code=f["zip"])
                    except geo.GeocodeError as exc:
                        found, reason = [], str(exc)
                    if not found:
                        reason = reason or "The lookup found nothing"
                    elif found[0]["confidence"] != "high":
                        reason = found[0].get("note") or "The lookup was not confident"
                    elif not router.on_map(found[0]["lat"], found[0]["lon"]):
                        reason = "Outside the loaded map region"
                    else:
                        spot = (found[0]["lat"], found[0]["lon"])
            if spot is not None:
                addr = save_address(db, f["street"], f["unit"], f["city"], f["state"], f["zip"], *spot)
                addr.usual_driver_id = owner.id if owner is not None else addr.usual_driver_id
                addr.notes = f["notes"] or addr.notes
                db.flush()
                book.add(addr)
                job["saved"] += 1
            else:
                waiting = db.get(PendingAddress, key) or PendingAddress(norm_key=key)
                waiting.street, waiting.unit, waiting.city = f["street"], f["unit"], f["city"]
                waiting.state, waiting.zip = f["state"], f["zip"]
                waiting.usual_driver_id = owner.id if owner is not None else None
                waiting.notes, waiting.reason = f["notes"], reason[:200]
                db.add(waiting)
                job["pending"] += 1
            db.commit()
        job.update(done=len(rows), status="done")
    except Exception as exc:  # keep the reason for the dispatcher instead of a silent stop
        db.rollback()
        job.update(status="error", message=f"The import stopped: {exc}")
    finally:
        _mark_plans_stale(db)
        db.commit()
        db.close()


@app.post("/api/import/addresses")
def import_start(body: ImportIn, db: Session = Depends(get_db)):
    """Load an existing address list in one go. Runs in the background."""
    rows = split_rows(body.text)
    if not rows:
        bad("Nothing to read. Copy the rows in Excel and paste them here.")
    layout = body.layout or _import_layout(db, rows)
    layout = [(r if r in IMPORT_ROLES else "extra") for r in layout][: len(rows[0])]
    layout += ["extra"] * (len(rows[0]) - len(layout))
    if "street" not in layout or "zip" not in layout:
        bad("Mark which columns hold the street address and the zip code.")
    with _import_lock:
        if _import_job.get("status") == "running":
            bad("An import is already running.", 409)
        _import_job.clear()
        _import_job.update(status="running", total=len(rows), done=0, saved=0, updated=0, pending=0,
                           problems=[], message="")
    threading.Thread(target=_run_import, args=(rows, layout, body.auto_save), daemon=True).start()
    return dict(_import_job)


@app.get("/api/import/status")
def import_status():
    return dict(_import_job)


def pending_out(p: PendingAddress) -> dict:
    return {"key": p.norm_key, "street": p.street, "unit": p.unit, "city": p.city, "state": p.state,
            "zip": p.zip, "usual_driver_id": p.usual_driver_id, "notes": p.notes or "", "reason": p.reason or ""}


@app.get("/api/pending")
def list_pending(db: Session = Depends(get_db)):
    """Imported addresses that still need their location checked on a map."""
    return [pending_out(p) for p in db.query(PendingAddress).order_by(PendingAddress.zip, PendingAddress.street)]


class PendingConfirmIn(BaseModel):
    key: str
    lat: float
    lon: float


@app.post("/api/pending/confirm")
def confirm_pending(body: PendingConfirmIn, db: Session = Depends(get_db)):
    p = db.get(PendingAddress, body.key) or bad("Address not found", 404)
    if get_router().ready and not get_router().on_map(body.lat, body.lon):
        bad("That location is outside the loaded map region.")
    addr = save_address(db, p.street, p.unit, p.city, p.state, p.zip, body.lat, body.lon)
    _mark_plans_stale(db)
    db.commit()
    return address_out(addr)


class PendingDeleteIn(BaseModel):
    key: str


@app.post("/api/pending/discard")
def discard_pending(body: PendingDeleteIn, db: Session = Depends(get_db)):
    p = db.get(PendingAddress, body.key) or bad("Address not found", 404)
    db.delete(p)
    db.commit()
    return {"ok": True}


# -------------------------------------------------------- backup and restore

DRIVER_FIELDS = ["name", "kind", "color", "start_time", "start_label", "start_lat", "start_lon", "end_label", "end_lat",
                 "end_lon", "avoid_highways", "max_stops", "max_route_minutes", "zip_codes", "locked"]
ADDRESS_FIELDS = ["street", "unit", "city", "state", "zip", "norm_key", "building_key", "aliases", "lat", "lon", "notes"]


BACKUP_DIR = os.environ.get("BACKUP_DIR", "").strip()
BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", "30") or 30)


def backup_data(db: Session) -> dict:
    return {
        "app": "route-planner", "version": 2, "exported_at": datetime.now().isoformat(timespec="seconds"),
        "settings": {row.key: row.value for row in db.query(Setting).all()},
        "drivers": [{"id": d.id, **{f: getattr(d, f) for f in DRIVER_FIELDS}} for d in db.query(Driver).all()],
        "addresses": [
            {**{f: getattr(a, f) for f in ADDRESS_FIELDS}, "usual_driver_id": a.usual_driver_id}
            for a in db.query(KnownAddress).all()
        ],
        "pending": [pending_out(p) for p in db.query(PendingAddress).all()],
    }


def write_backup_file() -> str:
    """Write today's backup into the mounted backup folder and drop the oldest ones."""
    import json
    from pathlib import Path

    if not BACKUP_DIR:
        raise RuntimeError("No backup folder is set up.")
    folder = Path(BACKUP_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    try:
        data = backup_data(db)
    finally:
        db.close()
    path = folder / f"route-planner-backup-{date.today().isoformat()}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(path)
    files = sorted(folder.glob("route-planner-backup-*.json"))
    for old in files[:-BACKUP_KEEP]:
        old.unlink(missing_ok=True)
    return path.name


def _backup_loop() -> None:
    """Save a backup shortly after start-up and then every few hours (one file per day)."""
    import time

    if not BACKUP_DIR:
        return
    time.sleep(20)
    while True:
        try:
            write_backup_file()
        except Exception:
            pass
        time.sleep(4 * 3600)


@app.get("/api/backup/files")
def backup_files():
    from pathlib import Path

    if not BACKUP_DIR:
        return {"enabled": False, "files": [], "keep": BACKUP_KEEP}
    files = sorted(Path(BACKUP_DIR).glob("route-planner-backup-*.json"), reverse=True)
    return {"enabled": True, "keep": BACKUP_KEEP,
            "files": [{"name": f.name, "bytes": f.stat().st_size} for f in files[:60]]}


@app.post("/api/backup/save")
def backup_save_now():
    try:
        return {"ok": True, "name": write_backup_file()}
    except Exception as exc:
        bad(f"The backup could not be written: {exc}")


@app.get("/api/backup")
def backup(db: Session = Depends(get_db)):
    """Everything that would be painful to re-enter: drivers, addresses, usual stops, notes, settings."""
    data = backup_data(db)
    import json

    return Response(
        content=json.dumps(data, indent=1), media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="route-planner-backup-{date.today().isoformat()}.json"'},
    )


@app.post("/api/restore")
def restore(data: dict, db: Session = Depends(get_db)):
    """Replace drivers, addresses and settings with a backup file. Day plans are cleared."""
    if data.get("app") != "route-planner" or not isinstance(data.get("drivers"), list) \
            or not isinstance(data.get("addresses"), list):
        bad("That file is not a Route Planner backup.")
    try:
        db.query(PlanStop).delete()
        db.query(Plan).delete()
        db.query(KnownAddress).delete()
        db.query(PendingAddress).delete()
        db.query(Driver).delete()
        db.query(Setting).delete()
        db.flush()
        new_id: dict[int, int] = {}
        for item in data["drivers"]:
            d = Driver(**{f: item.get(f) for f in DRIVER_FIELDS if f in item})
            d.zip_codes = d.zip_codes or []
            db.add(d)
            db.flush()
            new_id[item.get("id")] = d.id
        for item in data["addresses"]:
            a = KnownAddress(**{f: item.get(f) for f in ADDRESS_FIELDS if f in item})
            a.aliases = a.aliases or []
            a.usual_driver_id = new_id.get(item.get("usual_driver_id"))
            db.add(a)
        for item in data.get("pending") or []:
            db.add(PendingAddress(
                norm_key=item["key"], street=item.get("street", ""), unit=item.get("unit", ""),
                city=item.get("city", ""), state=item.get("state", ""), zip=item.get("zip", ""),
                usual_driver_id=new_id.get(item.get("usual_driver_id")), notes=item.get("notes"),
                reason=item.get("reason"),
            ))
        for key, value in (data.get("settings") or {}).items():
            db.add(Setting(key=str(key), value=value))
        db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        bad(f"The backup could not be loaded, and nothing was changed: {exc}")
    return {"ok": True, "drivers": len(data["drivers"]), "addresses": len(data["addresses"])}


@app.get("/api/health")
def health():
    return {"ok": True, "map_ready": get_router().ready}
