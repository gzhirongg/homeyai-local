"""Materialize PDF training reports in MinIO from existing experiment artefacts."""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ExperimentReportBuildError(Exception):
    """Raise when artefacts required to synthesize ``report.pdf`` are missing."""

    def __init__(self, message: str, *, missing: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.missing_components = list(missing or [])


def ensure_experiment_report_presigned_url(
    run_id: str,
    env_segment: str,
    *,
    presign_ttl: int = 900,
    use_existing_pdf: bool = False,
) -> tuple[str, bool]:
    """Return ``(presigned_get_url, was_just_built)``.

    By default **always regenerates** ``report.pdf`` from MinIO artefacts so styling/content updates
    (e.g. WeasyPrint vs legacy matplotlib) are not blocked by an older cached object.

    Set ``use_existing_pdf=True`` only when a cheap presign of the current blob is desired without rebuild.

    Downloads ``metrics.json`` (required), optional plots, ``config.json``, and ``best_params.json``,
    renders PDF via :mod:`services.training_report_html`, uploads (overwrites), then presigns.
    """

    from services import model_store

    rid = run_id.strip().strip("/")
    env_seg = env_segment.strip().strip("/")

    if use_existing_pdf:
        existing = model_store.presigned_experiment_report_pdf_url(env_seg, rid, ttl_seconds=presign_ttl)
        if existing:
            return existing, False

    base = f"{env_seg}/valuation/experiments/{rid}"
    met_key = f"{base}/metrics.json"

    if not model_store.object_exists(met_key):
        raise ExperimentReportBuildError(
            "Cannot build training report without metrics.json.",
            missing=["metrics.json"],
        )

    raw = model_store.get_object_bytes(met_key)
    try:
        metrics_payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ExperimentReportBuildError(
            "metrics.json is present but could not be parsed as JSON.", missing=["metrics.json (invalid)"]
        ) from exc
    if not isinstance(metrics_payload, dict):
        raise ExperimentReportBuildError(
            "metrics.json must decode to a JSON object.", missing=["metrics.json (unexpected shape)"]
        )

    dq_raw = metrics_payload.get("data_quality_summary")
    dq_summary: dict[str, Any] = dq_raw if isinstance(dq_raw, dict) else {}

    try:
        from services.training_report_html import render_training_report_pdf_bytes

        with tempfile.TemporaryDirectory(prefix=f"hm_exprep_{rid[:32]}_") as td:
            td_path = Path(td)
            plots = td_path / "plots"
            plots.mkdir(parents=False, exist_ok=True)
            for name in (
                "preds_vs_actual.png",
                "residuals.png",
                "missingness.png",
                "feature_importance.png",
                "shap_importance.png",
                "feature_selection_variance.png",
                "feature_selection_mi.png",
                "feature_selection_correlation.png",
            ):
                pk = f"{base}/plots/{name}"
                if model_store.object_exists(pk):
                    (plots / name).write_bytes(model_store.get_object_bytes(pk))
            for sel_name in (
                "feature_variance.json",
                "correlated_pairs.json",
                "feature_mi_scores.json",
                "feature_permutation_importance.json",
                "features_dropped.json",
            ):
                sk = f"{base}/{sel_name}"
                if model_store.object_exists(sk):
                    (td_path / sel_name).write_bytes(model_store.get_object_bytes(sk))
            bpk = f"{base}/best_params.json"
            if model_store.object_exists(bpk):
                (td_path / "best_params.json").write_bytes(model_store.get_object_bytes(bpk))
            cfg_key = f"{base}/config.json"
            if model_store.object_exists(cfg_key):
                (td_path / "config.json").write_bytes(model_store.get_object_bytes(cfg_key))

            from services.feature_selection_plot_synthesize import synthesize_missing_feature_selection_plots

            synthesize_missing_feature_selection_plots(experiment_root=td_path, plots_dir=plots)

            pdf_bytes = render_training_report_pdf_bytes(
                run_id=rid,
                metrics_payload=metrics_payload,
                dq_summary=dq_summary,
                plots_dir=plots,
            )
    except ExperimentReportBuildError:
        raise
    except Exception as exc:
        logger.exception("experiment report PDF generation failed")
        raise ExperimentReportBuildError(f"Report generation failed: {exc}", missing=[]) from exc

    if not pdf_bytes:
        raise ExperimentReportBuildError("Generated PDF was empty.")

    model_store.put_experiment_report_pdf_bytes(env_seg, rid, pdf_bytes)
    url = model_store.presigned_experiment_report_pdf_url(env_seg, rid, ttl_seconds=presign_ttl)
    if not url:
        raise ExperimentReportBuildError("Uploaded report.pdf but could not obtain a download URL.")
    return url, True
