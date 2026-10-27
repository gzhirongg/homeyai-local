"""HDB Property Information catalogue helpers (flat-type inventory from ``*_sold`` columns)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# (ORM attribute name on HdbPropertyInformation, resale / Valuation flat_type label)
SOLD_COLUMN_TO_FLAT_TYPE: Sequence[tuple[str, str]] = (
    ("room_1_sold", "1 ROOM"),
    ("room_2_sold", "2 ROOM"),
    ("room_3_sold", "3 ROOM"),
    ("room_4_sold", "4 ROOM"),
    ("room_5_sold", "5 ROOM"),
    ("exec_sold", "EXECUTIVE"),
    ("multigen_sold", "MULTI-GENERATION"),
    ("studio_apartment_sold", "STUDIO APARTMENT"),
)


def flat_types_from_property_row(row: Any) -> list[tuple[str, int]]:
    """Return ``(flat_type, units_sold)`` pairs where units_sold > 0, catalogue order preserved."""
    out: list[tuple[str, int]] = []
    for attr, flat_type in SOLD_COLUMN_TO_FLAT_TYPE:
        n = int(getattr(row, attr, 0) or 0)
        if n > 0:
            out.append((flat_type, n))
    return out


def resolve_property_for_address(db: Session, address: Any) -> Any | None:
    """Resolve ``HdbPropertyInformation`` for OneMap enrichment: FK first, then blk_street match."""
    from sqlalchemy import func

    from models import HdbPropertyInformation

    row = (
        db.query(HdbPropertyInformation)
        .filter(HdbPropertyInformation.enriched_addr_id == address.id)
        .order_by(HdbPropertyInformation.id)
        .first()
    )
    if row is not None:
        return row

    qs = (getattr(address, "query_sent", None) or "").strip()
    if not qs:
        return None

    norm = qs.lower().strip()
    return (
        db.query(HdbPropertyInformation)
        .filter(
            func.lower(func.trim(HdbPropertyInformation.blk_street)) == norm
        )
        .order_by(HdbPropertyInformation.id)
        .first()
    )
