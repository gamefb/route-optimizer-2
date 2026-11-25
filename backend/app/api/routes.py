"""A day's routes: building them, adjusting them by hand, undo and the CSV export."""

from __future__ import annotations

import copy
import csv
import io

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import planner
from ..db import get_db
from ..models import Driver, Plan, PlanStop
from ..routing import RoutingError, get_router
from .shared import bad, change_usual, get_plan, get_settings, get_stop, locked_message, plan_out

router = APIRouter()


EXTRA_LABELS = ("added", "manual")  # stops a volunteer has today that are not their usual ones


def _built(plan: Plan) -> dict:
    """The day's routes, for an action that only makes sense once they exist."""
    if plan.result is None:
        bad("Build the routes first.")
    return plan.result


def _run(db: Session, plan: Plan) -> dict:
    try:
        settings = get_settings(db)
        return planner.compute(
            db, plan, get_router(),
            staff_balance=settings["staff_balance"], minutes_per_stop=int(settings["minutes_per_stop"] or 0),
        )
    except (planner.PlanError, RoutingError) as exc:
        bad(str(exc), 422)


def _apply_hand_order(db: Session, plan: Plan, driver_id: int) -> None:
    """A driver's order was arranged by hand: redo just that route, or everything if the routes are out of date."""
    try:
        minutes = int(get_settings(db)["minutes_per_stop"] or 0)
        result = planner.resequence(db, plan, get_router(), driver_id, minutes_per_stop=minutes)
    except RoutingError as exc:
        bad(str(exc), 422)
    planner.apply_result(plan, result if result is not None else _run(db, plan))


@router.post("/api/plans/{plan_id}/compute")
def compute_plan(plan_id: int, db: Session = Depends(get_db)):
    plan = get_plan(db, plan_id)
    planner.apply_result(plan, _run(db, plan))
    db.commit()
    return plan_out(db, plan)


def _snapshot(plan: Plan, label: str) -> None:
    """Remember what a big change is about to replace, so it can be undone once."""
    plan.undo = {
        "label": label,
        "usual": {str(s.address_id): s.address.usual_driver_id for s in plan.stops if s.address is not None},
        "manual": {str(s.id): s.manual_driver_id for s in plan.stops},
        "manual_orders": plan.manual_orders or {},
        "result": plan.result,
    }


@router.post("/api/plans/{plan_id}/undo")
def undo_last(plan_id: int, db: Session = Depends(get_db)):
    """Put usual stops and the day's routes back to how they were before the last big change."""
    plan = get_plan(db, plan_id)
    saved = plan.undo
    if not saved:
        bad("There is nothing to undo.")
    drivers = {d.id for d in db.query(Driver).all()}
    for s in plan.stops:
        if s.address is not None and str(s.address_id) in saved["usual"]:
            previous = saved["usual"][str(s.address_id)]
            s.address.usual_driver_id = previous if previous in drivers else None
        if str(s.id) in saved["manual"]:
            s.manual_driver_id = saved["manual"][str(s.id)]
    plan.manual_orders = saved.get("manual_orders") or {}
    plan.undo = None
    if saved.get("result"):
        planner.apply_result(plan, saved["result"])
    else:
        plan.stale = True
    db.commit()
    return plan_out(db, plan)


class MoveIn(BaseModel):
    driver_id: int | None = None


@router.post("/api/stops/{stop_id}/move")
def move_stop(stop_id: int, body: MoveIn, db: Session = Depends(get_db)):
    """Send a stop to a chosen driver for the day, or clear that choice."""
    stop = get_stop(db, stop_id)
    plan = stop.plan
    usual = db.get(Driver, stop.address.usual_driver_id) if stop.address and stop.address.usual_driver_id else None
    if usual is not None and usual.is_locked and usual.id in (plan.working_driver_ids or []) and body.driver_id != usual.id:
        bad(locked_message(usual, "move this stop"))
    if body.driver_id is not None:
        target = db.get(Driver, body.driver_id) or bad("Driver not found", 404)
        if target.id not in (plan.working_driver_ids or []):
            bad(f"{target.name} is not working this day.")
        if target.is_locked and (usual is None or usual.id != target.id):
            bad(locked_message(target, "add a stop"))
    stop.manual_driver_id = body.driver_id
    plan.stale = True
    db.flush()
    if plan.result is not None:
        planner.apply_result(plan, _run(db, plan))
    db.commit()
    return plan_out(db, plan)


def _make_usual(db: Session, plan: Plan, stop: PlanStop, result: dict) -> None:
    driver = db.get(Driver, stop.driver_id) if stop.driver_id else None
    if driver is None or not driver.is_volunteer:
        bad("Only a stop on a volunteer's route can become a usual stop.")
    if stop.label not in EXTRA_LABELS:
        bad("This stop already belongs to a volunteer. Change its usual volunteer on the Addresses page.")
    change_usual(db, stop.address, driver.id)
    stop.label, stop.manual_driver_id = "usual", None
    a = result["assignments"].get(str(stop.id))
    if a:
        a["label"] = "usual"


def _make_stops_usual(db: Session, plan: Plan, stops: list[PlanStop], undo_label: str) -> dict:
    """Save these stops as their volunteer's usual stops, remembering how things were so it can be undone."""
    result = copy.deepcopy(_built(plan))
    _snapshot(plan, undo_label)
    for stop in stops:
        _make_usual(db, plan, stop, result)
    plan.result = result
    db.commit()
    return plan_out(db, plan)


@router.post("/api/stops/{stop_id}/make-usual")
def make_usual(stop_id: int, db: Session = Depends(get_db)):
    stop = get_stop(db, stop_id)
    return _make_stops_usual(db, stop.plan, [stop], "making a stop usual")


@router.post("/api/plans/{plan_id}/make-all-usual")
def make_all_usual(plan_id: int, body: MoveIn, db: Session = Depends(get_db)):
    plan = get_plan(db, plan_id)
    extras = [s for s in plan.stops if s.driver_id == body.driver_id and s.label in EXTRA_LABELS]
    return _make_stops_usual(db, plan, extras, "making all added stops usual")


class OrderIn(BaseModel):
    driver_id: int
    stop_ids: list[int]


@router.post("/api/plans/{plan_id}/set-order")
def set_order(plan_id: int, body: OrderIn, db: Session = Depends(get_db)):
    """Set a driver's whole stop order by hand (used by drag and drop)."""
    plan = get_plan(db, plan_id)
    route = next((r for r in _built(plan)["routes"] if r["driver_id"] == body.driver_id), None)
    if route is None or sorted(route["stop_ids"]) != sorted(body.stop_ids):
        bad("The route changed. Rebuild the routes, then try again.")
    plan.manual_orders = {**(plan.manual_orders or {}), str(body.driver_id): body.stop_ids}
    db.flush()
    _apply_hand_order(db, plan, body.driver_id)
    db.commit()
    return plan_out(db, plan)


class ReorderIn(BaseModel):
    direction: int


@router.post("/api/stops/{stop_id}/reorder")
def reorder_stop(stop_id: int, body: ReorderIn, db: Session = Depends(get_db)):
    """Move a stop one place earlier or later in its driver's route."""
    stop = get_stop(db, stop_id)
    plan = stop.plan
    if plan.result is None or stop.driver_id is None:
        bad("Build the routes first.")
    route = next((r for r in plan.result["routes"] if r["driver_id"] == stop.driver_id), None)
    if route is None or stop.id not in route["stop_ids"]:
        bad("Rebuild the routes, then try again.")
    order = list(route["stop_ids"])
    i = order.index(stop.id)
    j = i + (1 if body.direction > 0 else -1)
    if 0 <= j < len(order):
        order[i], order[j] = order[j], order[i]
        plan.manual_orders = {**(plan.manual_orders or {}), str(stop.driver_id): order}
        db.flush()
        _apply_hand_order(db, plan, stop.driver_id)
        db.commit()
    return plan_out(db, plan)


@router.post("/api/plans/{plan_id}/reset-order")
def reset_order(plan_id: int, body: MoveIn, db: Session = Depends(get_db)):
    """Drop the hand-arranged order for one driver and go back to the automatic one."""
    plan = get_plan(db, plan_id)
    plan.manual_orders = {k: v for k, v in (plan.manual_orders or {}).items() if k != str(body.driver_id)}
    db.flush()
    if plan.result is not None:
        planner.apply_result(plan, _run(db, plan))
    db.commit()
    return plan_out(db, plan)


@router.get("/api/plans/{plan_id}/export.csv")
def export_csv(plan_id: int, db: Session = Depends(get_db)):
    """One file for the day, in list order, with the driver and stop number."""
    plan = get_plan(db, plan_id)
    names = {d.id: d.name for d in db.query(Driver).all()}
    extra_width = max((len(s.extras or []) for s in plan.stops), default=0)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["List Order", "Street", "Unit", "City", "State", "Zip"]
        + [f"Extra {i + 1}" for i in range(extra_width)]
        + ["Driver", "Stop Number", "Estimated Arrival", "Notes"]
    )
    for s in sorted(plan.stops, key=lambda x: x.seq):
        extras = list(s.extras or []) + [""] * (extra_width - len(s.extras or []))
        writer.writerow(
            [s.seq, s.street, s.unit, s.city, s.state, s.zip] + extras
            + [names.get(s.driver_id, "") if s.driver_id else "", s.stop_number or "",
               s.eta or "", (s.address.notes or "") if s.address else ""]
        )
    return Response(
        content=buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="routes-{plan.day.isoformat()}.csv"'},
    )
