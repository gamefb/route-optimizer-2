"""Known addresses, and imported ones still waiting for a map check."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Driver, KnownAddress, PendingAddress, PlanStop
from .shared import (
    address_out,
    bad,
    change_usual,
    locked_message,
    mark_plans_stale,
    pending_out,
    require_on_map,
    save_address,
)

router = APIRouter()


class AddressIn(BaseModel):
    usual_driver_id: int | None = None
    set_usual: bool = False
    notes: str | None = None
    lat: float | None = None
    lon: float | None = None


@router.get("/api/addresses")
def list_addresses(q: str = "", driver_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(KnownAddress)
    if driver_id is not None:
        query = query.filter(KnownAddress.usual_driver_id == driver_id)
    rows = query.order_by(KnownAddress.zip, KnownAddress.street, KnownAddress.unit).all()
    if q.strip():
        needle = q.strip().lower()
        rows = [a for a in rows if needle in f"{a.street} {a.unit} {a.city} {a.zip} {a.notes or ''}".lower()]
    return [address_out(a) for a in rows]


@router.put("/api/addresses/{address_id}")
def update_address(address_id: int, body: AddressIn, db: Session = Depends(get_db)):
    a = db.get(KnownAddress, address_id) or bad("Address not found", 404)
    if body.notes is not None:
        a.notes = body.notes.strip()  # a note changes nothing about the routes
    if body.set_usual:
        change_usual(db, a, body.usual_driver_id)
        mark_plans_stale(db)
    if body.lat is not None and body.lon is not None:
        require_on_map(body.lat, body.lon)
        a.lat, a.lon = body.lat, body.lon
        mark_plans_stale(db)
    db.commit()
    return address_out(a)


@router.delete("/api/addresses/{address_id}")
def delete_address(address_id: int, db: Session = Depends(get_db)):
    a = db.get(KnownAddress, address_id) or bad("Address not found", 404)
    owner = db.get(Driver, a.usual_driver_id) if a.usual_driver_id else None
    if owner is not None and owner.is_locked:
        bad(locked_message(owner))
    for s in db.query(PlanStop).filter(PlanStop.address_id == a.id):
        s.address_id, s.match_state, s.driver_id, s.stop_number = None, "new", None, None
        s.plan.stale = True
    db.delete(a)
    db.commit()
    return {"ok": True}


@router.get("/api/pending")
def list_pending(db: Session = Depends(get_db)):
    """Imported addresses that still need their location checked on a map."""
    return [pending_out(p) for p in db.query(PendingAddress).order_by(PendingAddress.zip, PendingAddress.street)]


class PendingConfirmIn(BaseModel):
    key: str
    lat: float
    lon: float


@router.post("/api/pending/confirm")
def confirm_pending(body: PendingConfirmIn, db: Session = Depends(get_db)):
    p = db.get(PendingAddress, body.key) or bad("Address not found", 404)
    require_on_map(body.lat, body.lon)
    addr = save_address(db, p.street, p.unit, p.city, p.state, p.zip, body.lat, body.lon)
    mark_plans_stale(db)
    db.commit()
    return address_out(addr)


class PendingDeleteIn(BaseModel):
    key: str


@router.post("/api/pending/discard")
def discard_pending(body: PendingDeleteIn, db: Session = Depends(get_db)):
    p = db.get(PendingAddress, body.key) or bad("Address not found", 404)
    db.delete(p)
    db.commit()
    return {"ok": True}
