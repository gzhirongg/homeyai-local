# Glossary: HDB resale, URA planning geography, and spatial data

Singapore housing and planning data reuse similar words (**town**, **region**, **district**, **area**) in different official systems. This glossary separates meanings and notes how they show up in HomeyAI.

---

## How the systems relate (one paragraph)

**HDB** publishes resale transactions with a **`town`** field (a small, fixed set of labels, some merged or coarse). **URA** publishes **Master Plan** layers with **five regions** and **55 planning areas** (polygons). Names often align (e.g. `BEDOK`), but HDB also uses labels like **CENTRAL AREA** and **KALLANG/WHAMPOA** that do not match a single URA planning-area name. Spatial joins (point-in-polygon) resolve mismatches that string equality cannot.

---

## HDB resale (transaction dataset)

| Term | Meaning |
|------|--------|
| **Town** | Column on resale records: the HDB administrative/market bucket for the flat. Used in HomeyAI as the main analytics filter (`hdb_resale_transactions.town`). Values are uppercase strings (e.g. `TAMPINES`, `CENTRAL AREA`). |
| **Central Area** | HDB **town** label for many flats in the central core. **Not** a URA planning-area name; spans multiple URA planning polygons. |
| **Kallang/Whampoa** | HDB **town** label combining Kallang and Whampoa sub-markets. **Not** equal to URA `PLN_AREA_N` `KALLANG` alone (slash and pairing differ). |
| **Block** | HDB block number on the transaction; with street, identifies a project. |
| **Street name** | Road name for the block; used with block in listings and analytics. |
| **Postal code** | Singapore postal code when present; can be used to geocode for spatial joins. |
| **Building contract town (`bldg_contract_town`)** | Three-letter code on HDB **Property Information** blocks (often aligned with URA planning-area short codes); maps to the full resale **Town** label (e.g. `BD`→`BEDOK`). See **`hdb_contract_town_map`** / [`docs/knowledge/hdb-property-information.md`](../knowledge/hdb-property-information.md). |
| **`blk_street` / `block_street`** | Canonical block + normalised street string mirroring OneMap **`query_sent`**. Persisted as `blk_street` on **`hdb_property_information`** and (when populated) **`block_street`** on resale rows. |
| **Flat type** | HDB category (e.g. `3 ROOM`, `4 ROOM`, `EXECUTIVE`). Distinct from geography. |
| **Resale price / floor area** | Transaction economics; **PSF** (price per square foot) is often derived from price and area. |

---

## URA Master Plan 2019 (MP2019) geography

| Term | Meaning |
|------|--------|
| **Master Plan 2019** | Statutory land-use plan cycle; GIS layers are often labelled MP19 or similar. |
| **Region (URA)** | One of **five** macro areas: Central, East, North, North-East, West. In GeoJSON attributes: `REGION_N` (full name, e.g. `EAST REGION`), `REGION_C` (code: `CR`, `ER`, `NR`, `NER`, `WR`). |
| **Planning area** | One of **55** polygons covering mainland Singapore (land / “no sea” variants exclude offshore sea). Each has `PLN_AREA_N` (name) and `PLN_AREA_C` (short code). Often comparable to **HDB town** where names match. |
| **PLN_AREA_N** | URA attribute: planning area **name** (e.g. `BEDOK`, `DOWNTOWN CORE`). Primary key for name-based joins to HDB `town` when strings align. |
| **PLN_AREA_C** | URA attribute: planning area **code** (e.g. `BD` for Bedok). Stable for APIs and DB keys. |
| **Region boundary (no sea)** | Polygon layer with **five** features (multi-part geometries possible). Dataset name pattern: *Master Plan 2019 Region Boundary (No Sea)*. |
| **Planning area boundary (no sea)** | Polygon layer with **55** features. Dataset file example: `MasterPlan2019PlanningAreaBoundaryNoSea.geojson`. |
| **CA_IND** | Flag on some URA planning-area features (e.g. conservation-related); not an HDB field. |

---

## Geodata and coordinates

| Term | Meaning |
|------|--------|
| **GeoJSON** | JSON format for vector features. HomeyAI stores raw MP2019 layers in MinIO as `.geojson`. |
| **FeatureCollection** | GeoJSON root type: a list of **features**, each with `geometry` + `properties`. |
| **Polygon / MultiPolygon** | Geometry types for areas; Singapore layers use both. Coordinates are usually **longitude, latitude** in decimal degrees. |
| **EPSG:4326** | WGS 84 (GPS) CRS. Typical for GeoJSON used in web maps (Leaflet/MapLibre) and for `geometry(..., 4326)` in PostGIS. |
| **PostGIS** | PostgreSQL extension for spatial types and queries (`ST_Contains`, `ST_Intersects`, GIST indexes). |
| **Point-in-polygon** | Spatial test: whether a building or postal centroid falls inside a planning polygon; used when **town** text ≠ **PLN_AREA_N**. |

---

## HomeyAI codebase and infrastructure

| Term | Meaning |
|------|--------|
| **District** | **Ambiguous.** In analytics code, “district” sometimes means **HDB town** (e.g. `get_district_analytics(district_name)` filters on `town`). In UI copy it may mean “area” generically—check the API field actually used. |
| **`/api/analytics/filters`** | Returns distinct **towns** and flat types from the DB for dashboard filters. |
| **`query_transactions` (towns=…)** | Filters `HdbResaleTransaction.town` with uppercase town strings. |
| **MinIO `datasets` bucket** | Object storage for raw/processed datasets; canonical raw prefix for datagov-style uploads: `raw/datagovsg/…`. |
| **`hdb_buildings` / `mrt_station_exits`** | PostGIS tables for building footprints and MRT exits; used for **geospatial** features, not for HDB town enumeration. |

---

## Join and mapping concepts

| Term | Meaning |
|------|--------|
| **Exact name match** | `UPPER(TRIM(hdb.town)) = UPPER(TRIM(ura.PLN_AREA_N))`. Works for most heartland towns; fails for **CENTRAL AREA**, **KALLANG/WHAMPOA**, and all HDB towns that aggregate several planning areas. |
| **Aggregate town** | One HDB **town** label covering multiple URA planning areas (e.g. central core under **CENTRAL AREA**). |
| **Orphan planning area (name join)** | A `PLN_AREA_N` with no rows where `town` equals that string—often CBD/industrial/water, or areas rolled into a broader HDB town. |
| **Roll-up** | Aggregating statistics from planning areas to **URA regions** using `REGION_N` / `REGION_C` on planning-area features, or from towns to custom groupings. |

---

## Related reading

- Correlation of resale **town** vs **PLN_AREA_N** (matches and discrepancies): local notes under `experimental/masterplan2019_minio/TOWN_PLANNING_CORRELATION.md` (folder may be gitignored—regenerate from DB + GeoJSON if missing).
- HDB Property Information (`blk_street`, ingest): [hdb-property-information.md](../knowledge/hdb-property-information.md).
- API and env vars: [api-endpoints.md](./api-endpoints.md), [environment-variables.md](./environment-variables.md).

---

*Last updated: aligns with MP2019 “no sea” GeoJSON naming and `hdb_resale_transactions.town` usage in the backend analytics service.*
