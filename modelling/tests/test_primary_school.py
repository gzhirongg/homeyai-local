"""Tests for primary_school AB pack (two annulus counts, no distance column)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from modelling.config.feature_modules import assert_feature_set_coverage_matches_registry
from modelling.config.feature_sets import get_feature_registry
from modelling.features.primary_school import (
    PRIMARY_SCHOOL_NUMERIC,
    append_primary_school_features,
)


def _minimal_raw(lat: float = 1.352, lon: float = 103.85) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "month": ["2020-01"],
            "town": ["TAMPINES"],
            "flat_type": ["4 ROOM"],
            "flat_model": ["Model A"],
            "storey_range": ["10 TO 12"],
            "floor_area_sqm": [90.0],
            "lease_commence_date": [1999],
            "remaining_lease_years": [79.0],
            "lat": [lat],
            "lon": [lon],
        }
    )


def test_legacy_band_at_1500m_single_top20():
    """Between 1–2 km band: 0 in [0,1km], 1 in (1km, 2km] when exactly one school there."""
    hdb = _minimal_raw()
    schools = pd.DataFrame({"lat": [1.362], "lon": [103.85], "name": ["TopSchool"]})
    pois = {"top_20": schools}
    out = append_primary_school_features(hdb, pois)
    assert "dist_nearest_top20_school" not in out.columns
    d = float(abs(1.362 - 1.352)) * 111_000.0
    assert 1000 < d < 2000
    assert int(out["count_top20_schools_within_1km"].iloc[0]) == 0
    assert int(out["count_top20_schools_within_1km_2km"].iloc[0]) == 1


def test_within_1km_when_close():
    hdb = _minimal_raw(lat=1.3525, lon=103.85)
    schools = pd.DataFrame({"lat": [1.353], "lon": [103.85], "name": ["S"]})
    pois = {"top_20": schools}
    out = append_primary_school_features(hdb, pois)
    assert int(out["count_top20_schools_within_1km"].iloc[0]) == 1
    assert int(out["count_top20_schools_within_1km_2km"].iloc[0]) == 0


def test_two_schools_one_per_annulus():
    """One school ~500 m north, one ~1500 m north — counts 1 + 1."""
    hdb = _minimal_raw(lat=1.352, lon=103.85)
    dlat_500m = 500.0 / 111_000.0
    dlat_1500m = 1500.0 / 111_000.0
    schools = pd.DataFrame(
        {
            "lat": [1.352 + dlat_500m, 1.352 + dlat_1500m],
            "lon": [103.85, 103.85],
            "name": ["Near", "Mid"],
        }
    )
    pois = {"top_20": schools}
    out = append_primary_school_features(hdb, pois)
    assert int(out["count_top20_schools_within_1km"].iloc[0]) == 1
    assert int(out["count_top20_schools_within_1km_2km"].iloc[0]) == 1


def test_three_schools_all_within_1km():
    hdb = _minimal_raw(lat=1.352, lon=103.85)
    schools = pd.DataFrame(
        {
            "lat": [1.3525, 1.3526, 1.3527],
            "lon": [103.85, 103.85, 103.85],
            "name": ["A", "B", "C"],
        }
    )
    pois = {"top_20": schools}
    out = append_primary_school_features(hdb, pois)
    assert int(out["count_top20_schools_within_1km"].iloc[0]) == 3
    assert int(out["count_top20_schools_within_1km_2km"].iloc[0]) == 0


def test_registry_and_numeric_contract():
    root = Path(__file__).resolve().parents[2]
    from modelling.features.poi_distancing import POI_FILENAMES, pois_dir

    assert_feature_set_coverage_matches_registry(root)
    reg = get_feature_registry(root)
    fs = reg["primary_school"]
    for c in PRIMARY_SCHOOL_NUMERIC:
        assert c in fs.numeric_features
    base = pois_dir(root.resolve())
    if not all((base / fname).is_file() for fname in POI_FILENAMES.values()):
        pytest.skip("data/pois seven assets not present — engineer smoke skipped")
    raw = _minimal_raw()
    raw["enriched_addr_id"] = [1]
    out = fs.engineer(raw, **{**fs.engineer_kwargs, "project_root": root})
    assert "dist_nearest_top20_school" not in out.columns
    for c in PRIMARY_SCHOOL_NUMERIC:
        assert c in out.columns


def test_mrt_variant_registers():
    root = Path(__file__).resolve().parents[2]
    reg = get_feature_registry(root)
    assert "mrt_pit__primary_school" in reg


def test_mrt_primary_school_estate_feature_set_numeric_contract():
    root = Path(__file__).resolve().parents[2]
    from modelling.features.estate_maturity import ESTATE_MATURITY_NUMERIC_FEATURES
    from modelling.features.masterplan_landuse_pit import MASTERPLAN_LAND_USE_NUMERIC

    assert_feature_set_coverage_matches_registry(root)
    reg = get_feature_registry(root)
    fs = reg["mrt_pit__primary_school__estate_maturity"]
    for c in PRIMARY_SCHOOL_NUMERIC + ESTATE_MATURITY_NUMERIC_FEATURES:
        assert c in fs.numeric_features
    land_in_fs = set(fs.numeric_features) & set(MASTERPLAN_LAND_USE_NUMERIC)
    assert not land_in_fs


def test_mrt_landuse_primary_school_registers():
    root = Path(__file__).resolve().parents[2]
    from modelling.config.experiments import get_experiment
    from modelling.features.masterplan_landuse_pit import MASTERPLAN_LAND_USE_NUMERIC

    reg = get_feature_registry(root)
    fs = reg["mrt_pit__masterplan_landuse_pit__primary_school"]
    for c in PRIMARY_SCHOOL_NUMERIC + MASTERPLAN_LAND_USE_NUMERIC:
        assert c in fs.numeric_features
    exp = get_experiment(root, "xgboost_tuned__mrt_landuse_primary_school")
    assert exp.feature_set_id == "mrt_pit__masterplan_landuse_pit__primary_school"
    assert exp.model_id == "xgboost_tuned"
    assert exp.mrt_pit_min_years == 5


def test_core35_masterplan_area_proximity_ab_batch():
    root = Path(__file__).resolve().parents[2]
    from modelling.config.experiment_batches import CORE35_Y5_MASTERPLAN_AREA_PROXIMITY_AB
    from modelling.config.experiments import get_experiment
    from modelling.features.masterplan_landuse_pit import MASTERPLAN_AREA_NUMERIC, MASTERPLAN_PROXIMITY_NUMERIC
    from modelling.features.masterplan_loi_proximity import LOI_PROXIMITY_NUMERIC

    assert_feature_set_coverage_matches_registry(root)
    reg = get_feature_registry(root)
    area_only = reg["mrt_pit__masterplan_area__primary_school"]
    prox_only = reg["mrt_pit__masterplan_proximity__primary_school"]
    both = reg["mrt_pit__masterplan_area_proximity__primary_school"]
    assert set(MASTERPLAN_AREA_NUMERIC).isdisjoint(set(MASTERPLAN_PROXIMITY_NUMERIC))
    assert set(area_only.numeric_features) >= set(MASTERPLAN_AREA_NUMERIC)
    assert not set(MASTERPLAN_PROXIMITY_NUMERIC) & set(area_only.numeric_features)
    assert set(prox_only.numeric_features) >= set(MASTERPLAN_PROXIMITY_NUMERIC)
    assert not set(MASTERPLAN_AREA_NUMERIC) & set(prox_only.numeric_features)
    for c in LOI_PROXIMITY_NUMERIC:
        assert c in prox_only.numeric_features
        assert c not in area_only.numeric_features
    assert set(both.numeric_features) == set(area_only.numeric_features) | set(prox_only.numeric_features)
    for eid in CORE35_Y5_MASTERPLAN_AREA_PROXIMITY_AB:
        exp = get_experiment(root, eid)
        assert exp.flat_type_scope == "core_35"
        assert exp.mrt_pit_min_years == 5
