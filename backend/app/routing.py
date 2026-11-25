"""Road routing with Valhalla, running inside the API process.

Holds one map region at a time. A new region is downloaded and built in the
background, and the old one stays in use until the new one is ready.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path

import httpx
import valhalla

DATA_DIR = Path(os.environ.get("MAP_DATA_DIR", "./data")).resolve()
UNREACHABLE = 1_000_000  # seconds or meters used when no road connects two points
MAX_SNAP_M = 1500  # an address further than this from any road is outside the map
RECENT_TABLES = 8  # travel tables kept in memory, so re-ordering a route does not ask for them again


class RoutingError(Exception):
    pass


class Router:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.data_dir / "region.json"
        self._lock = threading.Lock()
        self._actor = None
        self._tables: OrderedDict[tuple, tuple[list, list]] = OrderedDict()
        self._build_thread: threading.Thread | None = None
        self.state = {"status": "none", "name": "", "url": "", "message": "", "dir": "", "built_at": None}
        self.pending = None  # progress of a build in flight
        self._load_state()

    # ------------------------------------------------------------- lifecycle

    def _load_state(self) -> None:
        if self.state_file.exists():
            try:
                self.state.update(json.loads(self.state_file.read_text()))
            except Exception:
                pass
        if self.state.get("dir") and Path(self.state["dir"]).exists():
            try:
                self._actor = valhalla.Actor(str(Path(self.state["dir"]) / "valhalla.json"))
                self.state["status"] = "ready"
            except Exception as exc:
                self.state.update(status="error", message=f"Could not load map: {exc}")
        elif self.state.get("status") == "ready":
            self.state.update(status="none", message="Map files are missing")

    def _save_state(self) -> None:
        self.state_file.write_text(json.dumps(self.state))

    @property
    def ready(self) -> bool:
        return self._actor is not None

    def info(self) -> dict:
        out = dict(self.state)
        out.pop("dir", None)
        out["ready"] = self.ready
        out["pending"] = self.pending
        return out

    # ----------------------------------------------------------------- build

    @staticmethod
    def _write_config(region_dir: Path) -> Path:
        tiles = region_dir / "tiles"
        tiles.mkdir(parents=True, exist_ok=True)
        cfg = valhalla.get_config(tile_extract="", tile_dir=str(tiles), verbose=False)
        cfg["mjolnir"]["admin"] = str(region_dir / "admins.sqlite")
        cfg["mjolnir"]["timezone"] = str(region_dir / "tz_world.sqlite")
        cfg["mjolnir"]["concurrency"] = max(1, (os.cpu_count() or 2) - 1)
        # The defaults are sized for a public server. A day's plan needs a table
        # of every stop against every stop, and a route through all of a driver's stops.
        cfg["service_limits"]["auto"].update({
            "max_locations": 2000,
            "max_matrix_location_pairs": 4_000_000,
            "max_matrix_distance": 5_000_000.0,
            "max_distance": 5_000_000.0,
        })
        path = region_dir / "valhalla.json"
        path.write_text(json.dumps(cfg))
        return path

    def start_build(self, name: str, url: str) -> None:
        """Download a map file (.osm.pbf) and build routing tiles from it, in the background."""
        if self._build_thread and self._build_thread.is_alive():
            raise RoutingError("A map is already being prepared. Wait for it to finish.")
        self.pending = {"name": name, "url": url, "status": "downloading", "message": "Starting download"}
        self._build_thread = threading.Thread(target=self._build, args=(name, url), daemon=True)
        self._build_thread.start()

    def build_now(self, name: str, url: str) -> None:
        """Same as start_build but waits until it is done. Used by tests."""
        self.pending = {"name": name, "url": url, "status": "downloading", "message": ""}
        self._build(name, url)
        if self.state["status"] != "ready":
            raise RoutingError(self.state.get("message") or "Map build failed")

    def _fetch(self, url: str, dest: Path) -> None:
        if url.startswith("file://") or url.startswith("/"):
            src = Path(url.replace("file://", "", 1))
            if not src.exists():
                raise RoutingError(f"Map file not found: {src}")
            shutil.copyfile(src, dest)
            return
        with httpx.stream("GET", url, follow_redirects=True, timeout=60) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length") or 0)
            done, last = 0, 0.0
            with open(dest, "wb") as fh:
                for chunk in resp.iter_bytes(1 << 20):
                    fh.write(chunk)
                    done += len(chunk)
                    if time.monotonic() - last > 1:
                        last = time.monotonic()
                        size = f"{done / 1e6:.0f} MB" + (f" of {total / 1e6:.0f} MB" if total else "")
                        self.pending["message"] = f"Downloading map: {size}"

    def _build(self, name: str, url: str) -> None:
        stamp = hashlib.sha1(f"{url}{time.time()}".encode()).hexdigest()[:10]
        region_dir = self.data_dir / "regions" / stamp
        try:
            region_dir.mkdir(parents=True, exist_ok=True)
            pbf = region_dir / "map.osm.pbf"
            self._fetch(url, pbf)
            self.pending.update(status="building", message="Building the road network. This can take a while for a large region.")
            cfg = self._write_config(region_dir)
            proc = subprocess.run(
                [sys.executable, "-m", "valhalla", "valhalla_build_tiles", "-c", str(cfg), str(pbf)],
                capture_output=True, text=True,
            )
            tiles = list((region_dir / "tiles").rglob("*.gph"))
            if proc.returncode != 0 or not tiles:
                tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
                raise RoutingError("Could not build the road network. " + " ".join(tail))
            pbf.unlink(missing_ok=True)  # only the tiles are needed from here on
            actor = valhalla.Actor(str(cfg))
            old_dir = self.state.get("dir")
            with self._lock:
                self._actor = actor
                self._tables.clear()  # they belong to the old map
            self.state = {
                "status": "ready", "name": name, "url": url, "message": "",
                "dir": str(region_dir), "built_at": time.strftime("%Y-%m-%d %H:%M"),
            }
            self._save_state()
            self.pending = None
            if old_dir and old_dir != str(region_dir):
                shutil.rmtree(old_dir, ignore_errors=True)
        except Exception as exc:
            shutil.rmtree(region_dir, ignore_errors=True)
            message = str(exc) or exc.__class__.__name__
            self.pending = {"name": name, "url": url, "status": "error", "message": message}
            if not self.ready:
                self.state.update(status="error", message=message)

    # --------------------------------------------------------------- queries

    def _require(self):
        if self._actor is None:
            raise RoutingError("No map region is loaded yet. Choose a region in Settings.")
        return self._actor

    @staticmethod
    def _costing_options(avoid_highways: bool, shortest: bool) -> dict:
        opts: dict = {}
        if avoid_highways:
            # A strong preference, not a ban: a highway is still used when there is
            # no reasonable alternative. Valhalla's "shortest" switch ignores every
            # preference, so highway-averse drivers keep fastest-path costing and
            # the least-miles objective is applied to their stop order instead.
            opts["use_highways"] = 0.0
        elif shortest:
            opts["shortest"] = True
        return {"auto": opts}

    def matrix(self, points: list[tuple[float, float]], avoid_highways: bool, shortest: bool):
        """Travel time (s) and distance (m) between every pair of points.

        The last few answers are remembered: a day's places stay the same while the
        dispatcher adjusts its routes. Callers must not change the tables they get back.
        """
        actor = self._require()
        key = (tuple(points), avoid_highways, shortest)
        locs = [{"lat": lat, "lon": lon} for lat, lon in points]
        req = {
            "sources": locs, "targets": locs, "costing": "auto", "units": "kilometers",
            "costing_options": self._costing_options(avoid_highways, shortest),
        }
        try:
            with self._lock:
                if key in self._tables:
                    self._tables.move_to_end(key)
                    return self._tables[key]
                res = actor.matrix(req)
        except Exception as exc:
            raise RoutingError(f"Could not compute travel times: {exc}") from exc
        n = len(points)
        durations = [[0] * n for _ in range(n)]
        distances = [[0] * n for _ in range(n)]
        for i, row in enumerate(res["sources_to_targets"]):
            for cell in row:
                j = cell["to_index"]
                if i == j:
                    continue
                t, d = cell.get("time"), cell.get("distance")
                durations[i][j] = UNREACHABLE if t is None else int(round(t))
                distances[i][j] = UNREACHABLE if d is None else int(round(d * 1000))
        with self._lock:
            self._tables[key] = (durations, distances)
            while len(self._tables) > RECENT_TABLES:
                self._tables.popitem(last=False)
        return durations, distances

    def route_shapes(self, points: list[tuple[float, float]], avoid_highways: bool, shortest: bool) -> list[str]:
        """The road path through the points in order, as encoded polylines (precision 6)."""
        actor = self._require()
        cleaned = [points[0]] + [p for prev, p in zip(points, points[1:]) if p != prev]
        if len(cleaned) < 2:
            return []
        req = {
            "locations": [{"lat": lat, "lon": lon} for lat, lon in cleaned],
            "costing": "auto", "directions_type": "none",
            "costing_options": self._costing_options(avoid_highways, shortest),
        }
        try:
            with self._lock:
                res = actor.route(req)
        except Exception:
            return []
        return [leg["shape"] for leg in res["trip"]["legs"] if leg.get("shape")]

    def on_map(self, lat: float, lon: float) -> bool:
        """True when the point is close to a road in the loaded region."""
        actor = self._require()
        try:
            with self._lock:
                res = actor.locate({"locations": [{"lat": lat, "lon": lon}], "costing": "auto"})
        except Exception:
            return False
        from .geocode import distance_m

        for item in res or []:
            for edge in item.get("edges") or []:
                clat, clon = edge.get("correlated_lat"), edge.get("correlated_lon")
                if clat is None or distance_m(lat, lon, clat, clon) <= MAX_SNAP_M:
                    return True
        return False


_router: Router | None = None


def get_router() -> Router:
    global _router
    if _router is None:
        _router = Router()
    return _router


def set_router(router: Router) -> None:
    global _router
    _router = router
