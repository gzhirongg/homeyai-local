"""hdb_mrt_routes: key routes by physical_station_id (not mrt_station_lines).

Revision ID: d3e5f7a9b1c2
Revises: c2d3e4f5a6b7
Create Date: 2026-05-13

"""

from typing import Sequence, Union

from alembic import op


revision: str = "d3e5f7a9b1c2"
down_revision: Union[str, None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE hdb_mrt_routes
            ADD COLUMN IF NOT EXISTS physical_station_id INTEGER;
        """
    )
    op.execute(
        """
        UPDATE hdb_mrt_routes r
        SET physical_station_id = ml.physical_station_id
        FROM mrt_station_lines ml
        WHERE ml.id = r.mrt_stn_id;
        """
    )
    op.execute(
        """
        DELETE FROM hdb_mrt_routes r
        WHERE r.physical_station_id IS NULL;
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT ctid,
                   ROW_NUMBER() OVER (
                       PARTITION BY hdb_addr_id, physical_station_id
                       ORDER BY walk_time_mins ASC NULLS LAST, ctid
                   ) AS rn
            FROM hdb_mrt_routes
        )
        DELETE FROM hdb_mrt_routes r
        USING ranked x
        WHERE r.ctid = x.ctid AND x.rn > 1;
        """
    )
    op.execute(
        """
        ALTER TABLE hdb_mrt_routes DROP CONSTRAINT IF EXISTS hdb_mrt_routes_pkey;
        ALTER TABLE hdb_mrt_routes DROP CONSTRAINT IF EXISTS hdb_mrt_routes_mrt_stn_id_fkey;
        """
    )
    op.execute(
        """
        ALTER TABLE hdb_mrt_routes DROP COLUMN IF EXISTS mrt_stn_id;
        """
    )
    op.execute(
        """
        ALTER TABLE hdb_mrt_routes
            ALTER COLUMN physical_station_id SET NOT NULL;
        """
    )
    op.execute(
        """
        ALTER TABLE hdb_mrt_routes
            ADD CONSTRAINT hdb_mrt_routes_physical_station_id_fkey
            FOREIGN KEY (physical_station_id)
            REFERENCES mrt_physical_stations(id)
            ON DELETE CASCADE
            ON UPDATE CASCADE;
        """
    )
    op.execute(
        """
        ALTER TABLE hdb_mrt_routes
            ADD CONSTRAINT hdb_mrt_routes_pkey
            PRIMARY KEY (hdb_addr_id, physical_station_id);
        """
    )

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

            WITH routed AS (
                SELECT
                    r.physical_station_id AS ph_key,
                    r.walk_distance_m::DOUBLE PRECISION AS d_m,
                    r.walk_time_mins,
                    r.pt_time_mins
                FROM hdb_mrt_routes r
                INNER JOIN mrt_physical_stations ps ON ps.id = r.physical_station_id
                WHERE r.hdb_addr_id = p_hdb_addr_id
                  AND ps.geom IS NOT NULL
                  AND r.walk_time_mins IS NOT NULL
                  AND EXISTS (
                      SELECT 1
                      FROM mrt_station_lines m
                      WHERE m.physical_station_id = r.physical_station_id
                        AND m.opening_date IS NOT NULL
                        AND m.opening_date <= p_tx_date
                  )
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
                    FROM mrt_station_lines m
                    WHERE m.physical_station_id = phys_key
                      AND m.opening_date IS NOT NULL
                      AND m.opening_date <= p_tx_date
                ) x;

                SELECT ARRAY_AGG(DISTINCT m.network_line::text ORDER BY m.network_line::text)
                INTO v_op_lines
                FROM mrt_station_lines m
                WHERE m.physical_station_id = phys_key
                  AND m.opening_date IS NOT NULL
                  AND m.opening_date <= p_tx_date;
            ELSE
                conn_ct := 1;
                v_op_lines := ARRAY[]::TEXT[];
            END IF;

            IF EXISTS (
                SELECT 1 FROM mrt_station_lines m
                INNER JOIN mrt_physical_stations ps ON ps.id = m.physical_station_id
                WHERE ps.geom IS NOT NULL
                  AND m.announcement_date IS NOT NULL
                  AND m.announcement_date <= p_tx_date
                  AND (m.opening_date IS NULL OR m.opening_date > p_tx_date)
                  AND ST_DWithin(v_ag, ps.geom::geography, 2000)
            ) THEN
                v_has_fu := 1;
            END IF;

            IF EXISTS (
                SELECT 1 FROM mrt_station_lines m
                INNER JOIN mrt_physical_stations ps ON ps.id = m.physical_station_id
                WHERE ps.geom IS NOT NULL
                  AND m.announcement_date IS NOT NULL
                  AND m.announcement_date <= p_tx_date
                  AND (m.opening_date IS NULL OR m.opening_date > p_tx_date)
                  AND ST_DWithin(v_ag, ps.geom::geography, 200)
            ) THEN
                v_nuis := 1;
            END IF;

            WITH stn2 AS (
                SELECT
                    m.physical_station_id AS ph_key,
                    m.network_line::text AS network_line,
                    m.announcement_date,
                    m.opening_date,
                    m.expected_completion,
                    (ps.geom::geography) AS sgeo,
                    CASE
                        WHEN m.announcement_date IS NOT NULL
                             AND m.announcement_date <= p_tx_date
                             AND (m.opening_date IS NULL OR m.opening_date > p_tx_date)
                            THEN TRUE
                        ELSE FALSE
                    END AS is_planned
                FROM mrt_station_lines m
                INNER JOIN mrt_physical_stations ps ON ps.id = m.physical_station_id
                WHERE ps.geom IS NOT NULL
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
                        m.physical_station_id AS ph_key,
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
                    FROM mrt_station_lines m
                    INNER JOIN mrt_physical_stations ps ON ps.id = m.physical_station_id
                    WHERE ps.geom IS NOT NULL
                ) s
                WHERE s.ph_key = pl_phys AND s.is_planned;

                SELECT MIN(s.announcement_date), MIN(COALESCE(s.opening_date, s.expected_completion))
                INTO v_ann, v_target
                FROM (
                    SELECT
                        m.physical_station_id AS ph_key,
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
                    FROM mrt_station_lines m
                    INNER JOIN mrt_physical_stations ps ON ps.id = m.physical_station_id
                    WHERE ps.geom IS NOT NULL
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

    op.execute(
        """
        ALTER TABLE hdb_mrt_routes DROP CONSTRAINT IF EXISTS hdb_mrt_routes_pkey;
        ALTER TABLE hdb_mrt_routes DROP CONSTRAINT IF EXISTS hdb_mrt_routes_physical_station_id_fkey;
        """
    )
    op.execute(
        """
        ALTER TABLE hdb_mrt_routes
            ADD COLUMN IF NOT EXISTS mrt_stn_id INTEGER;
        """
    )
    op.execute(
        """
        UPDATE hdb_mrt_routes r
        SET mrt_stn_id = sub.pick_id
        FROM (
            SELECT DISTINCT ON (r2.hdb_addr_id, r2.physical_station_id)
                r2.hdb_addr_id,
                r2.physical_station_id,
                ml.id AS pick_id
            FROM hdb_mrt_routes r2
            INNER JOIN mrt_station_lines ml
                ON ml.physical_station_id = r2.physical_station_id
            ORDER BY r2.hdb_addr_id, r2.physical_station_id, ml.id ASC
        ) sub
        WHERE r.hdb_addr_id = sub.hdb_addr_id
          AND r.physical_station_id = sub.physical_station_id;
        """
    )
    op.execute(
        """
        DELETE FROM hdb_mrt_routes r
        WHERE r.mrt_stn_id IS NULL;
        """
    )
    op.execute(
        """
        ALTER TABLE hdb_mrt_routes
            ALTER COLUMN mrt_stn_id SET NOT NULL;
        """
    )
    op.execute(
        """
        ALTER TABLE hdb_mrt_routes DROP COLUMN IF EXISTS physical_station_id;
        """
    )
    op.execute(
        """
        ALTER TABLE hdb_mrt_routes
            ADD CONSTRAINT hdb_mrt_routes_mrt_stn_id_fkey
            FOREIGN KEY (mrt_stn_id)
            REFERENCES mrt_station_lines(id)
            ON DELETE CASCADE
            ON UPDATE CASCADE;
        """
    )
    op.execute(
        """
        ALTER TABLE hdb_mrt_routes
            ADD CONSTRAINT hdb_mrt_routes_pkey
            PRIMARY KEY (hdb_addr_id, mrt_stn_id);
        """
    )

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

            WITH stn AS (
                SELECT m.id,
                    m.physical_station_id AS ph_key,
                    m.network_line::text AS network_line,
                    m.opening_date,
                    m.announcement_date,
                    m.expected_completion,
                    (ps.geom::geography) AS sgeo,
                    CASE
                        WHEN m.opening_date IS NOT NULL AND m.opening_date <= p_tx_date
                            THEN TRUE
                        ELSE FALSE
                    END AS is_op_at_tx
                FROM mrt_station_lines m
                INNER JOIN mrt_physical_stations ps ON ps.id = m.physical_station_id
                WHERE ps.geom IS NOT NULL
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
                    FROM mrt_station_lines m
                    WHERE m.physical_station_id = phys_key
                      AND m.opening_date IS NOT NULL
                      AND m.opening_date <= p_tx_date
                ) x;

                SELECT ARRAY_AGG(DISTINCT m.network_line::text ORDER BY m.network_line::text)
                INTO v_op_lines
                FROM mrt_station_lines m
                WHERE m.physical_station_id = phys_key
                  AND m.opening_date IS NOT NULL
                  AND m.opening_date <= p_tx_date;
            ELSE
                conn_ct := 1;
                v_op_lines := ARRAY[]::TEXT[];
            END IF;

            IF EXISTS (
                SELECT 1 FROM mrt_station_lines m
                INNER JOIN mrt_physical_stations ps ON ps.id = m.physical_station_id
                WHERE ps.geom IS NOT NULL
                  AND m.announcement_date IS NOT NULL
                  AND m.announcement_date <= p_tx_date
                  AND (m.opening_date IS NULL OR m.opening_date > p_tx_date)
                  AND ST_DWithin(v_ag, ps.geom::geography, 2000)
            ) THEN
                v_has_fu := 1;
            END IF;

            IF EXISTS (
                SELECT 1 FROM mrt_station_lines m
                INNER JOIN mrt_physical_stations ps ON ps.id = m.physical_station_id
                WHERE ps.geom IS NOT NULL
                  AND m.announcement_date IS NOT NULL
                  AND m.announcement_date <= p_tx_date
                  AND (m.opening_date IS NULL OR m.opening_date > p_tx_date)
                  AND ST_DWithin(v_ag, ps.geom::geography, 200)
            ) THEN
                v_nuis := 1;
            END IF;

            WITH stn2 AS (
                SELECT
                    m.physical_station_id AS ph_key,
                    m.network_line::text AS network_line,
                    m.announcement_date,
                    m.opening_date,
                    m.expected_completion,
                    (ps.geom::geography) AS sgeo,
                    CASE
                        WHEN m.announcement_date IS NOT NULL
                             AND m.announcement_date <= p_tx_date
                             AND (m.opening_date IS NULL OR m.opening_date > p_tx_date)
                            THEN TRUE
                        ELSE FALSE
                    END AS is_planned
                FROM mrt_station_lines m
                INNER JOIN mrt_physical_stations ps ON ps.id = m.physical_station_id
                WHERE ps.geom IS NOT NULL
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
                        m.physical_station_id AS ph_key,
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
                    FROM mrt_station_lines m
                    INNER JOIN mrt_physical_stations ps ON ps.id = m.physical_station_id
                    WHERE ps.geom IS NOT NULL
                ) s
                WHERE s.ph_key = pl_phys AND s.is_planned;

                SELECT MIN(s.announcement_date), MIN(COALESCE(s.opening_date, s.expected_completion))
                INTO v_ann, v_target
                FROM (
                    SELECT
                        m.physical_station_id AS ph_key,
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
                    FROM mrt_station_lines m
                    INNER JOIN mrt_physical_stations ps ON ps.id = m.physical_station_id
                    WHERE ps.geom IS NOT NULL
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
