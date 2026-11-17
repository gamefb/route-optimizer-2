"""Deciding which driver takes which stop, and in what order, with VROOM."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import vroom


@dataclass
class Vehicle:
    id: int
    start: int  # index into the travel tables
    end: int
    profile: str  # "hw" or "nohw"
    skills: set[int] = field(default_factory=set)
    max_tasks: int | None = None
    max_travel_time: int | None = None  # seconds of driving


@dataclass
class Job:
    id: int
    location: int
    skills: set[int] = field(default_factory=set)
    priority: int = 0


def solve(
    vehicles: list[Vehicle], jobs: list[Job], tables: dict[str, tuple[list, list]], objective: str
) -> tuple[dict[int, list[int]], list[int]]:
    """Returns ({vehicle id: [job ids in driving order]}, [unassigned job ids]).

    VROOM first places as many jobs as it can (higher priority first), then
    minimizes driving time or distance depending on the objective.
    """
    routes: dict[int, list[int]] = {v.id: [] for v in vehicles}
    if not jobs:
        return routes, []
    if not vehicles:
        return routes, [j.id for j in jobs]

    problem = vroom.Input()
    for profile in {v.profile for v in vehicles}:
        durations, distances = tables[profile]
        dur = np.array(durations, dtype=np.uint32)
        dist = np.array(distances, dtype=np.uint32)
        problem.set_durations_matrix(profile=profile, matrix_input=dur)
        problem.set_distances_matrix(profile=profile, matrix_input=dist)
        if objective == "distance":
            problem.set_costs_matrix(profile=profile, matrix_input=dist)

    for v in vehicles:
        kwargs = dict(id=v.id, start=v.start, end=v.end, profile=v.profile, skills=set(v.skills))
        if v.max_tasks is not None:
            kwargs["max_tasks"] = int(v.max_tasks)
        if v.max_travel_time is not None:
            kwargs["max_travel_time"] = int(v.max_travel_time)
        problem.add_vehicle(vroom.Vehicle(**kwargs))
    for j in jobs:
        problem.add_job(vroom.Job(id=j.id, location=j.location, skills=set(j.skills), priority=j.priority))

    solution = problem.solve(exploration_level=5, nb_threads=4).to_dict()
    for route in solution.get("routes", []):
        routes[route["vehicle"]] = [s["id"] for s in route["steps"] if s["type"] == "job"]
    unassigned = [u["id"] for u in solution.get("unassigned", [])]
    return routes, unassigned


def path_cost(table: list[list[int]], start: int, stops: list[int], end: int) -> int:
    """Total of one table (time or distance) along start -> stops -> end."""
    total, here = 0, start
    for nxt in stops + [end]:
        total += table[here][nxt]
        here = nxt
    return total


def insertion_delta(table: list[list[int]], prev: int, here: int, nxt: int) -> int:
    """What a stop adds to a route, given the points before and after it."""
    return table[prev][here] + table[here][nxt] - table[prev][nxt]
