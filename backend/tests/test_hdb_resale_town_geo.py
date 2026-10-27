"""Tests for deterministic HDB town harmonisation used in estate maturity."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

_SPEC = importlib.util.spec_from_file_location(
    "hdb_resale_town_geo",
    _REPO_ROOT / "backend" / "hdb_resale_town_geo.py",
)
assert _SPEC and _SPEC.loader
_g = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_g)

normalize_hdb_town_label = _g.normalize_hdb_town_label
planning_area_labels_for_resale_town = _g.planning_area_labels_for_resale_town
singapore_fy_date_bounds = _g.singapore_fy_date_bounds
singapore_fy_label_containing_calendar_month = _g.singapore_fy_label_containing_calendar_month


def test_normalize_hdb_town_label():
    assert normalize_hdb_town_label("  ang mo Kio ") == "ANG MO KIO"


def test_central_area_expands_pa_list():
    out = planning_area_labels_for_resale_town("CENTRAL AREA")
    assert "DOWNTOWN CORE" in out
    assert "ORCHARD" in out


def test_kallang_whampoa_both_areas():
    out = planning_area_labels_for_resale_town("KALLANG/WHAMPOA")
    assert out == ("KALLANG", "WHAMPOA")


def test_singapore_fy_calendar_mapping():
    assert singapore_fy_label_containing_calendar_month(2009, 3) == 2009
    assert singapore_fy_label_containing_calendar_month(2009, 6) == 2010


def test_fy_date_bounds_year_2009():
    a, b = singapore_fy_date_bounds(2009)
    assert a == "2008-04-01"
    assert b == "2009-03-31"
