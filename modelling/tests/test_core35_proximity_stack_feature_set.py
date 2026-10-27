"""Contract for Core35 L40S stack: proximity + macro + estate + primary_school counts (no POI distance numerics)."""

from __future__ import annotations

from pathlib import Path

from modelling.config.feature_modules import (
    TAG_ESTATE_MATURITY,
    assert_feature_set_coverage_matches_registry,
    feature_modules_for_feature_set,
)
from modelling.config.feature_sets import get_feature_registry
from modelling.features.estate_maturity import ESTATE_MATURITY_NUMERIC_FEATURES
from modelling.features.masterplan_landuse_pit import MASTERPLAN_AREA_NUMERIC, MASTERPLAN_PROXIMITY_NUMERIC
from modelling.features.poi_distancing import POI_NUMERIC_FEATURES
from modelling.features.primary_school import PRIMARY_SCHOOL_NUMERIC

_FS_ID = "mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity"

_POI_SCHOOL = frozenset(
    {
        "dist_nearest_top20_school",
        "dist_nearest_any_school",
        "within_1km_top20_school",
        "within_1km_2km_top20_school",
        "within_1km_any_pri_school",
        "within_1km_2km_pri_school",
        "gravity_schools",
    }
)


def test_registry_and_modules_sync():
    root = Path(__file__).resolve().parents[2]
    assert_feature_set_coverage_matches_registry(root)


def test_core35_stack_numeric_contract():
    root = Path(__file__).resolve().parents[2]
    reg = get_feature_registry(root)
    fs = reg[_FS_ID]
    nums = fs.numeric_features
    nums_set = set(nums)

    assert len(nums) == len(nums_set)
    assert "sale_year" not in nums_set
    assert "sale_month_sin" in nums_set and "sale_month_cos" in nums_set

    for a in MASTERPLAN_AREA_NUMERIC:
        assert a not in nums_set

    for p in MASTERPLAN_PROXIMITY_NUMERIC:
        assert p in nums_set

    # POI distance pack columns are excluded except those mirrored by masterplan proximity (dist_cbd, dist_airport).
    masterprox = frozenset(MASTERPLAN_PROXIMITY_NUMERIC)
    for col in POI_NUMERIC_FEATURES:
        if col in masterprox:
            assert col in nums_set
        else:
            assert col not in nums_set

    for col in _POI_SCHOOL:
        assert col not in nums_set

    for c in PRIMARY_SCHOOL_NUMERIC:
        assert c in nums_set
    for c in ESTATE_MATURITY_NUMERIC_FEATURES:
        assert c in nums_set

    tags = feature_modules_for_feature_set(_FS_ID)
    assert TAG_ESTATE_MATURITY in tags
