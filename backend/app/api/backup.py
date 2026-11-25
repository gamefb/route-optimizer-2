"""Backup and restore of drivers, addresses and settings."""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..db import SessionLocal, get_db
from ..models import Driver, KnownAddress, PendingAddress, Plan, PlanStop, Setting
from .shared import bad, pending_out

router = APIRouter()


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
    if not BACKUP_DIR:
        return
    time.sleep(20)
    while True:
        with contextlib.suppress(Exception):
            write_backup_file()
        time.sleep(4 * 3600)


def start_loop() -> None:
    threading.Thread(target=_backup_loop, daemon=True).start()


@router.get("/api/backup/files")
def backup_files():
    if not BACKUP_DIR:
        return {"enabled": False, "files": [], "keep": BACKUP_KEEP}
    files = sorted(Path(BACKUP_DIR).glob("route-planner-backup-*.json"), reverse=True)
    return {"enabled": True, "keep": BACKUP_KEEP,
            "files": [{"name": f.name, "bytes": f.stat().st_size} for f in files[:60]]}


@router.post("/api/backup/save")
def backup_save_now():
    try:
        return {"ok": True, "name": write_backup_file()}
    except Exception as exc:
        bad(f"The backup could not be written: {exc}")


@router.get("/api/backup")
def backup(db: Session = Depends(get_db)):
    """Everything that would be painful to re-enter: drivers, addresses, usual stops, notes, settings."""
    return Response(
        content=json.dumps(backup_data(db), indent=1), media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="route-planner-backup-{date.today().isoformat()}.json"'},
    )


@router.post("/api/restore")
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
