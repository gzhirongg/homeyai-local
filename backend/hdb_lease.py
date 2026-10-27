"""HDB remaining lease helpers (ingestion + shared parsing)."""

from __future__ import annotations

import math
import re
from typing import Optional

_RE_PLAIN_INT = re.compile(r"^\d+(?:\.\d+)?$")


def parse_remaining_lease_to_years(value: object) -> Optional[float]:
    """Parse open-data or legacy string/int lease values to fractional years."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return float(value)
    if isinstance(value, float):
        if math.isnan(value):
            return None
        return float(value)

    text = str(value).strip().lower()
    if not text:
        return None

    if _RE_PLAIN_INT.fullmatch(text):
        return float(text)

    years_match = re.search(r"(\d+)\s+year", text)
    months_match = re.search(r"(\d+)\s+month", text)
    if not years_match and not months_match:
        return None

    years = int(years_match.group(1)) if years_match else 0
    months = int(months_match.group(1)) if months_match else 0
    return years + (months / 12.0)


def compute_remaining_lease_years(
    sale_year: int,
    lease_commence_year: int,
    *,
    total_lease_years: int = 99,
) -> int:
    """99-year lease remaining at sale year (clamped 0–99)."""
    years = total_lease_years - (int(sale_year) - int(lease_commence_year))
    return max(0, min(total_lease_years, years))
