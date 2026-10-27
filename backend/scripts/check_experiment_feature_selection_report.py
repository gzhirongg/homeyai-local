#!/usr/bin/env python3
"""Triage feature-selection artefacts for an experiment run in MinIO (metrics audit + plots JSON/PNG presence).

Examples (backend repo root via docker or local venv where MinIO env vars resolve)::

    cd backend && python scripts/check_experiment_feature_selection_report.py <run_id>
    python scripts/check_experiment_feature_selection_report.py abc123 --env dev

Suggested log grep (training worker):

    rg 'prefit_feature_selection_skipped|prefit_feature_selection_done|feature_selection plot PNGs skipped|<run_id>'
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", help="Experiment folder id under valuation/experiments/")
    parser.add_argument(
        "--env",
        default=None,
        help="MinIO env segment prefix (default: $MODEL_ENV or prod)",
    )
    args = parser.parse_args()
    rid = args.run_id.strip().strip("/")
    env_seg = (args.env or os.getenv("MODEL_ENV", "prod")).strip().strip("/")

    from services import model_store

    base = f"{env_seg}/valuation/experiments/{rid}"
    met_key = f"{base}/metrics.json"
    prefix = base + "/"

    print(f"Run: {rid!r}")
    print(f"Env: {env_seg!r}")
    print(f"Prefix: models/{prefix}\n")

    if not model_store.object_exists(met_key):
        print("FAIL: metrics.json missing.")
        print("Suggestion: Confirm run_id / MODEL_ENV match the MinIO bucket layout.")
        return 1

    raw = model_store.get_object_bytes(met_key)
    try:
        m = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        print(f"FAIL: metrics.json is not JSON: {exc}")
        return 1

    if not isinstance(m, dict):
        print("FAIL: metrics.json decoded to something other than object.")
        return 1

    audit = m.get("training_matrix_audit")
    if not isinstance(audit, dict):
        print("SKIP: training_matrix_audit missing or wrong type.")
        print("Impact: audit page (including plot subsection heading) omitted from PDF report.")
        return 2

    rsi = audit.get("raw_split_input")
    if not rsi:
        print("SKIP: training_matrix_audit.raw_split_input absent or empty.")
        print("Impact: audit page omitted; feature-selection subsection never rendered.")
        return 2

    print("OK: training_matrix_audit.raw_split_input present.")

    objs = model_store.list_objects_with_prefix(prefix)
    names = {row["object_name"] for row in objs}

    for label, suffix in (
        ("Variance JSON", "feature_variance.json"),
        ("MI JSON", "feature_mi_scores.json"),
        ("Correlation JSON", "correlated_pairs.json"),
        ("Plots / variance PNG", "plots/feature_selection_variance.png"),
        ("Plots / MI PNG", "plots/feature_selection_mi.png"),
        ("Plots / correlation PNG", "plots/feature_selection_correlation.png"),
    ):
        fp = f"{base}/{suffix}"
        ok = fp in names or any(o.endswith(suffix) and rid in o for o in names)
        print(f"[{'YES' if ok else 'NO '}] {label}: {suffix}")

    print("\nRegenerate PDF (fresh embed of plots):")
    print(
        '  POST /api/admin/ml/experiment-report  body={"run_id":"<id>","env":"'
        + env_seg
        + '","use_existing_pdf":false}'
    )
    print("Log cues: prefit_feature_selection_skipped | prefit_feature_selection_done | feature_selection plot PNGs skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
