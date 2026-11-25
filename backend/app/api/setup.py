"""Settings, the map region, and free-form address lookup."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import geocode as geo
from ..db import get_db
from ..parsing import US_STATES
from ..routing import RoutingError, get_router
from .shared import (
    KEY_SETTINGS,
    bad,
    geocoder_keys,
    get_settings,
    lookup,
    mark_plans_stale,
    set_setting,
    valid_time,
    with_map_check,
)

router = APIRouter()


def settings_out(db: Session) -> dict:
    """Settings for the interface. API keys are never sent back, only whether one is saved."""
    out = get_settings(db)
    keys = geocoder_keys(out)
    for name, key in KEY_SETTINGS.items():
        out.pop(key, None)
        out[f"has_{name}_key"] = bool(keys[name])
    return out


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


@router.get("/api/settings")
def read_settings(db: Session = Depends(get_db)):
    return settings_out(db)


@router.put("/api/settings")
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
        mark_plans_stale(db)
    if body.minutes_per_stop is not None:
        if not 0 <= body.minutes_per_stop <= 120:
            bad("Minutes per stop must be between 0 and 120")
        set_setting(db, "minutes_per_stop", body.minutes_per_stop)
        mark_plans_stale(db)
    if body.default_start_time is not None:
        if not valid_time(body.default_start_time):
            bad("Start time must look like 09:00")
        set_setting(db, "default_start_time", body.default_start_time)
    if body.tile_url is not None and body.tile_url.strip():
        set_setting(db, "tile_url", body.tile_url.strip())
    db.commit()
    return settings_out(db)


class RegionIn(BaseModel):
    name: str
    url: str


@router.get("/api/region")
def region_info():
    return get_router().info()


@router.get("/api/region/catalog")
def region_catalog():
    base = "https://download.geofabrik.de/north-america/us"
    items = []
    for code, name in sorted(US_STATES.items(), key=lambda kv: kv[1]):
        slug = name.lower().replace(" ", "-")
        items.append({"name": name.title(), "url": f"{base}/{slug}-latest.osm.pbf"})
    return items


@router.post("/api/region")
def region_build(body: RegionIn):
    url = body.url.strip()
    if not (url.startswith("http://") or url.startswith("https://") or url.startswith("/")):
        bad("Give a link to an .osm.pbf map file, or a path inside the map data folder.")
    try:
        get_router().start_build(body.name.strip() or "Custom region", url)
    except RoutingError as exc:
        bad(str(exc), 409)
    return get_router().info()


class GeocodeIn(BaseModel):
    query: str


@router.post("/api/geocode")
def geocode_freeform(body: GeocodeIn, db: Session = Depends(get_db)):
    if not body.query.strip():
        bad("Type an address to look up.")
    try:
        found = lookup(db, freeform=body.query.strip())
    except geo.GeocodeError as exc:
        bad(str(exc), 502)
    return with_map_check(found)
