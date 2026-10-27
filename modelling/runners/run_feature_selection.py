#!/usr/bin/env python3
"""CLI: run variance / correlation / MI diagnostics on engineered training rows."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from modelling.config.experiments import get_experiment  # noqa: E402
from modelling.config.feature_sets import get_feature_set  # noqa: E402
from modelling.data.loaders import LoaderConfig, load_training_frame  # noqa: E402
from modelling.data.splits import make_temporal_split, restrict_training_window  # noqa: E402
from modelling.evaluation.metrics import TARGET_COLUMN  # noqa: E402
from modelling.feature_selection import diagnostic_row_mask, write_feature_selection_artifacts  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=_REPO)
    parser.add_argument("--name", type=str, required=True, help="Experiment registry id")
    parser.add_argument("--from-parquet-minio", action="store_true")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--var-threshold", type=float, default=1e-6)
    parser.add_argument("--r-threshold", type=float, default=0.85)
    parser.add_argument("--mi-floor-ratio", type=float, default=0.02)
    parser.add_argument(
        "--apply-drops",
        action="store_true",
        help="Also write features_dropped.json (recommended numeric drops vs registry).",
    )
    args = parser.parse_args(argv)

    root = args.project_root.resolve()
    exp = get_experiment(root, args.name)
    fs = get_feature_set(root, exp.feature_set_id)

    loader = LoaderConfig(project_root=root, parquet_minio=args.from_parquet_minio, use_database=not args.from_parquet_minio)
    raw = load_training_frame(loader)

    X_train, _, y_train, _ = make_temporal_split(raw, TARGET_COLUMN, test_fraction=exp.test_fraction)
    X_train, y_train = restrict_training_window(X_train, y_train, exp.max_train_rows)

    ek = {**fs.engineer_kwargs, **exp.extra_engineer_kwargs, "project_root": root}
    engineered = fs.engineer(X_train.copy(), **ek)

    row_mask = diagnostic_row_mask(X_train, y_train, feature_set_id=exp.feature_set_id)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = args.out_dir or (root / "modelling" / "outputs" / "feature_selection" / f"{args.name}__{stamp}")
    extra = (
        {"feature_set_id": exp.feature_set_id, "n_train_rows": int(len(X_train))}
        if args.apply_drops
        else None
    )
    write_feature_selection_artifacts(
        out,
        engineered,
        y_train,
        row_mask=row_mask,
        var_threshold=args.var_threshold,
        r_threshold=args.r_threshold,
        mi_floor_ratio=args.mi_floor_ratio,
        random_state=exp.random_state,
        registered_numeric=list(fs.numeric_features) if args.apply_drops else None,
        write_features_dropped_json=args.apply_drops,
        features_dropped_extra=extra,
    )
    print(f"Wrote feature selection artefacts to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
