"""Inference-time fetch of PIT MRT feature rows (snapshot + function fallback)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


_MRT_KEYS_FROZEN = frozenset(
    {
        "dist_to_nearest_op_mrt",
        "travel_time_to_active_mrt",
        "pt_time_savings_vs_walk",
        "line_connectivity_index",
        "nearest_op_lines",
        "days_since_mrt_announcement",
        "days_to_mrt_opening",
        "speculative_upside_score",
        "has_future_upside",
        "nearest_planned_lines",
        "is_proximity_nuisance",
        "num_unique_lines_within_1km",
        "nearest_planned_mrt_dist",
    }
)


def fetch_mrt_features_row_with_meta(
    db: Session, hdb_addr_id: int, valuation_month: str
) -> tuple[dict[str, Any], str | None]:
    """Return `(features, fetch_source)` with ``fetch_source`` one of ``snapshot``, ``function``, or ``None``."""
    ym = (valuation_month or "").strip()
    if len(ym) < 7:
        raise ValueError("valuation_month must be YYYY-MM")

    row = db.execute(
        text(
            """
            SELECT dist_to_nearest_op_mrt,
                   travel_time_to_active_mrt,
                   pt_time_savings_vs_walk,
                   line_connectivity_index,
                   nearest_op_lines,
                   days_since_mrt_announcement,
                   days_to_mrt_opening,
                   speculative_upside_score,
                   has_future_upside,
                   nearest_planned_lines,
                   is_proximity_nuisance,
                   num_unique_lines_within_1km,
                   nearest_planned_mrt_dist
              FROM hdb_mrt_features_pit_snapshot
             WHERE hdb_addr_id = :aid AND tx_year_month = :ym
             LIMIT 1
            """
        ),
        {"aid": hdb_addr_id, "ym": ym},
    ).mappings().first()

    if row:
        return {k: row[k] for k in _MRT_KEYS_FROZEN if k in row}, "snapshot"

    logger.warning(
        "mrt_features snapshot miss — falling back to hdb_mrt_features_at "
        "(hdb_addr_id=%s tx_year_month=%s)",
        hdb_addr_id,
        ym,
    )

    row2 = db.execute(
        text("SELECT * FROM hdb_mrt_features_at(:aid, CAST(:d AS DATE))"),
        {"aid": hdb_addr_id, "d": f"{ym}-01"},
    ).mappings().first()

    if not row2:
        return {}, None

    out: dict[str, Any] = {}
    for k in _MRT_KEYS_FROZEN:
        if k in row2:
            out[k] = row2[k]
    return out, "function"


def fetch_mrt_features_row(db: Session, hdb_addr_id: int, valuation_month: str) -> dict[str, Any]:
    """Return MRT columns for ``append_mrt_features`` / ``engineer_mrt_pit_frame``.

    Prefer ``hdb_mrt_features_pit_snapshot``; fall back to ``hdb_mrt_features_at``.
    """
    features, _ = fetch_mrt_features_row_with_meta(db, hdb_addr_id, valuation_month)
    return features
