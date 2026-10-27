"""HDB resale ``storey_range`` parsing (shared across API and feature engineering).

Open-data strings are typically ``"01 TO 03"`` (inclusive storey band). Some rows
use inconsistent spacing or casing; we normalize to integer ``(lower, upper)``.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

# Vectorized extract for pandas (case-insensitive ``TO``).
STOREY_PAIR_RE_PANDAS = r"(?i)(?P<storey_lower>\d+)\s+TO\s+(?P<storey_upper>\d+)"

_RE_TO = re.compile(r"(\d+)\s+TO\s+(\d+)", re.IGNORECASE)
_RE_DASH = re.compile(r"(\d+)\s*[-–—]\s*(\d+)")
_RE_SINGLE = re.compile(r"^\s*(\d{1,3})\s*$")

# HDB point blocks are rarely above ~51 storeys; guard garbage parses.
_MAX_STOREY = 60


def parse_storey_range_bounds(storey_range_raw: Optional[str]) -> Optional[Tuple[int, int]]:
    """
    Parse a storey_range cell into inclusive integer bounds ``(lower, upper)``.

    Returns ``None`` if the value is missing or not parseable.
    """
    if storey_range_raw is None:
        return None
    text = str(storey_range_raw).strip()
    if not text:
        return None

    m = _RE_TO.search(text)
    if not m:
        m = _RE_DASH.search(text)
    if m:
        lo = int(m.group(1))
        hi = int(m.group(2))
        if lo > hi:
            lo, hi = hi, lo
        if lo < 1 or hi > _MAX_STOREY or lo > _MAX_STOREY:
            return None
        return (lo, hi)

    m = _RE_SINGLE.match(text)
    if m:
        v = int(m.group(1))
        if 1 <= v <= _MAX_STOREY:
            return (v, v)
    return None


def storey_midpoint_from_bounds(lo: int, hi: int) -> int:
    """Midpoint of an inclusive storey band (matches legacy modelling convention)."""
    return (lo + hi) // 2
