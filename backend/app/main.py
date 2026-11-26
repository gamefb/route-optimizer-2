"""Route Planner API: the app itself. The endpoints live in app/api, one module per area."""

from __future__ import annotations

import contextlib
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import addresses, backup, day, drivers, imports, routes, setup
from .db import ensure_schema
from .routing import RoutingError, get_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_schema()
    backup.start_loop()
    router = get_router()
    url = os.environ.get("DEFAULT_REGION_URL", "").strip()
    if url and not router.ready and router.pending is None:
        with contextlib.suppress(RoutingError):
            router.start_build(os.environ.get("DEFAULT_REGION_NAME", "Default region"), url)
    yield


app = FastAPI(title="Route Planner", lifespan=lifespan)
for area in (setup, drivers, addresses, day, routes, imports, backup):
    app.include_router(area.router)


@app.get("/api/health")
def health():
    return {"ok": True, "map_ready": get_router().ready}


def _serve_folder(url: str, env_name: str) -> None:
    folder = os.environ.get(env_name, "").strip()
    if folder and Path(folder).is_dir():
        app.mount(url, StaticFiles(directory=folder, html=True), name=env_name.lower())


# In Docker, nginx serves the interface and the help pages. Run without it (see run_local.py)
# and the API serves them itself. Registered last, so the /api routes above always win.
_serve_folder("/help", "HELP_DIR")
_serve_folder("/", "WEB_DIR")
