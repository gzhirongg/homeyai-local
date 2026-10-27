"""WeasyPrint/HTML experiment training report (valuation-style layout)."""

from __future__ import annotations

import base64
from collections import Counter
import json
import logging
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from jinja2 import Environment, FileSystemLoader, select_autoescape

from services.report_assets import get_logo_base64
from services.training_report_feature_labels import (
    build_pillar_feature_inventory,
    build_selection_flags,
    feature_selection_policy_from_metrics,
    feature_selection_summary_from_metrics,
    format_columns_removed_cover_preview,
    format_feature_selection_policy_badge,
    format_feature_selection_policy_short,
    format_feature_set_display,
    format_training_matrix_audit_policy_text,
    group_feature_stats_by_pillar,
    load_selection_artifacts_from_dir,
)

logger = logging.getLogger(__name__)


def _static_reports_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "static" / "reports"


def _training_templates_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "templates" / "reports" / "training"


def _load_training_styles() -> str:
    root = _static_reports_dir()
    base = (root / "base_report.css").read_text(encoding="utf-8")
    extra = (root / "training_report.css").read_text(encoding="utf-8")
    return f"{base}\n{extra}"


def _get_training_report_print_stylesheet() -> Any:
    """Deferred WeasyPrint import so ``_build_pages`` can be imported without GObject/Pango on every host."""

    from weasyprint import CSS

    return CSS(
        string="""
        @page {
            size: A4;
            margin: 15mm 15mm 22mm 15mm;
            @bottom-center {
                content: "Page " counter(page) " of " counter(pages);
                font-size: 9px;
                color: #a0aec0;
            }
        }
        body {
            background: white !important;
            background-image: none !important;
            padding: 0 !important;
        }
        .page {
            box-shadow: none !important;
            margin: 0 !important;
            padding: 0 !important;
            border-radius: 0 !important;
            width: 100% !important;
            min-height: auto !important;
            page-break-after: always;
        }
    """
    )


_PRINT_CSS_SINGLETON: Any = None


def _print_stylesheet() -> Any:
    global _PRINT_CSS_SINGLETON
    if _PRINT_CSS_SINGLETON is None:
        _PRINT_CSS_SINGLETON = _get_training_report_print_stylesheet()
    return _PRINT_CSS_SINGLETON


PILLAR_HEADINGS: dict[str, str] = {
    "baseline": "Baseline (resale core)",
    "mrt": "MRT / accessibility (PIT)",
    "landuse": "Masterplan / land use",
    "macro": "Macro & sentiment",
    "poi": "POI distances",
    "primary_school": "Primary school (top-20 counts)",
    "estate": "Estate maturity",
    "other": "Other engineered columns",
}


_jinja_env = Environment(
    loader=FileSystemLoader(str(_training_templates_dir())),
    autoescape=select_autoescape(["html", "xml"]),
)


def _png_data_uri(plots_dir: Path, filename: str) -> str | None:
    pth = plots_dir / filename
    if not pth.is_file():
        return None
    try:
        raw = pth.read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except OSError:
        logger.warning("could not read plot %s", pth)
        return None


def _fig_to_data_uri(fig: Any) -> str:
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return "data:image/png;base64," + base64.b64encode(buf.read()).decode("ascii")


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x or x in (float("inf"), float("-inf")):
        return None
    return x


def _chart_flat_type_breakdown(data_profile: dict[str, Any]) -> str | None:
    rows = data_profile.get("flat_type_breakdown") or []
    if not isinstance(rows, list) or not rows:
        return None
    labels: list[str] = []
    vals: list[float] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        labels.append(str(r.get("flat_type", "?")))
        p = _safe_float(r.get("pct"))
        vals.append(float(p) if p is not None else 0.0)
    if not labels:
        return None
    labels, vals = labels[::-1], vals[::-1]
    fig, ax = plt.subplots(figsize=(8, max(3.0, 0.22 * len(labels))))
    ax.barh(labels, vals, color="#4c78a8")
    ax.set_xlabel("Share of rows (%)")
    ax.set_title("Flat type distribution")
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def _chart_top_towns(data_profile: dict[str, Any]) -> str | None:
    rows = data_profile.get("top_towns") or []
    if not isinstance(rows, list) or not rows:
        return None
    labels: list[str] = []
    vals: list[float] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        labels.append(str(r.get("town", "?")))
        p = _safe_float(r.get("pct"))
        vals.append(float(p) if p is not None else 0.0)
    if not labels:
        return None
    labels, vals = labels[::-1], vals[::-1]
    fig, ax = plt.subplots(figsize=(8, max(3.0, 0.28 * len(labels))))
    ax.barh(labels, vals, color="#72b7b2")
    ax.set_xlabel("Share of rows (%)")
    ax.set_title("Top towns (by row share)")
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def _chart_train_test_target_box(target_stats: dict[str, Any]) -> str | None:
    ts_train = target_stats.get("train") if isinstance(target_stats, dict) else {}
    ts_test = target_stats.get("test") if isinstance(target_stats, dict) else {}
    if not isinstance(ts_train, dict) or not isinstance(ts_test, dict):
        return None

    def _bx(d: dict[str, Any]) -> dict[str, Any] | None:
        try:
            return {
                "med": float(d["median"]),
                "q1": float(d["p25"]),
                "q3": float(d["p75"]),
                "whislo": float(d["min"]),
                "whishi": float(d["max"]),
                "fliers": [],
            }
        except (KeyError, TypeError, ValueError):
            return None

    b1 = _bx(ts_train)
    b2 = _bx(ts_test)
    if not b1 or not b2:
        return None
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    ax.bxp([b1, b2], positions=[1, 2], showfliers=False)
    ax.set_xticks([1, 2])
    ax.set_xticklabels(["Train target", "Test target"])
    ax.set_ylabel("resale_price")
    ax.set_title("Train vs test target (box from stored quantiles)")
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def _chart_sql_coverage_pct(sql_cov: dict[str, Any]) -> str | None:
    pct = sql_cov.get("aggregate_rates_pct") or {}
    if not isinstance(pct, dict) or not pct:
        return None
    items: list[tuple[str, float]] = []
    for k, raw_v in pct.items():
        if isinstance(raw_v, (int, float)):
            fv = float(raw_v)
        else:
            s = str(raw_v).replace("%", "").strip()
            try:
                fv = float(s)
            except ValueError:
                fv = 0.0
        items.append((str(k), fv))
    items.sort(key=lambda x: x[1])
    labels = [k[:52] for k, _ in items]
    vals = [v for _, v in items]
    fig, ax = plt.subplots(figsize=(8, max(3.0, 0.26 * len(labels))))
    ax.barh(labels, vals, color="#54a24b")
    ax.set_xlabel("Rate (%)")
    ax.set_title("SQL coverage / join rates")
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def _chart_feature_null_rates(fstats: dict[str, Any], *, top_n: int = 45) -> str | None:
    pairs: list[tuple[str, float]] = []
    for k, d in (fstats or {}).items():
        if not isinstance(d, dict):
            continue
        nr = _safe_float(d.get("null_rate"))
        if nr is None:
            continue
        pairs.append((str(k), nr))
    pairs.sort(key=lambda x: -x[1])
    pairs = pairs[:top_n]
    if not pairs:
        return None
    labels = [p[0][:44] for p in pairs][::-1]
    vals = [p[1] for p in pairs][::-1]
    fig, ax = plt.subplots(figsize=(8, max(3.5, 0.2 * len(labels))))
    ax.barh(labels, vals, color="#e45756")
    ax.set_xlabel("Null rate")
    ax.set_title(f"Top {len(pairs)} columns by null rate")
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def _chart_feature_cardinality(fstats: dict[str, Any], *, top_n: int = 45) -> str | None:
    triples: list[tuple[str, int, str]] = []
    for k, d in (fstats or {}).items():
        if not isinstance(d, dict):
            continue
        kind = str(d.get("kind") or "unknown")
        try:
            nu = int(d.get("nunique") or 0)
        except (TypeError, ValueError):
            continue
        triples.append((str(k), nu, kind))
    triples.sort(key=lambda x: -x[1])
    triples = triples[:top_n]
    if not triples:
        return None
    labels = [t[0][:44] for t in triples][::-1]
    vals = [t[1] for t in triples][::-1]
    colors = ["#4c78a8" if t[2] == "numeric" else "#f58518" for t in triples[::-1]]
    fig, ax = plt.subplots(figsize=(8, max(3.5, 0.2 * len(labels))))
    ax.barh(labels, vals, color=colors)
    ax.set_xlabel("Cardinality (nunique)")
    ax.set_title(f"Top {len(triples)} columns by cardinality (blue=numeric, orange=categorical)")
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def _chart_pillar_feature_nulls(
    fstats_sub: dict[str, Any],
    *,
    title: str,
    top_n: int = 18,
) -> str | None:
    pairs: list[tuple[str, float]] = []
    for k, d in fstats_sub.items():
        if not isinstance(d, dict):
            continue
        nr = _safe_float(d.get("null_rate"))
        if nr is None:
            continue
        pairs.append((str(k), nr))
    pairs.sort(key=lambda x: -x[1])
    pairs = pairs[:top_n]
    if not pairs:
        return None
    labels = [p[0][:46] for p in pairs][::-1]
    vals = [p[1] for p in pairs][::-1]
    fig, ax = plt.subplots(figsize=(8, max(3.2, 0.2 * len(labels))))
    ax.barh(labels, vals, color="#e45756")
    ax.set_xlim(0, min(1.0, max(vals) * 1.15 + 0.02) if vals else 1.0)
    ax.set_xlabel("Null rate")
    ax.set_title(title)
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def _chart_pillar_numeric_boxplots(
    fstats_sub: dict[str, Any],
    *,
    title: str,
    max_features: int = 14,
) -> str | None:
    specs: list[tuple[str, dict[str, Any]]] = []
    for k, d in sorted(fstats_sub.items(), key=lambda x: str(x[0])):
        if not isinstance(d, dict) or str(d.get("kind")) != "numeric":
            continue
        lo = _safe_float(d.get("min"))
        hi = _safe_float(d.get("max"))
        if lo is None or hi is None:
            continue
        p5 = _safe_float(d.get("p5"))
        p95 = _safe_float(d.get("p95"))
        mean = _safe_float(d.get("mean"))
        med = mean if mean is not None else (float(lo) + float(hi)) / 2.0
        q1 = p5 if p5 is not None else float(lo)
        q3 = p95 if p95 is not None else float(hi)
        box = {
            "med": float(med),
            "q1": float(q1),
            "q3": float(q3),
            "whislo": float(lo),
            "whishi": float(hi),
            "fliers": [],
        }
        specs.append((str(k)[:44], box))
        if len(specs) >= max_features:
            break
    if not specs:
        return None
    labels = [s[0] for s in specs]
    boxes = [s[1] for s in specs]
    fig, ax = plt.subplots(figsize=(8, max(3.5, 0.24 * len(labels))))
    pos = np.arange(len(labels))
    ax.bxp(boxes, positions=pos, vert=False, showfliers=False)
    ax.set_yticks(pos)
    ax.set_yticklabels(labels, fontsize=7)
    ax.set_title(title + " — approximate boxes (min / p5–p95 / max)")
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def _chart_dq_pillars(dq_summary: dict[str, Any]) -> str | None:
    pillars = dq_summary.get("pillar_results") or []
    if not isinstance(pillars, list) or not pillars:
        return None
    names: list[str] = []
    ok_frac: list[float] = []
    for p in pillars:
        if not isinstance(p, dict):
            continue
        checks = p.get("checks") or {}
        if not isinstance(checks, dict):
            checks = {}
        n_tot = len(checks)
        if n_tot == 0:
            continue
        n_ok = sum(1 for v in checks.values() if v)
        names.append(str(p.get("pillar", "?")))
        ok_frac.append(n_ok / float(n_tot))
    if not names:
        return None
    y = np.arange(len(names))
    bad_frac = [1.0 - o for o in ok_frac]
    fig, ax = plt.subplots(figsize=(8, max(3.0, 0.38 * len(names))))
    ax.barh(y, ok_frac, color="#91cf60", label="Checks passed")
    ax.barh(y, bad_frac, left=ok_frac, color="#fca5a5", label="Checks failed")
    ax.set_yticks(y)
    ax.set_yticklabels(names)
    ax.set_xlim(0, 1)
    ax.set_xlabel("Fraction of pillar checks")
    ax.set_title("Data quality pillars")
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def _chart_performance_metrics(
    best_cv_rmse: Any,
    test_m: dict[str, Any],
    perf_ctx: dict[str, Any],
) -> str | None:
    fig, axes = plt.subplots(2, 2, figsize=(8.5, 6.5))

    b_cv = _safe_float(best_cv_rmse)
    t_rmse = _safe_float(test_m.get("rmse"))
    ax = axes[0, 0]
    if b_cv is not None or t_rmse is not None:
        xs = ["Best CV\nRMSE", "Test\nRMSE"]
        ys = [(b_cv if b_cv is not None else 0.0), (t_rmse if t_rmse is not None else 0.0)]
        ax.bar(xs, ys, color=["#a7c7e7", "#4c78a8"])
        ax.set_title("RMSE")
        for i, v in enumerate(ys):
            if (b_cv if i == 0 else t_rmse) is not None:
                ax.text(i, v, f"{v:,.0f}", ha="center", va="bottom", fontsize=8)
    else:
        ax.text(0.5, 0.5, "No RMSE", ha="center", va="center", transform=ax.transAxes)

    mae = _safe_float(test_m.get("mae"))
    ax = axes[0, 1]
    if mae is not None:
        ax.bar(["Test MAE"], [mae], color="#f58518")
        ax.set_title("MAE")
        ax.text(0, mae, f"{mae:,.0f}", ha="center", va="bottom", fontsize=8)
    else:
        ax.text(0.5, 0.5, "No MAE", ha="center", va="center", transform=ax.transAxes)

    mape = _safe_float(test_m.get("mape"))
    ax = axes[1, 0]
    if mape is not None:
        ax.bar(["Test MAPE"], [mape], color="#54a24b")
        ax.set_title("MAPE")
        ax.text(0, mape, f"{mape:.4f}", ha="center", va="bottom", fontsize=8)
    else:
        ax.text(0.5, 0.5, "No MAPE", ha="center", va="center", transform=ax.transAxes)

    r2 = _safe_float(test_m.get("r2"))
    ax = axes[1, 1]
    if r2 is not None:
        ax.bar(["Test R²"], [r2], color="#b279a2")
        ax.set_title("R²")
        ax.text(0, r2, f"{r2:.4f}", ha="center", va="bottom", fontsize=8)
    else:
        ax.text(0.5, 0.5, "No R²", ha="center", va="center", transform=ax.transAxes)

    ratio = perf_ctx.get("best_cv_rmse_vs_test_rmse_ratio")
    pct_med = perf_ctx.get("rmse_pct_of_test_median_price")
    fig.suptitle(
        f"Context: RMSE % median price={pct_med!s}; CV/test RMSE ratio={ratio!s}",
        fontsize=9,
        y=0.02,
    )
    fig.tight_layout(rect=[0, 0.04, 1, 1])
    return _fig_to_data_uri(fig)


def _chart_cv_fold_rmse(tc: dict[str, Any]) -> str | None:
    test_v = tc.get("cv_fold_rmse_list") or []
    train_v = tc.get("cv_fold_train_rmse_list") or []
    if not isinstance(test_v, list):
        return None
    n = len(test_v)
    if n == 0 or all(v is None for v in test_v):
        return None
    x = np.arange(n)
    tests = [_safe_float(v) for v in test_v]
    trains: list[float | None] = []
    if isinstance(train_v, list) and len(train_v) >= n:
        trains = [_safe_float(train_v[i]) for i in range(n)]
    else:
        trains = [None] * n

    fig, ax = plt.subplots(figsize=(8, 4.2))
    t_vals = [float(t) if t is not None else np.nan for t in tests]
    bar_heights = [v if not np.isnan(v) else 0.0 for v in t_vals]
    ax.bar(x, bar_heights, color="#4c78a8", label="Test RMSE (fold)")
    tr_plot = [float(t) if t is not None else np.nan for t in trains]
    if any(not np.isnan(v) for v in tr_plot):
        ax.plot(x, tr_plot, "o-", color="#ff7f0e", linewidth=2, markersize=6, label="Train RMSE (fold)")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{i}" for i in range(n)])
    ax.set_xlabel("CV fold index")
    ax.set_ylabel("RMSE")
    ax.set_title("CV fold stability (best hyperparameter set)")
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def _chart_residual_by_flat_type(rows: list[Any]) -> str | None:
    if not rows:
        return None
    ok = [r for r in rows if isinstance(r, dict)]
    if not ok:
        return None
    labels = [str(r.get("flat_type", "?"))[:22] for r in ok][::-1]
    means = [_safe_float(r.get("residual_mean")) or 0.0 for r in ok][::-1]
    stds = [_safe_float(r.get("residual_std")) or 0.0 for r in ok][::-1]
    fig, ax = plt.subplots(figsize=(8, max(3.2, 0.26 * len(labels))))
    y_pos = np.arange(len(labels))
    ax.barh(y_pos, means, xerr=stds, color="#bc6c25", alpha=0.88, capsize=3)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels)
    ax.axvline(0, color="#333", linewidth=0.8)
    ax.set_xlabel("Residual mean ± 1 std (actual − pred)")
    ax.set_title("Residuals by flat type (test)")
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def _chart_residual_price_tiers(rows: list[Any]) -> str | None:
    if not rows:
        return None
    order = ("low", "mid", "high")
    by_tier: dict[str, dict[str, Any]] = {}
    for r in rows:
        if isinstance(r, dict) and r.get("tier") is not None:
            by_tier[str(r["tier"])] = r
    labels: list[str] = []
    over_v: list[float] = []
    under_v: list[float] = []
    for t in order:
        if t not in by_tier:
            continue
        d = by_tier[t]
        labels.append(t)
        over_v.append(float(_safe_float(d.get("over_predict_rate")) or 0.0))
        under_v.append(float(_safe_float(d.get("under_predict_rate")) or 0.0))
    if not labels:
        return None
    x = np.arange(len(labels))
    w = 0.35
    fig, ax = plt.subplots(figsize=(6.5, 4))
    ax.bar(x - w / 2, over_v, width=w, label="Over-predict rate", color="#72b7b2")
    ax.bar(x + w / 2, under_v, width=w, label="Under-predict rate", color="#f58518")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 1)
    ax.set_ylabel("Rate")
    ax.set_title("Over / under prediction by price tier (test)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def _chart_residual_by_town(rows: list[Any]) -> str | None:
    if not rows:
        return None
    ok = [r for r in rows if isinstance(r, dict)]
    if not ok:
        return None
    labels = [str(r.get("town", "?"))[:26] for r in ok][::-1]
    means = [_safe_float(r.get("residual_mean")) or 0.0 for r in ok][::-1]
    fig, ax = plt.subplots(figsize=(8, max(3.2, 0.28 * len(labels))))
    ax.barh(labels, means, color="#58508d")
    ax.axvline(0, color="#333", linewidth=0.8)
    ax.set_xlabel("Mean residual (actual − pred)")
    ax.set_title("Residuals by town (top-N by test count)")
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def _chart_residual_by_month(rows: list[Any]) -> str | None:
    if not rows:
        return None
    ok = [r for r in rows if isinstance(r, dict)]
    if not ok:
        return None
    ok.sort(key=lambda d: str(d.get("month", "")))
    xs = [str(d.get("month", "?")) for d in ok]
    means = [_safe_float(d.get("residual_mean")) for d in ok]
    stds = [_safe_float(d.get("residual_std")) for d in ok]
    if not xs:
        return None
    x_idx = np.arange(len(xs))
    m_arr = np.array([float(m) if m is not None else np.nan for m in means])
    s_arr = np.array([float(s) if s is not None else 0.0 for s in stds])
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.plot(x_idx, m_arr, "o-", color="#bc6c25", linewidth=2, markersize=5, label="Mean residual")
    ax.fill_between(
        x_idx,
        m_arr - s_arr,
        m_arr + s_arr,
        color="#bc6c25",
        alpha=0.2,
        label="±1 std",
    )
    ax.axhline(0, color="#333", linewidth=0.8)
    ax.set_xticks(x_idx)
    ax.set_xticklabels(xs, rotation=45, ha="right", fontsize=7)
    ax.set_ylabel("Residual")
    ax.set_title("Residual drift by transaction month (test)")
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def _chart_top_feature_importance(top_cross: list[Any]) -> str | None:
    items = [x for x in top_cross if isinstance(x, dict) and x.get("feature")]
    if not items:
        return None
    items = sorted(items, key=lambda d: float(_safe_float(d.get("importance")) or 0.0))
    items = items[-20:]
    labels = [str(d.get("feature"))[:38] for d in items]
    imp = [float(_safe_float(d.get("importance")) or 0.0) for d in items]
    nulls = [float(_safe_float(d.get("null_rate")) or 0.0) for d in items]
    mx = max(nulls) if nulls else 0.0
    norm_n = [0.25 + 0.75 * (n / mx) if mx > 0 else 0.25 for n in nulls]
    cmap = plt.cm.Reds
    colors = [cmap(min(1.0, x)) for x in norm_n]
    fig, ax = plt.subplots(figsize=(8, max(3.5, 0.32 * len(labels))))
    ax.barh(labels, imp, color=colors)
    ax.set_xlabel("Importance (higher null rate → redder)")
    ax.set_title("Top features × importance (color encodes training null rate)")
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def _format_numeric_cell(value: Any, *, precision: str = ".6g", empty: str = "—") -> str:
    if value is None:
        return empty
    try:
        return format(float(value), precision)
    except (TypeError, ValueError):
        return empty


def _feature_importance_table_page(top_cross: list[Any]) -> dict[str, Any] | None:
    rows_in = [x for x in top_cross if isinstance(x, dict) and x.get("feature")]
    if not rows_in:
        return None
    rows_in.sort(key=lambda d: float(_safe_float(d.get("importance")) or 0.0), reverse=True)
    columns = (
        {"key": "feature", "label": "Feature"},
        {"key": "importance", "label": "Importance"},
        {"key": "train_null_rate", "label": "Train null rate"},
    )
    tbl_rows = []
    for d in rows_in:
        nr = _safe_float(d.get("null_rate"))
        tbl_rows.append(
            {
                "feature": str(d["feature"]),
                "importance": _format_numeric_cell(d.get("importance")),
                "train_null_rate": "—" if nr is None else format(float(nr), ".6g"),
            }
        )
    return {
        "kind": "table",
        "heading": "Section 8 — Feature importances (table)",
        "caption": (
            "Preprocessor-output feature names ranked by fitted tree/model ``feature_importances_`` "
            "when applicable; aligns with matplotlib ``feature_importance.png``."
        ),
        "columns": list(columns),
        "rows": tbl_rows,
    }


def _shap_features_table_page(top_shap: list[Any]) -> dict[str, Any] | None:
    rows_in: list[dict[str, Any]] = []
    for x in top_shap:
        if isinstance(x, dict) and x.get("feature"):
            phi = _safe_float(x.get("mean_abs_shap"))
            if phi is not None:
                rows_in.append(x)
    if not rows_in:
        return None
    rows_in.sort(key=lambda d: float(_safe_float(d.get("mean_abs_shap")) or 0.0), reverse=True)
    columns = (
        {"key": "feature", "label": "Feature"},
        {"key": "mean_abs_shap", "label": "Mean |SHAP|"},
        {"key": "train_null_rate", "label": "Train null rate"},
    )
    tbl_rows = []
    for d in rows_in:
        nr = _safe_float(d.get("null_rate"))
        tbl_rows.append(
            {
                "feature": str(d["feature"]),
                "mean_abs_shap": _format_numeric_cell(d.get("mean_abs_shap")),
                "train_null_rate": "—" if nr is None else format(float(nr), ".6g"),
            }
        )
    return {
        "kind": "table",
        "heading": "Section 8 — SHAP attribution (table)",
        "caption": (
            "Mean |SHAP| aggregated over random rows from the engineered test split (~2000 cap). "
            "SHAP reflects the fitted inner estimator (adjusted target). Null rate from training stats keyed by preprocessor name."
        ),
        "columns": list(columns),
        "rows": tbl_rows,
    }


def _chart_mean_abs_shap(top_shap: list[Any]) -> str | None:
    rows_in: list[tuple[str, float]] = []
    for x in top_shap:
        if isinstance(x, dict) and x.get("feature"):
            phi = _safe_float(x.get("mean_abs_shap"))
            if phi is not None:
                rows_in.append((str(x["feature"])[:52], float(phi)))
    if not rows_in:
        return None
    rows_in.sort(key=lambda z: z[1])
    labels = [a for a, _ in rows_in]
    vals = [b for _, b in rows_in]
    fig, ax = plt.subplots(figsize=(8, max(3.5, 0.32 * len(labels))))
    ax.barh(labels, vals, color="#8e44ad")
    ax.set_xlabel("Mean |SHAP|")
    ax.set_title("SHAP attribution — ranked features")
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def _kv_rows(raw: list[tuple[Any, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for k, v in raw:
        out.append({"label": str(k), "value": str(v)})
    return out


def _build_pages(
    *,
    run_id: str,
    metrics_payload: dict[str, Any],
    dq_summary: dict[str, Any],
    plots_dir: Path,
    generated_at: str,
    fs_description: str,
    selection_artifacts: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []

    tc = metrics_payload.get("training_context") or {}
    test_m = metrics_payload.get("test_metrics") or {}
    best_rmse = metrics_payload.get("best_cv_rmse")

    fstats: dict[str, Any] = {}
    mp_fs = metrics_payload.get("feature_stats_full")
    if isinstance(mp_fs, dict) and mp_fs:
        fstats = mp_fs
    else:
        dq_fs = dq_summary.get("feature_stats")
        if isinstance(dq_fs, dict):
            fstats = dq_fs

    residual_month = metrics_payload.get("residual_by_month") or []
    if not isinstance(residual_month, list):
        residual_month = []
    residual_town = metrics_payload.get("residual_by_town") or []
    if not isinstance(residual_town, list):
        residual_town = []

    bp_plain = metrics_payload.get("best_params_plain")
    if not isinstance(bp_plain, dict):
        bp_plain = {}

    sql_cov = dq_summary.get("sql_coverage") if isinstance(dq_summary.get("sql_coverage"), dict) else {}

    top_cross = metrics_payload.get("top_feature_importances") or []
    if not isinstance(top_cross, list):
        top_cross = []

    top_shap_feats = metrics_payload.get("top_shap_features") or []
    if not isinstance(top_shap_feats, list):
        top_shap_feats = []

    data_profile = metrics_payload.get("data_profile") or {}
    target_stats = metrics_payload.get("target_stats") or {}
    perf_ctx = metrics_payload.get("performance_context") or {}
    residual_flat = metrics_payload.get("residual_by_flat_type") or []
    if not isinstance(residual_flat, list):
        residual_flat = []
    residual_tier = metrics_payload.get("residual_price_tier_calibration") or []
    if not isinstance(residual_tier, list):
        residual_tier = []

    fs_id = metrics_payload.get("feature_set")

    sel_art = selection_artifacts if isinstance(selection_artifacts, dict) else {}
    sel_flags = build_selection_flags(sel_art)

    audit_full = metrics_payload.get("training_matrix_audit")
    fd_doc = sel_art.get("features_dropped") if isinstance(sel_art.get("features_dropped"), dict) else None
    inventory_by_pillar: dict[str, list[dict[str, Any]]] = {}
    pack_inventory_summary: list[dict[str, Any]] = []
    if isinstance(audit_full, dict) and isinstance(audit_full.get("registered_feature_set"), dict):
        inventory_by_pillar, pack_inventory_summary = build_pillar_feature_inventory(
            training_matrix_audit=audit_full,
            selection_flags=sel_flags,
            feature_set_id=fs_id if isinstance(fs_id, str) else None,
            features_dropped_doc=fd_doc,
        )
    fs_display = format_feature_set_display(
        fs_id if isinstance(fs_id, str) else None,
        description=fs_description or None,
    )

    fs_pol = feature_selection_policy_from_metrics(metrics_payload)
    fs_cover_removed_preview = format_columns_removed_cover_preview(metrics_payload)

    columns_removed_cover_row: tuple[str, Any] | None = None
    if fs_pol == "apply_recommended_drops":
        rm_summary = feature_selection_summary_from_metrics(metrics_payload)
        n_rm = rm_summary.get("columns_removed_count")
        preview = fs_cover_removed_preview if fs_cover_removed_preview is not None else "(unknown)"
        columns_removed_cover_row = (
            "Columns removed (pre-fit)",
            f"{n_rm}: {preview}" if isinstance(n_rm, int) else preview,
        )

    cover_rows = [
        ("Run ID", run_id),
        ("Generated", generated_at),
        ("Experiment", metrics_payload.get("experiment_id")),
        ("Feature set", fs_display),
        ("Feature set (internal id)", fs_id),
        ("Model", metrics_payload.get("model")),
        ("N-train", metrics_payload.get("n_train")),
        ("N-test", metrics_payload.get("n_test")),
        ("Feature selection policy", format_feature_selection_policy_short(fs_pol)),
        *([] if columns_removed_cover_row is None else [columns_removed_cover_row]),
        ("Data source", tc.get("training_source", "")),
        ("Dataset path", tc.get("dataset_path", "")),
        ("Dataset months", f"{tc.get('dataset_month_min', '')} → {tc.get('dataset_month_max', '')}"),
        ("First test month", tc.get("temporal_split_first_test_month", "")),
        ("Test fraction", tc.get("test_fraction")),
        ("CV splits", tc.get("cv_splits")),
        ("Git commit", tc.get("git_commit") or "(unset)"),
        ("App version", tc.get("app_version") or "(unset)"),
        ("Dataset version", tc.get("dataset_version", "")),
        ("Loader min month", tc.get("min_tx_month") or "(none)"),
        ("DQ gates passed", dq_summary.get("gates_passed", "(no DQ block)")),
    ]
    hp_json: str | None = None
    if bp_plain:
        try:
            hp_json = json.dumps(bp_plain, indent=2, sort_keys=True, default=str)
        except (TypeError, ValueError):
            hp_json = None

    pages.append(
        {
            "kind": "cover",
            "title": "Experiment Training Report",
            "subtitle": "Prepared by HomeyAI — Model transparency",
            "lead": "Section 1 — Experiment identity and provenance",
            "rows": _kv_rows(cover_rows),
            "best_params_json": hp_json,
        }
    )

    audit = metrics_payload.get("training_matrix_audit")
    if isinstance(audit, dict) and audit.get("raw_split_input"):
        raw_a = audit.get("raw_split_input") if isinstance(audit.get("raw_split_input"), dict) else {}
        eng_a = audit.get("engineered") if isinstance(audit.get("engineered"), dict) else {}
        pre_a = audit.get("preprocessor_output") if isinstance(audit.get("preprocessor_output"), dict) else {}
        reg_a = audit.get("registered_feature_set") if isinstance(audit.get("registered_feature_set"), dict) else {}
        warns = audit.get("engineered_vs_registry_warnings") or []
        if not isinstance(warns, list):
            warns = []
        per_flag = Counter()
        for _fname, tags in sel_flags.items():
            for t in tags:
                per_flag[str(t)] += 1
        policy_text = format_training_matrix_audit_policy_text(audit)
        flag_rows = [{"flag": k, "n_features": int(v)} for k, v in sorted(per_flag.items())]
        policy_raw = audit.get("feature_selection_policy")
        policy_code = str(policy_raw).strip() if policy_raw is not None else None
        policy_badge = format_feature_selection_policy_badge(policy_code if policy_code else None)
        pack_summary_rows = (
            [
                {
                    "pack": PILLAR_HEADINGS.get(str(row.get("pillar_id", "")), str(row.get("pillar_id", ""))),
                    "registered": int(row["registered"]),
                    "retained": int(row["retained"]),
                    "dropped": int(row["dropped"]),
                    "flagged_advisory": int(row["flagged_advisory"]),
                }
                for row in pack_inventory_summary
            ]
            if pack_inventory_summary
            else []
        )
        audit_rows: list[tuple[str, str]] = []
        enc_map = audit.get("model_encoding")
        if isinstance(enc_map, dict):
            ft_enc = enc_map.get("flat_type")
            if isinstance(ft_enc, dict):
                audit_rows.append(
                    (
                        "Flat type in model",
                        (
                            f"ordinal column {ft_enc.get('model_column', 'flat_type_encoded')} "
                            f"({ft_enc.get('encoding', 'ordinal_1_7')}); "
                            f"raw {ft_enc.get('raw_column_eda_only', 'flat_type')} is EDA-only (not one-hot)."
                        ),
                    )
                )
        uri_variance = _png_data_uri(plots_dir, "feature_selection_variance.png")
        uri_mi = _png_data_uri(plots_dir, "feature_selection_mi.png")
        uri_corr = _png_data_uri(plots_dir, "feature_selection_correlation.png")
        pages.append(
            {
                "kind": "training_matrix_audit",
                "heading": "Training matrix audit",
                "policy_badge": policy_badge,
                "policy": policy_text,
                "rows": _kv_rows(
                    audit_rows
                    + [
                        (
                            "Raw split → pipeline input",
                            (
                                f"{raw_a.get('n_columns', '—')} columns, {raw_a.get('n_rows', '—')} training rows "
                                "(column list in metrics.json / training_matrix_audit)."
                            ),
                        ),
                        (
                            "Engineered frame (post feature_engineering step)",
                            (
                                f"{eng_a.get('n_columns', '—')} columns, {eng_a.get('n_rows', '—')} rows "
                                "(same row set as training split)."
                            ),
                        ),
                        (
                            "ColumnTransformer output (design matrix)",
                            f"{pre_a.get('n_features_out', '—')} features after preprocessing",
                        ),
                        (
                            "Registered in FeatureSet",
                            (
                                f"{reg_a.get('n_numeric', '—')} numeric + {reg_a.get('n_categorical', '—')} categorical "
                                "(see metrics.json for full lists)."
                            ),
                        ),
                    ]
                ),
                "flag_counts": flag_rows,
                "registry_warnings": [str(w) for w in warns],
                "sample_note": (
                    "Sample transformed names (head/tail) live in metrics.json under training_matrix_audit.preprocessor_output. "
                    "The full list is stored as pipeline_feature_names.json in the experiment bundle."
                ),
                "uri_variance": uri_variance,
                "uri_mi": uri_mi,
                "uri_corr": uri_corr,
                "selection_pngs_all_missing": uri_variance is None and uri_mi is None and uri_corr is None,
                "pack_summary_rows": pack_summary_rows,
            }
        )

    grouped_stats = group_feature_stats_by_pillar(fstats, feature_set_id=fs_id if isinstance(fs_id, str) else None)
    section2_lines: list[str] = [
        f"Profile rows: {data_profile.get('n_rows') if isinstance(data_profile, dict) else '—'}",
        f"Month span: {data_profile.get('month_min', '')} → {data_profile.get('month_max', '')}"
        if isinstance(data_profile, dict)
        else "",
        f"Registered feature set: {fs_id}",
        f"Human-readable label: {format_feature_set_display(fs_id if isinstance(fs_id, str) else None, description=None)}",
    ]
    if not pack_inventory_summary:
        section2_lines.append(
            "Full registry column inventory unavailable — metrics lack training_matrix_audit.registered_feature_set; "
            "re-run training or regenerate from a run that records the audit block."
        )
    else:
        for row in pack_inventory_summary:
            title = PILLAR_HEADINGS.get(str(row.get("pillar_id", "")), str(row.get("pillar_id", "")))
            section2_lines.append(
                f"{title} pack inventory: {row['retained']} retained, {row['dropped']} dropped (pipeline), "
                f"{row['flagged_advisory']} flagged (advisory); {row['registered']} registered columns."
            )
    for pid, title in PILLAR_HEADINGS.items():
        sub = grouped_stats.get(pid) or {}
        if not sub:
            continue
        n_num = sum(1 for d in sub.values() if isinstance(d, dict) and str(d.get("kind")) == "numeric")
        n_cat = sum(1 for d in sub.values() if isinstance(d, dict) and str(d.get("kind")) == "categorical")
        section2_lines.append(f"{title}: {n_num} numeric, {n_cat} categorical; {len(sub)} columns in this group")
    section2_lines.append(f"Grand total features (columns in training stats): {len(fstats)}")
    section2_lines = [ln for ln in section2_lines if ln]

    pages.append(
        {
            "kind": "section2_summary",
            "heading": "Section 2 — Training data summary",
            "lines": section2_lines,
            "note": (
                "Per-pack registry tables below list every registered model column with retained vs dropped (pipeline) vs "
                "flagged (advisory-only diagnostics). Prefit numeric drops only — categoricals are unchanged. "
                "See Training matrix audit for stage counts and policy."
            ),
        }
    )

    dp_dict = data_profile if isinstance(data_profile, dict) else {}
    uri_ft = _chart_flat_type_breakdown(dp_dict)
    pages.append(
        {
            "kind": "plot",
            "heading": "Section 2 — Flat type distribution",
            "src": uri_ft,
            "caption": (
                "Share of training rows by raw flat_type (EDA). "
                "The model uses ordinal flat_type_encoded (1–7), not one-hot flat_type columns."
            ),
        }
    )

    uri_tw = _chart_top_towns(dp_dict)
    pages.append(
        {
            "kind": "plot",
            "heading": "Section 2 — Top towns",
            "src": uri_tw,
            "caption": "Share of training rows for top towns.",
        }
    )

    ts_dict = target_stats if isinstance(target_stats, dict) else {}
    uri_box = _chart_train_test_target_box(ts_dict)
    pages.append(
        {
            "kind": "plot",
            "heading": "Section 2 — Train vs test target distribution",
            "src": uri_box,
            "caption": "Boxes reconstructed from stored quantiles (min, p25, median, p75, max).",
        }
    )

    for pid, pillar_title in PILLAR_HEADINGS.items():
        sub = grouped_stats.get(pid) or {}
        inv_rows = inventory_by_pillar.get(pid) or []
        if not sub and not inv_rows:
            continue
        null_uri = _chart_pillar_feature_nulls(
            sub,
            title=f"{pillar_title} — top null rates",
            top_n=18,
        )
        box_uri = _chart_pillar_numeric_boxplots(
            sub,
            title=pillar_title,
            max_features=14,
        )
        cat_rows: list[dict[str, Any]] = []
        for name in sorted(sub.keys()):
            d = sub[name]
            if isinstance(d, dict) and str(d.get("kind")) == "categorical":
                if d.get("in_model") is False:
                    continue
                enc = d.get("encoding")
                cat_rows.append(
                    {
                        "name": name,
                        "nunique": d.get("nunique"),
                        "null_rate": d.get("null_rate"),
                        "encoding": enc,
                    }
                )
        outcome_rows: list[dict[str, Any]] = []
        for name in sorted(sub.keys()):
            d = sub.get(name)
            if isinstance(d, dict) and d.get("in_model") is False:
                continue
            fl = sel_flags.get(name, [])
            enc = d.get("encoding") if isinstance(d, dict) else None
            base_summary = (
                "Used in model — no diagnostic flags"
                if not fl
                else "Flagged (diagnostic): " + ", ".join(fl)
            )
            if enc:
                base_summary = f"{base_summary}; encoding={enc}"
            outcome_rows.append(
                {
                    "feature": name,
                    "flags": fl,
                    "summary": base_summary,
                }
            )
        pages.append(
            {
                "kind": "feature_pillar",
                "heading": f"Section 2 — {pillar_title}",
                "null_chart_src": null_uri,
                "box_chart_src": box_uri,
                "categorical_rows": cat_rows,
                "inventory_rows": inv_rows,
                "outcome_rows": outcome_rows,
            }
        )

    if sql_cov.get("error"):
        pages.append(
            {
                "kind": "kv",
                "heading": "Section 3 — Data coverage and join rates (SQL)",
                "rows": _kv_rows([("SQL coverage", sql_cov.get("error"))]),
            }
        )
    else:
        ws = sql_cov.get("window_summary")
        ws_txt = str(ws)[:1200] if isinstance(ws, dict) else ""
        findings_lines: list[str] = []
        for f in sql_cov.get("findings") or []:
            if isinstance(f, dict):
                findings_lines.append(f"[{f.get('severity')}] {f.get('code')}: {f.get('message')}")
        cap_parts = []
        if ws_txt:
            cap_parts.append("Window summary: " + ws_txt)
        if findings_lines:
            cap_parts.append("Findings:\n" + "\n".join(findings_lines))
        caption_sql = "\n\n".join(cap_parts)[:4500]
        uri_sql = _chart_sql_coverage_pct(sql_cov)
        if uri_sql is not None:
            pages.append(
                {
                    "kind": "plot",
                    "heading": "Section 3 — SQL coverage rates",
                    "src": uri_sql,
                    "caption": caption_sql or "Aggregate rates (%).",
                }
            )
        else:
            fb_rows: list[tuple[str, Any]] = []
            if ws_txt:
                fb_rows.append(("Window summary", ws_txt))
            agg = sql_cov.get("aggregates") or {}
            if isinstance(agg, dict):
                for ak, av in sorted(agg.items()):
                    fb_rows.append((str(ak), av))
            pct = sql_cov.get("aggregate_rates_pct") or {}
            if isinstance(pct, dict) and pct:
                for pk, pv in sorted(pct.items()):
                    fb_rows.append((str(pk), f"{pv}%"))
            for msg in findings_lines:
                fb_rows.append(("Finding", msg))
            pages.append(
                {
                    "kind": "kv",
                    "heading": "Section 3 — Data coverage and join rates (SQL)",
                    "rows": _kv_rows(fb_rows or [("(none)", "")]),
                }
            )

    missing_uri = _png_data_uri(plots_dir, "missingness.png")
    pages.append(
        {
            "kind": "plot",
            "heading": "Diagnostics — Missingness",
            "src": missing_uri,
            "caption": "missingness.png",
        }
    )

    dq_fail_caption_parts: list[str] = []
    for p in dq_summary.get("pillar_results") or []:
        if isinstance(p, dict) and not p.get("passed"):
            name = str(p.get("pillar", "?"))
            fails = p.get("failures") or []
            if fails:
                dq_fail_caption_parts.append(f"[{name}] " + "; ".join(str(x) for x in fails))
    dq_caption = ("\n".join(dq_fail_caption_parts)[:4500]) if dq_fail_caption_parts else "Green = passed checks; red = failed."

    uri_dq = _chart_dq_pillars(dq_summary)
    pages.append(
        {
            "kind": "plot",
            "heading": "Section 4 — Data quality pillars",
            "src": uri_dq,
            "caption": dq_caption,
        }
    )

    uri_perf = _chart_performance_metrics(best_rmse, test_m if isinstance(test_m, dict) else {}, perf_ctx if isinstance(perf_ctx, dict) else {})
    pages.append(
        {
            "kind": "plot",
            "heading": "Section 5 — Model performance",
            "src": uri_perf,
            "caption": "Scalar metrics from metrics.json.",
        }
    )

    tc_dict = tc if isinstance(tc, dict) else {}
    uri_cv = _chart_cv_fold_rmse(tc_dict)
    pages.append(
        {
            "kind": "plot",
            "heading": "Section 6 — CV fold RMSE (test bars, train overlay)",
            "src": uri_cv,
            "caption": "Large train–test gap may indicate overfitting.",
        }
    )

    pages.append(
        {
            "kind": "plot",
            "heading": "Predicted vs actual (test)",
            "src": _png_data_uri(plots_dir, "preds_vs_actual.png"),
            "caption": "preds_vs_actual.png",
        }
    )
    pages.append(
        {
            "kind": "plot",
            "heading": "Residual distribution",
            "src": _png_data_uri(plots_dir, "residuals.png"),
            "caption": "residuals.png",
        }
    )

    uri_rflat = _chart_residual_by_flat_type(residual_flat)
    pages.append(
        {
            "kind": "plot",
            "heading": "Section 7 — Residuals by flat type",
            "src": uri_rflat,
            "caption": "Mean residual ± 1 std (horizontal error bars).",
        }
    )

    uri_rtier = _chart_residual_price_tiers(residual_tier)
    pages.append(
        {
            "kind": "plot",
            "heading": "Section 7 — Over/under prediction by price tier",
            "src": uri_rtier,
            "caption": "Test-set tiers by actual price quantiles.",
        }
    )

    uri_rtown = _chart_residual_by_town(residual_town)
    pages.append(
        {
            "kind": "plot",
            "heading": "Section 7 — Residuals by town",
            "src": uri_rtown,
            "caption": "Mean residual for towns with sufficient test rows.",
        }
    )

    uri_rmonth = _chart_residual_by_month(residual_month)
    pages.append(
        {
            "kind": "plot",
            "heading": "Section 7 — Residual drift by month (test)",
            "src": uri_rmonth,
            "caption": "Track temporal bias on the holdout window.",
        }
    )

    fs_body = (fs_description[:3500] if fs_description else "(no feature_set_description in config.json)")
    pages.append({"kind": "prose", "heading": "Section 8 — Feature set description", "body": fs_body})

    uri_fi = _chart_top_feature_importance(top_cross)
    fi_png = _png_data_uri(plots_dir, "feature_importance.png")
    pages.append(
        {
            "kind": "plot",
            "heading": "Section 8 — Top feature importances × training null rate",
            "src": uri_fi or fi_png,
            "caption": (
                "Bar chart from metrics when available; otherwise training-time feature_importance.png."
            ),
        }
    )

    tbl_fi = _feature_importance_table_page(top_cross)
    if tbl_fi:
        pages.append(tbl_fi)

    uri_shap = _png_data_uri(plots_dir, "shap_importance.png") or _chart_mean_abs_shap(top_shap_feats)
    shap_absent = None
    if uri_shap is None:
        shap_absent = (
            "SHAP summary plot not available (unsupported estimator, too few engineered test rows, "
            "run predates SHAP wiring, or ``training_shap_skipped`` in logs)."
        )

    pages.append(
        {
            "kind": "plot",
            "heading": "Section 8 — SHAP summary (mean |SHAP|)",
            "src": uri_shap,
            "caption": (
                "Purple bars show mean absolute SHAP on a stratified/random sample of engineered test rows; "
                "matches ``plots/shap_importance.png`` when present."
            ),
            "absent_note": shap_absent,
        }
    )

    tbl_shap = _shap_features_table_page(top_shap_feats)
    if tbl_shap:
        pages.append(tbl_shap)

    pages.append(
        {
            "kind": "disclaimer",
            "rows": [
                {
                    "value": (
                        "This report summarizes offline training diagnostics for transparency. "
                        "It is not investment advice. Production valuations may use different snapshots "
                        "or pinned models."
                    ),
                }
            ],
        }
    )

    return pages


def build_training_report_html_string(
    *,
    run_id: str,
    metrics_payload: dict[str, Any],
    dq_summary: dict[str, Any],
    plots_dir: Path,
    selection_artifacts: dict[str, Any] | None = None,
) -> str:
    """Compose the rendered training-report HTML prior to PDF conversion (explicit text for testing)."""

    plots_dir = plots_dir.resolve()
    exp_root = plots_dir.parent
    generated_at = datetime.now(ZoneInfo("Asia/Singapore")).strftime("%Y-%m-%d %H:%M UTC+8")

    metrics_local = dict(metrics_payload)

    cfg_path = exp_root / "config.json"
    fs_description = ""
    if cfg_path.is_file():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            fs_description = str(cfg.get("feature_set_description") or "")
        except (json.JSONDecodeError, OSError, TypeError):
            pass

    sel = selection_artifacts if isinstance(selection_artifacts, dict) else load_selection_artifacts_from_dir(exp_root)

    bpp = metrics_local.get("best_params_plain")
    if not isinstance(bpp, dict) or not bpp:
        bpath = exp_root / "best_params.json"
        if bpath.is_file():
            try:
                raw_bp = json.loads(bpath.read_text(encoding="utf-8"))
                if isinstance(raw_bp, dict):
                    metrics_local["best_params_plain"] = {
                        str(k): str(v) for k, v in raw_bp.items()
                    }
            except (json.JSONDecodeError, OSError, TypeError):
                pass

    pages = _build_pages(
        run_id=run_id,
        metrics_payload=metrics_local,
        dq_summary=dq_summary,
        plots_dir=plots_dir,
        generated_at=generated_at,
        fs_description=fs_description,
        selection_artifacts=sel,
    )

    styles = _load_training_styles()
    logo_uri = get_logo_base64() or ""
    return _jinja_env.get_template("training_report.html").render(
        logo_data_uri=logo_uri,
        styles=styles,
        pages=pages,
        year=datetime.now().year,
    )


def render_training_report_pdf_bytes(
    *,
    run_id: str,
    metrics_payload: dict[str, Any],
    dq_summary: dict[str, Any],
    plots_dir: Path,
    selection_artifacts: dict[str, Any] | None = None,
) -> bytes:
    """Return PDF bytes (WeasyPrint). Expects ``config.json`` beside ``plots_dir`` when available."""
    html_str = build_training_report_html_string(
        run_id=run_id,
        metrics_payload=metrics_payload,
        dq_summary=dq_summary,
        plots_dir=plots_dir,
        selection_artifacts=selection_artifacts,
    )

    try:
        from weasyprint import HTML
    except OSError as exc:
        raise RuntimeError(
            "WeasyPrint could not load its system libraries (GObject/Pango). "
            "See https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation ."
        ) from exc

    buf = BytesIO()
    HTML(string=html_str).write_pdf(buf, stylesheets=[_print_stylesheet()])
    out = buf.getvalue()
    if not out:
        raise RuntimeError("WeasyPrint produced an empty PDF buffer.")
    return out


def render_training_report_pdf_to_path(
    *,
    run_id: str,
    metrics_payload: dict[str, Any],
    dq_summary: dict[str, Any],
    plots_dir: Path,
    out_path: Path,
) -> Path:
    """Write training report PDF to ``out_path`` (for rare local tooling)."""
    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_bytes = render_training_report_pdf_bytes(
        run_id=run_id,
        metrics_payload=metrics_payload,
        dq_summary=dq_summary,
        plots_dir=plots_dir,
    )
    out_path.write_bytes(pdf_bytes)
    return out_path
