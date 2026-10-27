"""Pure helpers for comparing advisory vs apply feature-selection experiment runs (MinIO metrics.json)."""

from __future__ import annotations

import re
from typing import Any

_RUN_TS_RE = re.compile(r"^(.+)__(\d{8}T\d{6}Z)$")


def split_run_folder(run_folder: str) -> tuple[str, str | None]:
    """Split ``<experiment_id>__<YYYYMMDDTHHMMSSZ>`` → logical experiment id + UTC stamp."""
    m = _RUN_TS_RE.match(run_folder.strip())
    if not m:
        return run_folder.strip(), None
    return m.group(1), m.group(2)


def metrics_row_for_compare(metrics: dict[str, Any], *, run_folder: str) -> dict[str, Any]:
    """Flatten ``metrics.json`` for CSV / pairing."""
    logical_id, stamp = split_run_folder(run_folder)
    audit = metrics.get("training_matrix_audit") if isinstance(metrics.get("training_matrix_audit"), dict) else {}
    fs_audit = audit.get("feature_selection") if isinstance(audit.get("feature_selection"), dict) else {}
    pol = str(audit.get("feature_selection_policy") or "advisory_only")
    tm = metrics.get("test_metrics") if isinstance(metrics.get("test_metrics"), dict) else {}
    tc = metrics.get("training_context") if isinstance(metrics.get("training_context"), dict) else {}
    removed = fs_audit.get("columns_removed") or []
    if not isinstance(removed, list):
        removed = []
    test_rmse = tm.get("rmse")
    cv_rmse = metrics.get("best_cv_rmse")
    return {
        "run_folder": run_folder,
        "logical_experiment_id": logical_id,
        "run_timestamp": stamp or "",
        "feature_selection_policy": pol,
        "dataset_version": str(tc.get("dataset_version") or ""),
        "test_rmse": float(test_rmse) if test_rmse is not None else None,
        "cv_rmse": float(cv_rmse) if cv_rmse is not None else None,
        "n_removed": len(removed),
        "applied_to_pipeline": fs_audit.get("applied_to_pipeline"),
        "recommended_drop_count": fs_audit.get("recommended_drop_count"),
        "columns_removed_preview": ";".join(map(str, removed[:12])) + ("..." if len(removed) > 12 else ""),
    }


def pair_latest_advisory_vs_apply(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per ``logical_experiment_id``, pair latest advisory_only vs latest apply_recommended_drops by run_timestamp."""
    by_exp: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for r in rows:
        eid = str(r.get("logical_experiment_id") or "")
        pol = str(r.get("feature_selection_policy") or "")
        if pol == "apply_recommended_drops":
            bucket = "apply"
        elif pol in ("advisory_only", ""):
            bucket = "advisory"
        else:
            bucket = pol
        by_exp.setdefault(eid, {}).setdefault(bucket, []).append(r)

    out: list[dict[str, Any]] = []
    for eid, pol_map in sorted(by_exp.items()):
        adv_list = sorted(
            pol_map.get("advisory", []),
            key=lambda x: str(x.get("run_timestamp") or ""),
            reverse=True,
        )
        app_list = sorted(
            pol_map.get("apply", []),
            key=lambda x: str(x.get("run_timestamp") or ""),
            reverse=True,
        )
        adv = adv_list[0] if adv_list else None
        app = app_list[0] if app_list else None
        if adv is None or app is None:
            continue
        tr_a = adv.get("test_rmse")
        tr_b = app.get("test_rmse")
        delta = None
        if isinstance(tr_a, (int, float)) and isinstance(tr_b, (int, float)):
            delta = float(tr_b) - float(tr_a)
        out.append(
            {
                "logical_experiment_id": eid,
                "advisory_run": adv.get("run_folder"),
                "advisory_run_timestamp": adv.get("run_timestamp"),
                "apply_run": app.get("run_folder"),
                "apply_run_timestamp": app.get("run_timestamp"),
                "dataset_version_advisory": adv.get("dataset_version"),
                "dataset_version_apply": app.get("dataset_version"),
                "test_rmse_advisory": tr_a,
                "test_rmse_apply": tr_b,
                "test_rmse_delta_apply_minus_advisory": delta,
                "n_removed_apply": app.get("n_removed"),
                "applied_apply": app.get("applied_to_pipeline"),
            }
        )
    return out
