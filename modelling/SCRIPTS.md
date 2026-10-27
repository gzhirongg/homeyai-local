# Modelling scripts catalog

**Canonical package:** repo-root [`modelling/`](.).  
**Do not edit** `backend/modelling/` — it is a deploy import stub only (see [`../backend/modelling/README.md`](../backend/modelling/README.md)).

Run CLIs from the repo root:

```bash
PYTHONPATH=. python modelling/runners/<script>.py …
```

## Production path (Prefect / Modal / MinIO)

| Script | Role | Integrated with |
| --- | --- | --- |
| [`runners/train_core.py`](runners/train_core.py) | Core fit + diagnostics + artefact write | `run_experiment.py`, Prefect, Modal |
| [`runners/run_experiment.py`](runners/run_experiment.py) | Registry experiment → train → MinIO upload | Prefect `homeyai-model-train`, Modal |
| [`runners/minio_experiment_upload.py`](runners/minio_experiment_upload.py) | Upload local run dir to `valuation/experiments/` | `run_experiment.py`, backfill |
| [`modal_app.py`](modal_app.py) | Modal CPU/GPU training entrypoints | Prefect worker |
| [`data/snapshot_loader.py`](data/snapshot_loader.py) | Narrow v2 Parquet cache in MinIO | Prefect `model_train_flow` |
| [`runners/export_training_snapshot.py`](runners/export_training_snapshot.py) | Wide legacy snapshot → `datasets/training_snapshots/` | Prefect `snapshot_flow` |

## Admin / API (no CLI — use UI or HTTP)

| Surface | Backend |
| --- | --- |
| Models dashboard experiment list | `GET /api/admin/dashboard`, `/api/admin/ml/experiments` |
| Metrics comparison table | `GET /api/model/metrics` |
| Training PDF/HTML report | `backend/services/training_report_html.py`, `experiment_report_build.py` |
| Missing FS diagnostic plots in PDF | [`../backend/scripts/check_experiment_feature_selection_report.py`](../backend/scripts/check_experiment_feature_selection_report.py) — checks `training_matrix_audit.raw_split_input`, JSON/PNG objects under the run prefix; report build synthesizes PNGs from JSON when uploads lacked them |
| Training SHAP (per experiment) | `metrics.top_shap_features` + optional `plots/shap_importance.png` from [`modelling/training_shap.py`](../training_shap.py) (wired in [`runners/train_core.py`](runners/train_core.py)); admin PDF Section 8 |


## Operator CLIs

| Script | When to use |
| --- | --- |
| [`backfill_experiments_to_minio.py`](runners/backfill_experiments_to_minio.py) | Upload `--keep-local` folders to MinIO (default scan: `modelling/experiments/`) |
| [`run_model_sweep.py`](runners/run_model_sweep.py) | Multi model × feature-set × MRT-year grid (not the Prefect batch) |
| [`run_feature_selection.py`](runners/run_feature_selection.py) | Diagnostics only (no model fit) |
| [`compare_feature_selection_ab.py`](runners/compare_feature_selection_ab.py) | CSV summary / pair latest advisory vs apply runs from MinIO ``metrics.json`` |
| [`check_training_prerequisites.py`](runners/check_training_prerequisites.py) | Pre-flight DB / macro / window checks |
| [`ingest_training_parquets_to_minio.py`](runners/ingest_training_parquets_to_minio.py) | One-shot disk → MinIO for MRT/macro/POI sidecars |
| [`build_macro_sidecar.py`](runners/build_macro_sidecar.py) | Macro CSV/parquet → MinIO + optional DB |
| [`build_masterplan_landuse_pit_snapshot.py`](runners/build_masterplan_landuse_pit_snapshot.py) | Masterplan scalars → Postgres |
| [`report_training_completeness.py`](runners/report_training_completeness.py) | Join completeness markdown |
| [`run_eda.py`](runners/run_eda.py) | Profiling plots under `outputs/eda/` |
| [`verify_readonly_connection.py`](verify_readonly_connection.py) | Smoke-test read-only DB URL |
| [`network_diagnostics.py`](network_diagnostics.py) | MinIO/Postgres reachability (Modal preflight) |

## Legacy / shim (avoid for new work)

| Script | Notes |
| --- | --- |
| [`modelling.py`](modelling.py) | Notebook-era CLI; delegates to `run_experiment.py` where possible |
| [`report_mrt_shap.py`](report_mrt_shap.py) | Optional SHAP PNG for `/api/model/shap_chart` |
| [`runners/generate_training_report.py`](runners/generate_training_report.py) | **Removed** — raises `NotImplementedError`; reports are API-built |

## Suggested integrations

1. **After local training:** `backfill_experiments_to_minio.py` so runs appear in the admin dashboard (MinIO catalog).
2. **Single tree:** Keep all Python changes under repo-root `modelling/`; `backend/modelling/` must stay a stub to avoid import shadowing (see `backend/main.py` `sys.path` ordering).
