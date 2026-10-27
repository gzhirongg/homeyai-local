#!/usr/bin/env python3
"""Fit and publish a local baseline with separate train/calibration/test months.

Reuses the cached public CSVs and existing modelling pipeline. No network download
or production database is used. Keeps the preceding model available for rollback.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "backend"), str(Path(__file__).resolve().parent)]


def main():
    from bootstrap_local_valuation import ADDRESS_URL, require_local_database
    require_local_database()
    import joblib
    import numpy as np
    import pandas as pd
    from address_normalize import normalize_street
    from modelling.config.feature_sets import get_feature_set
    from modelling.config.model_specs import get_model_spec
    from modelling.models.pipelines import build_full_pipeline
    from modelling.evaluation.metrics import evaluate_regression_model
    from modelling.evaluation.prediction_intervals import calibrate_relative_interval
    from modelling.targets.rpi_normalization import align_rpi_index_to_months, adjust_prices_to_baseline100, validate_rpi_alignment
    from models import SessionLocal, ModelVersion
    from services import model_store

    raw = pd.read_csv(ROOT / "data/HDBResale2017Onwards.csv", dtype={"block": str})
    raw["block_street"] = raw["block"].str.strip().str.upper() + " " + raw["street_name"].map(normalize_street)
    addresses = pd.read_parquet(ROOT / "data/local_validated_addresses.parquet")
    raw = raw.merge(addresses[["block_street", "lat", "lon"]], on="block_street", validate="many_to_one")
    latest = pd.Period(raw.month.max(), freq="M")
    raw = raw[(raw.month >= str(latest - 59)) & (raw.resale_price > 0) & (raw.floor_area_sqm > 0)].sort_values("month").reset_index(drop=True)
    cal_start, test_start = str(latest - 5), str(latest - 2)
    train = (raw.month < cal_start).to_numpy()
    calibration = ((raw.month >= cal_start) & (raw.month < test_start)).to_numpy()
    test = (raw.month >= test_start).to_numpy()
    if train.sum() < 10000 or calibration.sum() < 1000 or test.sum() < 1000:
        raise ValueError("Insufficient rows for independent train/calibration/test periods")
    rpi = pd.read_csv(ROOT / "data/HDBResalePriceIndex.csv")
    indexes = align_rpi_index_to_months(raw.month, rpi)
    validate_rpi_alignment(indexes, context="local interval calibration")
    target = adjust_prices_to_baseline100(raw.resale_price, indexes)
    spec = get_model_spec(ROOT, "lightgbm")
    spec.estimator.set_params(n_estimators=400, learning_rate=0.05, num_leaves=63,
                              min_child_samples=30, reg_lambda=5.0, n_jobs=2)
    pipeline = build_full_pipeline(get_feature_set(ROOT, "baseline_v1"), spec, ROOT)
    print(f"Fit {train.sum():,}; calibrate {calibration.sum():,}; test {test.sum():,}", flush=True)
    pipeline.fit(raw.loc[train], target[train])
    pred_cal = pipeline.predict(raw.loc[calibration]) * indexes[calibration] / 100
    interval = calibrate_relative_interval(raw.loc[calibration, "resale_price"], pred_cal)
    predictions = pipeline.predict(raw.loc[test]) * indexes[test] / 100
    truth = raw.loc[test, "resale_price"].to_numpy()
    scores = evaluate_regression_model(truth, predictions)
    q = interval["relative_error_quantile"]
    test_coverage = float(np.mean((truth >= predictions * max(0, 1-q)) & (truth <= predictions * (1+q))))
    interval.update(calibration_start=cal_start, calibration_end=str(latest-3), test_start=test_start,
                    test_end=str(latest), test_count=int(test.sum()), test_coverage=test_coverage,
                    note="Chronological held-out calibration; market shifts can change future coverage.")
    if scores["mape"] > 0.2 or scores["r2"] < 0.8 or not 0.80 <= test_coverage <= 1 or not 0 < q < 1:
        raise ValueError(f"Local validation failed: {scores}, coverage={test_coverage}")
    run = "local_lightgbm_calibrated__" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "modelling/outputs/local_bootstrap" / run
    out.mkdir(parents=True)
    joblib.dump(pipeline, out / "model.pkl", compress=3)
    manifest = {"feature_set_id": "baseline_v1", "model_id": "lightgbm", "experiment_id": run,
        "target_normalization": "rpi_baseline_100", "local_development_model": True,
        "data_start": raw.loc[train, "month"].min(), "data_end": raw.loc[train, "month"].max(),
        "address_source": ADDRESS_URL, "prediction_interval": interval}
    metrics = {"feature_set": "baseline_v1", "model": "lightgbm", "experiment_id": run,
        "test_metrics": scores, "n_train": int(train.sum()), "n_calibration": int(calibration.sum()),
        "n_test": int(test.sum()), "target_normalization": "rpi_baseline_100",
        "prediction_interval": interval, "validation": "chronological train/calibration/test; no refit on held-out rows"}
    for filename, value in (("manifest.json", manifest), ("metrics.json", metrics),
        ("config.json", {"feature_set_id": "baseline_v1", "model_id": "lightgbm", "random_state": 42})):
        (out / filename).write_text(json.dumps(value, indent=2) + "\n")
    prefix = f"dev/valuation/experiments/{run}"
    for filename in ("model.pkl", "manifest.json", "metrics.json", "config.json"):
        model_store.put_file_if_absent(f"{prefix}/{filename}", out / filename)
    key = f"{prefix}/model.pkl"
    with SessionLocal() as db:
        db.query(ModelVersion).filter_by(env="dev").update({"is_production": False})
        db.add(ModelVersion(env="dev", object_key=key, experiment_id=run, feature_set_id="baseline_v1",
            model_id="lightgbm", rmse=scores["rmse"], is_production=True, promoted_at=datetime.now(timezone.utc)))
        db.commit()
    (ROOT / "data/local_calibration_report.json").write_text(json.dumps({"model_object_key": key, **metrics}, indent=2)+"\n")
    print(json.dumps({"model_object_key": key, "test_metrics": scores, "interval": interval}, indent=2), flush=True)


if __name__ == "__main__":
    main()
