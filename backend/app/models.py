from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

STAFF = "staff"
VOLUNTEER = "volunteer"


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20), default=STAFF)
    color: Mapped[str] = mapped_column(String(16), default="#2563eb")
    start_label: Mapped[str] = mapped_column(Text, default="")
    start_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_label: Mapped[str] = mapped_column(Text, default="")
    end_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    avoid_highways: Mapped[bool] = mapped_column(Boolean, default=False)
    start_time: Mapped[str | None] = mapped_column(String(5), nullable=True)  # optional; else the day's time
    # Volunteer-only settings. Ignored for staff.
    max_stops: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_route_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    zip_codes: Mapped[list] = mapped_column(JSON, default=list)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)

    @property
    def is_volunteer(self) -> bool:
        return self.kind == VOLUNTEER

    @property
    def is_locked(self) -> bool:
        return self.is_volunteer and bool(self.locked)

    @property
    def has_locations(self) -> bool:
        return None not in (self.start_lat, self.start_lon, self.end_lat, self.end_lon)


class KnownAddress(Base):
    __tablename__ = "addresses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    street: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str] = mapped_column(String(60), default="")
    city: Mapped[str] = mapped_column(String(120), default="")
    state: Mapped[str] = mapped_column(String(40), default="")
    zip: Mapped[str] = mapped_column(String(10), default="")
    norm_key: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    building_key: Mapped[str] = mapped_column(String(300), index=True, default="")
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    usual_driver_id: Mapped[int | None] = mapped_column(ForeignKey("drivers.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)  # gate codes, "leave at side door"
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now())


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date, unique=True, index=True)
    objective: Mapped[str] = mapped_column(String(12), default="time")  # time | distance
    working_driver_ids: Mapped[list] = mapped_column(JSON, default=list)
    layout: Mapped[list] = mapped_column(JSON, default=list)  # column roles of the pasted data
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    start_time: Mapped[str | None] = mapped_column(String(5), nullable=True)  # "09:00"; drivers leave at this time
    manual_orders: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {driver_id: [stop ids]} set by hand
    undo: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # what the last big change replaced
    stale: Mapped[bool] = mapped_column(Boolean, default=True)

    stops: Mapped[list["PlanStop"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="PlanStop.seq"
    )


class PlanStop(Base):
    __tablename__ = "plan_stops"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)  # list order (order entered)
    raw: Mapped[list] = mapped_column(JSON, default=list)  # the pasted cells
    street: Mapped[str] = mapped_column(String(200), default="")
    unit: Mapped[str] = mapped_column(String(60), default="")
    city: Mapped[str] = mapped_column(String(120), default="")
    state: Mapped[str] = mapped_column(String(40), default="")
    zip: Mapped[str] = mapped_column(String(10), default="")
    extras: Mapped[list] = mapped_column(JSON, default=list)
    # matched | possible | new | invalid
    match_state: Mapped[str] = mapped_column(String(12), default="new")
    address_id: Mapped[int | None] = mapped_column(ForeignKey("addresses.id", ondelete="SET NULL"), nullable=True)
    candidate_address_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)  # every near match, closest first
    is_new_address: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_of_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    problem: Mapped[str] = mapped_column(String(200), default="")
    # Day-only choice by the dispatcher: this stop goes to this driver today.
    manual_driver_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Filled in by the planner.
    driver_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    label: Mapped[str] = mapped_column(String(20), default="")  # usual|added|covering|manual|staff|overflow
    covering_for_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stop_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eta: Mapped[str | None] = mapped_column(String(5), nullable=True)  # estimated arrival, "10:42"
    added_time_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    added_distance_m: Mapped[int | None] = mapped_column(Integer, nullable=True)

    plan: Mapped[Plan] = relationship(back_populates="stops")
    address: Mapped[KnownAddress | None] = relationship(lazy="joined")


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON, nullable=True)


class PendingAddress(Base):
    """An imported address whose location still needs a map check.

    Its volunteer and notes are kept here and applied once the dispatcher
    confirms the location the first time the address appears on a day's list.
    """

    __tablename__ = "pending_addresses"

    norm_key: Mapped[str] = mapped_column(String(300), primary_key=True)
    street: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str] = mapped_column(String(60), default="")
    city: Mapped[str] = mapped_column(String(120), default="")
    state: Mapped[str] = mapped_column(String(40), default="")
    zip: Mapped[str] = mapped_column(String(10), default="")
    usual_driver_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
