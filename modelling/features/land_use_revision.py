"""Point-in-time choice of Master Plan Land Use GeoJSON keyed by transaction month."""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime
from pathlib import Path

from modelling.storage.minio_io import list_object_keys_with_prefix, minio_client

DEFAULT_BUCKET = "datasets"
DEFAULT_PREFIX = "raw/datagovsg/MasterPlan/LandUseLayer"
_YEAR_FROM_NAME = re.compile(r"(?:20(?:0[3-9]|1[0-9]|2[0-9])|203[0-9])")


def _parse_year(text: str) -> int | None:
    hits = sorted({int(y) for y in _YEAR_FROM_NAME.findall(text)})
    # Prefer plausible masterplan years inside 2003–2035 band
    for y in reversed(hits):
        if 2003 <= y <= 2035:
            return int(y)
    return None


def discover_revision_keys(
    *,
    bucket: str = DEFAULT_BUCKET,
    prefix: str = DEFAULT_PREFIX,
    extensions: tuple[str, ...] = (".geojson", ".json", ".GEOJSON"),
) -> list[tuple[int, str]]:
    """Parse years from MinIO keys; returns sorted (year asc, full object key)."""
    client = minio_client()
    keys = list_object_keys_with_prefix(bucket, prefix, client=client)
    items: list[tuple[int, str]] = []
    for k in keys:
        lowered = str(k).lower()
        if not any(lowered.endswith(ext.lower()) for ext in extensions):
            continue
        y = _parse_year(Path(k).name.replace(".", "_"))
        if y is None:
            y = _parse_year(k)
        if y is None:
            continue
        items.append((y, k))
    items.sort(key=lambda x: (x[0], x[1]))
    return items


def effective_date_for_revision_year(year: int) -> date:
    """Default PIT cutoff: planners treat the layer as authoritative from Jan 1 of that edition year."""
    return date(year, 1, 1)


def end_of_calendar_month(month_ym: str) -> date:
    """Last calendar day for ``YYYY-MM`` (inclusive cutoff for revision comparison)."""
    d0 = datetime.strptime(month_ym.strip()[:7] + "-01", "%Y-%m-%d").date()
    _, last_day = calendar.monthrange(d0.year, d0.month)
    return date(d0.year, d0.month, last_day)


def revision_key_for_tx_month(
    month_ym: str,
    catalog: list[tuple[int, str]] | None = None,
) -> str | None:
    """Latest Land Use GeoJSON revision known as-of transaction month."""
    revisions = catalog or discover_revision_keys()
    if not revisions:
        return None
    tx_cutoff = end_of_calendar_month(month_ym)
    best_key: str | None = None
    best_eff: date | None = None
    for yr, obj_key in revisions:
        eff = effective_date_for_revision_year(yr)
        if eff <= tx_cutoff and (best_eff is None or eff >= best_eff):
            best_eff = eff
            best_key = obj_key
    return best_key
