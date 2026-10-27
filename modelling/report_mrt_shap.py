#!/usr/bin/env python3
"""
Forest-level SHAP summary for the RandomForest baseline wrapped in modelling.py pipelines.

    pip install shap matplotlib
    PYTHONPATH=. python modelling/report_mrt_shap.py

Subsampling keeps runtime sane. Writes artefacts under modelling/outputs/mrt_pit_features/.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd


def main() -> int:
    try:
        import matplotlib.pyplot as plt
        import shap
    except ImportError as exc:
        print("Missing optional deps (pip install shap matplotlib numpy):", exc)
        return 2

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from modelling.modelling import (  # noqa: E402
        TARGET_COLUMN,
        build_model_specs,
        build_pipeline,
        engineer_features,
    )
    import modelling.modelling as mp  # noqa: E402

    out_dir = repo_root / "modelling" / "outputs" / "mrt_pit_features"
    out_dir.mkdir(parents=True, exist_ok=True)

    config = mp.RunConfig(max_train_rows=25_000, test_fraction=0.2, rf_search_iter=4, nn_search_iter=2)

    raw = mp.load_training_frame(config)

    merged = pd.to_datetime(raw["month"], format="%Y-%m", errors="coerce")
    ordered = raw.assign(_month_date=merged).sort_values("_month_date")
    subset = ordered.iloc[-35_000:].drop(columns=["_month_date"]).copy()

    y = subset[TARGET_COLUMN].astype(float)
    X = subset.drop(columns=[TARGET_COLUMN])

    specs = build_model_specs(config.random_state)
    rf_spec = next(s for s in specs if s.name == "Random Forest")
    pipe = build_pipeline(rf_spec)
    pipe.fit(X, y)

    pre = pipe.named_steps["preprocessor"]
    ttr = pipe.named_steps["model"]
    forest: object = ttr.regressor_

    X_eng = engineer_features(X)
    Xt = pd.DataFrame(
        pre.transform(X_eng),
        columns=pre.get_feature_names_out(),
        index=X_eng.index,
    )

    n_s = min(2000, len(Xt))
    sample_idx = Xt.sample(n=n_s, random_state=config.random_state).index
    Xt_s = Xt.loc[sample_idx]

    explainer = shap.TreeExplainer(forest)
    sv = explainer.shap_values(Xt_s.values)

    plt.figure(figsize=(11, 6))
    shap.summary_plot(sv, Xt_s, plot_type="bar", show=False, max_display=min(35, Xt_s.shape[1]))
    plt.title("RF baseline — mean |SHAP| ( sklearn pipeline preprocessing )")
    plt.tight_layout()
    png_path = out_dir / "rf_shap_bar.png"
    plt.savefig(png_path, dpi=150)
    plt.close()

    feat_names = list(Xt.columns)
    pit_names = [
        n
        for n in feat_names
        if any(
            frag in str(n).lower()
            for frag in (
                "dist",
                "travel",
                "pt_",
                "days",
                "speculative",
                "future",
                "proximity",
                "connectivity",
                "line",
                "op_line",
                "planned_line",
            )
        )
    ]

    (out_dir / "metrics.json").write_text(
        json.dumps(
            {
                "rows_train": len(X),
                "shap_samples": int(n_s),
                "processed_feature_dim": Xt.shape[1],
                "approx_pit_related_feature_columns": pit_names[:200],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {png_path} and {out_dir / 'metrics.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
