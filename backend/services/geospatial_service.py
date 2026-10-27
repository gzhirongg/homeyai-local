import math
from datetime import date
from collections import defaultdict
from typing import List, Dict, Optional, Set, TYPE_CHECKING, FrozenSet, Tuple, Any

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# Default: only currently-open stations for non-temporal callers (no look-ahead).
_DEFAULT_MRT_STATES: FrozenSet[str] = frozenset({"OPERATIONAL"})

# Pass-1 MRT routing ingest: operational + announced/planned buckets (excludes UNKNOWN).
MRT_ROUTING_PASS1_STATES: FrozenSet[str] = frozenset(
    {
        "OPERATIONAL",
        "COMMITTED_DATED",
        "COMMITTED_ESTIMATED",
        "ANNOUNCED_UNDATED",
    }
)


def greedy_line_diverse_physical_ids(
    phys_order: List[int],
    line_sets: Dict[int, Set[str]],
    *,
    max_stations: int = 4,
) -> List[int]:
    """
    ``phys_order``: physical_station_id sorted by ascending distance to the query point.
    ``line_sets``: pid -> set of network_line strings at that physical (non-empty strings).
    First station is always taken; each further station must add at least one new line.
    """
    covered: Set[str] = set()
    chosen: List[int] = []
    for pid in phys_order:
        lines = line_sets.get(pid, set()) or {""}
        if not chosen:
            chosen.append(pid)
            covered |= lines
            if len(chosen) >= max_stations:
                break
            continue
        if lines - covered:
            chosen.append(pid)
            covered |= lines
        if len(chosen) >= max_stations:
            break
    return chosen

# ---------------------------------------------------------------------------
# Pure-Python fallback (used only when DB is unavailable)
# ---------------------------------------------------------------------------

_FALLBACK_MRT_STATIONS = [
    {"name": "Clementi",       "lat": 1.3150, "lng": 103.7652},
    {"name": "Jurong East",    "lat": 1.3331, "lng": 103.7423},
    {"name": "Dover",          "lat": 1.3114, "lng": 103.7786},
    {"name": "Buona Vista",    "lat": 1.3072, "lng": 103.7906},
    {"name": "Commonwealth",   "lat": 1.3025, "lng": 103.7983},
    {"name": "Queenstown",     "lat": 1.2946, "lng": 103.8061},
    {"name": "Redhill",        "lat": 1.2896, "lng": 103.8168},
    {"name": "Tiong Bahru",    "lat": 1.2861, "lng": 103.8270},
    {"name": "Outram Park",    "lat": 1.2797, "lng": 103.8395},
    {"name": "Tanjong Pagar",  "lat": 1.2765, "lng": 103.8458},
    {"name": "Raffles Place",  "lat": 1.2841, "lng": 103.8515},
    {"name": "City Hall",      "lat": 1.2931, "lng": 103.8522},
    {"name": "Bugis",          "lat": 1.3007, "lng": 103.8557},
    {"name": "Lavender",       "lat": 1.3073, "lng": 103.8628},
    {"name": "Kallang",        "lat": 1.3115, "lng": 103.8714},
]


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def is_point_in_polygon(x: float, y: float, poly: List) -> bool:
    """Ray-casting point-in-polygon test."""
    n = len(poly)
    inside = False
    p1x, p1y = poly[0]
    for i in range(n + 1):
        p2x, p2y = poly[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xints = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xints:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside


# ---------------------------------------------------------------------------
# DB-backed functions (PostGIS)
# ---------------------------------------------------------------------------

def get_nearby_mrts(
    lat: float,
    lng: float,
    radius_km: float = 1.0,
    db: Optional["Session"] = None,
    unique_stations: bool = False,
    *,
    as_of: Optional[date] = None,
    states: Optional[Set[str]] = None,
) -> List[Dict]:
    """
    Return the closest MRT stations within radius_km, optionally filtered by
    point-in-time lifecycle state at ``as_of``.

    If ``as_of`` is None, uses today's date for state evaluation.
    If ``states`` is None, only ``OPERATIONAL`` rows are returned (no default-open
    leakage for unbuilt or undated stations).

    States: OPERATIONAL, COMMITTED_DATED, COMMITTED_ESTIMATED, ANNOUNCED_UNDATED, UNKNOWN.
    """
    if states is None:
        states_set = set(_DEFAULT_MRT_STATES)
    else:
        states_set = set(states)

    as_of_d = as_of if as_of is not None else date.today()
    state_list = sorted(states_set)
    if db is not None:
        try:
            from sqlalchemy import text

            if not state_list:
                return []

            placeholders = ", ".join(f":st{i}" for i in range(len(state_list)))
            bind = {"lat": lat, "lng": lng, "radius_m": radius_km * 1000, "as_of": as_of_d}
            for i, s in enumerate(state_list):
                bind[f"st{i}"] = s

            dedup_expr = "m.physical_station_id::text"
            base_cte = f"""
                WITH base AS (
                    SELECT
                        m.id,
                        m.station_name,
                        m.station_code,
                        m.station_status,
                        {dedup_expr} AS dedup_key,
                        ROUND(
                            ST_Distance(
                                ps.geom::geography,
                                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
                            )::numeric / 1000,
                            3
                        ) AS distance_km,
                        CASE
                            WHEN m.opening_date IS NOT NULL AND m.opening_date <= :as_of
                                THEN 'OPERATIONAL'
                            WHEN m.announcement_date IS NOT NULL
                                 AND m.announcement_date <= :as_of
                                 AND (m.opening_date IS NULL OR m.opening_date > :as_of)
                                THEN
                                CASE
                                    WHEN m.opening_date IS NOT NULL THEN 'COMMITTED_DATED'
                                    WHEN m.expected_completion IS NOT NULL
                                        THEN 'COMMITTED_ESTIMATED'
                                    ELSE 'ANNOUNCED_UNDATED'
                                END
                            ELSE 'UNKNOWN'
                        END AS pit_state
                    FROM mrt_station_lines m
                    INNER JOIN mrt_physical_stations ps ON ps.id = m.physical_station_id
                    WHERE ps.geom IS NOT NULL
                      AND ST_DWithin(
                          ps.geom::geography,
                          ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                          :radius_m
                      )
                ),
                filt AS (
                    SELECT * FROM base WHERE pit_state IN ({placeholders})
                )
            """

            if unique_stations:
                sql_text = base_cte + """
                SELECT DISTINCT ON (dedup_key)
                    id,
                    station_name,
                    station_code,
                    station_status,
                    distance_km,
                    pit_state
                FROM filt
                ORDER BY dedup_key, distance_km ASC
                """
            else:
                sql_text = base_cte + """
                SELECT
                    id,
                    station_name,
                    station_code,
                    station_status,
                    distance_km,
                    pit_state
                FROM filt
                ORDER BY distance_km ASC
                """

            rows = db.execute(text(sql_text), bind).fetchall()
            out = [
                {
                    "id": row.id,
                    "name": row.station_name,
                    "station_code": row.station_code,
                    "station_status": row.station_status,
                    "distance": float(row.distance_km),
                    "pit_state": row.pit_state,
                }
                for row in rows
            ]
            # DISTINCT ON orders by dedup_key first; callers (e.g. routing [:2]) need global nearest.
            if unique_stations:
                out.sort(key=lambda r: r["distance"])
            return out
        except Exception as e:
            print(f"[geospatial] DB query failed, using fallback: {e}")
            db.rollback()

    # Fallback — no temporal filter
    results = []
    seen_stations = set()
    for mrt in sorted(_FALLBACK_MRT_STATIONS, key=lambda x: haversine_distance(lat, lng, x["lat"], x["lng"])):
        dist = haversine_distance(lat, lng, mrt["lat"], mrt["lng"])
        if dist <= radius_km:
            pid = mrt["name"]
            if unique_stations:
                if pid in seen_stations:
                    continue
                seen_stations.add(pid)
            pit = "OPERATIONAL" if "OPERATIONAL" in states_set else None
            if pit is None:
                continue
            results.append({"name": mrt["name"], "exit_code": None, "distance": round(dist, 3), "pit_state": "OPERATIONAL"})
    return sorted(results, key=lambda x: x["distance"])


def select_line_diverse_mrt_candidates(
    lat: float,
    lng: float,
    db: "Session",
    *,
    radius_km: float = 2.0,
    max_stations: int = 4,
    as_of: Optional[date] = None,
) -> List[Dict]:
    """
    Pass-1 routing candidate set: up to ``max_stations`` distinct *physical* stations
    within ``radius_km``, greedy by geodesic distance, each pick must introduce at least
    one new ``network_line`` not already covered (except the first pick, which is always
    the nearest physical station).

    Lifecycle: ``MRT_ROUTING_PASS1_STATES`` (UNKNOWN excluded). PIT feature selection
    (pass 2) remains in ``hdb_mrt_features_at`` / snapshot SQL.

    Returns dicts: id (mrt_station_lines.id), name, station_code, distance, pit_state,
    physical_station_id.
    """
    from sqlalchemy import text

    as_of_d = as_of if as_of is not None else date.today()
    state_list = sorted(MRT_ROUTING_PASS1_STATES)
    placeholders = ", ".join(f":st{i}" for i in range(len(state_list)))
    bind: Dict = {"lat": lat, "lng": lng, "radius_m": radius_km * 1000, "as_of": as_of_d}
    for i, s in enumerate(state_list):
        bind[f"st{i}"] = s

    sql = text(
        f"""
        WITH base AS (
            SELECT
                m.id,
                m.physical_station_id,
                m.network_line::text AS network_line,
                m.station_name,
                m.station_code,
                m.station_status,
                ROUND(
                    ST_Distance(
                        ps.geom::geography,
                        ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
                    )::numeric / 1000,
                    3
                ) AS distance_km,
                CASE
                    WHEN m.opening_date IS NOT NULL AND m.opening_date <= :as_of
                        THEN 'OPERATIONAL'
                    WHEN m.announcement_date IS NOT NULL
                         AND m.announcement_date <= :as_of
                         AND (m.opening_date IS NULL OR m.opening_date > :as_of)
                        THEN
                        CASE
                            WHEN m.opening_date IS NOT NULL THEN 'COMMITTED_DATED'
                            WHEN m.expected_completion IS NOT NULL
                                THEN 'COMMITTED_ESTIMATED'
                            ELSE 'ANNOUNCED_UNDATED'
                        END
                    ELSE 'UNKNOWN'
                END AS pit_state
            FROM mrt_station_lines m
            INNER JOIN mrt_physical_stations ps ON ps.id = m.physical_station_id
            WHERE ps.geom IS NOT NULL
              AND ST_DWithin(
                  ps.geom::geography,
                  ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                  :radius_m
              )
        ),
        filt AS (
            SELECT * FROM base WHERE pit_state IN ({placeholders})
        )
        SELECT id, physical_station_id, network_line, station_name, station_code,
               station_status, distance_km, pit_state
        FROM filt
        ORDER BY distance_km ASC, physical_station_id ASC, network_line ASC NULLS LAST, id ASC
        """
    )

    rows = db.execute(sql, bind).fetchall()
    by_phys: Dict[int, List[Tuple]] = defaultdict(list)
    for row in rows:
        nl = (row.network_line or "").strip()
        by_phys[int(row.physical_station_id)].append(
            (int(row.id), nl, row.station_name, row.station_code, row.station_status, float(row.distance_km), row.pit_state)
        )

    if not by_phys:
        return []

    # One representative distance / pit_state / name per physical (same geom).
    phys_order: List[int] = sorted(
        by_phys.keys(),
        key=lambda pid: min(t[5] for t in by_phys[pid]),
    )

    def line_set(pid: int) -> Set[str]:
        s = {t[1] for t in by_phys[pid] if t[1]}
        return s if s else {""}

    def representative_id(pid: int) -> int:
        return min(t[0] for t in by_phys[pid])

    line_sets_map: Dict[int, Set[str]] = {pid: line_set(pid) for pid in phys_order}
    chosen = greedy_line_diverse_physical_ids(phys_order, line_sets_map, max_stations=max_stations)

    out: List[Dict] = []
    for pid in chosen:
        rid = representative_id(pid)
        meta = next(t for t in by_phys[pid] if t[0] == rid)
        _, _, st_name, st_code, st_status, _, pit = meta
        dist_km = min(t[5] for t in by_phys[pid])
        out.append(
            {
                "id": rid,
                "name": st_name,
                "station_code": st_code,
                "station_status": st_status,
                "distance": dist_km,
                "pit_state": pit,
                "physical_station_id": pid,
            }
        )
    return out


def get_insights_for_area(polygon_coords: List[List[float]],
                          db: Optional["Session"] = None) -> Dict:
    """
    Return MRT accessibility insights for a drawn polygon.
    Uses PostGIS ST_Within when db is provided; falls back to ray-casting.
    polygon_coords: list of [lat, lng] pairs.
    """
    if db is not None:
        try:
            from sqlalchemy import text
            import json

            # Convert [lat, lng] pairs to a GeoJSON polygon ([lng, lat] order)
            ring = [[lng, lat] for lat, lng in polygon_coords]
            if ring[0] != ring[-1]:
                ring.append(ring[0])
            geojson_polygon = json.dumps({
                "type": "Polygon",
                "coordinates": [ring],
            })

            sql = text("""
                SELECT DISTINCT m.station_name
                FROM mrt_station_lines m
                INNER JOIN mrt_physical_stations ps ON ps.id = m.physical_station_id
                WHERE ps.geom IS NOT NULL
                  AND m.opening_date IS NOT NULL
                  AND m.opening_date <= CURRENT_DATE
                  AND ST_Within(
                    ps.geom,
                    ST_SetSRID(ST_GeomFromGeoJSON(:poly), 4326)
                )
                ORDER BY m.station_name
            """)
            rows = db.execute(sql, {"poly": geojson_polygon}).fetchall()
            station_names = [r.station_name for r in rows]
            return {
                "mrt_count": len(station_names),
                "mrts": station_names,
                "region_score": (
                    "High Accessibility" if len(station_names) > 2
                    else "Moderate Accessibility"
                ),
            }
        except Exception as e:
            print(f"[geospatial] DB query failed, using fallback: {e}")
            db.rollback()

    # Fallback
    mrts_in_area = [
        mrt["name"] for mrt in _FALLBACK_MRT_STATIONS
        if is_point_in_polygon(mrt["lat"], mrt["lng"], polygon_coords)
    ]
    return {
        "mrt_count": len(mrts_in_area),
        "mrts": mrts_in_area,
        "region_score": (
            "High Accessibility" if len(mrts_in_area) > 2
            else "Moderate Accessibility"
        ),
    }


_PLANNED_PIT_STATES: FrozenSet[str] = frozenset(
    {"COMMITTED_DATED", "COMMITTED_ESTIMATED", "ANNOUNCED_UNDATED"}
)


def _pit_state_case_sql(alias: str = "m") -> str:
    """Point-in-time lifecycle label; bind ``:as_of`` (date)."""
    a = alias
    return f"""
        CASE
            WHEN {a}.opening_date IS NOT NULL AND {a}.opening_date <= :as_of
                THEN 'OPERATIONAL'
            WHEN {a}.announcement_date IS NOT NULL
                 AND {a}.announcement_date <= :as_of
                 AND ({a}.opening_date IS NULL OR {a}.opening_date > :as_of)
                THEN
                CASE
                    WHEN {a}.opening_date IS NOT NULL THEN 'COMMITTED_DATED'
                    WHEN {a}.expected_completion IS NOT NULL
                        THEN 'COMMITTED_ESTIMATED'
                    ELSE 'ANNOUNCED_UNDATED'
                END
            ELSE 'UNKNOWN'
        END
    """


def get_nearby_planned_mrts_detail(
    lat: float,
    lng: float,
    *,
    db: "Session",
    radius_km: float = 2.5,
    exclude_line_ids: Optional[Set[int]] = None,
    limit: int = 12,
    as_of: Optional[date] = None,
) -> List[Dict]:
    """
    Nearest announced / committed (non-operational) station *lines* within radius,
    excluding given ``mrt_station_lines.id`` values.
    """
    from sqlalchemy import text

    as_of_d = as_of if as_of is not None else date.today()
    excl = [int(x) for x in (exclude_line_ids or set())]
    bind: Dict = {
        "lat": lat,
        "lng": lng,
        "radius_m": radius_km * 1000,
        "as_of": as_of_d,
        "lim": limit,
    }
    excl_sql = ""
    if excl:
        excl_sql = " AND id NOT IN (" + ",".join(f":e{i}" for i in range(len(excl))) + ")"
        for i, eid in enumerate(excl):
            bind[f"e{i}"] = eid

    pit_sql = _pit_state_case_sql("m")
    st_list = sorted(_PLANNED_PIT_STATES)
    placeholders = ", ".join(f":st{i}" for i in range(len(st_list)))
    for i, s in enumerate(st_list):
        bind[f"st{i}"] = s

    sql_text = f"""
        WITH base AS (
            SELECT
                m.id,
                m.physical_station_id,
                ps.canonical_name AS physical_canonical_name,
                ps.lat AS station_lat,
                ps.long AS station_long,
                m.network_line,
                m.station_name,
                m.station_code,
                m.opening_date,
                m.expected_completion,
                m.announcement_date,
                m.announcement_date_raw,
                m.opening_date_raw,
                m.expected_completion_raw,
                m.source_url,
                m.subproject_or_stage,
                ROUND(
                    ST_Distance(
                        ps.geom::geography,
                        ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
                    )::numeric / 1000,
                    3
                ) AS distance_km,
                ({pit_sql.strip()}) AS pit_state
            FROM mrt_station_lines m
            INNER JOIN mrt_physical_stations ps ON ps.id = m.physical_station_id
            WHERE ps.geom IS NOT NULL
              AND ST_DWithin(
                  ps.geom::geography,
                  ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                  :radius_m
              )
        )
        SELECT *
        FROM base
        WHERE pit_state IN ({placeholders})
        {excl_sql}
        ORDER BY distance_km ASC
        LIMIT :lim
    """

    rows = db.execute(text(sql_text), bind).fetchall()
    out: List[Dict] = []
    for row in rows:
        od = row.opening_date.isoformat() if getattr(row, "opening_date", None) else None
        ec = row.expected_completion.isoformat() if getattr(row, "expected_completion", None) else None
        ad = row.announcement_date.isoformat() if getattr(row, "announcement_date", None) else None
        pid = int(row.physical_station_id)
        canon = (row.physical_canonical_name or row.station_name or "").strip()
        out.append(
            {
                "id": int(row.id),
                "physical_station_id": pid,
                "physical_canonical_name": canon,
                "station_lat": float(row.station_lat) if row.station_lat is not None else None,
                "station_long": float(row.station_long) if row.station_long is not None else None,
                "name": f"{row.station_name} MRT",
                "station_name": row.station_name,
                "network_line": row.network_line,
                "station_code": row.station_code,
                "pit_state": row.pit_state,
                "distance_m": int(float(row.distance_km) * 1000),
                "opening_date": od,
                "expected_completion": ec,
                "announcement_date": ad,
                "announcement_date_raw": row.announcement_date_raw,
                "opening_date_raw": row.opening_date_raw,
                "expected_completion_raw": row.expected_completion_raw,
                "source_url": row.source_url,
                "subproject_or_stage": row.subproject_or_stage,
                "type": "MRT",
                "icon": "Train",
            }
        )
    return out


# Resale analytics town labels that map to multiple URA planning areas (matches Map.tsx).
_CENTRAL_AREA_PLANNING_AREAS: Tuple[str, ...] = (
    "DOWNTOWN CORE",
    "ORCHARD",
    "MUSEUM",
    "SINGAPORE RIVER",
    "OUTRAM",
    "NEWTON",
    "RIVER VALLEY",
    "MARINA SOUTH",
    "MARINA EAST",
    "STRAITS VIEW",
    "ROCHOR",
)


def expand_resale_town_names(town_names: Optional[List[str]]) -> List[str]:
    """Map HDB resale town labels to ``pln_area_n`` values for spatial union queries."""
    out: List[str] = []
    seen: Set[str] = set()
    for raw in town_names or []:
        t = str(raw).strip().upper()
        if not t:
            continue
        if t == "CENTRAL AREA":
            candidates = _CENTRAL_AREA_PLANNING_AREAS
        elif t == "KALLANG/WHAMPOA":
            candidates = ("KALLANG", "WHAMPOA")
        else:
            candidates = (t,)
        for c in candidates:
            if c not in seen:
                seen.add(c)
                out.append(c)
    return out


def _planning_union_where_clause(
    region_c: Optional[str],
    town_names: Optional[List[str]],
) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    SQL ``WHERE`` fragment + bind dict for ``ura_mp19_planning_areas_no_sea`` alias ``pa``.
    Returns ``(None, {})`` when no region or town scope is provided.
    """
    towns_norm = expand_resale_town_names(town_names)
    rc = (region_c or "").strip().upper() or None
    if rc is None and not towns_norm:
        return None, {}
    if rc is not None and towns_norm:
        return (
            "pa.region_c = :region_c AND "
            "upper(btrim(pa.pln_area_n)) = ANY(CAST(:town_arr AS text[]))",
            {"region_c": rc, "town_arr": towns_norm},
        )
    if rc is not None:
        return ("pa.region_c = :region_c", {"region_c": rc})
    return (
        "upper(btrim(pa.pln_area_n)) = ANY(CAST(:town_arr AS text[]))",
        {"town_arr": towns_norm},
    )


def list_mrts_in_planning_union(
    db: "Session",
    *,
    region_c: Optional[str] = None,
    town_names: Optional[List[str]] = None,
    as_of: Optional[date] = None,
) -> List[Dict]:
    """
    All ``mrt_station_lines`` whose physical geometry lies inside the union of
    URA planning area polygons matching ``region_c`` and/or ``town_names``.
    """
    from sqlalchemy import text

    where_clause, bind_base = _planning_union_where_clause(region_c, town_names)
    if where_clause is None:
        return []

    as_of_d = as_of if as_of is not None else date.today()
    pit_sql = _pit_state_case_sql("m")
    bind: Dict[str, Any] = {**bind_base, "as_of": as_of_d}

    sql_text = f"""
        WITH area_union AS (
            SELECT ST_UnaryUnion(ST_Collect(pa.geom)) AS g
            FROM ura_mp19_planning_areas_no_sea pa
            WHERE {where_clause}
        )
        SELECT
            m.id,
            m.network_line,
            m.station_name,
            m.station_code,
            m.opening_date,
            m.expected_completion,
            m.announcement_date,
            m.announcement_date_raw,
            m.opening_date_raw,
            m.expected_completion_raw,
            m.source_url,
            m.subproject_or_stage,
            (""" + pit_sql.strip() + """) AS pit_state
        FROM mrt_station_lines m
        INNER JOIN mrt_physical_stations ps ON ps.id = m.physical_station_id
        CROSS JOIN area_union au
        WHERE ps.geom IS NOT NULL
          AND au.g IS NOT NULL
          AND ST_Within(ps.geom, au.g)
        ORDER BY m.station_name ASC, m.network_line ASC NULLS LAST, m.id ASC
        LIMIT 400
    """

    rows = db.execute(text(sql_text), bind).fetchall()
    out: List[Dict] = []
    for row in rows:
        od = row.opening_date.isoformat() if getattr(row, "opening_date", None) else None
        ec = row.expected_completion.isoformat() if getattr(row, "expected_completion", None) else None
        ad = row.announcement_date.isoformat() if getattr(row, "announcement_date", None) else None
        out.append(
            {
                "id": int(row.id),
                "name": f"{row.station_name} MRT",
                "station_name": row.station_name,
                "network_line": row.network_line,
                "station_code": row.station_code,
                "pit_state": row.pit_state,
                "opening_date": od,
                "expected_completion": ec,
                "announcement_date": ad,
                "announcement_date_raw": row.announcement_date_raw,
                "opening_date_raw": row.opening_date_raw,
                "expected_completion_raw": row.expected_completion_raw,
                "source_url": row.source_url,
                "subproject_or_stage": row.subproject_or_stage,
                "type": "MRT",
                "icon": "Train",
            }
        )
    return out


def list_pois_in_planning_union(
    db: "Session",
    *,
    region_c: Optional[str] = None,
    town_names: Optional[List[str]] = None,
    pcn_list_limit: int = 500,
    row_limit: int = 40000,
) -> Dict[str, Any]:
    """
    POIs in ``poi_locations`` whose (lon, lat) lies inside the union of URA planning polygons
    matching ``region_c`` and/or ``town_names`` (same filter semantics as ``list_mrts_in_planning_union``).

    PCN lists are capped at ``pcn_list_limit`` rows while ``counts_by_type`` reflects full counts
    within ``row_limit`` selected rows.
    """
    from sqlalchemy import text

    where_clause, bind_base = _planning_union_where_clause(region_c, town_names)
    if where_clause is None:
        return {
            "counts_by_type": {k: 0 for k in POI_TYPE_LABELS},
            "by_type": {k: [] for k in POI_TYPE_LABELS},
            "pcn_capped": False,
            "poi_total": 0,
            "row_truncated": False,
        }

    bind: Dict[str, Any] = {**bind_base, "row_limit": int(row_limit)}

    sql_text = f"""
        WITH area_union AS (
            SELECT ST_UnaryUnion(ST_Collect(pa.geom)) AS g
            FROM ura_mp19_planning_areas_no_sea pa
            WHERE {where_clause}
        )
        SELECT p.id, p.poi_type, p.name, p.lat, p.lon
        FROM poi_locations p
        CROSS JOIN area_union au
        WHERE au.g IS NOT NULL
          AND ST_Within(ST_SetSRID(ST_MakePoint(p.lon, p.lat), 4326), au.g)
        ORDER BY p.poi_type ASC NULLS LAST, p.name ASC NULLS LAST, p.id ASC
        LIMIT :row_limit
    """

    try:
        rows = db.execute(text(sql_text), bind).fetchall()
    except Exception:
        return {
            "counts_by_type": {k: 0 for k in POI_TYPE_LABELS},
            "by_type": {k: [] for k in POI_TYPE_LABELS},
            "pcn_capped": False,
            "poi_total": 0,
            "row_truncated": False,
        }

    counts: Dict[str, int] = defaultdict(int)
    items_by_type: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    pcn_seen = 0
    row_truncated = len(rows) >= int(row_limit)

    for row in rows:
        pt = str(row.poi_type or "")
        counts[pt] += 1
        rec = {"id": int(row.id), "name": row.name, "lat": float(row.lat), "lon": float(row.lon)}
        if pt == "pcn":
            pcn_seen += 1
            if len(items_by_type["pcn"]) < int(pcn_list_limit):
                items_by_type["pcn"].append(rec)
        else:
            items_by_type[pt].append(rec)

    pcn_capped = pcn_seen > len(items_by_type["pcn"])

    counts_by_type: Dict[str, int] = {k: int(counts.get(k, 0)) for k in POI_TYPE_LABELS}
    by_type: Dict[str, List[Dict[str, Any]]] = {k: items_by_type.get(k, []) for k in POI_TYPE_LABELS}
    poi_total = sum(counts_by_type.values())

    return {
        "counts_by_type": counts_by_type,
        "by_type": by_type,
        "pcn_capped": pcn_capped,
        "poi_total": poi_total,
        "row_truncated": row_truncated,
    }


def list_hdb_buildings_in_planning_union(
    db: "Session",
    *,
    region_c: Optional[str] = None,
    town_names: Optional[List[str]] = None,
    min_area: float = 0,
    max_area: float = 999999,
    postal_prefix: Optional[str] = None,
    limit: int = 2000,
    offset: int = 0,
) -> Dict[str, Any]:
    """HDB building footprints inside the URA planning-area union for ``region_c`` and/or towns."""
    from sqlalchemy import text

    where_clause, bind_base = _planning_union_where_clause(region_c, town_names)
    if where_clause is None:
        return {"type": "FeatureCollection", "features": [], "totalCount": 0}

    postal_filter = "AND hb.postal_cod LIKE :postal_prefix" if postal_prefix else ""
    bind: Dict[str, Any] = {
        **bind_base,
        "min_area": min_area,
        "max_area": max_area,
        "lim": int(limit),
        "off": int(offset),
    }
    if postal_prefix:
        bind["postal_prefix"] = postal_prefix + "%"

    sql = text(
        f"""
        WITH area_union AS (
            SELECT ST_UnaryUnion(ST_Collect(pa.geom)) AS g
            FROM ura_mp19_planning_areas_no_sea pa
            WHERE {where_clause}
        )
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', COALESCE(json_agg(feat), '[]'::json),
            'totalCount', (
                SELECT COUNT(*)::int FROM hdb_buildings hb
                CROSS JOIN area_union au
                WHERE hb.shape_area BETWEEN :min_area AND :max_area
                  {postal_filter}
                  AND au.g IS NOT NULL
                  AND ST_Within(hb.geom, au.g)
            )
        ) AS geojson
        FROM (
            SELECT json_build_object(
                'type', 'Feature',
                'geometry', ST_AsGeoJSON(hb.geom, 6)::json,
                'properties', json_build_object(
                    'blk_no', hb.blk_no,
                    'st_cod', hb.st_cod,
                    'entityid', hb.entityid,
                    'postal_cod', hb.postal_cod,
                    'inc_crc', hb.inc_crc,
                    'fmel_upd_d', hb.fmel_upd_d,
                    'shape_area', hb.shape_area,
                    'shape_len', hb.shape_len,
                    'objectid', hb.objectid
                )
            ) AS feat
            FROM hdb_buildings hb
            CROSS JOIN area_union au
            WHERE hb.shape_area BETWEEN :min_area AND :max_area
              {postal_filter}
              AND au.g IS NOT NULL
              AND ST_Within(hb.geom, au.g)
            ORDER BY hb.id
            LIMIT :lim OFFSET :off
        ) sub
        """
    )

    row = db.execute(sql, bind).fetchone()
    if row is None or row[0] is None:
        return {"type": "FeatureCollection", "features": [], "totalCount": 0}
    return row[0]


def build_area_amenity_breakdown(
    db: "Session",
    *,
    region_c: Optional[str] = None,
    town_names: Optional[List[str]] = None,
    as_of: Optional[date] = None,
) -> Dict[str, Any]:
    """MRT + POI payload for selected URA planning-area union (region and/or towns)."""
    as_of_d = as_of if as_of is not None else date.today()
    mrts = list_mrts_in_planning_union(db, region_c=region_c, town_names=town_names, as_of=as_of_d)
    operational = [
        m
        for m in mrts
        if str(m.get("pit_state") or "").strip().upper() == "OPERATIONAL"
    ]
    upcoming = [
        m
        for m in mrts
        if str(m.get("pit_state") or "").strip().upper()
        in ("COMMITTED_DATED", "COMMITTED_ESTIMATED", "ANNOUNCED_UNDATED")
    ]
    unknown = [m for m in mrts if m not in operational and m not in upcoming]
    pois_block = list_pois_in_planning_union(db, region_c=region_c, town_names=town_names)

    towns_norm = [
        t.strip().upper()
        for t in (town_names or [])
        if t and str(t).strip()
    ]
    rc_clean = (region_c or "").strip().upper() or None
    if towns_norm:
        area_names = towns_norm
    elif rc_clean:
        area_names = [rc_clean]
    else:
        area_names = []

    return {
        "area_names": area_names,
        "region_c": rc_clean,
        "mrts": {
            "operational": operational,
            "upcoming": upcoming,
            "unknown": unknown,
            "count": len(mrts),
        },
        "pois": {
            "counts_by_type": pois_block["counts_by_type"],
            "by_type": pois_block["by_type"],
            "pcn_capped": pois_block["pcn_capped"],
            "poi_total": pois_block["poi_total"],
            "row_truncated": pois_block.get("row_truncated", False),
        },
    }


def get_mrt_stations_geojson(db: "Session") -> Dict:
    """Return all MRT stations as a GeoJSON FeatureCollection."""
    from sqlalchemy import text
    sql = text("""
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', COALESCE(json_agg(
                json_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(ps.geom)::json,
                    'properties', json_build_object(
                        'station_name', m.station_name,
                        'station_code', m.station_code,
                        'station_status', m.station_status,
                        'physical_station_id', ps.id,
                        'source_note', m.source_note,
                        'dates_source_type', m.dates_source_type,
                        'network_line', m.network_line,
                        'opening_date', m.opening_date,
                        'expected_completion', m.expected_completion,
                        'announcement_date', m.announcement_date,
                        'opening_date_raw', m.opening_date_raw,
                        'expected_completion_raw', m.expected_completion_raw,
                        'pit_state', (
                            CASE
                                WHEN m.opening_date IS NOT NULL
                                     AND m.opening_date <= CURRENT_DATE
                                    THEN 'OPERATIONAL'
                                WHEN m.announcement_date IS NOT NULL
                                     AND m.announcement_date <= CURRENT_DATE
                                     AND (m.opening_date IS NULL
                                          OR m.opening_date > CURRENT_DATE)
                                    THEN
                                    CASE
                                        WHEN m.opening_date IS NOT NULL THEN 'COMMITTED_DATED'
                                        WHEN m.expected_completion IS NOT NULL
                                            THEN 'COMMITTED_ESTIMATED'
                                        ELSE 'ANNOUNCED_UNDATED'
                                    END
                                ELSE 'UNKNOWN'
                            END
                        ),
                        'display_state', (
                            CASE
                                WHEN m.opening_date IS NOT NULL
                                     AND m.opening_date <= CURRENT_DATE
                                    THEN 'OPERATIONAL'
                                WHEN m.announcement_date IS NOT NULL
                                     AND m.announcement_date <= CURRENT_DATE
                                     AND (m.opening_date IS NULL
                                          OR m.opening_date > CURRENT_DATE)
                                    THEN 'PLANNED'
                                ELSE 'UNKNOWN'
                            END
                        )
                    )
                )
            ), '[]'::json)
        ) AS geojson
        FROM mrt_station_lines m
        INNER JOIN mrt_physical_stations ps ON ps.id = m.physical_station_id
        WHERE ps.geom IS NOT NULL
    """)
    row = db.execute(sql).fetchone()
    if row is None or row[0] is None:
        return {"type": "FeatureCollection", "features": []}
    result = row[0]
    if any(f["properties"].get("dates_source_type") == "unavailable" for f in result["features"]):
        result["coverage_note"] = (
            "Local station location snapshot: opening/status history is unavailable for some stations "
            "(shown in grey under All / Unknown). Future stations are not included in this snapshot."
        )
    return result


# ---------------------------------------------------------------------------
# POI analytics (``poi_locations``) — see docs/knowledge/poi-data-km.md
# ---------------------------------------------------------------------------

POI_TYPE_LABELS: Dict[str, str] = {
    "school_top20": "Top primary schools",
    "school_any": "Primary schools",
    "mall": "Shopping malls",
    "supermarket": "Supermarkets",
    "park": "Parks & nature",
    "market": "Markets & food centres",
    "pcn": "Park connectors",
}


def query_pois_within_radius(
    db: "Session",
    lat: float,
    lng: float,
    radius_m: float,
    *,
    limit: int = 8000,
) -> List[Dict]:
    """Return POI rows within ``radius_m`` (geodesic), sorted by distance ascending."""
    from sqlalchemy import text

    lim = max(1, min(int(limit), 20_000))
    r = max(float(radius_m), 1.0)
    sql = text(
        """
        SELECT
            id,
            poi_type,
            name,
            lat,
            lon,
            source_file,
            ST_Distance(
                ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
            )::double precision AS distance_m
        FROM poi_locations
        WHERE ST_DWithin(
            ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography,
            ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
            :radius_m
        )
        ORDER BY distance_m ASC
        LIMIT :lim
        """
    )
    try:
        rows = db.execute(sql, {"lat": lat, "lng": lng, "radius_m": r, "lim": lim}).fetchall()
    except Exception:
        return []

    out: List[Dict] = []
    for row in rows:
        out.append(
            {
                "id": int(row.id),
                "poi_type": row.poi_type,
                "name": row.name,
                "lat": float(row.lat),
                "lon": float(row.lon),
                "source_file": row.source_file,
                "distance_m": round(float(row.distance_m), 1),
            }
        )
    return out


def nearest_school_amenity_within_radius(
    db: "Session",
    lat: float,
    lng: float,
    *,
    radius_m: float = 3000.0,
) -> Dict[str, Any] | None:
    """Closest ``school_top20`` or ``school_any`` POI within ``radius_m``.

    Faster than fetching thousands of unrelated POIs (used by valuation ``amenities.school``).
    """
    from sqlalchemy import text

    r = max(float(radius_m), 1.0)
    sql = text(
        """
        SELECT
            id,
            poi_type,
            name,
            lat,
            lon,
            source_file,
            ST_Distance(
                ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
            )::double precision AS distance_m
        FROM poi_locations
        WHERE poi_type IN ('school_top20', 'school_any')
          AND ST_DWithin(
              ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography,
              ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
              :radius_m
          )
        ORDER BY distance_m ASC
        LIMIT 1
        """
    )
    try:
        row = db.execute(sql, {"lat": lat, "lng": lng, "radius_m": r}).fetchone()
    except Exception:
        return None

    if row is None:
        return None
    return {
        "id": int(row.id),
        "poi_type": row.poi_type,
        "name": row.name,
        "lat": float(row.lat),
        "lon": float(row.lon),
        "source_file": row.source_file,
        "distance_m": round(float(row.distance_m), 1),
    }


def nearest_named_poi_per_type(
    db: "Session",
    lat: float,
    lng: float,
) -> List[Dict[str, Any]]:
    """Nearest POI row per ``poi_type`` among rows with non-empty ``name``; no radius filter."""
    from sqlalchemy import text

    sql = text(
        """
        SELECT DISTINCT ON (p.poi_type)
            p.id,
            p.poi_type,
            p.name,
            p.lat,
            p.lon,
            p.source_file,
            ST_Distance(
                ST_SetSRID(ST_MakePoint(p.lon, p.lat), 4326)::geography,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
            )::double precision AS distance_m
        FROM poi_locations p
        WHERE p.name IS NOT NULL AND TRIM(p.name) <> ''
        ORDER BY p.poi_type, distance_m ASC
        """
    )
    try:
        rows = db.execute(sql, {"lat": lat, "lng": lng}).fetchall()
    except Exception:
        return []

    out: List[Dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "id": int(row.id),
                "poi_type": row.poi_type,
                "name": row.name,
                "lat": float(row.lat),
                "lon": float(row.lon),
                "source_file": row.source_file,
                "distance_m": round(float(row.distance_m), 1),
            }
        )
    return out


def build_nearest_named_poi_by_type_payload(
    db: "Session",
    lat: float,
    lng: float,
    *,
    address_label: Optional[str] = None,
    postal_for_display: Optional[str] = None,
) -> Dict[str, Any]:
    """``by_type`` payload for UI: one nearest *named* POI per type (global nearest, no radius cap)."""
    pois = nearest_named_poi_per_type(db, lat, lng)
    by_poitype = {p["poi_type"]: p for p in pois}

    type_order = [
        "school_top20",
        "school_any",
        "mall",
        "supermarket",
        "park",
        "market",
        "pcn",
    ]
    by_type: List[Dict[str, Any]] = []
    for t in type_order:
        if t not in by_poitype:
            continue
        p = by_poitype[t]
        by_type.append(
            {
                "poi_type": t,
                "label": POI_TYPE_LABELS.get(t, t),
                "count": 1,
                "items": [p],
            }
        )
    for t, p in sorted(by_poitype.items(), key=lambda kv: kv[0]):
        if t in type_order:
            continue
        by_type.append(
            {
                "poi_type": t,
                "label": POI_TYPE_LABELS.get(t, t),
                "count": 1,
                "items": [p],
            }
        )

    return {
        "lat": lat,
        "lng": lng,
        "address": address_label,
        "postal_code": postal_for_display,
        "poi_total": len(pois),
        "by_type": by_type,
    }


def build_poi_nearby_payload(
    db: "Session",
    lat: float,
    lng: float,
    radius_m: float,
    *,
    address_label: Optional[str] = None,
    postal_for_display: Optional[str] = None,
) -> Dict:
    """Counts and lists by type (distance-sorted) within ``radius_m``."""
    pois = query_pois_within_radius(db, lat, lng, radius_m)

    counts: Dict[str, int] = {}
    buckets: Dict[str, List[Dict]] = {}
    for p in pois:
        t = p["poi_type"]
        counts[t] = counts.get(t, 0) + 1
        buckets.setdefault(t, []).append(p)

    type_order = [
        "school_top20",
        "school_any",
        "mall",
        "supermarket",
        "park",
        "market",
        "pcn",
    ]
    by_type: List[Dict] = []
    for t in type_order:
        if t not in buckets:
            continue
        items = sorted(buckets[t], key=lambda x: x["distance_m"])
        by_type.append(
            {
                "poi_type": t,
                "label": POI_TYPE_LABELS.get(t, t),
                "count": len(items),
                "items": items,
            }
        )
    for t, items in buckets.items():
        if t in type_order:
            continue
        items = sorted(items, key=lambda x: x["distance_m"])
        by_type.append(
            {
                "poi_type": t,
                "label": POI_TYPE_LABELS.get(t, t),
                "count": len(items),
                "items": items,
            }
        )

    return {
        "lat": lat,
        "lng": lng,
        "radius_m": radius_m,
        "address": address_label,
        "postal_code": postal_for_display,
        "poi_total": len(pois),
        "counts_by_type": dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_type": by_type,
    }
