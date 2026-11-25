"""Drivers: staff and volunteers."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import STAFF, VOLUNTEER, Driver, KnownAddress, Plan, PlanStop
from ..parsing import clean_zip
from .shared import bad, mark_plans_stale, require_on_map, valid_time

router = APIRouter()


COLORS = ["#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed", "#0891b2", "#db2777", "#4d7c0f", "#b45309", "#475569"]


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
        if lat is not None and lon is not None:
            require_on_map(lat, lon, f"The {what} location")
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


@router.get("/api/drivers")
def list_drivers(db: Session = Depends(get_db)):
    counts = _usual_counts(db)
    return [driver_out(d, counts.get(d.id, 0)) for d in db.query(Driver).order_by(Driver.kind, Driver.name)]


@router.post("/api/drivers")
def create_driver(body: DriverIn, db: Session = Depends(get_db)):
    d = Driver()
    _fill_driver(d, body)
    if not body.color:
        d.color = COLORS[db.query(Driver).count() % len(COLORS)]
    db.add(d)
    db.commit()
    return driver_out(d)


@router.put("/api/drivers/{driver_id}")
def update_driver(driver_id: int, body: DriverIn, db: Session = Depends(get_db)):
    d = db.get(Driver, driver_id) or bad("Driver not found", 404)
    was_volunteer = d.is_volunteer
    _fill_driver(d, body)
    if was_volunteer and not d.is_volunteer:
        # Staff have no usual stops.
        db.query(KnownAddress).filter(KnownAddress.usual_driver_id == d.id).update(
            {KnownAddress.usual_driver_id: None}
        )
    mark_plans_stale(db)
    db.commit()
    return driver_out(d, _usual_counts(db).get(d.id, 0))


@router.delete("/api/drivers/{driver_id}")
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
