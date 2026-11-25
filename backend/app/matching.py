"""Matching a day's rows to the list of known addresses."""

from __future__ import annotations

from sqlalchemy.orm import Session

from .models import KnownAddress, PlanStop
from .parsing import building_key, norm_key, normalize_unit, row_problem, street_similarity, street_type, zip5

POSSIBLE_THRESHOLD = 0.8


class AddressBook:
    """All known addresses, loaded once so a whole paste can be matched quickly."""

    def __init__(self, db: Session):
        self.all = db.query(KnownAddress).all()
        self.by_key: dict[str, KnownAddress] = {}
        self.by_zip: dict[str, list[KnownAddress]] = {}
        for a in self.all:
            self.add(a)

    def add(self, a: KnownAddress) -> None:
        self.by_key[a.norm_key] = a
        for alias in a.aliases or []:
            self.by_key.setdefault(alias, a)
        self.by_zip.setdefault(zip5(a.zip), []).append(a)

    def possible(self, street: str, unit: str, zip_code: str) -> list[KnownAddress]:
        """Every known address that nearly matches, closest first.

        Same house number, unit and zip, with a similar street name. A different kind of
        street ("Oak St" against "Oak Ct") is listed too, but after the plain misspellings,
        because it is more likely a different place than a typo.
        """
        found = []
        want_unit, want_type = normalize_unit(unit), street_type(street)
        for a in self.by_zip.get(zip5(zip_code), []):
            if normalize_unit(a.unit) != want_unit:
                continue
            score = street_similarity(street, a.street)
            if score > POSSIBLE_THRESHOLD:
                other_type = bool(want_type and street_type(a.street) and street_type(a.street) != want_type)
                found.append((other_type, -score, a.street, a))
        found.sort(key=lambda t: t[:3])
        return [t[3] for t in found]


def match_stop(stop: PlanStop, book: AddressBook) -> None:
    """Set the stop's match state: matched, possible, new or invalid."""
    stop.address_id = None
    stop.address = None
    stop.candidate_address_ids = None
    stop.is_new_address = False
    stop.problem = row_problem(
        {"street": stop.street, "zip": stop.zip, "state": stop.state}
    )
    if stop.problem:
        stop.match_state = "invalid"
        return
    known = book.by_key.get(norm_key(stop.street, stop.unit, stop.zip))
    if known is not None:
        stop.match_state = "matched"
        stop.address = known
        stop.address_id = known.id
        return
    close = book.possible(stop.street, stop.unit, stop.zip)
    if close:
        stop.match_state = "possible"
        stop.candidate_address_ids = [a.id for a in close]
        return
    stop.match_state = "new"


def flag_duplicates(stops: list[PlanStop]) -> None:
    seen: dict[str, int] = {}
    for s in sorted(stops, key=lambda x: x.seq):
        s.duplicate_of_seq = None
        if s.match_state == "invalid":
            continue
        key = norm_key(s.street, s.unit, s.zip)
        if key in seen:
            s.duplicate_of_seq = seen[key]
        else:
            seen[key] = s.seq


def same_building(book: AddressBook, street: str, zip_code: str) -> KnownAddress | None:
    key = building_key(street, zip_code)
    for a in book.by_zip.get(zip5(zip_code), []):
        if a.building_key == key:
            return a
    return None
