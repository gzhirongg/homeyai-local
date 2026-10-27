# Local experiment artefacts (dev / `--keep-local`)

**Canonical store for training runs, the admin models dashboard, and serving:** MinIO  
`models/<MODEL_ENV>/valuation/experiments/<run_id>/` (see [`Modelling_System_Design.md`](../Modelling_System_Design.md) §10).

This directory is **optional** and **gitignored**. It holds on-disk copies when you skip MinIO upload:

```bash
PYTHONPATH=. python modelling/runners/run_experiment.py --name <id> --keep-local
```

Each run creates a timestamped folder:

- `config.json` — frozen experiment + feature-set metadata
- `metrics.json` — CV / holdout metrics
- `best_params.json` — winning search params
- `model.pkl` — fitted sklearn `Pipeline` (pickle-safe feature step)
- `plots/` — preds vs actual, residuals, optional feature importance

Upload a local folder to MinIO:

```bash
PYTHONPATH=. python modelling/runners/backfill_experiments_to_minio.py \
  --scan-experiments-dir modelling/experiments --model-env prod
```

After training, upload to MinIO so the admin dashboard lists the run (see backfill command above).
