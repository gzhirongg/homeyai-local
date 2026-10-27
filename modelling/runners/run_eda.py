#!/usr/bin/env python3
"""Write EDA artefacts under modelling/outputs/eda/<tag>__<ts>/."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from modelling.data.loaders import LoaderConfig, load_training_frame  # noqa: E402
from modelling.data.splits import make_temporal_split  # noqa: E402
from modelling.eda.price_trends import plot_quarterly_price_trend, plot_regional_quarterly_trend  # noqa: E402
from modelling.eda.profile import (  # noqa: E402
    build_column_profile,
    plot_missingness,
    plot_target_distribution,
    profile_to_csv,
)
from modelling.eda.psi import psi_summary_table  # noqa: E402
from modelling.evaluation.metrics import TARGET_COLUMN  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=_REPO)
    parser.add_argument(
        "--from-parquet-minio",
        action="store_true",
        help="Load frames from HOMEYAI_MINIO_SOURCES_JSON parquet layout; default: Postgres.",
    )
    parser.add_argument("--tag", type=str, default="hdb_resale")
    args = parser.parse_args(argv)

    root = args.project_root.resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = root / "modelling" / "outputs" / "eda" / f"{args.tag}__{stamp}"
    out.mkdir(parents=True, exist_ok=False)

    pm = bool(args.from_parquet_minio)
    loader = LoaderConfig(project_root=root, parquet_minio=pm, use_database=not pm)
    df = load_training_frame(loader)
    profile = build_column_profile(df)
    profile_to_csv(profile, out / "column_profile.csv")

    plot_missingness(df, save_path=out / "missingness.png")
    plot_target_distribution(df, save_path=out / "target_distribution.png")

    plot_quarterly_price_trend(df, save_path=out / "quarterly_price_trend.png")
    plot_regional_quarterly_trend(df, save_path=out / "quarterly_price_by_region.png")

    X_train, X_test, _, _ = make_temporal_split(df, TARGET_COLUMN, test_fraction=0.2)
    psi_feats = [
        c for c in ("town", "flat_type", TARGET_COLUMN, "floor_area_sqm", "flat_model") if c in df.columns
    ]
    psi = psi_summary_table(X_train, X_test, psi_feats)
    psi.to_csv(out / "psi_summary.csv", index=False)

    _ = plt  # silence lint — pyplot imported for side effects in profile/trends
    print(f"Wrote EDA pack to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
