"""Harmonised HDB resale ``town`` labels and deterministic URA PA membership for aggregates.

Mirrors resale analytics behaviour in ``backend/services/geospatial_service.expand_resale_town_names``.
Used by land-area union computation and ingestion joins (**X0**).
"""

from __future__ import annotations

# CENTRAL AREA: matches Map.tsx / geospatial_service._CENTRAL_AREA_PLANNING_AREAS
CENTRAL_AREA_PLANNING_AREAS: tuple[str, ...] = (
    "DOWNTOWN CORE",
    "ORCHARD",
    "MUSEUM",
    "SINGAPORE RIVER",
    "OUTRAM",
    "NEWTON",
    "RIVER VALLEY",
    "MARINA SOUTH",
    "MARINA EAST",
    "STRAITS VIEW",
    "ROCHOR",
)


def normalize_hdb_town_label(raw: str | None) -> str:
    """Uppercase trimmed resale / catalogue / CSV town string."""
    if raw is None:
        return ""
    return " ".join(str(raw).strip().upper().split())


def planning_area_labels_for_resale_town(town_upper: str) -> tuple[str, ...]:
    """Return URA ``pln_area_n`` values (uppercase) whose union approximates the HDB town footprint."""
    t = normalize_hdb_town_label(town_upper)
    if not t:
        return ()
    if t == "CENTRAL AREA":
        return CENTRAL_AREA_PLANNING_AREAS
    if t == "KALLANG/WHAMPOA":
        return ("KALLANG", "WHAMPOA")
    return (t,)


def singapore_fy_label_containing_calendar_month(calendar_year: int, calendar_month: int) -> int:
    """SG FY ends 31 Mar: FY ``Y`` spans 1 Apr (Y-1) – 31 Mar Y. Return ``Y`` for a calendar month inside that span."""
    if calendar_month >= 4:
        return calendar_year + 1
    return calendar_year


def singapore_fy_date_bounds(fy_label: int) -> tuple[str, str]:
    """Return (fy_start, fy_end) as ISO date strings for FY ``fy_label``."""
    y = int(fy_label)
    return (f"{y - 1:04d}-04-01", f"{y:04d}-03-31")
