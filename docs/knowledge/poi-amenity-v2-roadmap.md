# POI amenity v2 — roadmap and deferred work

**Companion modules:** [`modelling/features/poi_amenity_v2.py`](../../modelling/features/poi_amenity_v2.py) · [`modelling/features/primary_school.py`](../../modelling/features/primary_school.py) · Feature sets `poi_amenity_v2`, `mrt_pit__poi_amenity_v2`, `primary_school`, `mrt_pit__primary_school` in [`modelling/config/feature_sets.py`](../../modelling/config/feature_sets.py)

---

## AB pack: `primary_school` (top-20 annulus counts only)

| Column | Source |
| --- | --- |
| `count_top20_schools_within_1km` | `query_radius` count on `pois["top_20"]` at 1000 m |
| `count_top20_schools_within_1km_2km` | count at 2000 m minus count at 1000 m (non-negative) |

Does **not** register `dist_nearest_top20_school`. Compare against `poi_amenity_v2` (all-primary + hawker + mall) or `poi_distancing` (full 20-col stack). **`hdb_poi_features`** still stores legacy 0/1 `within_1km_*` top-20 columns for `poi_distancing` / amenity blend paths only — not used by this AB pack.

---

## Shipped (Phase 1)

Seven numeric features from existing `poi_locations` types (`school_any`, `market`, `mall`), keyed off transaction `lat`/`lon`:

| Column | Source |
| --- | --- |
| `dist_nearest_primary_school` | BallTree on all-primary schools; blended from `hdb_poi_features.dist_nearest_any_school` when training with `use_db=True` and a matching `enriched_addr_id` row exists |
| `is_within_1km_primary_school` | `dist <= 1000` or `within_1km_any_pri_school` from `hdb_poi_features` |
| `is_within_2km_primary_school` | `dist <= 2000` — **not** the legacy `(1 km, 2 km]` band — or derived from `within_1km_any_pri_school OR within_1km_2km_pri_school` when blending |
| `dist_nearest_hawker` | BallTree on `market` (NEA hawker / food centre centroids) |
| `hawker_count_within_1km` | Radius count at 1000 m |
| `dist_nearest_mall` | BallTree; blended from `hdb_poi_features.dist_nearest_mall` when present |
| `mall_count_within_1_5km` | Radius count at 1500 m — **always** computed in Python (not stored in `hdb_poi_features` today) |

**Why blend `hdb_poi_features`:** The table is populated by [`backend/scripts/build_poi_features.py`](../../backend/scripts/build_poi_features.py) with the same BallTree logic as legacy `append_poi_features`, but avoids recomputing school/mall distances for every training row when Postgres already holds them. Hawker metrics and the 1.5 km mall count are not pre-materialised in that table.

---

## Deferred features (recommended suite gaps)

| Recommendation | Blocked by | Suggested source |
| --- | --- | --- |
| `phase_2c_balloting_ratio_nearest` | No ballot ratio in repo | MOE P1 registration statistics (Phase 2C applicants ÷ vacancies), keyed to school |
| `nearest_school_has_sec_affiliation` | No affiliation flags | MOE school directory / curated CSV |
| `within_1km_{EliteSchool}` one-hots | Selection rule + stable coordinates | Resale density analysis (≥150 txs within 1 km); see Phase 3 |
| `nearest_mall_size_tier` | Mall CSV is point-only today | Manual tier CSV or URA / landlord GFA keyed by mall name |

---

## Future Phase 2 — metadata sidecar

- Add `poi_metadata` (or JSONB on `poi_locations`) for ballot ratio, affiliation, mall tier / GFA.
- New ingest script e.g. `backend/scripts/ingest_poi_metadata.py`.
- Join on nearest `school_any` / `mall` name from BallTree (store nearest-name column internally when implementing).

**PIT note:** Ballot ratios vary by registration year; strict transaction-PIT joins need `ratio_at(tx_year)` — static “latest ratio” carries leakage similar to current POI snapshots (see [ADR 001](../adr/001-poi-ingestion.md)).

---

## Future Phase 3 — elite school one-hots

- Runner `modelling/runners/select_elite_school_onehots.py` scanning resale × school geometry.
- Emit `modelling/config/elite_school_onehots.yml` for approved slugs only.

---

## Future Phase 4 — evaluation and precompute

- Experiments: `xgboost__mrt_poi_amenity_v2` vs `xgboost__mrt_poi` (legacy Colab stack).
- Optionally extend `hdb_poi_features` + `build_poi_features.py` with hawker distance, `mall_count_within_1_5km`, and v2-only columns to speed Modal runs.

---

## Known limitations

- **Static POI snapshot:** Unless `valid_from` / `valid_to` on `poi_locations` are populated, long panels see modern geometry for old transactions.
- **NEA hawker geometry:** Polygon → centroid; walking distance is approximate vs front-door routing.
- **Collinearity:** `poi_amenity_v2` overlaps partially with legacy `poi_distancing` school/mall columns — run ablations rather than stacking both blindly.

---

## Revision history

| Date | Change |
| --- | --- |
| 2026-05-19 | Phase 1 shipped + `hdb_poi_features` blend documented |
