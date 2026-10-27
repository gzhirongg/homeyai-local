-- =============================================================================
-- Read-only PostgreSQL role for ML / model training (HomeyAI)
-- =============================================================================
-- Run as a superuser (e.g. postgres) or a role with CREATEROLE and rights to
-- GRANT on the target database.
--
-- Replace:
--   REPLACE_WITH_STRONG_PASSWORD
--   real_estate_db          → your DB name (e.g. real_estate_dev_db for dev)
--   admin                   → your app owner role (same as ADMIN_DB_USER in .env)
--
-- Training clients: set READ_ONLY_DB_* + DB_HOST / DB_INNER_PORT / DB_NAME, or
-- DATABASE_URL_READ_ONLY only, e.g.:
--   postgresql://ml_training_readonly:SECRET@host:5432/real_estate_db
-- =============================================================================

-- -----------------------------------------------------------------------------
-- A) CLUSTER-WIDE — run once (from any database, e.g. postgres)
-- -----------------------------------------------------------------------------
CREATE ROLE ml_training_readonly WITH LOGIN PASSWORD 'REPLACE_WITH_STRONG_PASSWORD';
ALTER ROLE ml_training_readonly SET default_transaction_read_only = on;

-- -----------------------------------------------------------------------------
-- B) PER DATABASE — repeat for each DB used for training (still as superuser)
--     Example for production DB name:
-- -----------------------------------------------------------------------------
GRANT CONNECT ON DATABASE real_estate_db TO ml_training_readonly;

-- Connect to that database before section C, e.g. in psql:
--   \c real_estate_db

-- -----------------------------------------------------------------------------
-- C) INSIDE the target database (e.g. real_estate_db)
-- -----------------------------------------------------------------------------
GRANT USAGE ON SCHEMA public TO ml_training_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO ml_training_readonly;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO ml_training_readonly;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO ml_training_readonly;

-- PostGIS topology (only if that schema exists)
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'topology') THEN
    EXECUTE 'GRANT USAGE ON SCHEMA topology TO ml_training_readonly';
    EXECUTE 'GRANT SELECT ON ALL TABLES IN SCHEMA topology TO ml_training_readonly';
    EXECUTE 'GRANT SELECT ON ALL SEQUENCES IN SCHEMA topology TO ml_training_readonly';
  END IF;
END;
$$;

-- New objects created by the app user (see ADMIN_DB_USER in .env)
ALTER DEFAULT PRIVILEGES FOR ROLE admin IN SCHEMA public
    GRANT SELECT ON TABLES TO ml_training_readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE admin IN SCHEMA public
    GRANT SELECT ON SEQUENCES TO ml_training_readonly;

-- If a training table was created before default privileges applied, or by another role,
-- run after migrations (table must exist):
--   psql … -f backend/scripts/sql/grant_ml_readonly_mrt_snapshot.sql

-- If table owners differ (e.g. migration user), add matching ALTER DEFAULT
-- PRIVILEGES FOR ROLE other_owner ...

-- -----------------------------------------------------------------------------
-- D) Optional second database (dev) — run B then C while connected to dev DB
-- -----------------------------------------------------------------------------
-- GRANT CONNECT ON DATABASE real_estate_dev_db TO ml_training_readonly;
-- \c real_estate_dev_db
-- (then repeat the GRANT / ALTER DEFAULT PRIVILEGES block from section C)
