"""Regenerate missing pre-fit feature-selection PNGs from JSON artefacts (training report fallback)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _load_json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, TypeError):
        logger.warning("could not load %s", path)
        return None
    return raw if isinstance(raw, dict) else None


def synthesize_missing_feature_selection_plots(*, experiment_root: Path, plots_dir: Path) -> None:
    """Write ``plots_dir/feature_selection_*.png`` for any missing PNG when JSON exists.

    Mirrors training-time behaviour in ``modelling.feature_selection_plots.write_feature_selection_plot_pngs``.
    Missing or degenerate diagnostics (empty ``variances``, ``ranked``, ``pairs``) still yield no PNG
    by design.
    """

    variance_png = plots_dir / "feature_selection_variance.png"
    mi_png = plots_dir / "feature_selection_mi.png"
    corr_png = plots_dir / "feature_selection_correlation.png"

    if variance_png.is_file() and mi_png.is_file() and corr_png.is_file():
        return

    variance_doc = _load_json_object(Path(experiment_root) / "feature_variance.json")
    mi_doc = _load_json_object(Path(experiment_root) / "feature_mi_scores.json")
    corr_doc = _load_json_object(Path(experiment_root) / "correlated_pairs.json")
    if variance_doc is None and mi_doc is None and corr_doc is None:
        return

    try:
        from modelling.feature_selection_plots import write_feature_selection_plot_pngs
    except ImportError:
        logger.warning("modelling.feature_selection_plots unavailable; cannot synthesize FS plots")
        return

    plots_dir.mkdir(parents=True, exist_ok=True)
    try:
        write_feature_selection_plot_pngs(
            plots_dir=plots_dir,
            variance_doc=variance_doc,
            mi_doc=mi_doc,
            correlated_pairs_doc=corr_doc,
        )
    except Exception:
        logger.exception("synthesize_missing_feature_selection_plots failed")
