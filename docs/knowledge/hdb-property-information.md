# HDB Property Information catalogue

Official block-level snapshot from [data.gov.sg — HDB Property Information](https://data.gov.sg/datasets/d_17f5382f26140b1fdae0ba2ef6239d2f) (`d_17f5382f26140b1fdae0ba2ef6239d2f`), stored locally as [`data/HDBPropertyInformation.csv`](../../data/HDBPropertyInformation.csv) and mirrored to MinIO at `datasets/raw/datagovsg/HDBPropertyInformation.csv` after ingestion.

## Grain and columns

- **Grain:** one row per **block + street** in the catalogue (~13k rows).
- **Not a monthly time series** — dataset metadata cites completion-year coverage (e.g. 1937–2025); `year_completed` is the statutory completion attribute for the block/project line.
- **Flags:** residential/commercial hawker/car park/pavilion (Y/N mapped to booleans).
- **`bldg_contract_town`:** three-letter HDB contract-town codes; mapped to full HDB resale `town` names in [`backend/hdb_contract_town_map.py`](../../backend/hdb_contract_town_map.py).

## Postgres table

[`hdb_property_information`](../../backend/models.py) (Alembic: `a8f7e6d5c4b3`)

| Column | Role |
| ------ | ----- |
| `blk_street` | Canonical join key: uppercase block, space, normalised street — same convention as [`hdb_address_enrichment_onemap.query_sent`](../../backend/models.py) ([`address_normalize`](../../backend/scripts/address_normalize.py)). **UNIQUE.** |
| `enriched_addr_id` | FK → `hdb_address_enrichment_onemap.id`, `ON DELETE SET NULL`; resolved at ingest via case-insensitive `query_sent` match. |
| `blk_no`, `street`, `street_norm` | Denormalised display / debugging helpers. |

## Ingest script

[`backend/scripts/ingest_hdb_property_information.py`](../../backend/scripts/ingest_hdb_property_information.py)

```bash
cd backend && alembic upgrade head
PYTHONPATH=. python scripts/ingest_hdb_property_information.py
```

Flags: `--dry-run`, `--skip-minio-upload`, `--force-minio`, `--quiet-stats`.

Prints enrichment match coverage and resale join sanity (`blk_street` = `hdb_resale_transactions.block_street`, and resale rows sharing `enriched_addr_id`). Re-run ingest after widening OneMap enrichment to backfill `enriched_addr_id`.

Unit tests (`contract town ↔ CSV codes`, sample `blk_street`): run from repo root with `python -m pytest backend/tests/test_hdb_contract_town_map.py --noconftest -q` if full `pytest`/`conftest` is blocked locally (optional WeasyPrint dependencies).

## Joins

| From | Relationship |
| ---- | ----------- |
| `hdb_resale_transactions` | Many → one on `block_street` = `blk_street`. |
| `hdb_address_enrichment_onemap` | One → one optional via `enriched_addr_id`; string fallback `LOWER(blk_street) = LOWER(query_sent)`. |
| `hdb_mrt_routes`, `hdb_poi_features` | Via `enriched_addr_id` (`hdb_addr_id`). |
| `hdb_buildings` | Rough match on `blk_no` ± postal (see footprints ingest). |

## Related

- Street normalisation extracted to [`backend/scripts/address_normalize.py`](../../backend/scripts/address_normalize.py) so ingest/backfill avoid importing Prefect/PDF-heavy modules.
- Estate maturity town-month panel (stock, density, FY completions / UC): [`hdb-estate-maturity-features.md`](hdb-estate-maturity-features.md).
- Glossary cross-ref: [`docs/reference/glossary-hdb-ura-spatial.md`](../reference/glossary-hdb-ura-spatial.md).
