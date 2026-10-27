"""Unit tests for resale town → URA planning area name expansion."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_GEO_PATH = _BACKEND / "services" / "geospatial_service.py"
_spec = importlib.util.spec_from_file_location("geospatial_service", _GEO_PATH)
assert _spec and _spec.loader
_gs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gs)

expand_resale_town_names = _gs.expand_resale_town_names
_planning_union_where_clause = _gs._planning_union_where_clause
_CENTRAL_AREA_PLANNING_AREAS = _gs._CENTRAL_AREA_PLANNING_AREAS


def test_expand_central_area_aliases():
    out = expand_resale_town_names(["CENTRAL AREA"])
    assert "DOWNTOWN CORE" in out
    assert "ORCHARD" in out
    assert len(out) == len(_CENTRAL_AREA_PLANNING_AREAS)


def test_expand_kallang_whampoa_alias():
    out = expand_resale_town_names(["KALLANG/WHAMPOA"])
    assert out == ["KALLANG", "WHAMPOA"]


def test_expand_plain_town_passthrough():
    out = expand_resale_town_names(["bedok", " Bedok "])
    assert out == ["BEDOK"]


def test_expand_deduplicates_mixed():
    out = expand_resale_town_names(["BEDOK", "bedok", "TAMPINES"])
    assert out == ["BEDOK", "TAMPINES"]


def test_planning_union_where_region_only():
    clause, bind = _planning_union_where_clause("cr", None)
    assert clause == "pa.region_c = :region_c"
    assert bind == {"region_c": "CR"}


def test_planning_union_where_towns_only():
    clause, bind = _planning_union_where_clause(None, ["CENTRAL AREA"])
    assert "town_arr" in bind
    assert "DOWNTOWN CORE" in bind["town_arr"]


def test_planning_union_where_region_and_towns():
    clause, bind = _planning_union_where_clause("ER", ["BEDOK"])
    assert "region_c" in bind and "town_arr" in bind
    assert bind["region_c"] == "ER"
    assert bind["town_arr"] == ["BEDOK"]


def test_planning_union_where_empty_scope():
    clause, bind = _planning_union_where_clause(None, None)
    assert clause is None
    assert bind == {}
