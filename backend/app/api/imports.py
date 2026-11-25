"""Bulk import of an existing address list."""

from __future__ import annotations

import threading

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import geocode as geo
from ..db import SessionLocal, get_db
from ..matching import AddressBook, same_building
from ..models import VOLUNTEER, Driver, PendingAddress
from ..parsing import ROLES, apply_layout, detect_layout, norm_key, row_problem
from ..routing import get_router
from .shared import bad, clean_layout, lookup, mark_plans_stale, read_rows, save_address

router = APIRouter()


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


@router.post("/api/import/preview")
def import_preview(body: ImportIn, db: Session = Depends(get_db)):
    rows = read_rows(body.text)
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
        mark_plans_stale(db)
        db.commit()
        db.close()


@router.post("/api/import/addresses")
def import_start(body: ImportIn, db: Session = Depends(get_db)):
    """Load an existing address list in one go. Runs in the background."""
    rows = read_rows(body.text)
    layout = clean_layout(body.layout or _import_layout(db, rows), len(rows[0]), IMPORT_ROLES)
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


@router.get("/api/import/status")
def import_status():
    return dict(_import_job)
