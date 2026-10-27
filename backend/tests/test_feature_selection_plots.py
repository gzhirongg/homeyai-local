"""Smoke tests for pre-fit feature-selection PNG helpers."""

from __future__ import annotations

from pathlib import Path


def test_write_feature_selection_plot_pngs_writes_three_files(tmp_path: Path) -> None:
    from modelling.feature_selection_plots import write_feature_selection_plot_pngs

    write_feature_selection_plot_pngs(
        plots_dir=tmp_path,
        variance_doc={
            "variances": {"low_feat": 1e-9, "ok_feat": 2.0},
            "dropped_low_variance": ["low_feat"],
            "var_threshold": 1e-6,
        },
        mi_doc={
            "ranked": [{"feature": "a", "mi": 0.01}, {"feature": "b", "mi": 0.5}],
            "flagged_low_mi": ["a"],
        },
        correlated_pairs_doc={
            "r_threshold": 0.85,
            "pairs": [
                {"feature_a": "a", "feature_b": "b", "pearson_r": 0.91},
            ],
        },
    )
    assert (tmp_path / "feature_selection_variance.png").is_file()
    assert (tmp_path / "feature_selection_mi.png").is_file()
    assert (tmp_path / "feature_selection_correlation.png").is_file()
    assert (tmp_path / "feature_selection_variance.png").stat().st_size > 100
