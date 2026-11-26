"""Run the whole app offline on a small made-up street grid.

Useful for trying the screens without downloading a real map or calling a
real address lookup. Addresses look like "37 Grid St": the number picks the
spot (row 3, column 7 of a 10 by 10 grid).

    cd backend && python -m tests.demo_server      (then open http://localhost:8000)

Build the frontend first (cd frontend && npm install && npm run build).
"""

from pathlib import Path

import uvicorn
from fastapi.staticfiles import StaticFiles

from . import conftest  # sets up a throwaway database and data folder, so it comes before the app

# isort: split
from app import geocode as geo
from app import routing
from app.main import app


def fake_geocode(provider, street="", city="", state="", zip_code="", freeform=None, keys=None):
    text = freeform or street
    try:
        number = int(text.split()[0])
    except (ValueError, IndexError):
        return []
    if number > 99:
        return []
    lat, lon = conftest.house_point(number)
    return [
        {
            "lat": lat,
            "lon": lon,
            "label": f"{text.upper()}, GRIDVILLE, OH",
            "confidence": "high",
            "note": "",
            "source": "demo",
        }
    ]


def main() -> None:
    pbf = conftest._TMP / "grid.osm.pbf"
    conftest._write_grid(pbf)
    router = routing.Router(conftest._TMP / "map")
    router.build_now("Demo grid", str(pbf))
    routing.set_router(router)
    geo.geocode = fake_geocode
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
