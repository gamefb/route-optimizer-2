"""Turning an address into map coordinates.

Free public services, no key needed:
  - census:    US Census Bureau geocoder (US street addresses only)
  - nominatim: OpenStreetMap Nominatim (worldwide, max 1 request per second)

Paid services, used when an API key is saved in Settings (or set in .env):
  - google:    Google Geocoding API          (GOOGLE_MAPS_API_KEY)
  - mapbox:    Mapbox Geocoding API v6       (MAPBOX_ACCESS_TOKEN)
  - geocodio:  Geocodio                      (GEOCODIO_API_KEY)
"""

from __future__ import annotations

import math
import os
import threading
import time

import httpx

USER_AGENT = os.environ.get("GEOCODER_USER_AGENT", "route-planner-internal/1.0")
NOMINATIM_URL = os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org")
CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations"

_nominatim_lock = threading.Lock()
_nominatim_last = 0.0


class GeocodeError(Exception):
    pass


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _get(url: str, params: dict) -> dict | list:
    try:
        resp = httpx.get(
            url, params=params, headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        # Never echo the request address: it can carry an API key.
        raise GeocodeError(f"The lookup service answered with error {exc.response.status_code}.") from None
    except Exception as exc:  # network trouble, bad JSON
        raise GeocodeError(f"The lookup service could not be reached ({exc.__class__.__name__}).") from None


def _census(street: str, city: str, state: str, zip_code: str, freeform: str | None) -> list[dict]:
    if freeform:
        data = _get(
            f"{CENSUS_URL}/onelineaddress",
            {"address": freeform, "benchmark": "Public_AR_Current", "format": "json"},
        )
    else:
        data = _get(
            f"{CENSUS_URL}/address",
            {
                "street": street, "city": city, "state": state, "zip": zip_code[:5],
                "benchmark": "Public_AR_Current", "format": "json",
            },
        )
    out = []
    for match in (data.get("result") or {}).get("addressMatches") or []:
        coords = match.get("coordinates") or {}
        if "x" not in coords or "y" not in coords:
            continue
        found_zip = (match.get("addressComponents") or {}).get("zip", "")
        low = bool(zip_code) and bool(found_zip) and found_zip[:5] != zip_code[:5]
        out.append({
            "lat": float(coords["y"]), "lon": float(coords["x"]),
            "label": match.get("matchedAddress", ""),
            "confidence": "low" if low else "high",
            "note": "Found in a different zip code" if low else "",
            "source": "census",
        })
    return out


def _nominatim(street: str, city: str, state: str, zip_code: str, freeform: str | None) -> list[dict]:
    global _nominatim_last
    params = {"format": "jsonv2", "addressdetails": 1, "limit": 5, "countrycodes": "us"}
    if freeform:
        params["q"] = freeform
    else:
        params.update({"street": street, "city": city, "state": state, "postalcode": zip_code[:5]})
    with _nominatim_lock:  # the public service allows one request per second
        wait = 1.1 - (time.monotonic() - _nominatim_last)
        if wait > 0:
            time.sleep(wait)
        try:
            data = _get(f"{NOMINATIM_URL}/search", params)
        finally:
            _nominatim_last = time.monotonic()
    out = []
    for item in data if isinstance(data, list) else []:
        kind = item.get("addresstype") or item.get("type") or ""
        precise = kind in ("building", "house", "place", "amenity", "shop", "office", "residential") or bool(
            (item.get("address") or {}).get("house_number")
        )
        found_zip = (item.get("address") or {}).get("postcode", "")
        note = ""
        if not precise:
            note = f"Only the {kind or 'area'} was found, not the building"
        elif zip_code and found_zip and found_zip[:5] != zip_code[:5]:
            note, precise = "Found in a different zip code", False
        out.append({
            "lat": float(item["lat"]), "lon": float(item["lon"]),
            "label": item.get("display_name", ""),
            "confidence": "high" if precise else "low",
            "note": note, "source": "nominatim",
        })
    return out


def _line(street: str, city: str, state: str, zip_code: str, freeform: str | None) -> str:
    if freeform:
        return freeform
    return ", ".join(p for p in (street, city, f"{state} {zip_code[:5]}".strip()) if p)


def _google(street, city, state, zip_code, freeform, key: str) -> list[dict]:
    data = _get(
        "https://maps.googleapis.com/maps/api/geocode/json",
        {"address": _line(street, city, state, zip_code, freeform), "components": "country:US", "key": key},
    )
    status = data.get("status")
    if status not in ("OK", "ZERO_RESULTS"):
        raise GeocodeError(f"Google lookup failed: {status} {data.get('error_message', '')}".strip())
    out = []
    for r in data.get("results") or []:
        loc = (r.get("geometry") or {}).get("location") or {}
        if "lat" not in loc:
            continue
        kind = (r.get("geometry") or {}).get("location_type", "")
        precise = kind in ("ROOFTOP", "RANGE_INTERPOLATED") and not r.get("partial_match")
        out.append({
            "lat": float(loc["lat"]), "lon": float(loc["lng"]), "label": r.get("formatted_address", ""),
            "confidence": "high" if precise else "low",
            "note": "" if precise else "Only an approximate or partial match was found",
            "source": "google",
        })
    return out


def _mapbox(street, city, state, zip_code, freeform, key: str) -> list[dict]:
    data = _get(
        "https://api.mapbox.com/search/geocode/v6/forward",
        {"q": _line(street, city, state, zip_code, freeform), "country": "us", "types": "address",
         "limit": 5, "access_token": key},
    )
    out = []
    for f in data.get("features") or []:
        coords = (f.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        props = f.get("properties") or {}
        confidence = (props.get("match_code") or {}).get("confidence", "")
        precise = confidence in ("exact", "high")
        out.append({
            "lat": float(coords[1]), "lon": float(coords[0]),
            "label": props.get("full_address") or props.get("name", ""),
            "confidence": "high" if precise else "low",
            "note": "" if precise else f"Match confidence is {confidence or 'unknown'}",
            "source": "mapbox",
        })
    return out


def _geocodio(street, city, state, zip_code, freeform, key: str) -> list[dict]:
    params = {"api_key": key, "limit": 5}
    if freeform:
        params["q"] = freeform
    else:
        params.update({"street": street, "city": city, "state": state, "postal_code": zip_code[:5]})
    data = _get("https://api.geocod.io/v1.12/geocode", params)
    out = []
    for r in data.get("results") or []:
        loc = r.get("location") or {}
        if "lat" not in loc:
            continue
        kind = r.get("accuracy_type", "")
        precise = kind in ("rooftop", "point", "range_interpolation", "nearest_rooftop_match")
        out.append({
            "lat": float(loc["lat"]), "lon": float(loc["lng"]), "label": r.get("formatted_address", ""),
            "confidence": "high" if precise else "low",
            "note": "" if precise else f"Only the {kind.replace('_', ' ') or 'area'} was found",
            "source": "geocodio",
        })
    return out


PROVIDERS = {"census": _census, "nominatim": _nominatim}
KEYED_PROVIDERS = {"google": _google, "mapbox": _mapbox, "geocodio": _geocodio}
KEY_ENV = {"google": "GOOGLE_MAPS_API_KEY", "mapbox": "MAPBOX_ACCESS_TOKEN", "geocodio": "GEOCODIO_API_KEY"}
ALL_PROVIDERS = list(PROVIDERS) + list(KEYED_PROVIDERS)


def env_key(provider: str) -> str:
    return os.environ.get(KEY_ENV.get(provider, ""), "").strip()


def geocode(
    provider: str, street: str = "", city: str = "", state: str = "", zip_code: str = "",
    freeform: str | None = None, keys: dict | None = None,
) -> list[dict]:
    """Return candidate locations, best first.

    Tries the chosen provider, then the free ones, until something is found.
    A paid provider is skipped when it has no key.
    """
    keys = keys or {}
    order = [provider] + [p for p in PROVIDERS if p != provider]
    errors, tried = [], 0
    for name in order:
        try:
            if name in KEYED_PROVIDERS:
                key = (keys.get(name) or env_key(name) or "").strip()
                if not key:
                    continue
                tried += 1
                found = KEYED_PROVIDERS[name](street, city, state, zip_code, freeform, key)
            elif name in PROVIDERS:
                tried += 1
                found = PROVIDERS[name](street, city, state, zip_code, freeform)
            else:
                continue
        except GeocodeError as exc:
            errors.append(str(exc))
            continue
        if found:
            return found
    if errors and len(errors) == tried:
        raise GeocodeError("; ".join(errors))
    return []
