# API Endpoints Reference

Last updated: 2026-05-13

## Public

| Method | Path | Description |
|--------|------|-------------|
| GET | / | Root welcome message |
| POST | /api/register | Register a new user (email, password, full_name) |
| POST | /api/login | Login, returns JWT token |
| GET | /api/version | App version and git commit |

## Valuation & model metrics

| Method | Path | Description |
|--------|------|-------------|
| POST | /api/valuation | Price prediction via pinned MinIO model (`VALUATION_MODEL_OBJECT_KEY`). Body: `ValuationInput` — `postal_code`, `town`, `flat_type`, `flat_model_grouped`, `region`, `storey_midpoint`, `floor_area_sqm`, `remaining_lease_years`, optional `latitude`, `longitude`, `lease_commence_year`. Query `debug_timings=true` adds `_timings` (segment ms: `wall_ms`, `feature_extras_ms`, `predict_ms`, `mrt_features_source`, etc.). **503** if model missing or prediction fails. |

**Diagnostics:** warm latency gate benchmark — `python backend/scripts/benchmark_valuation_latency.py --base-url http://localhost:8000` (pass when warm `wall_ms` ≤ 5000 ms). MRT snapshot coverage — `python backend/scripts/report_mrt_snapshot_completeness.py`.
| GET | /api/model/metrics | Experiment comparison rows + lowest-RMSE `best` from MinIO only (`models/<MODEL_ENV>/valuation/experiments/` and legacy `…/artifacts/`). Empty list when no runs exist. |
| GET | /api/model/shap_chart | PNG from `modelling/outputs/mrt_pit_features/rf_shap_bar.png` if generated (**404** otherwise). |

## Geospatial

| Method | Path | Description |
|--------|------|-------------|
| POST | /api/geospatial/nearby_mrts | Find nearest MRT stations (lat, lng) |
| GET | /api/geospatial/amenity_score | MRT stations + illustrative amenity rows for resolved postal/property (optional `radius_km`; name is historical) |
| POST | /api/geospatial/pois_nearby | POI lists and counts within radius for resolved address |
| GET | /api/geospatial/nearest_poi_per_type | Nearest named POI per type for resolved postal/property (no radius cap; `property_name` optional) |
| GET | /api/geospatial/mrt_in_planning_areas | MRT lines inside selected URA planning-area union |
| GET | /api/geospatial/area_amenity_breakdown | MRT + POI breakdown inside selected planning-area union (`region_c`, `towns`) |
| POST | /api/geospatial/area_insights | **Deprecated (410)** — use `area_amenity_breakdown` |
| GET | /api/geospatial/hdb_buildings | GeoJSON of HDB building footprints |
| GET | /api/geospatial/regions | Master Plan 2019 region polygons |
| GET | /api/geospatial/planning_areas | Planning-area polygons; optional `region` code filter |
| GET | /api/geospatial/mrt_stations | Station-line GeoJSON with physical station IDs, temporal states, and source notes; UI groups interchange markers |

Valuation responses may contain `confidence_interval_method: split_conformal_relative`,
`interval_coverage` (target), and `interval_calibration` (sample count, calibration/test
periods, observed test coverage). Metadata belongs to the active model manifest.
Legacy models retain the explicitly labelled `fixed_percentage_band` fallback.
Observed temporal coverage can be below the target; see the local feature audit.

Valuation report JSON/HTML previews and PDF downloads require premium entitlement.
Their property payload uses `floor_area_sqm`, `remaining_lease_years` and
`storey_midpoint`, matching `ValuationInput`. The default report-config endpoint
returns all six section flags. Preview section counts can differ from physical PDF
pagination. Comparables use the valuation response's recorded-sales payload.

`POST /api/ai/chat` now reuses the analytics service and returns `mode: local_data`
without a configured provider key (`openai` when configured). `confidence` is null
because a calibrated probability is not available. Local mode provides recorded
HDB statistics; it does not implement unrestricted conversational reasoning.

Address amenity responses include `mrt.unknown` separately from operational/upcoming.
Market signals return null `interest_rate_label` when rates are unavailable and
fail explicitly if RPI cannot be loaded; the client does not substitute demo data.

## Analytics

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/analytics/summary | Singapore-wide market summary |
| GET | /api/analytics/district/{district_name} | District-level analytics |
| GET | /api/analytics/properties/search | Address/name autocomplete (`q`, min 2 chars; token `ILIKE` on `query_sent`) |
| GET | /api/analytics/properties/postal_search | Postal prefix autocomplete (`postal_q`, min 2 digits) |
| POST | /api/analytics/query | Filtered resale analytics (towns, dates, `postal_code`, `property_name`, etc.) |

## Property lookup

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/properties/lookup | Resolve 6-digit postal to HDB catalogue + resale overlays (`postal_code` query param) |

## User (JWT required)

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/user/saved-properties | List saved properties |
| POST | /api/user/saved-properties | Save a new property |
| DELETE | /api/user/saved-properties/{id} | Delete a saved property |
| GET | /api/user/profile | Get current user profile |
| PUT | /api/user/profile | Update profile |
| DELETE | /api/user/profile | Delete account |

## Admin (JWT + admin role required)

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/admin/users | List all users |
| GET | /api/admin/ml/experiments | Experiment catalog from MinIO `models/<env>/valuation/experiments/<run_id>/`; `published` / `has_minio_experiment` flags vs `…/artifacts/`; optional `?env=` (default `MODEL_ENV`) |
| GET | /api/admin/ml/experiment-run-detail | Full single-run row (config, metrics, best_params) for one `run_id` from MinIO; optional `?env=` |
| GET | /api/admin/ml/runs | Run id list from MinIO `valuation/experiments` (canonical training store) |
| GET | /api/admin/dashboard | Bundled admin models UI payload; optional `?env=`; `?include=metrics,status,experiments,artifacts` (subset); `experiments_detail=false` for slim experiment rows; `debug_timings=true` adds `_timings` (ms per phase). Experiments from MinIO only; `metrics` from `/api/model/metrics` (same MinIO source). |
| GET | /api/admin/model/artifacts | List MinIO valuation `model.pkl` artifacts for `?env=` (default `MODEL_ENV`); includes manifest summary and `is_active` vs loaded model |
| GET | /api/admin/model/status | Live serving status (`is_ready`, pinned key, feature set, load error) |
| POST | /api/admin/model/promote | Body `{ "object_key": ".../model.pkl" }` — hot-reload inference and set `VALUATION_MODEL_OBJECT_KEY` in-process. Keys under **`…/valuation/experiments/<run>/model.pkl`** are copied server-side to **`…/valuation/artifacts/<run>/`** before pinning (same shape as publish-to-artifacts). |
| POST | /api/admin/model/train | Body `{ "experiment_id", "feature_set_id", "feature_selection_policy"? }` — trigger Prefect training deployment (**503** if `PREFECT_API_URL` unset) |
| POST | /api/admin/model/train/batch | Body optional `{ "experiment_ids"?, "dataset_version"?, "use_gpu"?, "max_concurrent"?, "feature_selection_policy"? }` — Prefect `homeyai-model-train-batch` (default IDs: `PERFORMANCE_PLAN_V1` when `experiment_ids` omitted). Use curated `FEATURE_SELECTION_AB_V1` from [`modelling/config/experiment_batches.py`](../../modelling/config/experiment_batches.py) for advisory vs apply comparisons; pin `dataset_version` for fairness. |
| GET | /api/admin/model/train/status/{flow_run_id} | Prefect flow-run proxy: `{ "state", "state_message" }` |
| GET | /api/admin/data-catalog | Browse PostgreSQL tables and MinIO objects |
| POST | /api/admin/data-query | Execute a sample or SQL query |
| GET | /api/health | System health check (DB, MinIO, Prefect connectivity) |

## Authentication

Endpoints marked as "JWT required" or "JWT + admin role required" require an access token in the request header. Include the token using the Bearer scheme:

```
Authorization: Bearer <token>
```

The token is obtained by calling `POST /api/login` with valid credentials. The response includes an `access_token` field. Use this token for all subsequent authenticated requests.

---

## Detailed Key Endpoint Specifications

### 1. HDB Flat Valuation (`POST /api/valuation`)

Submits historical and physical characteristics of an HDB flat to estimate its resale value using the trained machine learning model.

*   **Authentication**: Optional. If an authenticated JWT token for a **Premium** user is provided, the API enriches the response with SHAP feature contributions and neighboring property comparisons.
*   **Request Headers**:
    ```http
    Content-Type: application/json
    Authorization: Bearer <token> (Optional)
    ```

*   **Request Schema (JSON)**:
    ```json
    {
      "postal_code": "120601",
      "town": "CLEMENTI",
      "flat_type": "4 ROOM",
      "flat_model_grouped": "Model A",
      "region": "WEST",
      "storey_midpoint": 8,
      "floor_area_sqm": 92.5,
      "remaining_lease_years": 85
    }
    ```
    *   `postal_code` (string): 6-digit Singapore postal code.
    *   `town` (string): HDB town name (uppercase).
    *   `flat_type` (string): Room count category (e.g., "3 ROOM", "4 ROOM", "5 ROOM", "EXECUTIVE").
    *   `flat_model_grouped` (string): Model design group (e.g., "Model A", "Improved", "New Generation").
    *   `region` (string): Singapore region (e.g., "WEST", "EAST", "NORTH", "NORTH-EAST", "CENTRAL").
    *   `storey_midpoint` (integer): Integer midpoint of flat storey level.
    *   `floor_area_sqm` (number): Size of flat in square meters.
    *   `remaining_lease_years` (integer): Remaining lease duration in years.

*   **Response Schema (JSON) - Standard (Guest / Free User)**:
    ```json
    {
      "predicted_price": 542000.00,
      "confidence_interval": [487800.00, 596200.00],
      "amenities": {
        "mrt": "CLEMENTI MRT (0.45km)",
        "school": "Nan Hua Primary (0.3km)",
        "cbd_distance": "12.4km"
      },
      "nearby_mrt_distance": 0.45,
      "confidence_interval_method": "fixed_percentage_band"
    }
    ```

*   **Premium bonus fields**: `shap_values` (when attribution is available),
    `driver_context`, and `neighbor_comparison`. Admin preview requests may send
    `X-Homey-Preview-Role: premium`; non-admin users cannot elevate their access.

    `neighbor_comparison` uses actual rows from `hdb_resale_transactions` joined
    to validated address coordinates. It never generates sale prices or addresses
    from the model estimate.

    | Field | Meaning |
    | --- | --- |
    | `status` | `ok`, `no_matches`, or `unavailable` (e.g. missing building location) |
    | `source` | Name and URL of the HDB public resale source |
    | `criteria` | 1 km radius, last 12 calendar months through valuation month, same flat type, area ±15%, current lease ±10 years, floor-band midpoint ±6 |
    | `similar_properties` | Up to 10 recorded sales ranked by unit similarity, distance, and recency; maximum two per building |
    | `match_count` | Number of qualifying sales before limiting the displayed selection |
    | `average_neighbor_price` | Mean recorded total price across the selected sales |
    | `average_price_per_sqm` | Mean recorded price per sqm across the selected sales |
    | `market_position` | Model estimate per sqm relative to that mean, with a ±5% in-line band |
    | `price_percentile` | Percentage of selected sales whose price per sqm is at or below the estimate per sqm |

    Each comparable includes its database transaction ID, recorded address,
    postal code, sale month, floor band, area, price, price per sqm, straight-line
    distance, same-building flag, and `difference_pct`. The latter is
    `(recorded_price / model_estimate - 1) * 100`; it does not adjust historical
    sale prices for size or market timing. Example recorded row from the local data:

    ```json
    {
      "transaction_id": 230391,
      "address": "22 TEBAN GDNS RD",
      "postal_code": "600022",
      "sale_month": "2026-09",
      "storey_range": "10 TO 12",
      "flat_type": "4 ROOM",
      "flat_model": "Model A",
      "floor_area": 92,
      "price": 597000,
      "price_per_sqm": 6489.13,
      "distance_m": 117,
      "same_building": false,
      "difference_pct": 2.5
    }
    ```

    With no matching sales, `similar_properties` is empty and the summary prices,
    position, and percentile are `null`. Missing records are never replaced by
    invented comparisons. The standard price confidence band remains a ±10%
    heuristic, rather than a calibrated statistical prediction interval.

*   **Status Codes**:
    *   `200 OK`: Prediction succeeded.
    *   `400 Bad Request`: Missing or invalid input details.
    *   `422 Unprocessable Entity`: Request body failed data validation.
    *   `503 Service Unavailable`: Valuation model is unavailable or prediction failed.

---

### 2. Nearby MRT Search (`POST /api/geospatial/nearby_mrts`)

Finds all MRT lines and station checkpoints situated within a specified radius of a geographic location.

*   **Request Schema (JSON)**:
    ```json
    {
      "lat": 1.3150,
      "lng": 103.7652,
      "radius": 1.5
    }
    ```
    *   `lat` (number): Latitude coordinate (WGS84).
    *   `lng` (number): Longitude coordinate (WGS84).
    *   `radius` (number, optional): Search radius in kilometers. Defaults to `1.0`.

*   **Response Schema (JSON)**:
    ```json
    {
      "mrts": [
        {
          "id": 12,
          "name": "CLEMENTI",
          "station_code": "EW23",
          "station_status": "active",
          "distance": 0.45,
          "pit_state": "OPERATIONAL"
        },
        {
          "id": 13,
          "name": "CLEMENTI",
          "station_code": "CR17",
          "station_status": "planned",
          "distance": 0.45,
          "pit_state": "ANNOUNCED_UNDATED"
        }
      ]
    }
    ```
    *   `pit_state` (string): State value mapping to point-in-time timelines (`OPERATIONAL`, `COMMITTED_DATED`, `COMMITTED_ESTIMATED`, `ANNOUNCED_UNDATED`, `UNKNOWN`).

*   **Status Codes**:
    *   `200 OK`: Query completed.
    *   `422 Unprocessable Entity`: Latitude/Longitude missing or invalid.

---

### 3. Planning Area Amenity Breakdown (`GET /api/geospatial/area_amenity_breakdown`)

Compiles a consolidated list of MRT stations and points of interest (categorized by type) located inside a combined planning area or region polygon union.

*   **Request Query Parameters**:
    *   `region_c` (string, optional): URA Region Code (e.g., `CR` for Central, `WR` for West).
    *   `towns` (string, optional): Comma-separated string list of URA planning areas (e.g. `CLEMENTI,QUEENSTOWN`).
    *   *Note: At least one of `region_c` or `towns` must be supplied.*

*   **Response Schema (JSON)**:
    ```json
    {
      "area_names": ["CLEMENTI"],
      "region_c": null,
      "mrts": {
        "operational": [
          { "id": 12, "station_name": "CLEMENTI", "station_code": "EW23", "distance_km": 0.0 }
        ],
        "upcoming": [
          { "id": 13, "station_name": "CLEMENTI", "station_code": "CR17", "distance_km": 0.0 }
        ],
        "unknown": [],
        "count": 2
      },
      "pois": {
        "counts_by_type": {
          "school_top20": 1,
          "school_any": 4,
          "mall": 2,
          "supermarket": 8,
          "park": 10,
          "market": 6,
          "pcn": 14
        },
        "by_type": {
          "school_top20": [
            { "id": 102, "name": "NAN HUA PRIMARY SCHOOL", "lat": 1.3153, "lon": 103.7618 }
          ],
          "school_any": [ ... ],
          "mall": [ ... ],
          "supermarket": [ ... ],
          "park": [ ... ],
          "market": [ ... ],
          "pcn": [ ... ]
        },
        "pcn_capped": false,
        "poi_total": 45,
        "row_truncated": false
      }
    }
    ```

*   **Status Codes**:
    *   `200 OK`: Successfully aggregated.
    *   `400 Bad Request`: Missing both `region_c` and `towns` query parameters.

---

### 4. Pipeline Infrastructure Health Check (`GET /api/health`)

Probes the primary system dependencies of the application (PostgreSQL serving database, MinIO object store, and Prefect orchestration server) to ensure Tailscale reachability and database connection health.

*   **Authentication**: Required (**Admin** role only).
*   **Request Headers**:
    ```http
    Authorization: Bearer <token>
    ```

*   **Response Schema (JSON)**:
    ```json
    {
      "api": {
        "status": "ok",
        "message": "FastAPI backend is reachable"
      },
      "postgres": {
        "status": "ok",
        "message": "SELECT 1 succeeded — Tailscale connection is active"
      },
      "minio": {
        "status": "ok",
        "message": "Buckets accessible: models"
      },
      "prefect": {
        "status": "ok",
        "message": "Prefect API is reachable at http://100.100.100.101:4200/api"
      },
      "environment": {
        "db_host": "100.100.100.101",
        "db_port": "5432",
        "minio_endpoint": "100.100.100.101:9000",
        "prefect_api_url": "http://100.100.100.101:4200/api"
      }
    }
    ```

*   **Status Codes**:
    *   `200 OK`: Probe executed. Individual statuses inside the JSON body detail any failures (e.g. if Postgres is down, `"postgres": {"status": "error", "message": "..."}`).
    *   `401 Unauthorized`: Token missing or invalid.
    *   `403 Forbidden`: User role is not `admin`.
