#!/usr/bin/env python3
"""Rebuild ``report.pdf`` in MinIO for every run under ``{MODEL_ENV}/valuation/experiments/*/``.

Run inside the backend container (same env as the API), e.g.::

    ./scripts/docker_dev_backend.sh python /app/scripts/rebuild_all_experiment_reports.py

Uses :func:`services.experiment_report_build.ensure_experiment_report_presigned_url` (full PDF regen).
"""

from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env",
        default=None,
        help="MinIO env prefix (default: $MODEL_ENV)",
    )
    args = parser.parse_args()
    env = (args.env or os.getenv("MODEL_ENV", "prod")).strip()

    from services import model_store
    from services.experiment_report_build import ExperimentReportBuildError, ensure_experiment_report_presigned_url

    keys = model_store.list_valuation_experiment_model_keys(env)
    if not keys:
        print(f"No experiment model.pkl keys for env={env!r}", file=sys.stderr)
        return 1

    ok = 0
    failed = 0
    for mk in keys:
        rid = model_store.experiment_folder_from_model_object_key(mk)
        if not rid:
            continue
        try:
            _url, built = ensure_experiment_report_presigned_url(rid, env, use_existing_pdf=False)
            print(f"{rid}: ok (just_built={built})")
            ok += 1
        except ExperimentReportBuildError as exc:
            print(f"{rid}: fail — {exc}", file=sys.stderr)
            failed += 1
        except Exception as exc:  # noqa: BLE001 — batch tool; continue other runs
            print(f"{rid}: error — {exc}", file=sys.stderr)
            failed += 1

    print(f"Done env={env}: succeeded={ok} failed={failed} model_keys={len(keys)}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
