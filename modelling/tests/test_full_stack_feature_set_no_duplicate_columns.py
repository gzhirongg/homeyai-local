"""Full-stack FeatureSet numeric list has no duplicate names (POI/masterplan dedupe)."""

from __future__ import annotations

from pathlib import Path

from modelling.config.feature_sets import get_feature_registry

_REPO = Path(__file__).resolve().parents[2]
_FULL_STACK_ID = "mrt_pit__poi_distancing__macro__masterplan_landuse_pit"


def test_full_stack_numeric_features_are_unique():
    reg = get_feature_registry(_REPO)
    fs = reg[_FULL_STACK_ID]
    nums = fs.numeric_features
    assert len(nums) == len(set(nums))
