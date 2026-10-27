"""report-time regeneration of missing feature-selection PNGs from JSON artefacts."""

from __future__ import annotations

import json
from pathlib import Path


def test_synthesize_missing_feature_selection_plots_writes_pngs_when_json_present(tmp_path: Path) -> None:
    from services.feature_selection_plot_synthesize import synthesize_missing_feature_selection_plots

    root = tmp_path / "run"
    root.mkdir()
    plots = root / "plots"
    plots.mkdir()
    variance_doc = {
        "variances": {"low_feat": 1e-9, "ok_feat": 2.0},
        "dropped_low_variance": ["low_feat"],
        "var_threshold": 1e-6,
        "n_numeric_columns": 2,
    }
    mi_doc = {
        "ranked": [{"feature": "a", "mi": 0.01}, {"feature": "b", "mi": 0.5}],
        "flagged_low_mi": ["a"],
        "mi_floor_ratio": 0.02,
    }
    corr_doc = {
        "r_threshold": 0.85,
        "pairs": [{"feature_a": "a", "feature_b": "b", "pearson_r": 0.91}],
    }
    (root / "feature_variance.json").write_text(json.dumps(variance_doc), encoding="utf-8")
    (root / "feature_mi_scores.json").write_text(json.dumps(mi_doc), encoding="utf-8")
    (root / "correlated_pairs.json").write_text(json.dumps(corr_doc), encoding="utf-8")

    synthesize_missing_feature_selection_plots(experiment_root=root, plots_dir=plots)

    assert (plots / "feature_selection_variance.png").is_file()
    assert (plots / "feature_selection_mi.png").is_file()
    assert (plots / "feature_selection_correlation.png").is_file()


def test_synthesize_skips_when_all_three_pngs_already_exist(tmp_path: Path) -> None:
    from services.feature_selection_plot_synthesize import synthesize_missing_feature_selection_plots

    root = tmp_path / "run"
    root.mkdir()
    plots = root / "plots"
    plots.mkdir()
    for name in ("feature_selection_variance.png", "feature_selection_mi.png", "feature_selection_correlation.png"):
        (plots / name).write_bytes(b"x")

    synthesize_missing_feature_selection_plots(experiment_root=root, plots_dir=plots)

    assert all((plots / n).read_bytes() == b"x" for n in ["feature_selection_variance.png", "feature_selection_mi.png", "feature_selection_correlation.png"])
