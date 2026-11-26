"""Building a day's plan: who takes which stop, in what order.

Two passes, so volunteers are used to the fullest their limits allow:
  1. Volunteers get their usual stops, then spare room is filled with extras.
  2. Staff split whatever is left.

compute() runs the steps in order; each step is a function of its own below.
resequence() redoes only the last step for one driver, for an order arranged by hand.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from . import optimizer
from .models import Driver, Plan, PlanStop
from .optimizer import Job, Vehicle, insertion_delta, path_cost
from .parsing import zip5
from .routing import Router

SKILL_OPEN = 900_000
SKILL_ZIP_BASE = 1_000_000
PRIORITY_PINNED = 100
STAFF_SHARE_SLACK = 1.2  # a staff driver may take up to 20% more than an even share
TIME_SHARE_SLACKS = (1.15, 1.3, 1.5, 1.8)  # how far over an even share of driving time, tried in turn

# Given a stop and the driver it is on: the stop's label, and the volunteer it would usually go to.
Tag = Callable[[int, Driver], tuple[str, int | None]]


class PlanError(Exception):
    pass


def working_drivers(db: Session, plan: Plan) -> list[Driver]:
    ids = set(plan.working_driver_ids or [])
    return [d for d in db.query(Driver).order_by(Driver.kind.desc(), Driver.name).all() if d.id in ids]


def clock(start: str, seconds: float) -> str:
    """Clock time a number of seconds after a start time such as "09:00"."""
    try:
        h, m = (int(x) for x in start.split(":"))
    except ValueError:
        h, m = 9, 0
    total = (h * 60 + m + round(seconds / 60)) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def _zips(d: Driver) -> list[str]:
    """A volunteer's assigned zip codes."""
    return [zip5(z) for z in (d.zip_codes or []) if str(z).strip()]


def _unlimited(d: Driver) -> bool:
    """A volunteer with no limits at all (and not locked) shares the leftover stops like staff."""
    return d.is_volunteer and not d.is_locked and not d.max_stops and not d.max_route_minutes and not _zips(d)


# ------------------------------------------------------------- the day's data


@dataclass
class _Day:
    """What every step needs: the day's stops and drivers, and the travel tables between their places."""

    router: Router
    objective: str  # "time" or "distance"
    stops: dict[int, PlanStop]  # by stop id, in list order
    drivers: list[Driver]  # working today, with a start and end location
    all_drivers: dict[int, Driver]
    warnings: list[str]
    points: list[tuple[float, float]]  # every distinct place; the travel tables use the same order
    stop_loc: dict[int, int]  # stop id -> its place in points
    start_loc: dict[int, int]  # driver id -> its place in points
    end_loc: dict[int, int]
    tables: dict[str, tuple[list, list]] = field(default_factory=dict)  # profile -> (durations, distances)

    @staticmethod
    def profile(d: Driver) -> str:
        return "nohw" if d.avoid_highways else "hw"

    def load_tables(self, drivers: list[Driver]) -> None:
        """Fetch the travel tables these drivers need: one for normal driving, one for avoiding highways."""
        for d in drivers:
            if self.profile(d) not in self.tables:
                self.tables[self.profile(d)] = self.router.matrix(
                    self.points, d.avoid_highways, self.objective == "distance"
                )

    def durations(self, d: Driver) -> list:
        return self.tables[self.profile(d)][0]

    def distances(self, d: Driver) -> list:
        return self.tables[self.profile(d)][1]

    def vehicle(self, d: Driver, skills: set[int], **limits) -> Vehicle:
        return Vehicle(d.id, self.start_loc[d.id], self.end_loc[d.id], self.profile(d), skills, **limits)

    def job(self, stop_id: int, skills: set[int], priority: int = 0) -> Job:
        return Job(stop_id, self.stop_loc[stop_id], skills, priority)

    def trip(self, table: list, d: Driver, stop_ids: list[int]) -> int:
        """Total of one table (time or distance) along a driver's start, these stops in order, and their end."""
        return path_cost(table, self.start_loc[d.id], [self.stop_loc[i] for i in stop_ids], self.end_loc[d.id])

    def solve(self, vehicles: list[Vehicle], jobs: list[Job]) -> tuple[dict[int, list[int]], list[int]]:
        return optimizer.solve(vehicles, jobs, self.tables, self.objective)


def _load_day(db: Session, plan: Plan, router: Router) -> _Day:
    stops = list(plan.stops)
    not_ready = [s for s in stops if s.match_state != "matched" or s.address is None]
    if not_ready:
        raise PlanError(f"{len(not_ready)} row(s) still need attention before routes can be built.")
    if not stops:
        raise PlanError("There are no stops for this day yet.")

    warnings: list[str] = []
    drivers = []
    for d in working_drivers(db, plan):
        if d.has_locations:
            drivers.append(d)
        else:
            warnings.append(f"{d.name} has no start and end location and was left out.")
    if not drivers:
        raise PlanError("No working driver has a start and end location set.")

    # Every distinct place gets one row in the travel tables.
    points: list[tuple[float, float]] = []
    index: dict[tuple[float, float], int] = {}

    def loc(lat: float, lon: float) -> int:
        key = (round(lat, 6), round(lon, 6))
        if key not in index:
            index[key] = len(points)
            points.append(key)
        return index[key]

    return _Day(
        router=router,
        objective=plan.objective if plan.objective in ("time", "distance") else "time",
        stops={s.id: s for s in stops},
        drivers=drivers,
        all_drivers={d.id: d for d in db.query(Driver).all()},
        warnings=warnings,
        points=points,
        stop_loc={s.id: loc(s.address.lat, s.address.lon) for s in stops},
        start_loc={d.id: loc(d.start_lat, d.start_lon) for d in drivers},
        end_loc={d.id: loc(d.end_lat, d.end_lon) for d in drivers},
    )


# ------------------------------------------- who each stop is tied to, and why


@dataclass
class _Ties:
    pinned: dict[int, int] = field(default_factory=dict)  # stop id -> the driver it must go to
    reason: dict[int, str] = field(default_factory=dict)  # why it is pinned: "manual" or "usual"
    covering: dict[int, int] = field(default_factory=dict)  # stop id -> its usual volunteer, who is off today
    overflow: dict[int, int] = field(default_factory=dict)  # stop id -> the volunteer whose limit it did not fit

    def usual_volunteer(self, stop_id: int) -> int | None:
        """The volunteer a stop would normally go to, when it ended up with someone else."""
        return self.overflow.get(stop_id) or self.covering.get(stop_id)

    def tag(self, stop_id: int, d: Driver) -> tuple[str, int | None]:
        if stop_id in self.pinned:
            label = self.reason[stop_id]
        elif stop_id in self.overflow:
            label = "overflow"
        elif stop_id in self.covering:
            label = "covering"
        else:
            label = "added" if d.is_volunteer else "staff"
        return label, self.usual_volunteer(stop_id)


def _tie_stops(day: _Day) -> _Ties:
    """Before any optimizing: a stop moved by hand goes where it was sent, a usual stop to its volunteer."""
    ties = _Ties()
    working = {d.id for d in day.drivers}
    for s in day.stops.values():
        usual = day.all_drivers.get(s.address.usual_driver_id) if s.address.usual_driver_id else None
        if usual is not None and not usual.is_volunteer:
            usual = None
        if s.manual_driver_id in working:
            ties.pinned[s.id], ties.reason[s.id] = s.manual_driver_id, "manual"
        elif usual is not None:
            if usual.id in working:
                ties.pinned[s.id], ties.reason[s.id] = usual.id, "usual"
            else:
                ties.covering[s.id] = usual.id
    return ties


# -------------------------------------------------------------- the two passes


def _volunteer_pass(day: _Day, ties: _Ties, volunteers: list[Driver]) -> dict[int, list[int]]:
    """Pass 1: volunteers take their own stops, then as many others as their limits allow.

    A usual stop that does not fit its volunteer's limits is released (and noted in
    ties.overflow) for the next pass. A stop moved onto a volunteer by hand stays put.
    """
    if not volunteers:
        return {}
    zips_today = sorted({zip5(s.zip) for s in day.stops.values()})
    zip_skill = {z: SKILL_ZIP_BASE + i for i, z in enumerate(zips_today)}

    vehicles = []
    for d in volunteers:
        skills = {d.id}
        limits: dict = {}
        if not d.is_locked and not _unlimited(d):
            skills.add(SKILL_OPEN)
            skills |= {zip_skill[z] for z in (_zips(d) or zips_today) if z in zip_skill}
            limits["max_tasks"] = d.max_stops
            limits["max_travel_time"] = d.max_route_minutes * 60 if d.max_route_minutes else None
        vehicles.append(day.vehicle(d, skills, **limits))

    volunteer_ids = {d.id for d in volunteers}
    jobs = []
    for s in day.stops.values():
        target = ties.pinned.get(s.id)
        if target in volunteer_ids:
            jobs.append(day.job(s.id, {target}, PRIORITY_PINNED))
        elif target is None:
            jobs.append(day.job(s.id, {SKILL_OPEN, zip_skill[zip5(s.zip)]}))

    solved, left = day.solve(vehicles, jobs)
    routes = {d.id: solved.get(d.id, []) for d in volunteers}
    for stop_id in left:
        target = ties.pinned.get(stop_id)
        if target is None:
            continue  # an extra no volunteer could take; staff will
        if ties.reason[stop_id] == "manual":
            routes[target].append(stop_id)  # the dispatcher's choice stands; the route is flagged as over its limit
        else:
            ties.overflow[stop_id] = target
            del ties.pinned[stop_id]
    return routes


def _share_out(
    day: _Day, sharers: list[Driver], jobs: list[Job], staff_balance: str
) -> tuple[dict[int, list[int]], list[int]]:
    """Pass 2: split the leftover stops among the drivers who share them, as evenly as the setting asks."""

    def vehicles(**limits) -> list[Vehicle]:
        return [day.vehicle(d, {d.id}, **limits) for d in sharers]

    if staff_balance == "stops" and len(sharers) > 1:
        cap = math.ceil(len(jobs) / len(sharers) * STAFF_SHARE_SLACK)
        solved, left = day.solve(vehicles(max_tasks=cap), jobs)
        if left:  # the even share did not fit (for example many manual moves)
            solved, left = day.solve(vehicles(), jobs)
        return solved, left

    solved, left = day.solve(vehicles(), jobs)
    if staff_balance == "time" and len(sharers) > 1:
        # Find the total driving time first, then cap each driver near an even share of it.
        # Splitting the work across drivers adds some driving, so loosen the cap until all stops fit.
        total = sum(day.trip(day.durations(d), d, solved[d.id]) for d in sharers if solved.get(d.id))
        share = total / len(sharers)
        for slack in TIME_SHARE_SLACKS:
            trial, trial_left = day.solve(vehicles(max_travel_time=max(60, int(share * slack))), jobs)
            if not trial_left:
                return trial, trial_left
    return solved, left


def _no_one_left_reason(day: _Day, ties: _Ties, volunteers: list[Driver], stop_id: int) -> str:
    if stop_id in ties.overflow:
        return f"Over {day.all_drivers[ties.overflow[stop_id]].name}'s limit, and no staff driver is working."
    if all(v.is_locked for v in volunteers):
        return "Every working volunteer is locked, and no staff driver is working."
    return "No working volunteer can take it within their limits, and no staff driver is working."


# ------------------------------------------------ order, numbers and totals


def _hand_order(plan: Plan, d: Driver, stop_ids: list[int]) -> tuple[list[int], str]:
    """The order the dispatcher arranged for this driver, if any; anything new goes on the end."""
    on_route = set(stop_ids)
    by_hand = [i for i in (plan.manual_orders or {}).get(str(d.id), []) if i in on_route]
    if not by_hand:
        return stop_ids, "optimized"
    arranged = set(by_hand)
    return by_hand + [i for i in stop_ids if i not in arranged], "manual"


def _over_limit(day: _Day, d: Driver, stop_ids: list[int], time_s: int) -> list[str]:
    if not d.is_volunteer:
        return []
    over = []
    if d.max_stops and len(stop_ids) > d.max_stops:
        over.append(f"{len(stop_ids)} stops, limit is {d.max_stops}")
    if d.max_route_minutes and time_s > d.max_route_minutes * 60:
        over.append(f"{round(time_s / 60)} min driving, limit is {d.max_route_minutes}")
    if d.zip_codes:
        allowed = {zip5(z) for z in d.zip_codes}
        outside = [i for i in stop_ids if zip5(day.stops[i].zip) not in allowed]
        if outside:
            over.append(f"{len(outside)} stop(s) outside their zip codes")
    return over


def _route(
    day: _Day, d: Driver, stop_ids: list[int], mode: str, tag: Tag, day_start: str, service_s: int
) -> tuple[dict, dict[str, dict]]:
    """One driver's finished route, and what is saved onto each of its stops.

    Arrival at a stop is the start time, plus the driving so far, plus the time
    allowed at each earlier stop.
    """
    start_time = d.start_time or day_start  # a driver's own start time wins over the day's
    durations, distances = day.durations(d), day.distances(d)
    time_s = day.trip(durations, d, stop_ids) if stop_ids else 0
    chain = [day.start_loc[d.id]] + [day.stop_loc[i] for i in stop_ids] + [day.end_loc[d.id]]

    assignments: dict[str, dict] = {}
    driven = 0
    for n, stop_id in enumerate(stop_ids, start=1):
        before, here, after = chain[n - 1], chain[n], chain[n + 1]
        driven += durations[before][here]
        label, usual_volunteer = tag(stop_id, d)
        assignments[str(stop_id)] = {
            "driver_id": d.id,
            "label": label,
            "stop_number": n,
            "covering_for_id": usual_volunteer,
            "eta": clock(start_time, driven + service_s * (n - 1)),
            "added_time_s": insertion_delta(durations, before, here, after),
            "added_distance_m": insertion_delta(distances, before, here, after),
        }

    shapes = []
    if stop_ids:
        shapes = day.router.route_shapes([day.points[i] for i in chain], d.avoid_highways, day.objective == "distance")
    route = {
        "driver_id": d.id,
        "name": d.name,
        "kind": d.kind,
        "color": d.color,
        "locked": d.is_locked,
        "avoid_highways": d.avoid_highways,
        "order_mode": mode,
        "stop_ids": stop_ids,
        "stops": len(stop_ids),
        "time_s": time_s,
        "distance_m": day.trip(distances, d, stop_ids) if stop_ids else 0,
        "over_limit": _over_limit(day, d, stop_ids, time_s),
        "shapes": shapes,
        "start_time": start_time,
        "finish_time": clock(start_time, time_s + service_s * len(stop_ids)) if stop_ids else start_time,
        "start": [d.start_lat, d.start_lon],
        "end": [d.end_lat, d.end_lon],
        "limits": {
            "max_stops": d.max_stops,
            "max_route_minutes": d.max_route_minutes,
            "zip_codes": d.zip_codes or [],
        }
        if d.is_volunteer
        else None,
    }
    return route, assignments


def _totals(routes: list[dict]) -> dict:
    return {key: sum(r[key] for r in routes) for key in ("time_s", "distance_m", "stops")}


def _stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _service_seconds(minutes_per_stop: int) -> int:
    return max(0, int(minutes_per_stop or 0)) * 60


# ------------------------------------------------------------------ the plan


def compute(
    db: Session,
    plan: Plan,
    router: Router,
    staff_balance: str = "stops",
    minutes_per_stop: int = 0,
) -> dict:
    """Work out the plan and return it. Nothing is saved; see apply_result.

    staff_balance: how the leftover stops are shared among staff drivers.
      "stops" roughly equal stop counts, "time" roughly equal driving time,
      "off" minimize the total only (usually one staff driver gets nearly everything).
    minutes_per_stop: time allowed at each stop, used only for estimated arrival times.
      Volunteer route-time limits stay driving time only.
    """
    day = _load_day(db, plan, router)
    day.load_tables(day.drivers)
    ties = _tie_stops(day)
    volunteers = [d for d in day.drivers if d.is_volunteer]
    # Everyone who shares what the limited volunteers leave behind.
    sharers = [d for d in day.drivers if not d.is_volunteer] + [d for d in volunteers if _unlimited(d)]

    routes: dict[int, list[int]] = {d.id: [] for d in day.drivers}
    routes.update(_volunteer_pass(day, ties, volunteers))
    # Unlimited volunteers keep their usual stops but take their share in the next pass.
    for d in sharers:
        routes[d.id] = []
    taken = {stop_id for ids in routes.values() for stop_id in ids}
    remaining = [stop_id for stop_id in day.stops if stop_id not in taken]

    unassigned: list[dict] = []
    if remaining and sharers:
        jobs = [day.job(i, {ties.pinned[i]} if i in ties.pinned else set()) for i in remaining]
        solved, left = _share_out(day, sharers, jobs, staff_balance)
        for d in sharers:
            routes[d.id] = solved.get(d.id, [])
        unassigned = [{"stop_id": i, "reason": "Could not be placed on any route."} for i in left]
    elif remaining:
        unassigned = [{"stop_id": i, "reason": _no_one_left_reason(day, ties, volunteers, i)} for i in remaining]
    for item in unassigned:
        item["covering_for_id"] = ties.usual_volunteer(item["stop_id"])

    day_start = plan.start_time or "09:00"
    service_s = _service_seconds(minutes_per_stop)
    assignments: dict[str, dict] = {}
    route_out = []
    for d in day.drivers:
        stop_ids, mode = _hand_order(plan, d, routes[d.id])
        route, assigned = _route(day, d, stop_ids, mode, ties.tag, day_start, service_s)
        route_out.append(route)
        assignments.update(assigned)

    return {
        "objective": day.objective,
        "computed_at": _stamp(),
        "start_time": day_start,
        "minutes_per_stop": service_s // 60,
        "routes": route_out,
        "assignments": assignments,
        "unassigned": unassigned,
        "warnings": day.warnings,
        "totals": _totals(route_out),
    }


def resequence(db: Session, plan: Plan, router: Router, driver_id: int, minutes_per_stop: int = 0) -> dict | None:
    """Put one driver's route in the order arranged by hand, without working the whole day out again.

    Who has which stop stays exactly as built; only this driver's order, arrival
    times and totals change. Returns None when the built routes cannot be reused
    (something changed since they were built), and the caller then runs compute().
    """
    built = plan.result
    if not built or plan.stale:
        return None
    try:
        day = _load_day(db, plan, router)
    except PlanError:
        return None
    day_start = plan.start_time or "09:00"
    service_s = _service_seconds(minutes_per_stop)
    same_setup = (
        built.get("objective") == day.objective
        and built.get("start_time") == day_start
        and built.get("minutes_per_stop") == service_s // 60
        and [r["driver_id"] for r in built["routes"]] == [d.id for d in day.drivers]
    )
    d = next((x for x in day.drivers if x.id == driver_id), None)
    at = next((n for n, r in enumerate(built["routes"]) if r["driver_id"] == driver_id), None)
    if not same_setup or d is None or at is None:
        return None
    was = built["assignments"]
    stop_ids = built["routes"][at]["stop_ids"]
    if any(i not in day.stops or str(i) not in was for i in stop_ids):
        return None

    def tag(stop_id: int, _: Driver) -> tuple[str, int | None]:
        return was[str(stop_id)]["label"], was[str(stop_id)]["covering_for_id"]

    day.load_tables([d])
    stop_ids, mode = _hand_order(plan, d, stop_ids)
    route, assigned = _route(day, d, stop_ids, mode, tag, day_start, service_s)
    routes = [route if n == at else r for n, r in enumerate(built["routes"])]
    return {
        **built,
        "computed_at": _stamp(),
        "routes": routes,
        "assignments": {**was, **assigned},
        "totals": _totals(routes),
    }


def apply_result(plan: Plan, result: dict) -> None:
    """Save a computed plan onto the day's stops."""
    for s in plan.stops:
        a = result["assignments"].get(str(s.id))
        if a:
            s.driver_id, s.label, s.stop_number = a["driver_id"], a["label"], a["stop_number"]
            s.covering_for_id = a["covering_for_id"]
            s.eta = a.get("eta")
            s.added_time_s, s.added_distance_m = a["added_time_s"], a["added_distance_m"]
        else:
            s.driver_id = s.stop_number = s.covering_for_id = s.eta = None
            s.added_time_s = s.added_distance_m = None
            s.label = ""
    plan.result = result
    plan.stale = False
