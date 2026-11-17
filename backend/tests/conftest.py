"""Test setup: a throwaway database and a small made-up street grid to route on."""

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="routeplanner-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["MAP_DATA_DIR"] = str(_TMP / "map")

import osmium  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import geocode as geo  # noqa: E402
from app import routing  # noqa: E402
from app.db import Base, engine, ensure_schema  # noqa: E402
from app.main import app  # noqa: E402

GRID = 10
LAT0, LON0, DLAT, DLON = 40.0, -83.0, 0.0045, 0.006  # roughly 500 m blocks


def grid_point(row: int, col: int) -> tuple[float, float]:
    return (round(LAT0 + row * DLAT, 6), round(LON0 + col * DLON, 6))


def house_point(number: int) -> tuple[float, float]:
    """House number 37 sits at row 3, column 7 of the grid."""
    return grid_point(number // 10, number % 10)


def zip_for(number: int) -> str:
    return "43001" if number % 10 < 5 else "43002"


def _write_grid(path: Path) -> None:
    writer = osmium.SimpleWriter(str(path))
    node_id = lambda r, c: 1 + r * GRID + c  # noqa: E731
    for r in range(GRID):
        for c in range(GRID):
            lat, lon = grid_point(r, c)
            writer.add_node(osmium.osm.mutable.Node(id=node_id(r, c), location=(lon, lat), version=1, visible=True))
    way = 1
    for r in range(GRID):
        tags = {"highway": "motorway", "maxspeed": "110", "oneway": "no"} if r == 0 else {"highway": "residential", "name": f"Row {r} St"}
        writer.add_way(osmium.osm.mutable.Way(id=way, nodes=[node_id(r, c) for c in range(GRID)], tags=tags, version=1, visible=True))
        way += 1
    for c in range(GRID):
        writer.add_way(osmium.osm.mutable.Way(id=way, nodes=[node_id(r, c) for r in range(GRID)], tags={"highway": "residential", "name": f"Col {c} Ave"}, version=1, visible=True))
        way += 1
    writer.close()


@pytest.fixture(scope="session")
def router():
    pbf = _TMP / "grid.osm.pbf"
    _write_grid(pbf)
    r = routing.Router(_TMP / "map")
    r.build_now("Test grid", str(pbf))
    routing.set_router(r)
    return r


@pytest.fixture()
def client(router, monkeypatch):
    Base.metadata.drop_all(engine)
    ensure_schema()

    def fake_geocode(provider, street="", city="", state="", zip_code="", freeform=None, keys=None):
        text = freeform or street
        try:
            number = int(text.split()[0])
        except (ValueError, IndexError):
            return []
        if number >= 1000:  # far outside the grid
            return [{"lat": 10.0, "lon": 10.0, "label": "Somewhere else", "confidence": "low", "note": "", "source": "test"}]
        lat, lon = house_point(number)
        return [{"lat": lat, "lon": lon, "label": f"{text} (found)", "confidence": "high", "note": "", "source": "test"}]

    monkeypatch.setattr(geo, "geocode", fake_geocode)
    with TestClient(app) as c:
        yield c
