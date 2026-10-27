"""Smoke test for WeasyPrint experiment training report."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


def _skip_if_weasyprint_unusable() -> None:
    try:
        import weasyprint  # noqa: F401
    except OSError:
        pytest.skip("WeasyPrint system libraries unavailable (GObject/Pango).")


def test_render_training_report_pdf_smoke():
    _skip_if_weasyprint_unusable()

    from services.training_report_html import (
        build_training_report_html_string,
        render_training_report_pdf_bytes,
    )

    dq = {
        "gates_passed": True,
        "pillar_results": [
            {
                "pillar": "base",
                "passed": True,
                "checks": {"min_rows": True, "coords_ok": True},
                "failures": [],
            },
            {
                "pillar": "mrt",
                "passed": False,
                "checks": {"hit_rate": False},
                "failures": ["snapshot hit rate low"],
            },
        ],
        "sql_coverage": {
            "aggregate_rates_pct": {"mrt_hit": 92.5, "poi_join": 88.0},
            "findings": [{"severity": "warn", "code": "coords_sparse", "message": "Coordinates sparse in east"}],
        },
        "feature_stats": {
            "feat_a": {"null_rate": 0.1, "nunique": 5, "kind": "numeric", "mean": 1.0, "std": 0.5},
            "feat_b": {"null_rate": 0.4, "nunique": 2, "kind": "categorical"},
        },
    }

    metrics = {
        "experiment_id": "exp_smoke",
        "feature_set": "mrt_pit",
        "model": "xgboost",
        "best_cv_rmse": 42000.0,
        "best_params_plain": {"max_depth": 5, "learning_rate": 0.1},
        "n_train": 800,
        "n_test": 200,
        "training_context": {
            "cv_fold_rmse_list": [43000.0, 41000.0, None],
            "cv_fold_train_rmse_list": [21000.0, 22000.0, 23000.0],
        },
        "test_metrics": {"rmse": 12345.0, "mae": 9000.0, "mape": 0.11, "r2": 0.85},
        "target_stats": {
            "train": {"min": 200000, "p25": 350000, "median": 450000, "p75": 550000, "max": 700000},
            "test": {"min": 210000, "p25": 360000, "median": 460000, "p75": 560000, "max": 710000},
        },
        "data_profile": {
            "n_rows": 1000,
            "month_min": "2020-01",
            "month_max": "2024-12",
            "flat_type_breakdown": [
                {"flat_type": "4 ROOM", "count": 600, "pct": 60.0},
                {"flat_type": "5 ROOM", "count": 400, "pct": 40.0},
            ],
            "top_towns": [
                {"town": "TAMPINES", "count": 300, "pct": 30.0},
                {"town": "BEDOK", "count": 200, "pct": 20.0},
            ],
        },
        "performance_context": {
            "rmse_pct_of_test_median_price": 2.7,
            "best_cv_rmse_vs_test_rmse_ratio": 3.4,
        },
        "residual_by_flat_type": [
            {"flat_type": "4 ROOM", "n": 100, "residual_mean": 1200.0, "residual_std": 8000.0},
        ],
        "residual_by_month": [
            {"month": "2024-01", "n": 40, "residual_mean": 500.0, "residual_std": 7000.0},
            {"month": "2024-02", "n": 45, "residual_mean": -200.0, "residual_std": 6800.0},
        ],
        "residual_by_town": [
            {"town": "TAMPINES", "n": 80, "residual_mean": 300.0, "residual_std": 7500.0},
        ],
        "residual_price_tier_calibration": [
            {"tier": "low", "n": 60, "over_predict_rate": 0.45, "under_predict_rate": 0.55},
            {"tier": "mid", "n": 70, "over_predict_rate": 0.5, "under_predict_rate": 0.5},
            {"tier": "high", "n": 70, "over_predict_rate": 0.55, "under_predict_rate": 0.45},
        ],
        "top_feature_importances": [
            {"feature": "floor_area_sqm", "importance": 0.35, "null_rate": 0.0},
            {"feature": "town", "importance": 0.2, "null_rate": 0.05},
        ],
        "feature_stats_full": {
            "floor_area_sqm": {
                "null_rate": 0.01,
                "nunique": 120,
                "kind": "numeric",
                "mean": 90.0,
                "std": 10.0,
                "min": 40.0,
                "max": 140.0,
                "p5": 55.0,
                "p95": 120.0,
            },
            "lat": {
                "null_rate": 0.35,
                "nunique": 500,
                "kind": "numeric",
                "min": 1.2,
                "max": 1.45,
                "p5": 1.25,
                "p95": 1.42,
                "mean": 1.35,
            },
            "flat_type_encoded": {
                "null_rate": 0.0,
                "nunique": 7,
                "kind": "numeric",
                "min": 1.0,
                "max": 7.0,
                "encoding": "ordinal_1_7",
                "in_model": True,
            },
        },
        "near_constant_numeric_columns": ["legacy_flag"],
        "top_feature_importances": [
            {"feature": "floor_area_sqm", "importance": 0.31, "null_rate": 0.01},
            {"feature": "num__lat", "importance": 0.07, "null_rate": 0.35},
        ],
        "top_shap_features": [
            {"feature": "floor_area_sqm", "mean_abs_shap": 0.12, "null_rate": 0.01},
            {"feature": "num__lat", "mean_abs_shap": 0.04, "null_rate": 0.35},
        ],
        "training_matrix_audit": {
            "feature_selection_policy": "advisory_only",
            "raw_split_input": {"n_rows": 800, "n_columns": 3, "columns": ["a", "b", "resale_price"]},
            "engineered": {"n_rows": 800, "n_columns": 5, "columns": ["a", "b", "c", "d", "e"]},
            "registered_feature_set": {
                "numeric_features": ["a", "b"],
                "categorical_features": ["c"],
                "n_numeric": 2,
                "n_categorical": 1,
            },
            "preprocessor_output": {
                "n_features_out": 12,
                "feature_names_head": ["num__a", "num__b"],
                "feature_names_tail": ["cat__c__x"],
            },
            "engineered_vs_registry_warnings": [],
            "model_encoding": {
                "flat_type": {
                    "raw_column_eda_only": "flat_type",
                    "model_column": "flat_type_encoded",
                    "encoding": "ordinal_1_7",
                },
            },
        },
    }

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        plots = td_path / "plots"
        plots.mkdir(parents=True, exist_ok=True)
        (td_path / "feature_variance.json").write_text(
            '{"dropped_low_variance": ["lat"]}',
            encoding="utf-8",
        )
        html_doc = build_training_report_html_string(
            run_id="unit_test__20260101T000000Z",
            metrics_payload=metrics,
            dq_summary=dq,
            plots_dir=plots,
        )
        pdf = render_training_report_pdf_bytes(
            run_id="unit_test__20260101T000000Z",
            metrics_payload=metrics,
            dq_summary=dq,
            plots_dir=plots,
        )
    assert "Section 8 — Feature importances (table)" in html_doc
    assert "Section 8 — SHAP summary (mean |SHAP|)" in html_doc
    assert "Section 8 — SHAP attribution (table)" in html_doc
    assert "Training matrix audit" in html_doc
    assert "Feature selection policy" in html_doc
    assert "Advisory only" in html_doc
    assert "Recorded policy:" in html_doc
    assert pdf.startswith(b"%PDF")


def test_feature_pillar_inventory_table_includes_dropped_pipeline(tmp_path: Path) -> None:
    from services.training_report_html import build_training_report_html_string

    plots = tmp_path / "plots"
    plots.mkdir()
    metrics = {
        "feature_set": "mrt_pit",
        "feature_stats_full": {
            "dist_to_nearest_op_mrt": {
                "kind": "numeric",
                "null_rate": 0.0,
                "min": 0.0,
                "max": 1.0,
                "p5": 0.0,
                "p95": 1.0,
                "mean": 0.5,
            },
        },
        "training_matrix_audit": {
            "feature_selection_policy": "apply_recommended_drops",
            "raw_split_input": {"n_rows": 10, "n_columns": 1, "columns": ["x"]},
            "engineered": {"n_rows": 10, "n_columns": 1, "columns": ["x"]},
            "registered_feature_set": {
                "numeric_features": ["dist_to_nearest_op_mrt"],
                "categorical_features": [],
            },
            "feature_selection": {
                "applied_to_pipeline": True,
                "columns_removed": ["dist_to_nearest_op_mrt"],
                "numeric_features_before_apply": ["dist_to_nearest_op_mrt"],
            },
            "preprocessor_output": {"n_features_out": 1, "feature_names_head": ["n"], "feature_names_tail": []},
            "engineered_vs_registry_warnings": [],
        },
    }
    html_doc = build_training_report_html_string(
        run_id="unit_inv",
        metrics_payload=dict(metrics),
        dq_summary={},
        plots_dir=plots,
        selection_artifacts={},
    )
    assert "Registry column inventory" in html_doc
    assert "Dropped (pipeline)" in html_doc
    assert ">Outcome</th>" in html_doc
    assert "Feature pack inventory summary" in html_doc


def test_audit_page_sets_selection_pngs_all_missing_when_no_plot_files(tmp_path: Path) -> None:
    from services.training_report_html import _build_pages

    plots = tmp_path / "plots"
    plots.mkdir()
    metrics_min = {
        "feature_set": "mrt_pit",
        "training_matrix_audit": {
            "feature_selection_policy": "advisory_only",
            "raw_split_input": {"n_rows": 10, "n_columns": 1, "columns": ["a"]},
            "engineered": {"n_rows": 10, "n_columns": 1, "columns": ["a"]},
            "registered_feature_set": {
                "numeric_features": [],
                "categorical_features": [],
                "n_numeric": 0,
                "n_categorical": 0,
            },
            "preprocessor_output": {"n_features_out": 0, "feature_names_head": [], "feature_names_tail": []},
            "engineered_vs_registry_warnings": [],
        },
    }
    pages = _build_pages(
        run_id="unit_audit",
        metrics_payload=dict(metrics_min),
        dq_summary={},
        plots_dir=plots,
        generated_at="2026-05-01 12:00",
        fs_description="",
        selection_artifacts={},
    )
    audit = next(p for p in pages if p.get("kind") == "training_matrix_audit")
    assert audit["selection_pngs_all_missing"]


def test_audit_page_clears_all_missing_when_three_placeholder_png_exist(tmp_path: Path) -> None:
    from services.training_report_html import _build_pages

    plots = tmp_path / "plots"
    plots.mkdir()
    for name in (
        "feature_selection_variance.png",
        "feature_selection_mi.png",
        "feature_selection_correlation.png",
    ):
        (plots / name).write_bytes(b"not-a-real-png")
    metrics_min = {
        "feature_set": "mrt_pit",
        "training_matrix_audit": {
            "feature_selection_policy": "advisory_only",
            "raw_split_input": {"n_rows": 10, "n_columns": 1, "columns": ["a"]},
            "engineered": {"n_rows": 10, "n_columns": 1, "columns": ["a"]},
            "registered_feature_set": {
                "numeric_features": [],
                "categorical_features": [],
                "n_numeric": 0,
                "n_categorical": 0,
            },
            "preprocessor_output": {"n_features_out": 0, "feature_names_head": [], "feature_names_tail": []},
            "engineered_vs_registry_warnings": [],
        },
    }
    pages = _build_pages(
        run_id="unit_audit_png",
        metrics_payload=dict(metrics_min),
        dq_summary={},
        plots_dir=plots,
        generated_at="2026-05-01 12:00",
        fs_description="",
        selection_artifacts={},
    )
    audit = next(p for p in pages if p.get("kind") == "training_matrix_audit")
    assert not audit["selection_pngs_all_missing"]


def test_pdf_explains_when_all_selection_png_missing():
    _skip_if_weasyprint_unusable()

    from services.training_report_html import (
        build_training_report_html_string,
        render_training_report_pdf_bytes,
    )

    dq: dict[str, object] = {}
    metrics_min = {
        "experiment_id": "exp_aud",
        "feature_set": "mrt_pit",
        "training_matrix_audit": {
            "feature_selection_policy": "advisory_only",
            "raw_split_input": {"n_rows": 10, "n_columns": 1, "columns": ["a"]},
            "engineered": {"n_rows": 10, "n_columns": 1, "columns": ["a"]},
            "registered_feature_set": {
                "numeric_features": [],
                "categorical_features": [],
                "n_numeric": 0,
                "n_categorical": 0,
            },
            "preprocessor_output": {"n_features_out": 0, "feature_names_head": [], "feature_names_tail": []},
            "engineered_vs_registry_warnings": [],
            "model_encoding": {},
        },
    }
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        plots = td_path / "plots"
        plots.mkdir()
        html_doc = build_training_report_html_string(
            run_id="unit_test__explain_png",
            metrics_payload=dict(metrics_min),
            dq_summary=dq,
            plots_dir=plots,
        )
        pdf = render_training_report_pdf_bytes(
            run_id="unit_test__explain_png",
            metrics_payload=dict(metrics_min),
            dq_summary=dq,
            plots_dir=plots,
        )
    assert "No feature-selection diagnostic PNGs were embedded." in html_doc
    assert pdf.startswith(b"%PDF")
