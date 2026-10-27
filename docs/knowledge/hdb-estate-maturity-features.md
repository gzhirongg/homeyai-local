# HDB estate maturity features (town × month)

Town-level **supply lifecycle** features for training: mean block age (**PiT**), cumulative completed residential stock from the **HDB Property Information** catalogue, **dwelling density** (÷ URA planning-area union footprint), **FY completion** flows (**lagging** 36-month **Completed** totals / **leading** **Under Construction** snapshots from the same data.gov feed), and **`town_supply_maturity_ratio`**.

## Interpretation (brief)

- **`town_hdb_completed_units_roll36m`** / **`town_bto_velocity_36m`**: mass handovers in the prior 36 calendar months — nearer **occupied demand** and turnover.
- **`town_units_under_construction`**: committed pipeline before TOP — nearer **planner/market forward pricing** of infra; **Tier-1** source is FY **Under Construction** rows in the completions CSV (annual granularity; forward-filled across months in the materialised panel).

These are **economic proxies**, not causal shocks. See `modelling/Modelling_System_Design.md` §4.6.

## Data line

| Table | Role |
| ----- | ---- |
| [`hdb_property_information`](../backend/models.py) | `year_completed`, `total_dwelling_units`, **`residential`**, **`hdb_town`** → stock (**B1**) and mean age (**A2**). |
| [`hdb_town_completion_fy`](../backend/models.py) | Ingest **[Completion Status CSV](https://data.gov.sg/datasets/d_9bbcd0c9b0351c7f41c9bfdcdc746668)** — **HDB**, **Completed** / **Under Construction**. |
| [`hdb_resale_town_planning_area`](../backend/models.py) | Deterministic resale `town` → `pln_area_n` list (**CENTRAL AREA**, **`KALLANG/WHAMPOA`**, …). |
| [`hdb_resale_town_land_area_km2`](../backend/models.py) | `ST_Area(geography(ST_UnaryUnion(ST_Collect(geom)))) / 1e6` km² |
| [`hdb_estate_maturity_by_town_month`](../backend/models.py) | Join key: **`town_normalized`** = `UPPER(BTRIM(resale town))`, **`year_month`** = resale `YYYY-MM`. |

Singapore **FY(Y)** spans **1 Apr (Y−1) – 31 Mar Y**. Calendar month **`m`** maps to containing FY via `backend/hdb_resale_town_geo.singapore_fy_label_containing_calendar_month`. Rolling **36m Completed** totals attribute each FY bucket to **March FY** (FY end).

## Ops (admin DB)

Alembic: revision **`d4e3f2a1b9c8`** (`hdb_estate_maturity*` tables).

```bash
cd backend && alembic upgrade head

# Junction + land union (needs URA planning polygons ingested):
PYTHONPATH=. python scripts/populate_resale_town_land_area.py

PYTHONPATH=. python scripts/ingest_hdb_town_completion_fy.py \
  --source ../data/CompletionStatusofHDBResidentialUnitsbyTownEstate.csv

PYTHONPATH=. python scripts/materialize_hdb_estate_maturity_panel.py
```

Re-run **`ml_training_readonly` GRANTs** if not using migrations-only grants: [`backend/scripts/sql/grant_ml_readonly_mrt_snapshot.sql`](../backend/scripts/sql/grant_ml_readonly_mrt_snapshot.sql).

## Training

- Build tag **`estate_maturity`** in [`modelling/config/feature_modules.py`](../modelling/config/feature_modules.py).
- **Dynamic Parquet (v2):** `query_estate_maturity_window_dataframe` selects **only** from `hdb_estate_maturity_by_town_month` (panel PK `town_normalized`, `year_month`). [`dataset_builder.py`](../modelling/data/dataset_builder.py) left-merges that panel onto the resale baseline using **`normalize_hdb_town_label`** + `month`. If the right-hand frame were one row per resale transaction, a merge on `(town, month)` would duplicate rows ~\(n\) times per town-month.
- Engineering: [`modelling/features/estate_maturity.py`](../modelling/features/estate_maturity.py).
- Inference: [`modelling/inference/serving.py`](../modelling/inference/serving.py) loads **`hdb_estate_maturity_by_town_month`** rows when **`estate_maturity`** appears in the feature set ID (requires **`town`** + **`valuation_month`**).

## Related

- [glossary-hdb-ura-spatial.md](../reference/glossary-hdb-ura-spatial.md) — resale `town` vs URA polygons.
- [hdb-property-information.md](hdb-property-information.md) — catalogue ingest.
