"""State filtering behaviour for ``get_nearby_mrts`` fallback path."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sys
from unittest.mock import MagicMock

_BACKENDS = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(_BACKENDS))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker  # noqa: E402

from services import geospatial_service  # noqa: E402


def test_fallback_returns_operational_default_and_excludes_planned_states_when_db_raises():
    """
    Without PostGIS, DB execute raises → fallback path still defaults to OPERATIONAL-only
    and returns no rows for speculative-only lifecycle requests.
    """
    engine = create_engine("sqlite+pysqlite:///:memory:")
    db = sessionmaker(bind=engine)()

    out = geospatial_service.get_nearby_mrts(
        1.3150,
        103.7652,
        radius_km=5.0,
        db=db,
        as_of=date(2019, 1, 1),
    )
    assert out

    planned = geospatial_service.get_nearby_mrts(
        1.3150,
        103.7652,
        radius_km=5.0,
        db=db,
        states={"COMMITTED_DATED", "COMMITTED_ESTIMATED", "ANNOUNCED_UNDATED"},
        as_of=date(2019, 1, 1),
    )
    assert planned == []

    mocked = MagicMock()
    mocked.execute.side_effect = RuntimeError("simulated postgis outage")

    only_op = geospatial_service.get_nearby_mrts(
        1.3150,
        103.7652,
        radius_km=5.0,
        db=mocked,
        as_of=date(2018, 6, 1),
        states={"OPERATIONAL"},
    )
    assert only_op
