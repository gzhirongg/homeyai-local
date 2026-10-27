#!/usr/bin/env python3
"""One-off completeness report for the raw training frame (resale + OneMap + PIT MRT snapshot).

Uses the same join shape as ``modelling.training_db.get_hdb_resale_query()``. Does not run modelling
pipelines or train models.

Examples::

    PYTHONPATH=. python modelling/runners/report_training_completeness.py
    PYTHONPATH=. python modelling/runners/report_training_completeness.py \\
        --training-source parquet_minio
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from sqlalchemy import text  # noqa: E402


def _pct(part: float, whole: float) -> str:
    if whole <= 0:
        return "n/a"
    return f"{100.0 * part / whole:.2f}%"


def _report_from_db() -> str:
    from modelling.training_db import (
        create_training_engine,
        get_mrt_pit_min_years,
        get_training_window_summary,
    )

    my = get_mrt_pit_min_years()
    engine = create_training_engine()
    win_lines: list[str] = []
    try:
        summary = get_training_window_summary(engine, min_years=my)
        need = int(summary["expected_min_months"])
        got = int(summary["n_done_months_in_window"])
        ok = got >= need
        win_lines = [
            "## MRT PIT training window (complete job-months)",
            "",
            f"| Check | Value |",
            f"| --- | --- |",
            f"| `MRT_PIT_MIN_YEARS` | {summary['min_years']} |",
            f"| Window start month (`YYYY-MM`) | `{summary['window_start_month']}` |",
            f"| Distinct **done** job-months in window | {got} |",
            f"| Minimum required (`years*12 - 2`) | {need} |",
            f"| Eligible transactions (approx., join-ready) | {int(summary['n_eligible_tx']):,} |",
            f"| **Window OK** | **{'yes' if ok else 'NO — run batch snapshot for more months or lower MRT_PIT_MIN_YEARS'}** |",
            "",
        ]
    except Exception as exc:
        win_lines = [
            "## MRT PIT training window",
            "",
            f"*Could not read `mrt_pit_build_jobs` (apply Alembic `a1b2c3d4e5f6`?).* `{exc}`",
            "",
        ]

    sql = text(
        f"""
        SELECT
            (SELECT COUNT(*)::bigint FROM hdb_mrt_features_pit_snapshot) AS n_snapshot_rows,
            COUNT(*)::bigint AS n_transactions,
            COUNT(*) FILTER (WHERE t.enriched_addr_id IS NOT NULL)::bigint AS n_enriched_id,
            COUNT(*) FILTER (
                WHERE oe.latitude IS NOT NULL AND oe.longitude IS NOT NULL
            )::bigint AS n_onemap_coords,
            COUNT(*) FILTER (WHERE t.remaining_lease_years IS NOT NULL)::bigint AS n_remaining_lease_years,
            COUNT(*) FILTER (WHERE f.hdb_addr_id IS NOT NULL)::bigint AS n_snapshot_join,
            COUNT(*) FILTER (WHERE f.dist_to_nearest_op_mrt IS NOT NULL)::bigint AS n_dist_mrt,
            COUNT(*) FILTER (WHERE f.travel_time_to_active_mrt IS NOT NULL)::bigint AS n_tt_mrt,
            COUNT(*) FILTER (
                WHERE f.pt_time_savings_vs_walk IS NOT NULL
            )::bigint AS n_pt_savings,
            COUNT(*) FILTER (WHERE f.line_connectivity_index IS NOT NULL)::bigint AS n_line_conn,
            COUNT(*) FILTER (
                WHERE f.days_since_mrt_announcement IS NOT NULL
            )::bigint AS n_days_since_ann,
            COUNT(*) FILTER (WHERE f.days_to_mrt_opening IS NOT NULL)::bigint AS n_days_to_open,
            COUNT(*) FILTER (
                WHERE f.speculative_upside_score IS NOT NULL
            )::bigint AS n_spec_score,
            COUNT(*) FILTER (
                WHERE f.has_future_upside IS NOT NULL
            )::bigint AS n_has_future_upside_cell,
            COUNT(*) FILTER (WHERE f.is_proximity_nuisance IS NOT NULL)::bigint AS n_nuisance_cell,
            COUNT(*) FILTER (
                WHERE f.nearest_op_lines IS NOT NULL
                  AND cardinality(f.nearest_op_lines) > 0
            )::bigint AS n_op_lines_nonempty,
            COUNT(*) FILTER (
                WHERE f.nearest_planned_lines IS NOT NULL
                  AND cardinality(f.nearest_planned_lines) > 0
            )::bigint AS n_planned_lines_nonempty
        FROM hdb_resale_transactions t
        INNER JOIN mrt_pit_build_jobs jobs
          ON jobs.tx_year_month = t.month AND jobs.status = 'done'
        LEFT JOIN hdb_address_enrichment_onemap oe ON oe.id = t.enriched_addr_id
        LEFT JOIN hdb_mrt_features_pit_snapshot f
          ON f.hdb_addr_id = t.enriched_addr_id
         AND f.tx_year_month = t.month
        WHERE t.month >= to_char(CURRENT_DATE - ({my} * INTERVAL '1 year'), 'YYYY-MM')
        """
    )
    try:
        row = dict(engine.connect().execute(sql).mappings().one())
    finally:
        engine.dispose()

    n = float(row["n_transactions"])
    lines = [
        "# Training dataset completeness (PIT MRT snapshot join)",
        "",
        f"Generated (UTC): `{datetime.now(timezone.utc).isoformat()}`",
        f"Source: **PostgreSQL** (read-only training URL), same join shape as "
        f"`get_hdb_resale_query()` (done job-months + rolling window).",
        "",
        *win_lines,
        "## Row counts (within rolling window)",
        "",
        "| Metric | Count | % of window transactions |",
        "| --- | ---:| --- |",
        f"| Rows in `hdb_mrt_features_pit_snapshot` (full table) | {int(row['n_snapshot_rows'])} | — |",
        f"| Transactions (eligible window) | {int(row['n_transactions'])} | 100.00% |",
        f"| `enriched_addr_id` present | {int(row['n_enriched_id'])} | {_pct(row['n_enriched_id'], n)} |",
        f"| OneMap lat/lon present | {int(row['n_onemap_coords'])} | {_pct(row['n_onemap_coords'], n)} |",
        f"| `remaining_lease_years` non-null | {int(row['n_remaining_lease_years'])} | {_pct(row['n_remaining_lease_years'], n)} |",
        f"| PIT snapshot row matched (`f` join hit) | {int(row['n_snapshot_join'])} | {_pct(row['n_snapshot_join'], n)} |",
        "",
        "## PIT MRT scalars (non-null among window transactions)",
        "",
        "| Column | Non-null count | % of window transactions |",
        "| --- | ---:| --- |",
        f"| `dist_to_nearest_op_mrt` | {int(row['n_dist_mrt'])} | {_pct(row['n_dist_mrt'], n)} |",
        f"| `travel_time_to_active_mrt` | {int(row['n_tt_mrt'])} | {_pct(row['n_tt_mrt'], n)} |",
        f"| `pt_time_savings_vs_walk` | {int(row['n_pt_savings'])} | {_pct(row['n_pt_savings'], n)} |",
        f"| `line_connectivity_index` | {int(row['n_line_conn'])} | {_pct(row['n_line_conn'], n)} |",
        f"| `days_since_mrt_announcement` | {int(row['n_days_since_ann'])} | {_pct(row['n_days_since_ann'], n)} |",
        f"| `days_to_mrt_opening` | {int(row['n_days_to_open'])} | {_pct(row['n_days_to_open'], n)} |",
        f"| `speculative_upside_score` | {int(row['n_spec_score'])} | {_pct(row['n_spec_score'], n)} |",
        f"| `has_future_upside` (cell present) | {int(row['n_has_future_upside_cell'])} | {_pct(row['n_has_future_upside_cell'], n)} |",
        f"| `is_proximity_nuisance` (cell present) | {int(row['n_nuisance_cell'])} | {_pct(row['n_nuisance_cell'], n)} |",
        "",
        "## Line arrays",
        "",
        "| Metric | Count | % of window transactions |",
        "| --- | ---:| --- |",
        f"| `nearest_op_lines` non-empty | {int(row['n_op_lines_nonempty'])} | {_pct(row['n_op_lines_nonempty'], n)} |",
        f"| `nearest_planned_lines` non-empty | {int(row['n_planned_lines_nonempty'])} | {_pct(row['n_planned_lines_nonempty'], n)} |",
        "",
        "## Interpretation",
        "",
        "- **`Rows in hdb_mrt_features_pit_snapshot` = 0** means the table was never populated. "
        "Run `backend/scripts/build_mrt_pit_snapshot.py` (batch workers; see mrt-enrichment-pipeline.md). "
        "Read-only roles cannot INSERT the snapshot.",
        "- Training loads only **done** `mrt_pit_build_jobs` months inside **`MRT_PIT_MIN_YEARS`** (default 5).",
        "- If **PIT snapshot row matched** < 100% within the window but jobs are **done**, investigate join keys.",
        "",
    ]
    return "\n".join(lines)


def _report_from_frame(df, source_desc: str) -> str:
    import numpy as np
    import pandas as pd

    n = len(df)
    def rate(series: pd.Series) -> tuple[int, str]:
        if series.dtype == object or getattr(series.dtype, "name", "") == "string":
            valid = series.notna() & (series.astype(str).str.strip() != "") & (series.astype(str) != "nan")
        else:
            valid = series.notna()
        c = int(valid.sum())
        return c, _pct(c, float(n))

    lines = [
        "# Training dataset completeness (PIT MRT snapshot join)",
        "",
        f"Generated (UTC): `{datetime.now(timezone.utc).isoformat()}`",
        f"Source: **{source_desc}**",
        "",
        f"**Rows loaded:** {n}",
        "",
        "## Keys and base columns",
        "",
        "| Column | Non-null | % |",
        "| --- | ---:| --- |",
    ]
    for col in ("enriched_addr_id", "month", "resale_price", "remaining_lease_years"):
        if col in df.columns:
            c, p = rate(df[col])
            lines.append(f"| `{col}` | {c} | {p} |")
    if "lat" in df.columns and "lon" in df.columns:
        both = df["lat"].notna() & df["lon"].notna()
        c = int(both.sum())
        lines.append(f"| OneMap lat/lon both | {c} | {_pct(c, float(n))} |")
    lines.extend(["", "## PIT MRT columns", "", "| Column | Non-null | % |", "| --- | ---:| --- |"])
    mrt_cols = [
        "dist_to_nearest_op_mrt",
        "travel_time_to_active_mrt",
        "pt_time_savings_vs_walk",
        "line_connectivity_index",
        "num_unique_lines_within_1km",
        "nearest_planned_mrt_dist",
        "nearest_op_lines",
        "nearest_planned_lines",
        "days_since_mrt_announcement",
        "days_to_mrt_opening",
        "speculative_upside_score",
        "has_future_upside",
        "is_proximity_nuisance",
    ]
    for col in mrt_cols:
        if col not in df.columns:
            lines.append(f"| `{col}` | — | *missing in frame* |")
            continue
        if col in ("nearest_op_lines", "nearest_planned_lines"):
            def nonempty(cell: object) -> bool:
                if cell is None:
                    return False
                if isinstance(cell, float) and np.isnan(cell):
                    return False
                if hasattr(cell, "__len__") and not isinstance(cell, str):
                    return len(cell) > 0
                s = str(cell).strip()
                return bool(s) and s not in ("{}", "[]")

            c = int(df[col].map(nonempty).sum())
            lines.append(f"| `{col}` (non-empty) | {c} | {_pct(c, float(n))} |")
        else:
            c, p = rate(df[col])
            lines.append(f"| `{col}` | {c} | {p} |")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--training-source",
        choices=("postgresql", "parquet_minio"),
        default="postgresql",
        help="postgresql: DB aggregates report; parquet_minio: manifest-backed MinIO resale parquet (+ sidecars).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write Markdown here (default: modelling/outputs/training_completeness_<UTC>.md)",
    )
    parser.add_argument("--project-root", type=Path, default=_REPO)
    parser.add_argument(
        "--append-data-quality-report",
        action="store_true",
        help="Merge modelling/outputs/training_data_report.json + .md (SQL + engineered-frame profiles for current window).",
    )
    args = parser.parse_args(argv)

    root = args.project_root.resolve()
    if args.training_source == "postgresql":
        body = _report_from_db()
    else:
        from modelling.data.loaders import LoaderConfig, describe_training_source, load_training_frame

        loader = LoaderConfig(
            project_root=root,
            parquet_minio=True,
            use_database=False,
        )
        df = load_training_frame(loader)
        _, uri = describe_training_source(loader)
        body = _report_from_frame(df, f"parquet_minio ({uri}) via manifest merges")

    if args.append_data_quality_report:
        from modelling.data.loaders import LoaderConfig, describe_training_source, load_training_frame
        from modelling.runners.training_data_quality import (
            append_window_to_report,
            run_window_quality,
            write_markdown_report,
        )
        from modelling.training_db import get_mrt_pit_min_years

        my = get_mrt_pit_min_years()
        pm = args.training_source == "parquet_minio"
        lq = LoaderConfig(project_root=root, parquet_minio=pm, use_database=not pm)
        raw_q = load_training_frame(lq)
        _, uri = describe_training_source(lq)
        desc = f"training_source={args.training_source} uri={uri}"
        wq = run_window_quality(root, min_years=my, raw_df=raw_q, loader_desc=desc)
        append_window_to_report(root, wq)
        mdq = write_markdown_report(root)
        print(
            f"Appended training_data_report window {my} → modelling/outputs/training_data_report.json and {mdq}",
            file=sys.stderr,
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = args.out or root / "modelling" / "outputs" / f"training_completeness__{stamp}.md"
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    print(body)
    print(f"\nWrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
