"""Unit tests for training report feature-set labels and pillar grouping."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_ROOT.parent

for _p in (str(_BACKEND_ROOT), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_MOD_PATH = _BACKEND_ROOT / "services" / "training_report_feature_labels.py"
_spec = importlib.util.spec_from_file_location("training_report_feature_labels_testmod", _MOD_PATH)
assert _spec and _spec.loader
_fr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fr)

build_selection_flags = _fr.build_selection_flags
build_pillar_feature_inventory = _fr.build_pillar_feature_inventory
classify_feature_pillar = _fr.classify_feature_pillar
format_feature_set_display = _fr.format_feature_set_display
group_feature_stats_by_pillar = _fr.group_feature_stats_by_pillar
feature_selection_policy_from_metrics = _fr.feature_selection_policy_from_metrics
feature_selection_summary_from_metrics = _fr.feature_selection_summary_from_metrics
format_feature_selection_policy_short = _fr.format_feature_selection_policy_short
format_columns_removed_cover_preview = _fr.format_columns_removed_cover_preview


def test_format_feature_set_display_mrt_macro():
    s = format_feature_set_display("mrt_pit__poi_distancing__macro", description=None)
    assert "MRT" in s
    assert "POI" in s
    assert "Macro" in s


def test_format_feature_set_display_grouped_note():
    s = format_feature_set_display(
        "mrt_pit__poi_distancing__macro__masterplan_landuse_pit__grouped",
        description=None,
    )
    assert "grouped" in s
    assert "Baseline" in s


def test_format_feature_set_display_core35_proximity_stack():
    fs_id = "mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity"
    s = format_feature_set_display(fs_id, description=None)
    assert "Primary school" in s
    assert "Estate maturity" in s
    assert "Land use" in s
    assert "Macro" in s
    assert "POI" not in s


def test_classify_feature_pillar_estate_and_primary_school():
    assert classify_feature_pillar("count_top20_schools_within_1km") == "primary_school"
    assert classify_feature_pillar("town_supply_maturity_ratio") == "estate"


def test_classify_feature_pillar_baseline_and_mrt():
    assert classify_feature_pillar("town") == "baseline"
    assert classify_feature_pillar("dist_to_nearest_op_mrt") == "mrt"


def test_group_feature_stats_core35_stack_pillars():
    fs_id = "mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity"
    fs = {
        "count_top20_schools_within_1km": {"null_rate": 0.0, "kind": "numeric"},
        "town_supply_maturity_ratio": {"null_rate": 0.0, "kind": "numeric"},
    }
    g = group_feature_stats_by_pillar(fs, feature_set_id=fs_id)
    assert "count_top20_schools_within_1km" in g["primary_school"]
    assert "town_supply_maturity_ratio" in g["estate"]


def test_group_feature_stats_by_pillar():
    fs = {
        "town": {"null_rate":0.0, "nunique":5, "kind":"categorical"},
        "dist_to_nearest_op_mrt":{"null_rate":0.1, "nunique":100, "kind":"numeric", "min":0, "max":10},
    }
    g = group_feature_stats_by_pillar(fs, feature_set_id="mrt_pit")
    assert "town" in g["baseline"]
    assert "dist_to_nearest_op_mrt" in g["mrt"]


def test_build_selection_flags_merges_sources():
    sel = {
        "feature_variance": {"dropped_low_variance": ["bad_col"]},
        "correlated_pairs": {
            "pairs": [{"recommended_drop": "twin_col", "feature_a": "a", "feature_b": "b"}]
        },
        "feature_mi_scores": {"flagged_low_mi": ["weak_col"]},
        "feature_permutation_importance": {
            "feature_names": ["a", "b"],
            "importances_mean": [0.01, -0.02],
        },
    }
    fl = build_selection_flags(sel)
    assert "low_variance" in fl["bad_col"]
    assert "high_correlation_pair" in fl["twin_col"]
    assert "low_mutual_information" in fl["weak_col"]
    assert "permutation_importance_le_0" in fl["b"]


def test_feature_selection_helpers_from_metrics():
    m_adv = {"training_matrix_audit": {"feature_selection_policy": "advisory_only"}}
    assert feature_selection_policy_from_metrics(m_adv) == "advisory_only"
    assert format_feature_selection_policy_short("advisory_only") == "Advisory only"
    assert format_columns_removed_cover_preview(m_adv) is None

    m_apply = {
        "training_matrix_audit": {
            "feature_selection_policy": "apply_recommended_drops",
            "feature_selection": {"columns_removed": ["c1", "c2"]},
        }
    }
    assert feature_selection_policy_from_metrics(m_apply) == "apply_recommended_drops"
    assert format_feature_selection_policy_short("apply_recommended_drops") == "Drops applied"
    prev = format_columns_removed_cover_preview(m_apply)
    assert prev is not None and "c1" in prev and "c2" in prev
    summ = feature_selection_summary_from_metrics(m_apply)
    assert summ["policy"] == "apply_recommended_drops"
    assert summ["columns_removed_count"] == 2

    assert feature_selection_policy_from_metrics({}) is None
    assert format_feature_selection_policy_short(None) == "Not recorded"


def test_build_pillar_feature_inventory_advisory_flagged_and_retained():
    audit = {
        "feature_selection_policy": "advisory_only",
        "registered_feature_set": {
            "numeric_features": ["dist_to_nearest_op_mrt", "floor_area_sqm"],
            "categorical_features": ["town"],
        },
        "feature_selection": {"columns_removed": []},
    }
    flags = {"dist_to_nearest_op_mrt": ["low_variance"]}
    inv, summary = build_pillar_feature_inventory(
        training_matrix_audit=audit,
        selection_flags=flags,
        feature_set_id="mrt_pit",
        features_dropped_doc=None,
    )
    mrt_by = {r["feature"]: r for r in inv["mrt"]}
    assert mrt_by["dist_to_nearest_op_mrt"]["outcome"] == "Flagged (advisory)"
    assert "low_variance" in mrt_by["dist_to_nearest_op_mrt"]["notes"]
    baseline_by = {r["feature"]: r for r in inv["baseline"]}
    assert baseline_by["floor_area_sqm"]["outcome"] == "Retained"
    assert baseline_by["town"]["outcome"] == "Retained"
    assert any(s["pillar_id"] == "mrt" for s in summary)


def test_build_pillar_feature_inventory_apply_dropped_uses_features_dropped_reasons():
    audit = {
        "feature_selection_policy": "apply_recommended_drops",
        "registered_feature_set": {
            "numeric_features": ["dist_to_nearest_op_mrt", "floor_area_sqm"],
            "categorical_features": [],
        },
        "feature_selection": {
            "applied_to_pipeline": True,
            "columns_removed": ["dist_to_nearest_op_mrt"],
            "numeric_features_before_apply": ["dist_to_nearest_op_mrt", "floor_area_sqm"],
        },
    }
    flags = {"dist_to_nearest_op_mrt": ["low_variance"]}
    fd = {"reasons": {"dist_to_nearest_op_mrt": ["high_correlation_pair", "low_variance"]}}
    inv, _ = build_pillar_feature_inventory(
        training_matrix_audit=audit,
        selection_flags=flags,
        feature_set_id="mrt_pit",
        features_dropped_doc=fd,
    )
    mrt_by = {r["feature"]: r for r in inv["mrt"]}
    assert mrt_by["dist_to_nearest_op_mrt"]["outcome"] == "Dropped (pipeline)"
    notes = mrt_by["dist_to_nearest_op_mrt"]["notes"]
    assert "high_correlation_pair" in notes and "low_variance" in notes


def test_build_pillar_feature_inventory_apply_kept_numeric_shows_diagnostic_note():
    audit = {
        "feature_selection_policy": "apply_recommended_drops",
        "registered_feature_set": {
            "numeric_features": ["dist_to_nearest_op_mrt"],
            "categorical_features": [],
        },
        "feature_selection": {
            "applied_to_pipeline": True,
            "columns_removed": [],
            "numeric_features_before_apply": ["dist_to_nearest_op_mrt"],
        },
    }
    flags = {"dist_to_nearest_op_mrt": ["low_mutual_information"]}
    inv, _ = build_pillar_feature_inventory(
        training_matrix_audit=audit,
        selection_flags=flags,
        feature_set_id="mrt_pit",
        features_dropped_doc=None,
    )
    mrt_by = {r["feature"]: r for r in inv["mrt"]}
    assert mrt_by["dist_to_nearest_op_mrt"]["outcome"] == "Retained"
    assert "Diagnostics (not dropped)" in mrt_by["dist_to_nearest_op_mrt"]["notes"]
