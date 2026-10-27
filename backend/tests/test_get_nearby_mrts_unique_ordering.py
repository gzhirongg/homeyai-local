"""Regression: unique_stations DB path must be globally ordered by distance."""

from __future__ import annotations

import importlib.util
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import MagicMock

_BACKENDS = Path(__file__).resolve().parents[1]
_GEO_PATH = _BACKENDS / "services" / "geospatial_service.py"
_spec = importlib.util.spec_from_file_location("geospatial_service", _GEO_PATH)
assert _spec and _spec.loader
_geospatial_service = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_geospatial_service)
get_nearby_mrts = _geospatial_service.get_nearby_mrts


def test_unique_stations_db_path_sorts_by_distance_not_dedup_key_order():
    """
    DISTINCT ON (dedup_key) ... ORDER BY dedup_key, distance_km returns one row
    per physical station but row order follows dedup_key, not global distance.
    Callers slice [:2] expecting nearest — results must be sorted by distance.
    """
    row_far = SimpleNamespace(
        id=1592,
        station_name="SOMERSET",
        station_code="NS23",
        station_status="Operational",
        distance_km=1.2,
        pit_state="OPERATIONAL",
    )
    row_near = SimpleNamespace(
        id=999,
        station_name="CHINATOWN",
        station_code="NE4",
        station_status="Operational",
        distance_km=0.25,
        pit_state="OPERATIONAL",
    )
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [row_far, row_near]

    db = MagicMock()
    db.execute.return_value = mock_result

    out = get_nearby_mrts(
        1.286235,
        103.842303,
        radius_km=2.0,
        db=db,
        unique_stations=True,
        states={"OPERATIONAL"},
    )

    assert [r["name"] for r in out] == ["CHINATOWN", "SOMERSET"]
    assert [r["distance"] for r in out] == [0.25, 1.2]
