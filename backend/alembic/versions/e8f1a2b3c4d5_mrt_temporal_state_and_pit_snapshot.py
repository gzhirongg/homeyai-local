"""mrt temporal state + PIT snapshot + hdb_mrt_features_at function

Revision ID: e8f1a2b3c4d5
Revises: c1d4e8f0a2b3
Create Date: 2026-05-08
"""

from typing import Sequence, Union

from alembic import op


revision: str = "e8f1a2b3c4d5"
down_revision: Union[str, None] = "c1d4e8f0a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE mrt_stations_temporal
          ADD COLUMN IF NOT EXISTS is_interchange BOOLEAN,
          ADD COLUMN IF NOT EXISTS opening_date_confidence VARCHAR(16),
          ADD COLUMN IF NOT EXISTS derived_state VARCHAR(24),
          ADD COLUMN IF NOT EXISTS physical_station_id INTEGER;
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_mrt_temporal_opening_date
          ON mrt_stations_temporal (opening_date);
        CREATE INDEX IF NOT EXISTS idx_mrt_temporal_state
          ON mrt_stations_temporal (derived_state);
        CREATE INDEX IF NOT EXISTS idx_mrt_temporal_announce
          ON mrt_stations_temporal (announcement_date);
        CREATE INDEX IF NOT EXISTS idx_mrt_temporal_physical
          ON mrt_stations_temporal (physical_station_id);
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS hdb_mrt_features_pit_snapshot (
            hdb_addr_id INTEGER NOT NULL,
            tx_year_month VARCHAR(7) NOT NULL,
            dist_to_nearest_op_mrt DOUBLE PRECISION,
            travel_time_to_active_mrt INTEGER,
            pt_time_savings_vs_walk DOUBLE PRECISION,
            line_connectivity_index INTEGER,
            nearest_op_lines TEXT[],
            days_since_mrt_announcement DOUBLE PRECISION,
            days_to_mrt_opening DOUBLE PRECISION,
            speculative_upside_score DOUBLE PRECISION,
            has_future_upside INTEGER,
            nearest_planned_lines TEXT[],
            is_proximity_nuisance INTEGER,
            computed_at TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (hdb_addr_id, tx_year_month)
        );
        CREATE INDEX IF NOT EXISTS idx_mrt_pit_snapshot_month
          ON hdb_mrt_features_pit_snapshot (tx_year_month);
        """
    )
    # Point-in-time feature function (Postgres + PostGIS). See ideation/MRT_FeatureEngineering_Strategy.md
    op.execute(
        """
        CREATE OR REPLACE FUNCTION hdb_mrt_features_at(
            p_hdb_addr_id INTEGER,
            p_tx_date DATE
        )
        RETURNS TABLE (
            dist_to_nearest_op_mrt DOUBLE PRECISION,
            travel_time_to_active_mrt INTEGER,
            pt_time_savings_vs_walk DOUBLE PRECISION,
            line_connectivity_index INTEGER,
            nearest_op_lines TEXT[],
            days_since_mrt_announcement DOUBLE PRECISION,
            days_to_mrt_opening DOUBLE PRECISION,
            speculative_upside_score DOUBLE PRECISION,
            has_future_upside INTEGER,
            nearest_planned_lines TEXT[],
            is_proximity_nuisance INTEGER
        )
        LANGUAGE plpgsql
        STABLE
        AS $func$
        DECLARE
            v_lon DOUBLE PRECISION;
            v_lat DOUBLE PRECISION;
            v_ag geography;
            best_walk_dist DOUBLE PRECISION;
            best_walk_time INTEGER;
            best_pt_time INTEGER;
            phys_key BIGINT;
            v_open_days DOUBLE PRECISION;
            v_ann_days DOUBLE PRECISION;
            v_has_fu INTEGER := 0;
            v_nuis INTEGER := 0;
            pl_phys BIGINT;
            v_pl_lines TEXT[];
            v_ann DATE;
            v_target DATE;
            v_score DOUBLE PRECISION;
            conn_ct INTEGER := 1;
            v_op_lines TEXT[];
            v_pt_sav DOUBLE PRECISION;
        BEGIN
            SELECT longitude, latitude INTO v_lon, v_lat
            FROM hdb_address_enrichment_onemap
            WHERE id = p_hdb_addr_id;
            IF v_lon IS NULL OR v_lat IS NULL THEN
                RETURN QUERY SELECT
                    NULL::DOUBLE PRECISION,
                    NULL::INTEGER,
                    NULL::DOUBLE PRECISION,
                    1::INTEGER,
                    ARRAY[]::TEXT[],
                    NULL::DOUBLE PRECISION,
                    NULL::DOUBLE PRECISION,
                    NULL::DOUBLE PRECISION,
                    0::INTEGER,
                    NULL::TEXT[],
                    0::INTEGER;
                RETURN;
            END IF;
            v_ag := ST_SetSRID(ST_MakePoint(v_lon, v_lat), 4326)::geography;

            -- Nearest routed operational cluster (walk time)
            WITH stn AS (
                SELECT m.id,
                    COALESCE(m.physical_station_id, -m.id) AS ph_key,
                    m.network_line::text AS network_line,
                    m.opening_date,
                    m.announcement_date,
                    m.expected_completion,
                    (m.geom::geography) AS sgeo,
                    CASE
                        WHEN m.opening_date IS NOT NULL AND m.opening_date <= p_tx_date
                            THEN TRUE
                        ELSE FALSE
                    END AS is_op_at_tx
                FROM mrt_stations_temporal m
            ),
            routed AS (
                SELECT
                    s.ph_key,
                    r.walk_distance_m::DOUBLE PRECISION AS d_m,
                    r.walk_time_mins,
                    r.pt_time_mins
                FROM hdb_mrt_routes r
                INNER JOIN stn s ON s.id = r.mrt_stn_id
                WHERE r.hdb_addr_id = p_hdb_addr_id
                  AND s.is_op_at_tx
                  AND r.walk_time_mins IS NOT NULL
            ),
            per_phys AS (
                SELECT DISTINCT ON (ph_key)
                    ph_key,
                    d_m,
                    walk_time_mins,
                    pt_time_mins
                FROM routed
                ORDER BY ph_key, walk_time_mins ASC NULLS LAST
            ),
            best_row AS (
                SELECT * FROM per_phys
                ORDER BY walk_time_mins ASC NULLS LAST
                LIMIT 1
            )
            SELECT
                br.ph_key,
                br.d_m,
                br.walk_time_mins::INTEGER,
                br.pt_time_mins::INTEGER
            INTO phys_key, best_walk_dist, best_walk_time, best_pt_time
            FROM best_row br;

            IF phys_key IS NULL THEN
                best_walk_dist := NULL;
                best_walk_time := NULL;
                best_pt_time := NULL;
            END IF;

            IF best_walk_time IS NOT NULL AND best_pt_time IS NOT NULL THEN
                v_pt_sav := GREATEST(0::DOUBLE PRECISION,
                    best_walk_time::DOUBLE PRECISION - best_pt_time::DOUBLE PRECISION);
            ELSIF best_walk_time IS NOT NULL THEN
                v_pt_sav := 0::DOUBLE PRECISION;
            ELSE
                v_pt_sav := NULL::DOUBLE PRECISION;
            END IF;

            IF phys_key IS NOT NULL THEN
                SELECT COALESCE(MAX(cnt), 1)::INTEGER INTO conn_ct
                FROM (
                    SELECT COUNT(DISTINCT m.network_line) AS cnt
                    FROM mrt_stations_temporal m
                    WHERE COALESCE(m.physical_station_id, -m.id) = phys_key
                      AND m.opening_date IS NOT NULL
                      AND m.opening_date <= p_tx_date
                ) x;

                SELECT ARRAY_AGG(DISTINCT m.network_line::text ORDER BY m.network_line::text)
                INTO v_op_lines
                FROM mrt_stations_temporal m
                WHERE COALESCE(m.physical_station_id, -m.id) = phys_key
                  AND m.opening_date IS NOT NULL
                  AND m.opening_date <= p_tx_date;
            ELSE
                conn_ct := 1;
                v_op_lines := ARRAY[]::TEXT[];
            END IF;

            IF EXISTS (
                SELECT 1 FROM mrt_stations_temporal m
                WHERE m.geom IS NOT NULL
                  AND m.announcement_date IS NOT NULL
                  AND m.announcement_date <= p_tx_date
                  AND (m.opening_date IS NULL OR m.opening_date > p_tx_date)
                  AND ST_DWithin(v_ag, m.geom::geography, 2000)
            ) THEN
                v_has_fu := 1;
            END IF;

            IF EXISTS (
                SELECT 1 FROM mrt_stations_temporal m
                WHERE m.geom IS NOT NULL
                  AND m.announcement_date IS NOT NULL
                  AND m.announcement_date <= p_tx_date
                  AND (m.opening_date IS NULL OR m.opening_date > p_tx_date)
                  AND ST_DWithin(v_ag, m.geom::geography, 200)
            ) THEN
                v_nuis := 1;
            END IF;

            -- Planned: nearest physical cluster within 2 km
            WITH stn2 AS (
                SELECT
                    COALESCE(m.physical_station_id, -m.id) AS ph_key,
                    m.network_line::text AS network_line,
                    m.announcement_date,
                    m.opening_date,
                    m.expected_completion,
                    (m.geom::geography) AS sgeo,
                    CASE
                        WHEN m.announcement_date IS NOT NULL
                             AND m.announcement_date <= p_tx_date
                             AND (m.opening_date IS NULL OR m.opening_date > p_tx_date)
                            THEN TRUE
                        ELSE FALSE
                    END AS is_planned
                FROM mrt_stations_temporal m
                WHERE m.geom IS NOT NULL
            ),
            near_pl AS (
                SELECT
                    s.ph_key,
                    ST_Distance(v_ag, s.sgeo) AS d_m
                FROM stn2 s
                WHERE s.is_planned
                  AND ST_DWithin(v_ag, s.sgeo, 2000)
            ),
            pick_phys AS (
                SELECT ph_key, MIN(d_m) AS md
                FROM near_pl
                GROUP BY ph_key
            ),
            best_pl AS (
                SELECT ph_key FROM pick_phys ORDER BY md ASC LIMIT 1
            )
            SELECT b.ph_key INTO pl_phys FROM best_pl b;

            IF pl_phys IS NOT NULL THEN
                SELECT ARRAY_AGG(DISTINCT s.network_line ORDER BY s.network_line)
                INTO v_pl_lines
                FROM (
                    SELECT
                        COALESCE(m.physical_station_id, -m.id) AS ph_key,
                        m.network_line::text AS network_line,
                        m.announcement_date,
                        m.opening_date,
                        m.expected_completion,
                        CASE
                            WHEN m.announcement_date IS NOT NULL
                                 AND m.announcement_date <= p_tx_date
                                 AND (m.opening_date IS NULL OR m.opening_date > p_tx_date)
                                THEN TRUE
                            ELSE FALSE
                        END AS is_planned
                    FROM mrt_stations_temporal m
                    WHERE m.geom IS NOT NULL
                ) s
                WHERE s.ph_key = pl_phys AND s.is_planned;

                SELECT MIN(s.announcement_date), MIN(COALESCE(s.opening_date, s.expected_completion))
                INTO v_ann, v_target
                FROM (
                    SELECT
                        COALESCE(m.physical_station_id, -m.id) AS ph_key,
                        m.announcement_date,
                        m.opening_date,
                        m.expected_completion,
                        CASE
                            WHEN m.announcement_date IS NOT NULL
                                 AND m.announcement_date <= p_tx_date
                                 AND (m.opening_date IS NULL OR m.opening_date > p_tx_date)
                                THEN TRUE
                            ELSE FALSE
                        END AS is_planned
                    FROM mrt_stations_temporal m
                    WHERE m.geom IS NOT NULL
                ) s
                WHERE s.ph_key = pl_phys AND s.is_planned;

                IF v_ann IS NOT NULL THEN
                    v_ann_days := (p_tx_date - v_ann)::DOUBLE PRECISION;
                END IF;
                IF v_target IS NOT NULL THEN
                    v_open_days := (v_target - p_tx_date)::DOUBLE PRECISION;
                    v_score := 1.0 / (1.0 + exp(0.005 * (v_open_days - 365.0)));
                END IF;
            ELSE
                v_pl_lines := NULL;
                v_ann_days := NULL;
                v_open_days := NULL;
                v_score := NULL;
            END IF;

            RETURN QUERY SELECT
                best_walk_dist,
                best_walk_time,
                v_pt_sav,
                conn_ct,
                COALESCE(v_op_lines, ARRAY[]::TEXT[]),
                v_ann_days,
                v_open_days,
                v_score,
                v_has_fu,
                v_pl_lines,
                v_nuis;
        END;
        $func$;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS hdb_mrt_features_at(INTEGER, DATE);")
    op.execute("DROP TABLE IF EXISTS hdb_mrt_features_pit_snapshot;")
    op.execute(
        """
        ALTER TABLE mrt_stations_temporal
          DROP COLUMN IF EXISTS physical_station_id,
          DROP COLUMN IF EXISTS derived_state,
          DROP COLUMN IF EXISTS opening_date_confidence,
          DROP COLUMN IF EXISTS is_interchange;
        """
    )
    op.execute("DROP INDEX IF EXISTS idx_mrt_temporal_physical;")
    op.execute("DROP INDEX IF EXISTS idx_mrt_temporal_announce;")
    op.execute("DROP INDEX IF EXISTS idx_mrt_temporal_state;")
    op.execute("DROP INDEX IF EXISTS idx_mrt_temporal_opening_date;")
