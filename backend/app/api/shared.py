"""What the endpoint modules share: errors, settings, and the pieces of a plan sent to the interface."""

from __future__ import annotations

import re
from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import geocode as geo
from ..models import Driver, KnownAddress, PendingAddress, Plan, PlanStop, Setting
from ..parsing import ROLES, building_key, norm_key, split_rows
from ..routing import get_router


def bad(message: str, status: int = 400):
    raise HTTPException(status_code=status, detail=message)


def require_on_map(lat: float, lon: float, what: str = "That location") -> None:
    """Refuse a spot the loaded map cannot route to. Before a map is loaded there is nothing to check against."""
    router = get_router()
    if router.ready and not router.on_map(lat, lon):
        bad(f"{what} is outside the loaded map region.")


def locked_message(driver: Driver, to: str = "change them") -> str:
    return f"{driver.name}'s addresses are locked. Turn the lock off to {to}."


def read_rows(text: str) -> list[list[str]]:
    """Pasted spreadsheet text as rows of cells; an empty paste is refused."""
    rows = split_rows(text)
    if not rows:
        bad("Nothing to read. Copy the rows in Excel and paste them here.")
    return rows


def valid_time(value: str) -> bool:
    return bool(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value or ""))


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


def set_setting(db: Session, key: str, value) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value


def lookup(db: Session, **kwargs) -> list[dict]:
    settings = get_settings(db)
    return geo.geocode(settings["geocoder"], keys=geocoder_keys(settings), **kwargs)


def with_map_check(candidates: list[dict]) -> list[dict]:
    router = get_router()
    for c in candidates:
        c["on_map"] = router.on_map(c["lat"], c["lon"]) if router.ready else None
    return candidates


def mark_plans_stale(db: Session) -> None:
    db.query(Plan).filter(Plan.day >= date.today()).update({Plan.stale: True})


def address_out(a: KnownAddress) -> dict:
    return {
        "id": a.id,
        "street": a.street,
        "unit": a.unit,
        "city": a.city,
        "state": a.state,
        "zip": a.zip,
        "lat": a.lat,
        "lon": a.lon,
        "usual_driver_id": a.usual_driver_id,
        "notes": a.notes or "",
    }


def pending_out(p: PendingAddress) -> dict:
    return {
        "key": p.norm_key,
        "street": p.street,
        "unit": p.unit,
        "city": p.city,
        "state": p.state,
        "zip": p.zip,
        "usual_driver_id": p.usual_driver_id,
        "notes": p.notes or "",
        "reason": p.reason or "",
    }


def change_usual(db: Session, addr: KnownAddress, new_id: int | None) -> None:
    """Change who an address usually belongs to. Locked volunteers gain and lose nothing."""
    if addr.usual_driver_id == new_id:
        return
    current = db.get(Driver, addr.usual_driver_id) if addr.usual_driver_id else None
    if current is not None and current.is_locked:
        bad(locked_message(current))
    if new_id is not None:
        target = db.get(Driver, new_id) or bad("Driver not found", 404)
        if not target.is_volunteer:
            bad("Only volunteers have usual stops.")
        if target.is_locked:
            bad(locked_message(target))
    addr.usual_driver_id = new_id


def save_address(
    db: Session, street: str, unit: str, city: str, state: str, zip_code: str, lat: float, lon: float
) -> KnownAddress:
    """Save a confirmed location as a known address (or move an existing one)."""
    key = norm_key(street, unit, zip_code)
    addr = db.query(KnownAddress).filter(KnownAddress.norm_key == key).first()
    if addr is None:
        addr = KnownAddress(
            street=street,
            unit=unit,
            city=city,
            state=state,
            zip=zip_code,
            norm_key=key,
            building_key=building_key(street, zip_code),
            aliases=[],
            lat=lat,
            lon=lon,
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


def get_plan(db: Session, plan_id: int) -> Plan:
    return db.get(Plan, plan_id) or bad("Plan not found", 404)


def get_stop(db: Session, stop_id: int) -> PlanStop:
    return db.get(PlanStop, stop_id) or bad("Stop not found", 404)


def stop_out(s: PlanStop, candidates: dict[int, KnownAddress]) -> dict:
    a = s.address
    ids = (s.candidate_address_ids or []) if s.match_state == "possible" else []
    near = [address_out(candidates[i]) for i in ids if i in candidates]
    return {
        "id": s.id,
        "seq": s.seq,
        "street": s.street,
        "unit": s.unit,
        "city": s.city,
        "state": s.state,
        "zip": s.zip,
        "extras": s.extras or [],
        "match_state": s.match_state,
        "problem": s.problem,
        "duplicate_of_seq": s.duplicate_of_seq,
        "is_new_address": s.is_new_address,
        "address_id": s.address_id,
        "lat": a.lat if a else None,
        "lon": a.lon if a else None,
        "usual_driver_id": a.usual_driver_id if a else None,
        "notes": (a.notes or "") if a else "",
        "eta": s.eta,
        "candidates": near,
        "manual_driver_id": s.manual_driver_id,
        "driver_id": s.driver_id,
        "label": s.label,
        "covering_for_id": s.covering_for_id,
        "stop_number": s.stop_number,
        "added_time_s": s.added_time_s,
        "added_distance_m": s.added_distance_m,
    }


def plan_out(db: Session, plan: Plan) -> dict:
    cand_ids = list({i for s in plan.stops for i in (s.candidate_address_ids or [])})
    candidates = {a.id: a for a in db.query(KnownAddress).filter(KnownAddress.id.in_(cand_ids))} if cand_ids else {}
    return {
        "id": plan.id,
        "day": plan.day.isoformat(),
        "objective": plan.objective,
        "working_driver_ids": plan.working_driver_ids or [],
        "layout": plan.layout or [],
        "stale": plan.stale,
        "result": plan.result,
        "start_time": plan.start_time or "09:00",
        "undo_label": (plan.undo or {}).get("label") or "",
        "sample": next((s.raw for s in plan.stops if s.raw), []),
        "stops": [stop_out(s, candidates) for s in plan.stops],
    }


def clean_layout(layout: list[str], width: int, roles: list[str] = ROLES) -> list[str]:
    """Column roles for a sheet this many columns wide: unknown roles and missing columns become "extra"."""
    out = [(r if r in roles else "extra") for r in layout][:width]
    return out + ["extra"] * (width - len(out))
