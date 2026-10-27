"""Training data quality: SQL join completeness + engineered-frame profiling.

Used by the model sweep and standalone reporting. Emits
``modelling/outputs/training_data_report.json`` and a Markdown companion.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text

FEATURE_SET_IDS = ("baseline_v1", "mrt_pit", "poi_distancing", "mrt_pit__poi_distancing")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _pct(part: float, whole: float) -> float:
    if whole <= 0:
        return 0.0
    return 100.0 * part / whole


def collect_sql_training_stats(*, min_years: int) -> dict[str, Any]:
    """Read-only aggregates matching ``get_hdb_resale_query`` join shape."""
    from modelling.training_db import create_training_engine, get_training_window_summary

    engine = create_training_engine()
    out: dict[str, Any] = {"mrt_pit_min_years": min_years, "window_summary": None, "aggregates": {}}
    try:
        try:
            out["window_summary"] = dict(get_training_window_summary(engine, min_years=min_years))
        except Exception as exc:  # noqa: BLE001
            out["window_summary"] = {"error": str(exc)}

        sql = text(
            f"""
            WITH base AS (
                SELECT t.id, t.month, t.enriched_addr_id, t.resale_price,
                       oe.latitude AS lat, oe.longitude AS lon,
                       f.hdb_addr_id AS snap_id,
                       f.dist_to_nearest_op_mrt, f.travel_time_to_active_mrt
                FROM hdb_resale_transactions t
                INNER JOIN mrt_pit_build_jobs jobs
                  ON jobs.tx_year_month = t.month AND jobs.status = 'done'
                LEFT JOIN hdb_address_enrichment_onemap oe ON oe.id = t.enriched_addr_id
                LEFT JOIN hdb_mrt_features_pit_snapshot f
                  ON f.hdb_addr_id = t.enriched_addr_id AND f.tx_year_month = t.month
                WHERE t.month >= to_char(CURRENT_DATE - ({min_years} * INTERVAL '1 year'), 'YYYY-MM')
            ),
            dup AS (
                SELECT enriched_addr_id, month, COUNT(*)::int AS c
                FROM base
                WHERE enriched_addr_id IS NOT NULL AND month IS NOT NULL
                GROUP BY enriched_addr_id, month
                HAVING COUNT(*) > 1
            )
            SELECT
                (SELECT COUNT(*)::bigint FROM base) AS n_transactions,
                (SELECT COUNT(*) FILTER (WHERE enriched_addr_id IS NOT NULL)::bigint FROM base) AS n_enriched,
                (SELECT COUNT(*) FILTER (WHERE lat IS NOT NULL AND lon IS NOT NULL)::bigint FROM base) AS n_coords,
                (SELECT COUNT(*) FILTER (WHERE resale_price IS NULL OR resale_price <= 0)::bigint FROM base) AS n_bad_price,
                (SELECT COUNT(*) FILTER (WHERE snap_id IS NOT NULL)::bigint FROM base) AS n_snapshot_join,
                (SELECT COUNT(*) FILTER (
                    WHERE dist_to_nearest_op_mrt IS NOT NULL AND travel_time_to_active_mrt IS NOT NULL
                 )::bigint FROM base) AS n_mrt_core_nonnull,
                (SELECT COALESCE(SUM(c - 1), 0)::bigint FROM dup) AS n_duplicate_extra_rows
            """
        )
        row = dict(engine.connect().execute(sql).mappings().one())
        out["aggregates"] = {k: int(v) if v is not None else 0 for k, v in row.items()}
    finally:
        engine.dispose()
    return out


def _findings_from_sql(stats: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    ws = stats.get("window_summary") or {}
    if isinstance(ws, dict) and ws.get("error"):
        findings.append(
            {
                "severity": "critical",
                "code": "window_summary_unavailable",
                "message": f"Could not read training window: {ws['error']}",
            }
        )
    elif isinstance(ws, dict):
        need = int(ws.get("expected_min_months", 0))
        got = int(ws.get("n_done_months_in_window", 0))
        if got < need:
            findings.append(
                {
                    "severity": "critical",
                    "code": "pit_window_incomplete",
                    "message": f"Only {got} done job-months in window vs required {need}",
                }
            )
        else:
            findings.append(
                {
                    "severity": "info",
                    "code": "pit_window_ok",
                    "message": f"PIT window OK: {got} done months >= {need}",
                }
            )

    agg = stats.get("aggregates") or {}
    n = max(int(agg.get("n_transactions", 0)), 1)
    join_pct = _pct(float(agg.get("n_snapshot_join", 0)), float(n))
    if join_pct < 85.0:
        findings.append(
            {
                "severity": "warn",
                "code": "snapshot_join_low",
                "message": f"PIT snapshot join rate {join_pct:.1f}% ({agg.get('n_snapshot_join')}/{n})",
            }
        )
    mrt_pct = _pct(float(agg.get("n_mrt_core_nonnull", 0)), float(n))
    if mrt_pct < 70.0:
        findings.append(
            {
                "severity": "warn",
                "code": "mrt_core_sparse",
                "message": f"Core MRT walk/time non-null only {mrt_pct:.1f}% — routing gaps likely",
            }
        )
    if int(agg.get("n_duplicate_extra_rows", 0)) > 0:
        findings.append(
            {
                "severity": "warn",
                "code": "duplicate_addr_month",
                "message": f"Duplicate (enriched_addr_id, month) extra rows: {agg.get('n_duplicate_extra_rows')}",
            }
        )
    if int(agg.get("n_bad_price", 0)) > 0:
        findings.append(
            {
                "severity": "warn",
                "code": "bad_resale_price",
                "message": f"Rows with null or non-positive resale_price: {agg.get('n_bad_price')}",
            }
        )
    coord_pct = _pct(float(agg.get("n_coords", 0)), float(n))
    if coord_pct < 50.0:
        findings.append(
            {
                "severity": "warn",
                "code": "coords_sparse",
                "message": f"Lat/lon present for only {coord_pct:.1f}% — POI stacks will be weak",
            }
        )
    return findings


def profile_engineered_frame(df: pd.DataFrame, feature_set_id: str) -> dict[str, Any]:
    """Null rates, cardinality, near-constant numeric columns (post-engineering)."""
    n = len(df)
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    null_rates = {c: float(df[c].isna().mean()) for c in df.columns}
    high_null = {c: r for c, r in null_rates.items() if r > 0.25}
    cardinality = {}
    for c in ("town", "flat_model"):
        if c in df.columns:
            cardinality[c] = int(df[c].astype(str).nunique(dropna=True))
    ordinal_stats = {}
    if "flat_type_encoded" in df.columns:
        s = pd.to_numeric(df["flat_type_encoded"], errors="coerce")
        ordinal_stats["flat_type_encoded"] = {
            "min": float(s.min(skipna=True)) if s.notna().any() else None,
            "max": float(s.max(skipna=True)) if s.notna().any() else None,
            "null_rate": float(s.isna().mean()),
        }
    const_numeric = []
    for c in numeric_cols:
        if df[c].notna().sum() < 2:
            continue
        std = float(df[c].std(skipna=True))
        if std == 0 or (df[c].notna().sum() > 10 and std < 1e-12):
            const_numeric.append(c)
    return {
        "rows": n,
        "columns": len(df.columns),
        "null_rate_high": high_null,
        "cardinality": cardinality,
        "ordinal_encoded": ordinal_stats,
        "near_constant_numeric": const_numeric[:30],
    }


def engineer_for_feature_set(
    raw_df: pd.DataFrame,
    project_root: Path,
    feature_set_id: str,
    *,
    merge_coords_csv: str | None = None,
    use_db: bool = False,
    database_url: str | None = None,
) -> pd.DataFrame:
    from modelling.config.feature_sets import get_feature_set

    fs = get_feature_set(project_root, feature_set_id)
    kwargs: dict[str, Any] = {"project_root": project_root, **fs.engineer_kwargs}
    if merge_coords_csv is not None:
        kwargs["merge_coords_csv"] = merge_coords_csv
    if use_db and database_url:
        kwargs["use_db"] = True
        kwargs["database_url"] = database_url
    return fs.engineer(raw_df.copy(), **kwargs)


def run_window_quality(
    project_root: Path,
    *,
    min_years: int,
    raw_df: pd.DataFrame,
    loader_desc: str,
) -> dict[str, Any]:
    """SQL stats + per-feature-set engineered profiles for one rolling window."""
    sql_stats = collect_sql_training_stats(min_years=min_years)
    findings = _findings_from_sql(sql_stats)

    poi_path = project_root / "data" / "pois" / "hdb_block_coords.csv"
    merge_csv = str(poi_path) if poi_path.is_file() else None

    poi_db_ok = False
    training_db_url: str | None = None
    try:
        from modelling.training_db import get_training_database_url
        from modelling.features.poi_distancing import poi_locations_populated

        training_db_url = get_training_database_url()
        poi_db_ok = poi_locations_populated(training_db_url)
    except Exception:  # noqa: BLE001
        pass

    engineered: dict[str, Any] = {}
    for fs_id in FEATURE_SET_IDS:
        if fs_id in ("poi_distancing", "mrt_pit__poi_distancing") and not merge_csv and not poi_db_ok:
            engineered[fs_id] = {
                "skipped": True,
                "reason": "missing data/pois/hdb_block_coords.csv and empty poi_locations (or DB unreachable)",
            }
            findings.append(
                {
                    "severity": "info",
                    "code": "poi_skipped",
                    "message": f"Feature set {fs_id} skipped in profile (no coords CSV and no POI DB)",
                }
            )
            continue
        try:
            if fs_id in ("baseline_v1", "mrt_pit"):
                eng = engineer_for_feature_set(raw_df, project_root, fs_id)
            elif fs_id in ("poi_distancing", "mrt_pit__poi_distancing") and poi_db_ok and training_db_url:
                eng = engineer_for_feature_set(
                    raw_df,
                    project_root,
                    fs_id,
                    use_db=True,
                    database_url=training_db_url,
                )
            elif fs_id in ("poi_distancing", "mrt_pit__poi_distancing") and merge_csv:
                eng = engineer_for_feature_set(
                    raw_df, project_root, fs_id, merge_coords_csv=merge_csv
                )
            else:
                eng = engineer_for_feature_set(raw_df, project_root, fs_id)
            engineered[fs_id] = profile_engineered_frame(eng, fs_id)
        except Exception as exc:  # noqa: BLE001
            engineered[fs_id] = {"error": str(exc)}
            findings.append(
                {
                    "severity": "warn",
                    "code": "engineer_failed",
                    "message": f"{fs_id}: {exc}",
                }
            )

    return {
        "mrt_pit_min_years": min_years,
        "loader": loader_desc,
        "sql": sql_stats,
        "engineered_profiles": engineered,
        "findings": findings,
    }


def merge_report_file(project_root: Path) -> Path:
    return project_root / "modelling" / "outputs" / "training_data_report.json"


def append_window_to_report(project_root: Path, window_payload: dict[str, Any]) -> None:
    """Merge ``window_payload`` (from ``run_window_quality``) under ``windows[y]``."""
    path = merge_report_file(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    years = int(window_payload["mrt_pit_min_years"])
    key = str(years)
    doc: dict[str, Any]
    if path.is_file():
        doc = json.loads(path.read_text(encoding="utf-8"))
    else:
        doc = {"generated_at": None, "windows": {}}
    doc["windows"][key] = window_payload
    doc["generated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def write_markdown_report(project_root: Path) -> Path:
    """Rewrite MD summary from JSON."""
    jpath = merge_report_file(project_root)
    out = project_root / "modelling" / "outputs" / "training_data_report.md"
    if not jpath.is_file():
        out.write_text("# Training data report\n\nNo JSON yet.\n", encoding="utf-8")
        return out
    doc = json.loads(jpath.read_text(encoding="utf-8"))
    lines = [
        "# Training data quality report",
        "",
        f"Generated (UTC): `{doc.get('generated_at', '')}`",
        "",
        "## Risks to training quality",
        "",
    ]
    for yk, w in sorted(doc.get("windows", {}).items(), key=lambda x: int(x[0])):
        lines.append(f"### Window {yk} years (`MRT_PIT_MIN_YEARS`)")
        lines.append("")
        for f in w.get("findings", []):
            sev = f.get("severity", "info")
            lines.append(f"- **[{sev}]** {f.get('message', '')}")
        lines.append("")
        agg = (w.get("sql") or {}).get("aggregates") or {}
        if agg:
            lines.append("| Aggregate | Value |")
            lines.append("| --- | ---:|")
            for k, v in sorted(agg.items()):
                lines.append(f"| `{k}` | {v} |")
            lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def sql_coverage_for_dq_summary(min_years: int) -> dict[str, Any]:
    """SQL join coverage + window findings for embedding under ``data_quality_summary`` / PDF Section 3."""
    try:
        stats = collect_sql_training_stats(min_years=min_years)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "mrt_pit_min_years": int(min_years)}
    findings = _findings_from_sql(stats)
    agg = stats.get("aggregates") or {}
    n = max(int(agg.get("n_transactions", 0)), 1)
    pct_row: dict[str, float] = {}
    for key in (
        "n_enriched",
        "n_coords",
        "n_snapshot_join",
        "n_mrt_core_nonnull",
        "n_bad_price",
        "n_duplicate_extra_rows",
    ):
        if key in agg:
            pct_row[f"{key}_pct_of_transactions"] = round(_pct(float(agg[key]), float(n)), 3)
    return {
        "mrt_pit_min_years": int(min_years),
        "window_summary": stats.get("window_summary"),
        "aggregates": agg,
        "aggregate_rates_pct": pct_row,
        "findings": findings,
    }


def data_quality_summary_for_metrics(project_root: Path, min_years: int) -> dict[str, Any]:
    """Lightweight pointer for ``metrics.json`` from existing report file."""
    jpath = merge_report_file(project_root)
    if not jpath.is_file():
        return {"report_path": str(jpath.relative_to(project_root)), "embedded": False}
    doc = json.loads(jpath.read_text(encoding="utf-8"))
    w = doc.get("windows", {}).get(str(min_years), {})
    crit = sum(1 for f in w.get("findings", []) if f.get("severity") == "critical")
    warn = sum(1 for f in w.get("findings", []) if f.get("severity") == "warn")
    return {
        "report_path": str(jpath.relative_to(project_root)),
        "mrt_pit_min_years": min_years,
        "critical_findings": crit,
        "warn_findings": warn,
        "embedded": True,
    }
