# Geospatial analytics (KM)

Operational reference for the **Analytics** explorer: how address vs area modes are triggered, which tables are queried, and known limitations.

## Two analytics scenarios

### 1. Deterministic address (point)

**Frontend gating**

- Runs when **either**:
  - `property_name` is set (length ≥ 2), typically from property search pick, **or**
  - `postal_code` contains exactly **6 digits** (non-digit characters stripped), e.g. `058357`.
- Partial postals (e.g. `058`) do **not** trigger calls.

**Backend**

- Resolves one row in `hdb_address_enrichment_onemap` via `_resolve_enrichment_for_amenity` (see `backend/main.py`).
- **No user-supplied lat/lon** — coordinates come only from enrichment.
- If the row has no `latitude` / `longitude`, APIs return HTTP **200** with:
  - `no_coordinates: true`
  - `message`: *Geographical Analysis Unavailable: No Lat-long*  
  (not a generic 404 for missing coordinates on `amenity_score` / `pois_nearby`.)

**MRT (two-pass)**

1. **Pass 1 — physical radius:** `mrt_station_lines` joined to `mrt_physical_stations`, filtered with `ST_DWithin` on station geometry vs the address point. Default radius **2 km** (`radius_km` query param on `GET /api/geospatial/amenity_score`, bounds 0.25–15).
2. **Pass 2 — routing:** `LEFT JOIN hdb_mrt_routes` on `(physical_station_id, hdb_addr_id)` to attach pre-computed walk/drive/PT distance and time where the ingest pipeline populated them. Stations inside radius but without a route row still appear; routing fields are null.

**POI near address**

- `POST /api/geospatial/pois_nearby` uses `poi_locations` with `ST_DWithin` around the resolved point (same deterministic input rules and `no_coordinates` behaviour). Returns lists and counts within radius (no headline accessibility composite).

**Geospatial bundle (`amenity_score` payload — name is historical)**

- Returns **`mrt`** (operational / upcoming within radius) and a short **`amenities`** list (illustrative school/park/mosque rows derived from nearby `poi_locations`). **Not** the same dataset as `pois_nearby`. The analytics UI treats verified POIs as the source of truth for “Places”.

**Trigger**

- User selects **URA region** and/or one or more **towns** (planning area names aligned with `pln_area_n` in `ura_mp19_planning_areas_no_sea`).

**Backend**

- `GET /api/geospatial/area_amenity_breakdown?region_c=...&towns=...`
- **MRT:** `list_mrts_in_planning_union` — `ST_Within` physical station geometry inside the union of matching planning polygons (same filter semantics as `mrt_in_planning_areas`).
- **POIs:** `list_pois_in_planning_union` — points from `poi_locations` with `ST_Within(ST_MakePoint(lon, lat), union)`. Types: `school_top20`, `school_any`, `mall`, `supermarket`, `park`, `market`, `pcn`.
- **PCN density:** connector vertices can be very numerous; the API caps the **returned list** of PCN points while `counts_by_type.pcn` reflects counts within the server row cap (see `row_truncated` / `pcn_capped` in the JSON payload).

**Deprecated**

- `POST /api/geospatial/area_insights` returns **410 Gone** (was synthetic POC). Clients must use `area_amenity_breakdown`.

## Smoke tests (PostGIS environment)

With API base URL set (e.g. local backend):

```bash
# Address — 6-digit postal
curl -s "$API/api/geospatial/amenity_score?postal_code=058357" | jq .

# Address — property name
curl -s "$API/api/geospatial/amenity_score?property_name=34+UPPER+CROSS+STREET" | jq .

# Area
curl -s "$API/api/geospatial/area_amenity_breakdown?towns=BUKIT+MERAH" | jq .
```

Automated tests in `backend/tests/test_main.py` cover **400** validation and **410** deprecation without requiring PostGIS (SQLite test harness).
