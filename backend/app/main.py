"""Route Planner API: the app itself. The endpoints live in app/api, one module per area."""

from __future__ import annotations

import contextlib
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

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
