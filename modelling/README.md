# HomeyAI — Modelling workspace

**Script catalog:** [`SCRIPTS.md`](SCRIPTS.md) — runners, production integrations, legacy shims.

Config-driven ML experiments for HDB resale price prediction.
Feature sets, model specs, and named experiments are first-class objects in `modelling/config/`.
Every training run is reproducible and self-contained.

---

## Table of contents

1. [Installation](#1-installation)
2. [Data sources](#2-data-sources)
3. [Three repeatable workflows](#3-three-repeatable-workflows)
   - [Add a new feature](#31-add-a-new-feature)
   - [Run EDA](#32-run-eda)
   - [Train, compare, and report](#33-train-compare-and-report)
4. [Feature sets](#4-feature-sets)
5. [Model specs](#5-model-specs)
6. [Experiment registry](#6-experiment-registry)
7. [Package layout](#7-package-layout)
8. [Artefact structure](#8-artefact-structure)
9. [Legacy compatibility](#9-legacy-compatibility)
10. [Testing](#10-testing)

---

## 1. Installation

```bash
cd /path/to/FYP-HomeyAI
python3 -m venv .venv && source .venv/bin/activate

# Core (required for all experiments except XGBoost and POI)
pip install -r modelling/requirements.txt

# Optional — XGBoost experiments (macOS: brew install libomp first)
pip install -r modelling/requirements-xgboost.txt

# Optional — LightGBM experiments (``lightgbm__*`` registry ids)
pip install -r modelling/requirements-lgbm.txt

# Optional — POI/distancing experiments
pip install -r modelling/requirements-poi.txt

# Optional — DB-backed training
pip install -r modelling/requirements-db.txt

# Optional — SHAP attribution report
pip install -r modelling/requirements-shap.txt

export PYTHONPATH=.   # required for all commands below
```

---

## 2. Data sources

### Primary training data

| Source | Config | Notes |
| --- | --- | --- |
| **Postgres resale + MRT + masterplan joins** (`training_db`) | `DATABASE_URL_READ_ONLY` / `READ_ONLY_DB_*` + `DB_*` | **Default** for all modelling CLIs. |
| **MinIO parquet mirror** (`--from-parquet-minio` or `RunConfig(parquet_minio=True)`) | `HOMEYAI_MINIO_SOURCES_JSON` → defaults to [`modelling/config/minio_training_sources.sample.json`](config/minio_training_sources.sample.json) | Optional resale frame at manifest key `training_hdb_resale_parquet` (+ optional merges). |

Training builders never read repo `data/*.parquet`; one-shot disk ingest for eligible legacy artefacts
(MRT parquet, macros, POI blobs) uploads to manifest keys via:

```bash
PYTHONPATH=. python modelling/runners/ingest_training_parquets_to_minio.py
```

Rebuild MRT snapshot tables still uses backend batch (`python backend/scripts/build_mrt_pit_snapshot.py`).


### Macros (volume lag, RPI, rates)

Volume series is aggregated from Postgres and PUT to MinIO by
`PYTHONPATH=. python modelling/runners/build_macro_sidecar.py`.
`macro_sentiment` reads blobs from manifest keys **`global_volume_monthly`**, **`macro_interest_csv`**
(**`macro_rpi_csv`** quarterly levels are a fallback when Postgres `hdb_resale_price_index` is unavailable —
training labels are RPI-adjusted regardless of macro feature IDs).
(or live APIs — no commits under `data/macro`).

**RPI-backed valuation inference:** Inference rescale carry-forwards when the valuation month’s calendar quarter is not yet in open data (`rpi_normalization`), but **at least one** quarterly row must be available somewhere in the Postgres / MinIO / data.gov.sg chain. Hydrate Postgres with [`backend/scripts/ingest_hdb_rpi.py`](../backend/scripts/ingest_hdb_rpi.py) (canonical CSV from [HDB Resale Price Index on data.gov.sg](https://data.gov.sg/datasets/d_14f63e595975691e7c24a27ae4c07c79/view)).

### POI assets (`poi_distancing` / `mrt_pit__poi_distancing` feature sets)

Place files in `data/pois/` (see [`data/pois/README.md`](../data/pois/README.md) for expected filenames).
`hdb_block_coords.csv` supports sweep fallbacks until `poi_locations` is hydrated.
Postgres-backed training merges OneMap coordinates from `hdb_address_enrichment_onemap`.

**Ingested copies (MinIO + Postgres):** after running [`backend/scripts/ingest_poi_assets.py`](../backend/scripts/ingest_poi_assets.py), raw files are mirrored to MinIO `datasets/pois/` and point rows are stored in `poi_locations`. Pre-computed per-address scalars go to `hdb_poi_features` via [`build_poi_features.py`](../backend/scripts/build_poi_features.py). **Knowledge management** (destinations, justification, modelling integration): [`docs/knowledge/poi-data-km.md`](../docs/knowledge/poi-data-km.md). Architecture context: [`docs/architecture/data-storage-strategy.md`](../docs/architecture/data-storage-strategy.md), decision record: [`docs/adr/001-poi-ingestion.md`](../docs/adr/001-poi-ingestion.md).

When `poi_locations` is populated, [`run_model_sweep.py`](runners/run_model_sweep.py) prefers loading POIs from the DB (read-only URL); otherwise it falls back to files + `hdb_block_coords.csv` when that CSV exists.

---

## 3. Three repeatable workflows

### 3.1 Add a new feature

**Step 1 — implement the transformation**

Write a function that accepts a raw `pd.DataFrame` and returns an engineered `pd.DataFrame`.
Place it in the appropriate module:

| Scope | Module |
| --- | --- |
| Core HDB tabular | `modelling/features/base.py` |
| MRT point-in-time | `modelling/features/mrt_pit.py` |
| POI / spatial | `modelling/features/poi_distancing.py` |
| New domain | New file under `modelling/features/` |

```python
# modelling/features/base.py — example: add months_since_start
def engineer_base_features(frame, *, categorical_style="legacy"):
    ...
    out["months_since_start"] = (sale_year - 1990) * 12 + sale_month
    ...
```

**Step 2 — register a feature set**

In `modelling/config/feature_sets.py`, add a new `FeatureSet` entry (or extend an existing one)
inside `build_feature_set_registry`:

```python
"my_feature_set": FeatureSet(
    id="my_feature_set",
    description="Baseline + months_since_start.",
    categorical_features=cat_b,
    numeric_features=num_b + ["months_since_start"],
    engineer=_eng_my_set,       # top-level function, not a lambda
    engineer_kwargs={},
),
```

**Step 3 — register an experiment**

In `modelling/config/experiments.py`, add to `default_experiments`:

```python
"random_forest__my_features": Experiment(
    id="random_forest__my_features",
    feature_set_id="my_feature_set",
    model_id="random_forest",
    description="RF with months_since_start feature.",
),
```

**Step 4 — run it**

```bash
python modelling/runners/run_experiment.py --name random_forest__my_features
```

---

### 3.2 Run EDA

```bash
# Default: Postgres read-only snapshot
PYTHONPATH=. python modelling/runners/run_eda.py --tag my_run

# Explicit MinIO manifest parquet (+ optional parquet sidecars)
PYTHONPATH=. python modelling/runners/run_eda.py --from-parquet-minio --tag my_run
```

Outputs land in `modelling/outputs/eda/<tag>__<utc>/`:

| File | Content |
| --- | --- |
| `column_profile.csv` | dtype, missingness %, unique count, column role |
| `missingness.png` | Bar chart of missing % per column |
| `target_distribution.png` | Raw and log-transformed resale price histograms |
| `quarterly_price_trend.png` | Market-wide price/sqm trend (quarterly) |
| `quarterly_price_by_region.png` | Per-region price/sqm trend (quarterly) |
| `psi_summary.csv` | Population Stability Index (train vs test, key features) |

**One-off completeness report (raw training join: resale + OneMap + PIT snapshot)**

```bash
PYTHONPATH=. python modelling/runners/report_training_completeness.py
# Manifest-backed parquet frame:
PYTHONPATH=. python modelling/runners/report_training_completeness.py --training-source parquet_minio
```

Writes `modelling/outputs/training_completeness__<utc>.md` (Markdown tables: join hit rate, non-null PIT columns).

---

### 3.3 Train, compare, and report

**Run a single experiment**

```bash
PYTHONPATH=. python modelling/runners/run_experiment.py \
    --name random_forest__mrt \
    --max-train-rows 200000

# Explicit MinIO manifest frame (cold environments)
PYTHONPATH=. python modelling/runners/run_experiment.py \
    --name random_forest__mrt \
    --from-parquet-minio \
    --max-train-rows 200000
```

Override any experiment default at the command line:

```bash
python modelling/runners/run_experiment.py \
    --name linear__baseline \
    --test-fraction 0.15 \
    --cv-splits 5 \
    --max-train-rows 0          # 0 = no cap (full history)
```

**Run all baseline experiments**

```bash
for exp in linear__baseline random_forest__baseline mlp__baseline \
           linear__mrt random_forest__mrt mlp__mrt; do
    python modelling/runners/run_experiment.py --name "$exp"
done
```

**Run EDA + SHAP attribution** (optional, needs `pip install shap`):

```bash
PYTHONPATH=. python modelling/report_mrt_shap.py
# writes modelling/outputs/mrt_pit_features/rf_shap_bar.png
```

---

## 4. Feature sets

Registered in `modelling/config/feature_sets.py`.
The feature set controls both the engineering function and the exact column lists fed to
`ColumnTransformer`.

| ID | Description | Requires |
| --- | --- | --- |
| `baseline_v1` | Core HDB structural features + ``lat``/``lon`` (block WGS84) | Postgres (default) or manifest parquet |
| `mrt_pit` | `baseline_v1` (+ coordinates) + 11 point-in-time MRT columns + unified per-line indicators | Postgres snapshot joins (or parquet sidecars when `--from-parquet-minio`) |
| `poi_distancing` | `baseline_v1` + 17 POI distance/density/gravity columns (+ keeps ``lat``/``lon`` as model inputs) | `data/pois/` assets + lat/lon |
| `mrt_pit__poi_distancing` | Union of `mrt_pit` and `poi_distancing` | both above |

Every baseline-derived set passes **longitude and latitude through to the preprocessor** after OneMap-aligned geocoding. Tree ensembles can split on coordinates to learn implicit map overlays and smooth across **town** administrative borders; correlate `lat`/`lon` with `town`/`dist_cbd` (`poi_distancing` / masterplan stacks) during §5 diagnostics before dropping any of them.

### `baseline_v1` columns

**Numeric (9):** `sale_year`, `sale_month_sin`, `sale_month_cos`, `floor_area_sqm`, `flat_type_encoded`, `remaining_lease_years`, `storey_mid`, `lat`, `lon`.

`flat_type_encoded` is a single **ordinal** feature (1–7) derived from raw HDB `flat_type` after normalizing strings to canonical forms (`1 ROOM` … `5 ROOM`, `EXECUTIVE`, `MULTI-GENERATION`). One-hot encoding was removed: flat type is a size / utility ladder that aligns with `floor_area_sqm`, and tree models can separate “smaller vs larger” in one split instead of many sparse binaries. Rare categories (e.g. 1–2 ROOM on resale) impute via the numeric median like other scalars when needed.

| Ordinal | Canonical `flat_type` (after normalize) |
| --- | --- |
| 1 | `1 ROOM` |
| 2 | `2 ROOM` |
| 3 | `3 ROOM` |
| 4 | `4 ROOM` |
| 5 | `5 ROOM` |
| 6 | `EXECUTIVE` |
| 7 | `MULTI-GENERATION` |

| Column | Description |
| --- | --- |
| `sale_year` | Transaction year (`month` splits) |
| `sale_month_sin` / `sale_month_cos` | Cyclical calendar-month encoding (`sale_month` 1–12 is **not** a model column) |
| `floor_area_sqm` | Flat size |
| `flat_type_encoded` | Ordinal flat-type ladder (see table above); hyphenated inputs (e.g. `1-ROOM`) align to space form |
| `remaining_lease_years` | Years remaining on lease at sale (integer from DB; legacy string mapped when needed) |
| `storey_mid` | Midpoint inferred from storey band (`NN TO NN`); band edges **not** model features |
| `lat` | Block latitude — WGS84 from OneMap enrichment |
| `lon` | Block longitude — WGS84 from OneMap enrichment |

**Variants:** ``baseline_v1__months_since_2015`` appends anchored trend ``months_since_2015`` (10 numeric columns total).

**Categorical (2):** `town`, `flat_model`

### `mrt_pit` additional columns

**Numeric (10 scalars + 2 binary)**

Training merges **`num_unique_lines_within_1km`** and **`nearest_planned_mrt_dist`** from `hdb_mrt_features_pit_snapshot` / `hdb_mrt_features_at`. **`project_completion_fraction`** is derived in Python from announcement age and days-to-opening. Raw SQL still returns **`nearest_op_lines`** and **`nearest_planned_lines`** for audits; [`validate_mrt_line_registry`](features/mrt_pit.py) checks literals against **`_mrt_lines.json`**. Per-line **`is_nearest_line_*`** one-hots are **not** part of the registered MRT pack.

| Column | Channel | Description |
| --- | --- | --- |
| `dist_to_nearest_op_mrt` | Operational | Walking metres to nearest open station |
| `travel_time_to_active_mrt` | Operational | Walking minutes |
| `pt_time_savings_vs_walk` | Operational | Minutes saved by feeder bus |
| `line_connectivity_index` | Operational | Distinct open lines at nearest routed station |
| `num_unique_lines_within_1km` | Operational | Distinct open `network_line` values with any station within 1 km (geography) at PIT |
| `days_since_mrt_announcement` | Speculative | Hype/announcement recency |
| `days_to_mrt_opening` | Speculative | Countdown to nearest planned station |
| `speculative_upside_score` | Speculative | Sigmoid 0–1 score |
| `nearest_planned_mrt_dist` | Speculative | Straight-line metres to nearest planned physical cluster (2 km candidate window) |
| `project_completion_fraction` | Speculative | Bounded [0,1] `days_since_announcement / (days_since_announcement + days_to_opening)`; Python-derived; NaN when no planned cluster within 2 km |
| `has_future_upside` | Speculative | Binary gate — planned station ≤ 2 km |
| `is_proximity_nuisance` | Nuisance | Binary — within 200 m of active dig site |

### `poi_distancing` additional columns

| Column | Description |
| --- | --- |
| `dist_cbd` | Haversine km to CBD (1.2830, 103.8513) |
| `dist_airport` | Haversine km to Changi Airport |
| `dist_nearest_top20_school` | Metres to nearest top-20 primary school |
| `dist_nearest_any_school` | Metres to nearest primary school (all-schools list) |
| `within_1km_top20_school` | Binary — top-20 primary school within 1 km |
| `within_1km_2km_top20_school` | Binary — top-20 school between 1–2 km |
| `within_1km_any_pri_school` | Binary — any primary school within 1 km |
| `within_1km_2km_pri_school` | Binary — any school between 1–2 km |
| `dist_nearest_mall` | Metres to nearest mall |
| `malls_within_2km` | Count of malls within 2 km |
| `supermarkets_within_500m` | Count of supermarkets within 500 m |
| `markets_within_500m` | Count of hawker/food centres within 500 m |
| `dist_nearest_park` | Metres to nearest park centroid |
| `is_park_200m` | Binary — park centroid within 200 m |
| `dist_nearest_pcn` | Metres to nearest Park Connector Network sample point (100 m spacing) |
| `gravity_malls` | Exponential decay sum over k nearest malls (default weight 1.2) |
| `gravity_schools` | Exponential decay sum over k nearest schools (default 1.0) |
| `gravity_parks` | Exponential decay sum over k nearest parks (default 1.0) |
| `gravity_markets` | Exponential decay sum over k nearest markets (default 0.9) |

### `primary_school` (AB pack — two columns)

| Column | Description |
| --- | --- |
| `count_top20_schools_within_1km` | Count of top-20 primary school POIs within 1000 m |
| `count_top20_schools_within_1km_2km` | Count strictly in the (1 km, 2 km] annulus |

Implemented in `features/primary_school.py` (no `dist_nearest_top20_school`; counts from BallTree `query_radius`, not from `hdb_poi_features`).

POI points can be loaded from `data/pois/` files or from Postgres `poi_locations` (`engineer_poi_frame(..., use_db=True)`). See `docs/adr/001-poi-ingestion.md`.

### `poi_amenity_v2` (seven columns)

Slim pack in `features/poi_amenity_v2.py`: nearest primary school (+ 1 km / 2 km flags), hawker distance/count (1 km), mall distance/count (1.5 km). Training from DB can blend school/mall distances from `hdb_poi_features` when `enriched_addr_id` matches; see `docs/knowledge/poi-amenity-v2-roadmap.md`.

---

## 5. Model specs

Registered in `modelling/config/model_specs.py`.

| ID | Display name | Scaling | Search | Target inverse | Notes |
| --- | --- | --- | --- | --- | --- |
| `linear` | Linear Regression | StandardScaler | GridSearch (3×2 = 6 fits) | `expm1` clipped at `e^15` | Interpretable baseline |
| `random_forest` | Random Forest | None | RandomSearch (10 iters) | `expm1` clipped | Best classical baseline for tabular HDB data |
| `mlp` | Neural Network | StandardScaler | RandomSearch (8 iters) | `expm1` clipped | Most sensitive to scale and LR |
| `xgboost` | XGBoost | None | RandomSearch (6 iters) | `expm1` **unclipped** | TargetEncoder on `town`/`flat_model`; optional (needs libomp on macOS) |
| `xgboost_tuned_gpu` | XGBoost (tuned, CUDA) | None | RandomSearch (15 iters) | `expm1` **unclipped** | Same grid as tuned CPU spec; `device=cuda`, `n_jobs=1`; use with Modal L40S (`modal_profile=l40s`) |

All models train in **log-adjusted-dollar space**: labels are resale price divided by HDB quarterly RPI
`×100` before `log1p` (`modelling.targets.rpi_normalization`); artefacts and API responses are nominal SGD again.
**Serving:** if the valuation month’s calendar quarter is not yet in the RPI table, rescale uses the **latest published prior quarter** (small nominal bias until open data catches up — see Modelling_System_Design.md §9).
The clipped inverse (`target_clip_inverse=True`) caps predictions at `e^15 ≈ S$3.27M` for
linear and neural models to prevent runaway extrapolation; XGBoost does not require this.

**XGBoost / LightGBM preprocessing** (same high-cardinality treatment; trees use the numeric branch for `flat_type_encoded`):

- `TargetEncoder(smoothing=20)` on `town` and `flat_model` (high-cardinality, M-estimate smoothing).
- `region` only on **`xgboost_grouped`**: low-cardinality `OneHotEncoder` (no infrequent bucketing).
- Standard `SimpleImputer(median)` on numerics (including `flat_type_encoded`); no scaling for tree specs.

---

## 6. Experiment registry

Registered in `modelling/config/experiments.py`.

### Core 3/4/5 ROOM (`flat_type_scope` / `__core35`)

Roughly ninety percent of the resale corpus is **3 ROOM**, **4 ROOM**, and **5 ROOM**. Training on that subset lowers variance and often improves validation MAE/R² versus a single model strained by rare strata (Executive, Multi-Generation, smaller-room types), at the cost of **not targeting** those minorities.

Each base experiment listed in [`CORE35_SOURCE_EXPERIMENT_IDS`](config/experiments.py) also appears as **`{id}__core35`**, with `Experiment.flat_type_scope="core_35"` so rows outside normalized 3/4/5 ROOM labels are **dropped before the temporal split**. Hyphen inputs (for example `4-ROOM`) match the core set the same way as ordinal encoding. Batch list: **`CORE35_XGBOOST_V1`** in [`config/experiment_batches.py`](config/experiment_batches.py).

**Core35 MRT + primary school pack A/B (5y window, no macro).** For a matched **four-arm** comparison of land-use and/or estate pillars on top of MRT + top-20 school annulus counts, use batch **`CORE35_Y5_MRT_PRIMARY_SCHOOL_PACK_AB_V1`** in [`config/experiment_batches.py`](config/experiment_batches.py). All use `xgboost_tuned`, `flat_type_scope=core_35`, and `mrt_pit_min_years=5`.

| Experiment ID | Feature set |
| --- | --- |
| `xgboost_tuned__core35_y5__mrt_primary_school` | `mrt_pit__primary_school` (control) |
| `xgboost_tuned__core35_y5__mrt_primary_school__landuse` | `mrt_pit__masterplan_landuse_pit__primary_school` |
| `xgboost_tuned__core35_y5__mrt_primary_school__estate` | `mrt_pit__primary_school__estate_maturity` |
| `xgboost_tuned__core35_y5__mrt_primary_school__landuse_estate` | `mrt_pit__masterplan_landuse_pit__primary_school__estate_maturity` |

**Core35 masterplan area vs proximity A/B (5y window, no macro).** Batch **`CORE35_Y5_MASTERPLAN_AREA_PROXIMITY_AB`** isolates **pack 1** (polygon intersection areas only), **pack 2** (GPR, reference distances, derived scores, B2/business-park proximity columns), and **both** against the same MRT + primary-school control. Re-run `build_masterplan_landuse_pit_snapshot.py --write-db` after Alembic `e9a0b1c2d3e4` so `dist_to_nearest_b2_zone`, `b2_zoning_ratio_1km`, and `dist_to_nearest_business_park` are populated.

| Experiment ID | Feature set |
| --- | --- |
| `xgboost_tuned__core35_y5__mrt_primary_school` | `mrt_pit__primary_school` (control) |
| `xgboost_tuned__core35_y5__mrt_primary_school__masterplan_area` | `mrt_pit__masterplan_area__primary_school` |
| `xgboost_tuned__core35_y5__mrt_primary_school__masterplan_proximity` | `mrt_pit__masterplan_proximity__primary_school` |
| `xgboost_tuned__core35_y5__mrt_primary_school__masterplan_area_proximity` | `mrt_pit__masterplan_area_proximity__primary_school` |

**Modal L40S + CUDA XGBoost.** Use batch tuple **`MODAL_L40S_XGBOOST_V1`** for `xgboost_tuned_gpu__core35_y5__mrt_primary_school` (same feature set as the control row; `model_id=xgboost_tuned_gpu`, `device=cuda`). **`Experiment.modal_profile=l40s`** dispatches **`train_one_experiment_l40s_gen`**; you do **not** need `use_gpu: true` on the train API body.

**Core35 full pillar stack on L40S (window grid).** Batch tuple **`MODAL_L40S_CORE35_FULL_STACK_WINDOW_GRID_V1`** runs CUDA tuned XGBoost on **`mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity`** for **3/4/5 ROOM** only, at **5 / 10 / 15 / 20**-year rolling windows: MRT + macro + masterplan **proximity** (no `area_*`) + top-20 school **count** columns + estate maturity; **POI distance numerics are excluded** from the model (school counts still use POI tables at engineer time). Baseline numerics omit **`sale_year`** (month sin/cos retained). Not the same contract as CPU **`xgboost_tuned__full_stack`** (`mrt_pit__poi_distancing__macro__masterplan_landuse_pit`). Prefer **`TRAINING_FORCE_DATASET_REBUILD=1`** once when the feature set id changed so dataset cache keys do not reuse older Parquet. **Feature-selection A/B:** run the batch twice with different `feature_selection_policy` (`advisory_only` vs `apply`) on `POST /api/admin/model/train/batch`; for fair comparison, pin the same `dataset_version` and keep `TRAINING_FORCE_DATASET_REBUILD=0` on the worker between those two runs after the rebuild (see environment-variables docs). These runs record `training_context.flat_type_scope=core_35` in `metrics.json`.

| Experiment ID | Rolling window |
| --- | --- |
| `xgboost_tuned_gpu__core35_y5__full_stack` | 5y |
| `xgboost_tuned_gpu__core35_y10__full_stack` | 10y |
| `xgboost_tuned_gpu__core35_y15__full_stack` | 15y |
| `xgboost_tuned_gpu__core35_y20__full_stack` | 20y |

**Core35 full pillar stack on CPU (linear + MLP window grid).** Batch tuple **`CORE35_LINEAR_MLP_FULL_STACK_WINDOW_GRID_V1`** runs **sklearn linear + MLP** on the **same feature set** as the L40S grid above, for **3/4/5 ROOM** at **5 / 10 / 15 / 20**-year windows. Uses default **`modal_profile=cpu`** → **`train_one_experiment_cpu_gen`**; omit API `use_gpu`. Launch with **`feature_selection_policy=advisory_only`** (default) for diagnostics without column drops. Wall-clock is not comparable to L40S XGBoost.

| Experiment ID | Model | Rolling window |
| --- | --- | --- |
| `linear__core35_y5__full_stack` | `linear` | 5y |
| `linear__core35_y10__full_stack` | `linear` | 10y |
| `linear__core35_y15__full_stack` | `linear` | 15y |
| `linear__core35_y20__full_stack` | `linear` | 20y |
| `mlp__core35_y5__full_stack` | `mlp` | 5y |
| `mlp__core35_y10__full_stack` | `mlp` | 10y |
| `mlp__core35_y15__full_stack` | `mlp` | 15y |
| `mlp__core35_y20__full_stack` | `mlp` | 20y |

CLI override (does not change the registry id):

```bash
PYTHONPATH=. python modelling/runners/run_experiment.py \
  --name xgboost_tuned__mrt --flat-type-scope core_35
```

`metrics.json` records `training_context.flat_type_scope`, `training_context.flat_type_filter` (counts), and **`data_profile_pre_filter`** when the subset is enabled (EDA on the loaded frame before the filter). **Inference:** promoting a core-35 artefact without checks makes Executive and minority flat types **out-of-distribution** compared to training; keep a broader model or handle this in product.

| Experiment ID | Feature set | Model | Notes |
| --- | --- | --- | --- |
| `linear__baseline` | `baseline_v1` | `linear` | Clean linear baseline |
| `random_forest__baseline` | `baseline_v1` | `random_forest` | |
| `mlp__baseline` | `baseline_v1` | `mlp` | |
| `xgboost__baseline` | `baseline_v1` | `xgboost` | TargetEncoder; needs XGBoost installed |
| `linear__mrt` | `mrt_pit` | `linear` | MRT PIT lift comparison |
| `random_forest__mrt` | `mrt_pit` | `random_forest` | |
| `mlp__mrt` | `mrt_pit` | `mlp` | |
| `xgboost__mrt` | `mrt_pit` | `xgboost` | |
| `xgboost_tuned__mrt` | `mrt_pit` | `xgboost_tuned` | Wide HPO on MRT pack |
| `xgboost__mrt_poi` | `mrt_pit__poi_distancing` | `xgboost` | Full Colab-style stack; needs POI assets |
| `xgboost__primary_school` | `primary_school` | `xgboost` | Top-20 school annulus-count AB pack (2 counts); snapshot lat/lon + POI via feature set |
| `xgboost__mrt_primary_school` | `mrt_pit__primary_school` | `xgboost` | MRT + same primary-school counts; window from `MRT_PIT_MIN_YEARS` env (default 5y) |
| `xgboost_tuned__mrt_landuse_primary_school` | `mrt_pit__masterplan_landuse_pit__primary_school` | `xgboost_tuned` | Baseline + MRT + land use + school counts; fixed **5**-year window (no macro) |
| `xgboost__mrt_primary_school__y10` | `mrt_pit__primary_school` | `xgboost` | Same stack; fixed **10**-year rolling window (`mrt_pit_min_years` on experiment) |
| `xgboost__mrt_primary_school__y15` | `mrt_pit__primary_school` | `xgboost` | Same stack; fixed **15**-year rolling window |
| `xgboost__mrt_primary_school__y20` | `mrt_pit__primary_school` | `xgboost` | Same stack; fixed **20**-year rolling window |
| `linear__mrt_primary_school` | `mrt_pit__primary_school` | `linear` | Same stack as `xgboost__mrt_primary_school` |
| `random_forest__mrt_primary_school` | `mrt_pit__primary_school` | `random_forest` | Same stack as `xgboost__mrt_primary_school` |
| `mlp__mrt_primary_school` | `mrt_pit__primary_school` | `mlp` | Same stack as `xgboost__mrt_primary_school` |
| `ridge__mrt_primary_school` | `mrt_pit__primary_school` | `ridge` | Same stack as `xgboost__mrt_primary_school` |
| `extra_trees__mrt_primary_school` | `mrt_pit__primary_school` | `extra_trees` | Same stack as `xgboost__mrt_primary_school` |
| `lightgbm__mrt_primary_school` | `mrt_pit__primary_school` | `lightgbm` | Same stack as `xgboost__mrt_primary_school` |
| `xgboost_tuned_gpu__core35_y5__mrt_primary_school` | `mrt_pit__primary_school` | `xgboost_tuned_gpu` | Core35 5y MRT + school counts; CUDA + Modal L40S (`modal_profile=l40s`; see `MODAL_L40S_XGBOOST_V1`) |
| `xgboost_tuned_gpu__core35_y5__full_stack` | `mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity` | `xgboost_tuned_gpu` | Core35 5y: macro+proximity+estate+school counts, no POI numerics, no sale_year (`MODAL_L40S_CORE35_FULL_STACK_WINDOW_GRID_V1`) |
| `xgboost_tuned_gpu__core35_y10__full_stack` | `mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity` | `xgboost_tuned_gpu` | Core35 10y; same batch tuple |
| `xgboost_tuned_gpu__core35_y15__full_stack` | `mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity` | `xgboost_tuned_gpu` | Core35 15y; same batch tuple |
| `xgboost_tuned_gpu__core35_y20__full_stack` | `mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity` | `xgboost_tuned_gpu` | Core35 20y; same batch tuple |
| `linear__core35_y5__full_stack` | `mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity` | `linear` | Core35 5y: same stack as GPU full-stack; CPU Modal (`CORE35_LINEAR_MLP_FULL_STACK_WINDOW_GRID_V1`) |
| `linear__core35_y10__full_stack` | `mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity` | `linear` | Core35 10y; same CPU batch tuple |
| `linear__core35_y15__full_stack` | `mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity` | `linear` | Core35 15y; same CPU batch tuple |
| `linear__core35_y20__full_stack` | `mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity` | `linear` | Core35 20y; same CPU batch tuple |
| `mlp__core35_y5__full_stack` | `mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity` | `mlp` | Core35 5y: same stack; CPU Modal |
| `mlp__core35_y10__full_stack` | `mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity` | `mlp` | Core35 10y; same CPU batch tuple |
| `mlp__core35_y15__full_stack` | `mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity` | `mlp` | Core35 15y; same CPU batch tuple |
| `mlp__core35_y20__full_stack` | `mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity` | `mlp` | Core35 20y; same CPU batch tuple |
| `mrt_pit_baselines` | — | — | Meta: runs `linear`, `random_forest`, `mlp` on `mrt_pit` sequentially |

Each `Experiment` dataclass stores: `feature_set_id`, `model_id`, `test_fraction` (default 0.2),
`cv_splits` (default 4), `max_train_rows` (default **no cap**; pass a positive integer for the most recent N train rows), optional `flat_type_scope` (**`all`** vs **`core_35`** slice), optional `mrt_pit_min_years` (overrides `MRT_PIT_MIN_YEARS` for dataset SQL + metrics when set), optional **`modal_profile`** (`cpu` \| `t4` \| `l40s`) for Modal routing, and search iteration budgets.
Override any field at the CLI without editing config:

```bash
python modelling/runners/run_experiment.py \
    --name mlp__mrt \
    --cv-splits 6 \
    --max-train-rows 0      # no cap
```

---

## 7. Package layout

```
modelling/
├── README.md                          ← this file
├── Modelling_System_Design.md         ← architecture decisions + lift table
├── __init__.py
├── modelling.py                       ← legacy notebook CLI + backward-compat exports
├── training_db.py                     ← read-only URL (`DATABASE_URL_READ_ONLY` or assembled)
├── mrt_pit_helpers.py                 ← re-exports features/line_vocab (backward compat)
├── report_mrt_shap.py                 ← SHAP attribution for RF baseline
│
├── config/
│   ├── __init__.py
│   ├── feature_sets.py                ← FeatureSet registry
│   ├── model_specs.py                 ← ModelSpec registry + preprocessor factory
│   └── experiments.py                 ← Experiment dataclass + registry
│
├── data/
│   ├── __init__.py
│   ├── flat_type_scope.py             ← training row subsets (core 3/4/5 ROOM)
│   ├── loaders.py                     ← Postgres / manifest MinIO frame loading
│   └── splits.py                      ← temporal split + row-cap
│
├── features/
│   ├── __init__.py
│   ├── base.py                        ← time / lease / storey / categorical engineering
│   ├── mrt_pit.py                     ← PIT MRT pack (scalars + binaries + line coverage / planned distance)
│   ├── poi_distancing.py              ← POI distances, density, gravity
│   └── line_vocab.py                  ← MRT line registry helpers
│
├── models/
│   ├── __init__.py
│   └── pipelines.py                   ← build_full_pipeline (pickle-safe)
│
├── eda/
│   ├── profile.py                     ← column profile, missingness, target plots
│   ├── psi.py                         ← Population Stability Index
│   └── price_trends.py                ← quarterly / regional price trends (Colab RQ1)
│
├── evaluation/
│   ├── __init__.py
│   └── metrics.py                     ← RMSE/MAE/MAPE/R², target transforms
│
├── runners/
│   ├── __init__.py
│   ├── run_eda.py                     ← CLI: outputs/eda/<tag>__<ts>/
│   ├── report_training_completeness.py ← one-off PIT/join completeness → outputs/*.md
│   ├── run_experiment.py              ← CLI: experiments/<id>__<ts>/
│
├── experiments/                       ← local dev artefacts only (gitignored); see README
│   └── README.md
│
├── outputs/
│   ├── eda/                           ← generated by run_eda.py
│   └── mrt_pit_features/             ← generated by report_mrt_shap.py
│
├── tests/
│   ├── conftest.py
│   ├── test_mrt_features_pit.py
│   └── test_feature_sets.py
│
├── requirements.txt
├── requirements-db.txt
├── requirements-xgboost.txt
├── requirements-lgbm.txt
├── requirements-poi.txt
└── requirements-shap.txt
```

---

## 8. Artefact structure

### Canonical store (MinIO)

Production training (Prefect / Modal / default `run_experiment.py`) uploads to:

```
models/<MODEL_ENV>/valuation/experiments/<run_id>/
├── model.pkl
├── metrics.json
├── config.json
├── best_params.json
├── manifest.json
├── feature_*.json / *.csv   ← optional diagnostics
├── training_data.parquet    ← optional
├── report.pdf               ← optional
└── plots/ …
```

The admin **models** dashboard (`/api/admin/dashboard`), experiment catalog, promote-to-live, and `/api/valuation` all use this prefix (`MODEL_ENV` must match across API, workers, and upload CLIs).

### Local directory (dev / `--keep-local`)

Each `run_experiment.py` run can also leave a timestamped folder under `modelling/experiments/`:

```
experiments/random_forest__mrt__20260510T041637Z/
├── config.json          ← frozen experiment settings + feature-set description + Python version
├── metrics.json         ← CV RMSE, holdout RMSE/MAE/MAPE/R², n_train, n_test + optional `data_quality_summary`
├── best_params.json     ← winning hyperparameters from search
├── model.pkl            ← fitted sklearn Pipeline (pickle-safe)
├── report.pdf           ← optional; HTML/PDF reports may also be built in the API from MinIO artefacts
└── plots/
    ├── preds_vs_actual.png
    ├── residuals.png
    └── feature_importance.png   ← tree-importance bar chart when available
```

Backfill local runs to MinIO with `modelling/runners/backfill_experiments_to_minio.py`.

Pre-flight data quality thresholds live in **`modelling/config/training_quality_gates.yml`** (override with `HOMEYAI_DQ_CONFIG` or `HOMEYAI_DQ_<section>__<key>` env vars — see **`docs/reference/environment-variables.md`**). Quick DB window check: **`python modelling/runners/check_training_prerequisites.py`**.

**Pipeline internals** (`model.pkl`):

```
Pipeline(
    feature_engineering → FunctionTransformer(engineering_dispatch, kw_args={...})
    preprocessor        → ColumnTransformer(numeric | categorical)
    model               → TransformedTargetRegressor(log1p / expm1)
)
```

The `engineering_dispatch` step is a top-level module function (not a closure) so the
pipeline serialises cleanly with `joblib`.

---

## 9. Legacy compatibility

| What | Where | Status |
| --- | --- | --- |
| `engineer_features(frame)` | `modelling/modelling.py` | Shim → `engineer_mrt_pit_frame` |
| `_validate_mrt_line_registry(frame)` | `modelling/modelling.py` | Shim → `features/mrt_pit.py` |
| `modelling.mrt_pit_helpers` | `modelling/mrt_pit_helpers.py` | Re-exports `features/line_vocab` |
| `RunConfig`, `ModelSpec` | `modelling/modelling.py` | Preserved for notebook / SHAP usage |
| `build_pipeline(spec)` | `modelling/modelling.py` | Preserved for `report_mrt_shap.py` |
| `python modelling/modelling.py` | `modelling/modelling.py` | Notebook flow (defaults to Postgres snapshot) |
| `python modelling/modelling.py --from-parquet-minio --runner` | `modelling/modelling.py` | Delegates manifest-backed batches to `run_experiment.py --name mrt_pit_baselines` |

POI and distancing features from the original Colab workflow are implemented in
[`features/poi_distancing.py`](features/poi_distancing.py).

---

## 10. Testing

```bash
PYTHONPATH=. pytest modelling/tests -q
```

| Test file | What it covers |
| --- | --- |
| `test_mrt_features_pit.py` | Speculative score sigmoid, line token parsing, registry validation, PIT unified line indicators |
| `test_feature_sets.py` | Feature set composition — `baseline_v1` engineer returns expected column sets |
| `test_minio_sources_manifest.py` | Sample MinIO manifest keys resolve to `(bucket,key)` tuples |

Quick smoke slice (needs read-only Postgres by default):

```bash
PYTHONPATH=. python modelling/runners/run_experiment.py \
    --name linear__baseline \
    --max-train-rows 5000
```

Cold environments can pass `--from-parquet-minio` once `HOMEYAI_MINIO_SOURCES_JSON` points at manifests with uploaded objects.
