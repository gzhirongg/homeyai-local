/*
 * Point-in-Time MRT features — documentation only.
 *
 * Live implementation: PostgreSQL function
 *   public.hdb_mrt_features_at(p_hdb_addr_id integer, p_tx_date date)
 * created by Alembic revision e8f1a2b3c4d5_mrt_temporal_state_and_pit_snapshot.py
 *
 * Example:
 *   SELECT * FROM hdb_mrt_features_at(1, DATE '2022-06-01');
 *
 * Snapshot table: hdb_mrt_features_pit_snapshot (see build_mrt_pit_snapshot.py)
 * Spec: ideation/MRT_FeatureEngineering_Strategy.md
 */
