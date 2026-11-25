"""Reading pasted spreadsheet rows and tidying addresses for matching."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

ROLES = ["street", "unit", "city", "state", "zip", "extra"]

US_STATES = {
    "AL": "ALABAMA", "AK": "ALASKA", "AZ": "ARIZONA", "AR": "ARKANSAS", "CA": "CALIFORNIA",
    "CO": "COLORADO", "CT": "CONNECTICUT", "DE": "DELAWARE", "DC": "DISTRICT OF COLUMBIA",
    "FL": "FLORIDA", "GA": "GEORGIA", "HI": "HAWAII", "ID": "IDAHO", "IL": "ILLINOIS",
    "IN": "INDIANA", "IA": "IOWA", "KS": "KANSAS", "KY": "KENTUCKY", "LA": "LOUISIANA",
    "ME": "MAINE", "MD": "MARYLAND", "MA": "MASSACHUSETTS", "MI": "MICHIGAN", "MN": "MINNESOTA",
    "MS": "MISSISSIPPI", "MO": "MISSOURI", "MT": "MONTANA", "NE": "NEBRASKA", "NV": "NEVADA",
    "NH": "NEW HAMPSHIRE", "NJ": "NEW JERSEY", "NM": "NEW MEXICO", "NY": "NEW YORK",
    "NC": "NORTH CAROLINA", "ND": "NORTH DAKOTA", "OH": "OHIO", "OK": "OKLAHOMA", "OR": "OREGON",
    "PA": "PENNSYLVANIA", "PR": "PUERTO RICO", "RI": "RHODE ISLAND", "SC": "SOUTH CAROLINA",
    "SD": "SOUTH DAKOTA", "TN": "TENNESSEE", "TX": "TEXAS", "UT": "UTAH", "VT": "VERMONT",
    "VA": "VIRGINIA", "WA": "WASHINGTON", "WV": "WEST VIRGINIA", "WI": "WISCONSIN", "WY": "WYOMING",
}
_STATE_NAMES = {name: code for code, name in US_STATES.items()}

_SUFFIXES = {
    "STREET": "ST", "AVENUE": "AVE", "AV": "AVE", "BOULEVARD": "BLVD", "DRIVE": "DR",
    "ROAD": "RD", "LANE": "LN", "COURT": "CT", "PLACE": "PL", "TERRACE": "TER",
    "CIRCLE": "CIR", "HIGHWAY": "HWY", "PARKWAY": "PKWY", "SQUARE": "SQ", "TRAIL": "TRL",
    "WAY": "WAY", "ALLEY": "ALY", "EXTENSION": "EXT", "HEIGHTS": "HTS", "POINT": "PT",
    "CRESCENT": "CRES", "TURNPIKE": "TPKE", "ROUTE": "RTE", "MOUNT": "MT", "SAINT": "ST",
    "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W",
    "NORTHEAST": "NE", "NORTHWEST": "NW", "SOUTHEAST": "SE", "SOUTHWEST": "SW",
}
_UNIT_WORDS = (
    "APARTMENT", "APT", "UNIT", "SUITE", "STE", "NUMBER", "NO", "RM", "ROOM", "LOT",
    "BLDG", "BUILDING", "FL", "FLOOR", "TRLR", "SPC", "SPACE", "PH",
)
_UNIT_RE = re.compile(r"^\s*(#|(%s)\b\.?)" % "|".join(_UNIT_WORDS), re.I)
_ZIP_RE = re.compile(r"^\d{3,5}(-\d{4})?$")
_STREET_RE = re.compile(r"^\d+[A-Za-z]?(-\d+)?\s+\S+")


# ---------------------------------------------------------------- pasted text


def split_rows(text: str) -> list[list[str]]:
    """Split pasted text into rows of cells. Excel separates cells with tabs."""
    rows = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not line.strip():
            continue
        rows.append([cell.strip() for cell in line.split("\t")])
    width = max((len(r) for r in rows), default=0)
    return [r + [""] * (width - len(r)) for r in rows]


def _fraction(values: list[str], test) -> float:
    filled = [v for v in values if v]
    if not filled:
        return 0.0
    return sum(1 for v in filled if test(v)) / len(filled)


def _is_state(value: str) -> bool:
    v = value.strip().upper().rstrip(".")
    return v in US_STATES or v in _STATE_NAMES


def _is_unit(value: str) -> bool:
    v = value.strip()
    return bool(_UNIT_RE.match(v)) or (len(v) <= 6 and bool(re.fullmatch(r"[A-Za-z0-9\-/ ]+", v)))


def _is_city(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z .'\-]{2,}", value.strip())) and not _is_state(value)


def detect_layout(rows: list[list[str]]) -> list[str]:
    """Work out what each column holds by looking at its contents.

    Returns one role per column: street, unit, city, state, zip or extra.
    """
    width = max((len(r) for r in rows), default=0)
    if width == 0:
        return []
    columns = [[r[i] if i < len(r) else "" for r in rows] for i in range(width)]
    layout = ["extra"] * width
    free = set(range(width))

    def claim(role: str, score, minimum: float) -> None:
        best, best_score = None, minimum
        for i in sorted(free):
            s = score(i)
            if s > best_score:
                best, best_score = i, s
        if best is not None:
            layout[best] = role
            free.discard(best)

    empty_share = [1 - (len([v for v in col if v]) / max(len(col), 1)) for col in columns]

    claim("zip", lambda i: _fraction(columns[i], lambda v: bool(_ZIP_RE.match(v))) * (1 - empty_share[i]), 0.6)
    claim("state", lambda i: _fraction(columns[i], _is_state) * (1 - empty_share[i]), 0.6)
    claim("street", lambda i: _fraction(columns[i], lambda v: bool(_STREET_RE.match(v))) * (1 - empty_share[i]), 0.5)
    # City: mostly letters and nearly always filled in. Prefer the column next to the state.
    state_at = layout.index("state") if "state" in layout else None

    def city_score(i: int) -> float:
        s = _fraction(columns[i], _is_city) * (1 - empty_share[i])
        if state_at is not None and i == state_at - 1:
            s += 0.2
        return s

    claim("city", city_score, 0.5)
    # Unit: short values or "Apt 4" style, often blank. Prefer the column right after the street.
    street_at = layout.index("street") if "street" in layout else None

    def unit_score(i: int) -> float:
        return _fraction(columns[i], _is_unit) if any(columns[i]) else 0.4

    beside = street_at + 1 if street_at is not None else None
    if beside in free and unit_score(beside) >= 0.4:
        # The column right after the street is the unit, even when every cell in it is blank.
        layout[beside] = "unit"
        free.discard(beside)
    else:
        claim("unit", unit_score, 0.5)
    return layout


def apply_layout(cells: list[str], layout: list[str]) -> dict:
    """Turn one row of cells into address fields using the column roles."""
    out = {"street": "", "unit": "", "city": "", "state": "", "zip": "", "extras": []}
    for i, value in enumerate(cells):
        role = layout[i] if i < len(layout) else "extra"
        if role == "extra":
            out["extras"].append(value)
        elif out[role]:
            out[role] = f"{out[role]} {value}".strip()
        else:
            out[role] = value
    out["zip"] = clean_zip(out["zip"])
    out["state"] = clean_state(out["state"])
    return out


def clean_zip(value: str) -> str:
    """Excel drops leading zeros from zip codes stored as numbers; put them back."""
    v = value.strip()
    if v.endswith(".0"):
        v = v[:-2]
    m = re.fullmatch(r"(\d{3,5})(-\d{4})?", v)
    if not m:
        return v
    return m.group(1).zfill(5) + (m.group(2) or "")


def clean_state(value: str) -> str:
    v = value.strip().upper().rstrip(".")
    return _STATE_NAMES.get(v, v)


def row_problem(fields: dict) -> str:
    if not fields["street"]:
        return "Missing street address"
    if not re.fullmatch(r"\d{5}(-\d{4})?", fields["zip"] or ""):
        return "Missing or invalid zip code"
    if fields["state"] and fields["state"] not in US_STATES:
        return "Unknown state"
    return ""


# ------------------------------------------------------------------ tidying


def _tokens(value: str) -> list[str]:
    cleaned = re.sub(r"[.,;:'\"]", "", value.upper())
    cleaned = re.sub(r"[^A-Z0-9#/\- ]", " ", cleaned)
    return [t for t in cleaned.split() if t]


def normalize_street(street: str) -> str:
    return " ".join(_SUFFIXES.get(t, t) for t in _tokens(street))


def normalize_unit(unit: str) -> str:
    tokens = [t.lstrip("#") for t in _tokens(unit)]
    tokens = [t for t in tokens if t and t not in _UNIT_WORDS]
    return "".join(tokens)


def zip5(value: str) -> str:
    return (value or "").strip()[:5]


def building_key(street: str, zip_code: str) -> str:
    return f"{normalize_street(street)}|{zip5(zip_code)}"


def norm_key(street: str, unit: str, zip_code: str) -> str:
    return f"{normalize_street(street)}|{normalize_unit(unit)}|{zip5(zip_code)}"


STREET_TYPES = set(_SUFFIXES.values()) - {"N", "S", "E", "W", "NE", "NW", "SE", "SW", "MT"}


def street_type(street: str) -> str:
    """The kind of street (ST, AVE, CT ...), or "" when the line does not end in one."""
    tokens = normalize_street(street).split()
    while tokens and tokens[-1] in ("N", "S", "E", "W", "NE", "NW", "SE", "SW"):
        tokens.pop()
    return tokens[-1] if tokens and tokens[-1] in STREET_TYPES else ""


def street_similarity(a: str, b: str) -> float:
    """How alike two street lines are, 0 to 1. House numbers must match exactly."""
    ta, tb = normalize_street(a).split(), normalize_street(b).split()
    if not ta or not tb or ta[0] != tb[0]:
        return 0.0
    return SequenceMatcher(None, " ".join(ta[1:]), " ".join(tb[1:])).ratio()
