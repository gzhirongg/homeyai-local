-- =============================================================================
-- Grant ml_training_readonly read access to PIT MRT snapshot (and related MRT
-- tables only if you call hdb_mrt_features_at as an unprivileged invoker).
-- =============================================================================
-- Snapshot-backed training (`modelling/training_db.py` default query) needs:
--   - `hdb_mrt_features_pit_snapshot` (feature columns)
--   - `mrt_pit_build_jobs` (training gate / INNER JOIN on done months)
--   - `masterplan_revision_catalog`, `masterplan_landuse_pit_scalars`
--       (normalized Master Plan Land Use scalars; optional if you never populate them)
--   - `hdb_resale_price_index` (HDB resale price index; use when avoiding blanket `ALL TABLES`)
-- Re-run as superuser / table owner after migrations:
--
--   psql -U postgres -d real_estate_dev_db \
--     -f backend/scripts/sql/grant_ml_readonly_mrt_snapshot.sql
--
-- Adjust database name and role if needed.
-- =============================================================================

GRANT SELECT ON TABLE public.hdb_mrt_features_pit_snapshot TO ml_training_readonly;
GRANT SELECT ON TABLE public.mrt_pit_build_jobs TO ml_training_readonly;
GRANT SELECT ON TABLE public.masterplan_revision_catalog TO ml_training_readonly;
GRANT SELECT ON TABLE public.masterplan_landuse_pit_scalars TO ml_training_readonly;

-- Estate maturity panel (populate via backend/scripts/populate_* and materialize_*).
GRANT SELECT ON TABLE public.hdb_resale_town_planning_area TO ml_training_readonly;
GRANT SELECT ON TABLE public.hdb_resale_town_land_area_km2 TO ml_training_readonly;
GRANT SELECT ON TABLE public.hdb_town_completion_fy TO ml_training_readonly;
GRANT SELECT ON TABLE public.hdb_estate_maturity_by_town_month TO ml_training_readonly;

-- HDB RPI quarterly levels (`modelling/training_db.load_hdb_rpi_index_levels`).
GRANT SELECT ON TABLE public.hdb_resale_price_index TO ml_training_readonly;

-- Optional — only if you must invoke hdb_mrt_features_at() as ml_training_readonly
-- (normally prefer the snapshot table above; function body reads routing tables).
-- GRANT SELECT ON TABLE public.hdb_mrt_routes TO ml_training_readonly;
-- GRANT SELECT ON TABLE public.mrt_station_lines TO ml_training_readonly;
-- GRANT SELECT ON TABLE public.mrt_physical_stations TO ml_training_readonly;
-- Add other tables referenced inside hdb_mrt_features_at if errors mention them.
