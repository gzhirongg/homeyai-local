# System Design

> Last updated: 2026-03-18

## 1. Overview

HomeyAI is an AI-powered real estate valuation platform for Singapore's residential market. It combines historical transaction data, geospatial analysis, and machine learning to predict property prices with explainable reasoning.

The system follows a three-layer architecture: a **data layer** (PostgreSQL + MinIO), a **model layer** (ML training and inference), and an **application layer** (FastAPI backend + Next.js frontend). All services run as Docker containers on an Oracle Cloud VM, with developer access via Tailscale VPN.

---

## 2. Architecture Diagram

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Oracle Cloud VM                                 │
│                  Tailscale IP: REMOTE_VM_IP (.env)                       │
│                                                                        │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────────────┐│
│  │   Frontend    │  │   Backend    │  │    Data Layer                 ││
│  │   Next.js     │──│   FastAPI    │──│                               ││
│  │   Port 3000   │  │   Port 8000  │  │  PostgreSQL    MinIO          ││
│  └──────────────┘  └──────┬───────┘  │  (PostGIS)     (S3)           ││
│                           │          │  Port 5432     Port 9000       ││
│                           │          │  Port 5433     Port 9001       ││
│                           │          │  (dev DB)      (console)       ││
│                           │          └───────────────────────────────┘│
│                           │                                            │
│                    ┌──────┴───────┐  ┌───────────────────────────────┐│
│                    │  ML Models   │  │  Prefect (Orchestration)      ││
│                    │ (MinIO:models│  │  Prod:  Port 4200             ││
│                    │  /prod /dev) │  │  Dev:   Port 4201             ││
│                    └──────────────┘  └───────────────────────────────┘│
└────────────────────────────────────────────────────────────────────────┘
         ▲                    ▲
         │ Tailscale VPN      │ Tailscale VPN
    ┌────┴────┐          ┌────┴────┐
    │ Dev Mac │          │ Dev Mac │
    │ (Mode C)│          │ (Mode B)│
    └─────────┘          └─────────┘
```

---

## 3. Tech Stack

### Frontend
| Technology | Version | Purpose |
|------------|---------|---------|
| Next.js | 16.1.6 | React framework with App Router |
| React | 19.2.3 | UI library |
| Tailwind CSS | 4.x | Utility-first CSS |
| Leaflet + React-Leaflet | latest | Interactive maps and geospatial overlays |
| Recharts | latest | Data visualisation charts |
| Framer Motion | 12.x | Animations |
| Lucide React | latest | Icon library |

### Backend
| Technology | Version | Purpose |
|------------|---------|---------|
| Python | 3.11 | Runtime |
| FastAPI | latest | REST API framework |
| SQLAlchemy | latest | ORM and database toolkit |
| Uvicorn | latest | ASGI server |
| Alembic | latest | Database migrations |
| Minio (Python SDK) | latest | Object storage client |
| Pandas + PyArrow | latest | Data processing and parquet I/O |

### Database and Storage
| Technology | Version | Purpose |
|------------|---------|---------|
| PostgreSQL + PostGIS | 15 + 3.3 | Relational DB with geospatial extensions |
| MinIO | latest | S3-compatible object storage for datasets and ML models |

### Infrastructure
| Technology | Purpose |
|------------|---------|
| Oracle Cloud VM | Hosting (ARM-based compute) |
| Docker Compose | Container orchestration |
| Tailscale VPN | Secure developer access to VM services |
| Prefect 3 | Workflow / pipeline orchestration |
| GitHub Actions | CI pipeline (lint, test, build, migration check) |

---

## 4. Data Architecture

The system uses a hybrid storage architecture where PostgreSQL serves as the real-time query layer for the web application, and MinIO stores large datasets and ML artifacts.

### PostgreSQL (Serving Layer)

All data that the web application queries directly lives in PostgreSQL with PostGIS:

| Table | Purpose | Approximate Size |
|-------|---------|-----------------|
| `users` | User accounts, roles, subscription state | Small (< 1000 rows) |
| `saved_properties` | User-saved valuations | Small |
| `hdb_resale_transactions` | Historical HDB resale data (1990-present) | ~960,000 rows |
| `hdb_buildings` | PostGIS geometry table for HDB building footprints | ~12,000 rows |

### MinIO (Object Storage)

MinIO provides centralised, versioned storage for data pipeline assets and ML model artifacts:

**Bucket: `datasets`**
| Path | Content | Purpose |
|------|---------|---------|
| `raw/hdb_resale/` | Original CSV files from Data.gov.sg | Immutable raw data archive |
| `raw/ura/` | URA API response dumps | Raw private property data |
| `raw/scraped/` | Web-scraped datasets (future) | Additional training data |
| `processed/` | Cleaned parquet files (e.g. `hdb_resale_full.parquet`) | Feature-engineered training datasets |

**Bucket: `models`**
| Path | Content | Purpose |
|------|---------|---------|
| `prod/` | Production model artifacts (pkl, scalers, SHAP explainers) | Loaded by FastAPI for live inference |
| `dev/` | Experimental/testing model artifacts | Developers test new models here |

### Data Flow

```
External Sources                     MinIO                        PostgreSQL
─────────────────                    ─────                        ──────────
Data.gov.sg CSVs  ──upload──▶  datasets/raw/hdb_resale/
                                        │
                                   processing
                                        │
                                        ▼
                               datasets/processed/    ──ingest──▶  hdb_resale_transactions
                               (parquet files)                     (serving layer)

ML Training reads from ◀── datasets/processed/
ML Training writes to  ──▶ models/prod/ or models/dev/

FastAPI loads models from ◀── models/prod/
```

---

## 5. Database Schema

### users
| Column | Type | Constraints |
|--------|------|------------|
| id | Integer | Primary key, auto-increment |
| email | String | Unique, indexed |
| hashed_password | String | bcrypt hash |
| full_name | String | |
| role | String | One of: guest, free, premium, admin |
| remaining_valuations | Integer | Default 3 |

### saved_properties
| Column | Type | Constraints |
|--------|------|------------|
| id | Integer | Primary key, auto-increment |
| user_id | Integer | Indexed (references users.id) |
| postal_code | String | |
| property_type | String | HDB, Condo, or Landed |
| predicted_price | Integer | |
| created_at | String | ISO 8601 timestamp |

### hdb_resale_transactions
| Column | Type | Constraints |
|--------|------|------------|
| id | Integer | Primary key, auto-increment |
| month | String | YYYY-MM, indexed |
| town | String | Indexed |
| flat_type | String | e.g. "3 ROOM", "4 ROOM" |
| block | String | |
| street_name | String | |
| storey_range | String | e.g. "07 TO 09" |
| floor_area_sqm | Integer | |
| flat_model | String | |
| lease_commence_date | Integer | Year |
| remaining_lease_years | Integer | Nullable; years remaining on 99-year lease at transaction month |
| resale_price | Integer | |

### hdb_buildings (PostGIS)
Defined in [models.py](file:///c:/Users/offic/Desktop/CSIT321-FYP-PredictingHomePrices/backend/models.py#L262-L283). Contains building footprint geometries for map rendering.

| Column | Type | Constraints | Description |
|--------|------|------------|-------------|
| id | Integer | Primary key, auto-increment | Internal unique building ID |
| objectid | Integer | Nullable | OneMap original object ID |
| blk_no | String(20) | Nullable | Block number (e.g., "123") |
| st_cod | String(20) | Nullable | OneMap street code |
| entityid | Integer | Nullable | Unique entity ID |
| postal_cod | String(10) | Nullable, Indexed | 6-digit postal code |
| inc_crc | String(20) | Nullable | Ingestion verification code |
| fmel_upd_d | String(20) | Nullable | Update date string |
| shape_area | Float | Nullable, Indexed | Footprint area in sqm |
| shape_len | Float | Nullable | Footprint perimeter length |
| geom | Geometry(GEOMETRY, 4326) | Nullable, GIST index (`idx_hdb_buildings_geom`) | PostGIS polygon/geometry footprint |

### poi_locations (PostGIS)
Defined in migration [c2d3e4f5a6b7_add_poi_tables.py](file:///c:/Users/offic/Desktop/CSIT321-FYP-PredictingHomePrices/backend/alembic/versions/c2d3e4f5a6b7_add_poi_tables.py#L24-L36). Represents points of interest (schools, malls, parks) ingested from various sources.

| Column | Type | Constraints | Description |
|--------|------|------------|-------------|
| id | Integer | Primary key, auto-increment | Unique identifier |
| poi_type | String(32) | NOT NULL, Indexed | POI category (e.g. school, mall, supermarket, park) |
| name | Text | Nullable | Canonical name of the POI |
| lat | Double Precision | NOT NULL | Latitude (WGS 84) |
| lon | Double Precision | NOT NULL | Longitude (WGS 84) |
| valid_from | Date | Nullable | Validity window start |
| valid_to | Date | Nullable | Validity window end |
| source_file | String(128) | NOT NULL | Name of source data file |
| ingested_at | Timestamptz | NOT NULL, DEFAULT NOW() | Timestamp of record ingestion |

*Indexes:*
- `idx_poi_locations_type` on `poi_type`
- `idx_poi_locations_geom` using GIST on `ST_SetSRID(ST_MakePoint(lon, lat), 4326)`

### hdb_poi_features
Defined in migration [c2d3e4f5a6b7_add_poi_tables.py](file:///c:/Users/offic/Desktop/CSIT321-FYP-PredictingHomePrices/backend/alembic/versions/c2d3e4f5a6b7_add_poi_tables.py#L52-L77). Contains precomputed distances and counts of POIs around HDB address locations.

| Column | Type | Constraints | Description |
|--------|------|------------|-------------|
| hdb_addr_id | Integer | Primary key, FK references `hdb_address_enrichment_onemap(id)` ON DELETE CASCADE | Enrichment address key |
| dist_cbd | Real | Nullable | Distance to Central Business District in meters |
| dist_airport | Real | Nullable | Distance to Changi Airport in meters |
| dist_nearest_top20_school | Real | Nullable | Distance to nearest Top-20 primary school in meters |
| dist_nearest_any_school | Real | Nullable | Distance to nearest primary school in meters |
| within_1km_top20_school | Smallint | Nullable | Count of Top-20 primary schools within 1km |
| within_1km_2km_top20_school | Smallint | Nullable | Count of Top-20 primary schools between 1km and 2km |
| within_1km_any_pri_school | Smallint | Nullable | Count of primary schools within 1km |
| within_1km_2km_pri_school | Smallint | Nullable | Count of primary schools between 1km and 2km |
| dist_nearest_mall | Real | Nullable | Distance to the nearest shopping mall in meters |
| malls_within_2km | Smallint | Nullable | Count of malls within 2km |
| supermarkets_within_500m | Smallint | Nullable | Count of supermarkets within 500m |
| markets_within_500m | Smallint | Nullable | Count of wet markets/hawkers within 500m |
| dist_nearest_park | Real | Nullable | Distance to the nearest park in meters |
| is_park_200m | Smallint | Nullable | Indicator (1/0) if a park is within 200m |
| dist_nearest_pcn | Real | Nullable | Distance to the nearest Park Connector Network route in meters |
| gravity_malls | Real | Nullable | Gravity accessibility score for shopping malls |
| gravity_schools | Real | Nullable | Gravity accessibility score for primary schools |
| gravity_parks | Real | Nullable | Gravity accessibility score for parks |
| gravity_markets | Real | Nullable | Gravity accessibility score for markets |
| computed_at | Timestamptz | NOT NULL, DEFAULT NOW() | Precomputation execution timestamp |

### mrt_physical_stations (PostGIS)
Defined in [models.py](file:///c:/Users/offic/Desktop/CSIT321-FYP-PredictingHomePrices/backend/models.py#L186-L199) and migration [f1a2b3c4d5e6_split_mrt_physical_station.py](file:///c:/Users/offic/Desktop/CSIT321-FYP-PredictingHomePrices/backend/alembic/versions/f1a2b3c4d5e6_split_mrt_physical_station.py#L45-L56). Represents geographic MRT station footprints.

| Column | Type | Constraints | Description |
|--------|------|------------|-------------|
| id | Integer | Primary key, auto-increment | Unique identifier |
| canonical_name | String(255) | NOT NULL, UNIQUE, Indexed | Capitalized name (e.g. "DHOBY GHAUT") |
| lat | Double Precision | Nullable | Center latitude |
| long | Double Precision | Nullable | Center longitude |
| geom | Geometry(POINT, 4326) | Nullable, GIST index (`idx_mrt_physical_stations_geom`) | Geographic point of station footprint centroid |
| is_interchange | Boolean | NOT NULL, DEFAULT FALSE | True if the station serves multiple lines |

### mrt_station_lines
Defined in [models.py](file:///c:/Users/offic/Desktop/CSIT321-FYP-PredictingHomePrices/backend/models.py#L201-L238) and migration [f1a2b3c4d5e6_split_mrt_physical_station.py](file:///c:/Users/offic/Desktop/CSIT321-FYP-PredictingHomePrices/backend/alembic/versions/f1a2b3c4d5e6_split_mrt_physical_station.py#L75-L102). Links a physical station to its line-specific network variations and timeline data.

| Column | Type | Constraints | Description |
|--------|------|------------|-------------|
| id | Integer | Primary key, generated by default | Unique identifier |
| physical_station_id | Integer | NOT NULL, FK references `mrt_physical_stations(id)` ON DELETE CASCADE | Parent geographic station |
| network_line | String(255) | NOT NULL | Abbreviated network line (e.g. "North South Line") |
| subproject_or_stage | String(255) | Nullable | Phase or extension description (e.g., "Stage 1") |
| station_code | String(50) | NOT NULL, UNIQUE | Station code prefix and number (e.g., "NS24", "NE6") |
| station_name | String(255) | NOT NULL, Indexed | Local spelling variant of station |
| station_status | String(50) | Nullable | Operational status (e.g., "active", "planned") |
| derived_state | String(24) | Nullable, Indexed | Derived state (e.g., "operational", "under_construction") |
| opening_date_confidence | String(16) | Nullable | Timeline confidence level |
| working_name_flag | String(50) | Nullable | Flag indicating if name is placeholder |
| code_source_type | String(100) | Nullable | Origin of station code data |
| announcement_date_raw | String(255) | Nullable | Raw announcement date |
| announcement_date | Date | Nullable, Indexed | Standardized announcement date |
| expected_completion_raw | String(255) | Nullable | Raw expected completion timeline |
| expected_completion | Date | Nullable | Standardized expected completion date |
| opening_date_raw | String(255) | Nullable | Raw opening date string |
| opening_date | Date | Nullable, Indexed | Standardized operational opening date |
| dates_source_type | String(100) | Nullable | Reference origin of dates |
| phase2_review_priority | String(50) | Nullable | Phase 2 Review priority rating |
| source_url | Text | Nullable | Reference link |
| source_note | Text | Nullable | Operational notes |
| search_term | String(255) | Nullable | Search string utilized for OneMap resolution |
| found | Integer | Nullable | Flag if geographic location lookup succeeded |
| api_response | Text | Nullable | JSON string payload from OneMap lookup |

### hdb_mrt_routes
Defined in [models.py](file:///c:/Users/offic/Desktop/CSIT321-FYP-PredictingHomePrices/backend/models.py#L101-L143) and migration [d3e5f7a9b1c2_hdb_mrt_routes_physical_station_fk.py](file:///c:/Users/offic/Desktop/CSIT321-FYP-PredictingHomePrices/backend/alembic/versions/d3e5f7a9b1c2_hdb_mrt_routes_physical_station_fk.py#L69-L89). Precalculated routing distances and travel durations from HDB addresses to MRT physical stations.

| Column | Type | Constraints | Description |
|--------|------|------------|-------------|
| hdb_addr_id | Integer | Primary key, FK references `hdb_address_enrichment_onemap(id)` ON DELETE CASCADE | Reference address |
| physical_station_id | Integer | Primary key, FK references `mrt_physical_stations(id)` ON DELETE CASCADE | Target physical station |
| haversine_distance_m | Float | Nullable | Straight-line distance in meters |
| walk_distance_m | Integer | Nullable | Routing walking distance in meters |
| walk_time_mins | Integer | Nullable | Routing walking duration in minutes |
| raw_walk_response | Text | Nullable | Raw JSON response payload of walk route from router |
| drive_distance_m | Integer | Nullable | Driving distance in meters |
| drive_time_mins | Integer | Nullable | Driving duration in minutes |
| raw_drive_response | Text | Nullable | Raw JSON response payload of drive route from router |
| pt_distance_m | Integer | Nullable | Public transit distance in meters |
| pt_time_mins | Integer | Nullable | Public transit duration in minutes |
| raw_pt_response | Text | Nullable | Raw JSON response payload of public transit route |
| updated_at | DateTime | DEFAULT CURRENT_TIMESTAMP | Date modified |

### hdb_mrt_features_pit_snapshot
Defined in migration [e8f1a2b3c4d5_mrt_temporal_state_and_pit_snapshot.py](file:///c:/Users/offic/Desktop/CSIT321-FYP-PredictingHomePrices/backend/alembic/versions/e8f1a2b3c4d5_mrt_temporal_state_and_pit_snapshot.py#L43-L62). Precomputed historical snapshot of MRT features for a given address at a specific point in time (transaction month). Used for training and testing ML models without data leakage.

| Column | Type | Constraints | Description |
|--------|------|------------|-------------|
| hdb_addr_id | Integer | Primary key | Reference address id |
| tx_year_month | String(7) | Primary key, Indexed | Transaction month formatted as YYYY-MM |
| dist_to_nearest_op_mrt | Double Precision | Nullable | Distance in meters to nearest operational MRT station at this month |
| travel_time_to_active_mrt | Integer | Nullable | Travel time in minutes to nearest active MRT station at this month |
| pt_time_savings_vs_walk | Double Precision | Nullable | Time saved using public transit versus walking to the nearest active MRT |
| line_connectivity_index | Integer | Nullable | Number of active lines at nearest station |
| nearest_op_lines | Text[] | Nullable | Active MRT lines serving the nearest operational station at this month |
| days_since_mrt_announcement | Double Precision | Nullable | Days elapsed since the nearest station was announced, or negative if unannounced |
| days_to_mrt_opening | Double Precision | Nullable | Days remaining until the nearest station opens, or negative if already open |
| speculative_upside_score | Double Precision | Nullable | Weighted score indicating proximity to upcoming lines |
| has_future_upside | Integer | Nullable | Binary flag indicating if there is a planned station nearby (within 1km) |
| nearest_planned_lines | Text[] | Nullable | Codes/Names of planned MRT lines within 1km |
| is_proximity_nuisance | Integer | Nullable | Binary flag indicating if active station is closer than 150m (noise/vibration) |
| computed_at | Timestamptz | DEFAULT NOW() | Precomputation execution timestamp |

---

## 6. API Surface

See [API Endpoints Reference](../reference/api-endpoints.md) for the full list. Summary:

| Category | Endpoints | Auth |
|----------|-----------|------|
| Public | `POST /api/register`, `POST /api/login`, `GET /` | None |
| Valuation | `POST /api/valuation` | None (rate limited by role) |
| Geospatial | `POST /api/geospatial/nearby_mrts`, `GET /api/geospatial/area_amenity_breakdown`, `GET /api/geospatial/hdb_buildings` | None |
| Analytics | `GET /api/analytics/summary`, `GET /api/analytics/district/{name}` | None |
| User | `GET/POST/DELETE /api/user/saved-properties`, `GET/PUT/DELETE /api/user/profile` | JWT |
| Admin | `GET /api/admin/users`, `GET /api/admin/data-catalog`, `POST /api/admin/data-query`, `GET /api/health` | JWT + Admin role |
| System | `GET /api/version` | None |

---

## 7. Frontend Pages

| Route | Access | Description |
|-------|--------|-------------|
| `/` | Public | Landing page with product features |
| `/login` | Public | Login form |
| `/register` | Public | Registration form |
| `/dashboard` | Authenticated | User dashboard with summary charts |
| `/valuation` | Authenticated | Property valuation input form |
| `/valuation-report` | Authenticated | Detailed valuation results with map, charts, SHAP |
| `/saved-properties` | Authenticated | List of saved valuations |
| `/calculators` | Authenticated | Mortgage and profit calculators |
| `/profile` | Authenticated | User profile management |
| `/admin` | Admin | Admin dashboard |
| `/admin/health` | Admin | System health monitor |
| `/admin/data-catalog` | Admin | Database and MinIO data browser |

---

## 8. Infrastructure and Networking

See [Infrastructure](infrastructure.md) for full details. Key facts:

- **VM:** Oracle Cloud (ARM); set **`REMOTE_VM_IP`** in `.env` to the address you use for that VM (Tailscale or public—or the same hostname for both stacks if you unify routing).
- **Developer access:** Tailscale VPN — no SSH tunnels, no public ports for databases
- **Port map:**

| Service | Port | Access |
|---------|------|--------|
| Frontend (Next.js) | 3000 | Public via VM IP |
| Backend (FastAPI) | 8000 | Public via VM IP |
| Production PostgreSQL | 5432 | Tailscale only |
| Development PostgreSQL | 5433 | Tailscale only |
| MinIO API | 9000 | Tailscale only |
| MinIO Console | 9001 | Tailscale only |

---

## 9. Security Model

### Authentication
- JWT tokens issued on login, required for protected endpoints
- Passwords hashed with bcrypt via passlib
- Token includes user ID and role, validated on each request

### Authorisation
- Role-based access: `guest`, `free`, `premium`, `admin`
- Admin endpoints check `current_user.role == UserRole.ADMIN`
- Free users have rate-limited valuations (`remaining_valuations` counter)

### Network Security
- Databases and MinIO are NOT exposed on the public internet
- Access is restricted to the Tailscale VPN (invite-only network)
- CORS configured to allow known origins only
- The application frontend/backend are the only public-facing services

---

## 10. Dev/Prod Environment Separation

The system runs two isolated database environments on the same VM:

| Environment | Database | Port | MinIO Folder | Purpose |
|-------------|----------|------|-------------|---------|
| Production | `real_estate_db` | 5432 | `models/prod/` | Live application serving real users |
| Development | `real_estate_dev_db` | 5433 | `models/dev/` | Developer testing, migration experiments |

Developers connect to the dev environment by default (Mode C in `.env`). Production data is never modified during development. See the [Developer Manual](../guides/developer-manual.md) for rules on environment usage.

### Promotion Workflow

```
Dev DB (test migration) → PR (CI validates) → Merge → Deploy script → Prod DB (alembic upgrade)
```
