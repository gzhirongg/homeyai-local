-- Read-only probes for POST /api/valuation latency diagnosis.
-- Run with psql after sourcing repo .env ($DATABASE_URL_READ_ONLY or ADMIN).
--
-- A) Row count by month — empty current month ⇒ snapshot miss → slower hdb_mrt_features_at fallback.
SELECT tx_year_month, COUNT(*) AS n
FROM hdb_mrt_features_pit_snapshot
GROUP BY tx_year_month
ORDER BY tx_year_month DESC
LIMIT 12;

-- B) Spot-check a valuation month + enriched address id from postal (replace placeholders).
/*
SELECT ae.id AS hdb_addr_id, ae.postal_code
FROM hdb_address_enrichment_onemap ae
WHERE ae.postal_code = '120601';

SELECT 1
FROM hdb_mrt_features_pit_snapshot s
WHERE s.hdb_addr_id = :aid
  AND s.tx_year_month = to_char((CURRENT_TIMESTAMP AT TIME ZONE 'utc'), 'YYYY-MM');

EXPLAIN (ANALYZE, BUFFERS)
SELECT id, poi_type
FROM poi_locations
WHERE poi_type IN ('school_top20', 'school_any')
  AND ST_DWithin(
      ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography,
      ST_SetSRID(ST_MakePoint(103.78, 1.34), 4326)::geography,
      5000
  )
ORDER BY ST_Distance(
    ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography,
    ST_SetSRID(ST_MakePoint(103.78, 1.34), 4326)::geography
)::double precision ASC
LIMIT 1;

EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM hdb_mrt_features_at(:aid, date_trunc('month', CURRENT_TIMESTAMP AT TIME ZONE 'utc')::date);
*/
