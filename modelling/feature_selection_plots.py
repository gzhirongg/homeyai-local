"""Matplotlib plots for pre-fit feature-selection diagnostics (paired with feature_selection JSON)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt


def write_feature_selection_plot_pngs(
    *,
    plots_dir: Path,
    variance_doc: dict[str, Any] | None,
    mi_doc: dict[str, Any] | None,
    correlated_pairs_doc: dict[str, Any] | None,
    max_variance_bars: int = 20,
    max_mi_bars: int = 25,
    max_corr_pairs: int = 15,
) -> None:
    """Write ``feature_selection_*.png`` under ``plots_dir`` (idempotent; skips empty input)."""
    plots_dir = Path(plots_dir)
    plots_dir.mkdir(parents=True, exist_ok=True)

    if isinstance(variance_doc, dict) and variance_doc.get("variances"):
        _plot_variance(variance_doc, plots_dir / "feature_selection_variance.png", max_bars=max_variance_bars)

    if isinstance(mi_doc, dict) and mi_doc.get("ranked"):
        _plot_mi(mi_doc, plots_dir / "feature_selection_mi.png", max_bars=max_mi_bars)

    if isinstance(correlated_pairs_doc, dict):
        _plot_corr_pairs(correlated_pairs_doc, plots_dir / "feature_selection_correlation.png", top_n=max_corr_pairs)


def _plot_variance(doc: dict[str, Any], out_path: Path, *, max_bars: int) -> None:
    var_thr = float(doc.get("var_threshold") or 1e-6)
    variances = doc.get("variances") or {}
    if not isinstance(variances, dict):
        return
    pairs: list[tuple[str, float]] = []
    for k, v in variances.items():
        if v is None or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
            continue
        pairs.append((str(k), float(v)))
    pairs.sort(key=lambda x: x[1])
    flagged = set(doc.get("dropped_low_variance") or [])
    pairs = pairs[:max_bars]
    if not pairs:
        return
    labels = [p[0][:44] for p in pairs]
    vals = [p[1] for p in pairs]
    colors = ["#e45756" if p[0] in flagged else "#4c78a8" for p in pairs]
    fig, ax = plt.subplots(figsize=(8, max(3.2, 0.22 * len(labels))))
    ax.barh(labels, vals, color=colors)
    ax.axvline(var_thr, color="#333", linestyle="--", linewidth=0.8, label=f"threshold={var_thr:g}")
    ax.set_xlabel("Population variance (numeric)")
    ax.set_title(f"Lowest variances (red = flagged low-variance, n={len(flagged)})")
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


def _plot_mi(doc: dict[str, Any], out_path: Path, *, max_bars: int) -> None:
    ranked = doc.get("ranked") or []
    if not isinstance(ranked, list) or not ranked:
        return
    flagged = set(doc.get("flagged_low_mi") or [])
    items: list[tuple[str, float]] = []
    for row in ranked:
        if isinstance(row, dict) and row.get("feature") is not None:
            try:
                items.append((str(row["feature"]), float(row.get("mi", 0.0))))
            except (TypeError, ValueError):
                continue
    if not items:
        return
    items.sort(key=lambda x: x[1])
    n_bottom = max(1, max_bars // 2)
    n_top = max_bars - n_bottom
    seen: set[str] = set()
    show: list[tuple[str, float]] = []
    for t in items[:n_bottom]:
        if t[0] not in seen:
            seen.add(t[0])
            show.append(t)
    for t in items[-n_top:]:
        if t[0] not in seen:
            seen.add(t[0])
            show.append(t)
    show.sort(key=lambda x: x[1])
    if not show:
        return
    labels = [s[0][:44] for s in show]
    vals = [s[1] for s in show]
    colors = ["#e45756" if s[0] in flagged else "#54a24b" for s in show]
    fig, ax = plt.subplots(figsize=(8, max(3.2, 0.22 * len(show))))
    ax.barh(labels, vals, color=colors)
    ax.set_xlabel("Mutual information vs log1p(price) (median-imputed for MI only)")
    ax.set_title("MI — red = flagged below floor ratio; green = retained")
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


def _plot_corr_pairs(doc: dict[str, Any], out_path: Path, *, top_n: int) -> None:
    pairs = doc.get("pairs") or []
    if not isinstance(pairs, list) or not pairs:
        return
    ok = [p for p in pairs if isinstance(p, dict)]
    ok.sort(key=lambda p: -abs(float(p.get("pearson_r") or 0.0)))
    ok = ok[:top_n]
    if not ok:
        return
    labels: list[str] = []
    heights: list[float] = []
    for p in ok:
        a, b = str(p.get("feature_a", "?"))[:18], str(p.get("feature_b", "?"))[:18]
        labels.append(f"{a} | {b}")
        heights.append(abs(float(p.get("pearson_r") or 0.0)))
    labels, heights = labels[::-1], heights[::-1]
    fig, ax = plt.subplots(figsize=(8, max(3.2, 0.26 * len(labels))))
    ax.barh(labels, heights, color="#72b7b2")
    ax.set_xlabel("|Pearson r| (pairs above threshold)")
    thr = doc.get("r_threshold")
    ax.set_title(f"High-correlation pairs (top {len(ok)}); threshold |r|={thr}")
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


__all__ = ["write_feature_selection_plot_pngs"]
