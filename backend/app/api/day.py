"""A day's list: pasting rows, the review table, and matching rows to known addresses."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import geocode as geo
from ..db import get_db
from ..matching import AddressBook, flag_duplicates, match_stop, same_building
from ..models import Driver, KnownAddress, Plan, PlanStop
from ..parsing import apply_layout, clean_state, clean_zip, detect_layout, norm_key, normalize_unit
from .shared import (
    address_out,
    bad,
    clean_layout,
    get_plan,
    get_settings,
    get_stop,
    lookup,
    plan_out,
    read_rows,
    require_on_map,
    save_address,
    set_setting,
    valid_time,
    with_map_check,
)

router = APIRouter()


@router.get("/api/plans")
def list_plans(db: Session = Depends(get_db)):
    out = []
    for p in db.query(Plan).order_by(Plan.day.desc()).limit(60):
        out.append({"id": p.id, "day": p.day.isoformat(), "stops": len(p.stops), "computed": p.result is not None})
    return out


@router.get("/api/plans/by-day/{day}")
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


@router.put("/api/plans/{plan_id}")
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


@router.post("/api/plans/{plan_id}/paste")
def paste_rows(plan_id: int, body: PasteIn, db: Session = Depends(get_db)):
    plan = get_plan(db, plan_id)
    rows = read_rows(body.text)
    width = len(rows[0])
    remembered = body.layout or plan.layout or get_settings(db).get("layout") or []
    # Use the remembered layout when the pasted data has the same shape; otherwise look again.
    layout = clean_layout(remembered, width) if len(remembered) == width else detect_layout(rows)
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


@router.post("/api/plans/{plan_id}/layout")
def change_layout(plan_id: int, body: LayoutIn, db: Session = Depends(get_db)):
    """The dispatcher corrected which column is which. Re-read every pasted row."""
    plan = get_plan(db, plan_id)
    layout = clean_layout(body.layout, len(body.layout))
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


@router.post("/api/plans/{plan_id}/stops")
def add_stop(plan_id: int, body: StopIn, db: Session = Depends(get_db)):
    plan = get_plan(db, plan_id)
    stop = PlanStop(seq=max((s.seq for s in plan.stops), default=0) + 1, raw=[])
    _set_fields(stop, {**body.model_dump(), "extras": []})
    plan.stops.append(stop)
    db.flush()
    _rematch(db, plan, [stop])
    db.commit()
    return plan_out(db, plan)


@router.delete("/api/plans/{plan_id}/stops")
def clear_stops(plan_id: int, db: Session = Depends(get_db)):
    plan = get_plan(db, plan_id)
    plan.stops.clear()
    plan.result, plan.stale, plan.undo, plan.manual_orders = None, True, None, {}
    db.commit()
    return plan_out(db, plan)


@router.put("/api/stops/{stop_id}")
def edit_stop(stop_id: int, body: StopIn, db: Session = Depends(get_db)):
    stop = get_stop(db, stop_id)
    _set_fields(stop, {**body.model_dump(), "extras": stop.extras or []})
    _rematch(db, stop.plan, [stop])
    db.commit()
    return plan_out(db, stop.plan)


@router.delete("/api/stops/{stop_id}")
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


@router.post("/api/stops/{stop_id}/shift")
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


@router.post("/api/stops/{stop_id}/confirm-match")
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


@router.post("/api/stops/{stop_id}/mark-new")
def mark_new(stop_id: int, db: Session = Depends(get_db)):
    stop = get_stop(db, stop_id)
    if stop.match_state == "possible":
        stop.match_state, stop.candidate_address_ids = "new", None
        db.commit()
    return plan_out(db, stop.plan)


@router.get("/api/stops/{stop_id}/candidates")
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
    out = with_map_check(out)
    nearby = []
    if out:
        top, unit = out[0], normalize_unit(stop.unit)
        for a in book.by_zip.get(stop.zip[:5], []):
            if normalize_unit(a.unit) == unit and geo.distance_m(top["lat"], top["lon"], a.lat, a.lon) <= 30:
                nearby.append(address_out(a))
    return {"candidates": out, "nearby_known": nearby, "error": error}


class LocationIn(BaseModel):
    lat: float
    lon: float


@router.post("/api/stops/{stop_id}/confirm-location")
def confirm_location(stop_id: int, body: LocationIn, db: Session = Depends(get_db)):
    """The dispatcher confirmed where a new address is. Save it as a known address."""
    stop = get_stop(db, stop_id)
    if stop.match_state == "invalid":
        bad("Fix the row first: " + stop.problem)
    require_on_map(body.lat, body.lon)
    addr = save_address(db, stop.street, stop.unit, stop.city, stop.state, stop.zip, body.lat, body.lon)
    plan = stop.plan
    pending = [s for s in plan.stops if s.match_state != "matched"]
    _rematch(db, plan, pending)
    for s in pending:
        if s.address_id == addr.id:
            s.is_new_address = True
    db.commit()
    return plan_out(db, plan)
