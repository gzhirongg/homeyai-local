export type NearestPoi = {
    type: string;
    label: string;
    name: string | null;
    distance_m: number;
};

export type NearestMrt = {
    name: string;
    walk_time_mins: number | null;
    walk_distance_m: number | null;
    pt_time_mins: number | null;
    straight_line_m: number | null;
};

export type AmenitySummary = {
    nearestMrts: NearestMrt[];
    nearestPois: NearestPoi[];
};

type TravelLegJson = { time_mins?: unknown; distance_m?: unknown };

type AmenityMrtStationJson = {
    name?: unknown;
    canonical_name?: unknown;
    station_name?: unknown;
    distance_m?: unknown;
    travel_times?: { walk?: TravelLegJson; pt?: TravelLegJson };
    lines?: Array<{ station_name?: unknown }>;
};

type PoiByTypeJson = {
    poi_type?: unknown;
    label?: unknown;
    items?: Array<{ name?: unknown; distance_m?: unknown }>;
};

function numOrNull(v: unknown): number | null {
    if (typeof v === "number" && Number.isFinite(v)) return v;
    return null;
}

export function extractNearestMrtsFromScore(scoreJson: unknown): NearestMrt[] {
    if (!scoreJson || typeof scoreJson !== "object") return [];
    const o = scoreJson as Record<string, unknown>;
    if (o.no_coordinates === true) return [];
    const mrt = o.mrt as Record<string, unknown> | undefined;
    const operational = mrt?.operational;
    if (!Array.isArray(operational)) return [];

    return operational.slice(0, 2).map((raw): NearestMrt => {
        const s = raw as AmenityMrtStationJson;
        let name =
            typeof s.name === "string"
                ? s.name
                : typeof s.canonical_name === "string" && s.canonical_name.trim()
                  ? `${s.canonical_name.trim()} MRT`
                  : typeof s.lines?.[0]?.station_name === "string"
                    ? String(s.lines[0].station_name)
                    : "—";
        if (name !== "—" && !/\bMRT\b/i.test(name)) name = `${name} MRT`;

        const walk = s.travel_times?.walk;
        const pt = s.travel_times?.pt;

        return {
            name,
            walk_time_mins: numOrNull(walk?.time_mins),
            walk_distance_m: numOrNull(walk?.distance_m),
            pt_time_mins: numOrNull(pt?.time_mins),
            straight_line_m: numOrNull(s.distance_m),
        };
    });
}

export function formatMrtAccessLine(m: NearestMrt): {
    primary: string;
    transitHint: string | null;
} {
    const chunks: string[] = [];
    if (m.walk_time_mins != null) chunks.push(`${m.walk_time_mins} min walk`);
    if (m.walk_distance_m != null) chunks.push(formatHorizontalDistanceM(m.walk_distance_m));

    let primary: string;
    if (chunks.length > 0) {
        primary = chunks.join(" · ");
    } else if (m.straight_line_m != null) {
        primary = `≈ ${formatHorizontalDistanceM(m.straight_line_m)} straight-line`;
    } else {
        primary = "Walk / transit routing unavailable";
    }

    let transitHint: string | null = null;
    const wt = m.walk_time_mins;
    const pt = m.pt_time_mins;
    if (pt != null && wt != null && pt < wt) transitHint = `${Math.round(pt)} min transit`;

    return { primary, transitHint };
}

export function extractNearestPois(poiJson: unknown): NearestPoi[] {
    if (!poiJson || typeof poiJson !== "object") return [];
    const o = poiJson as Record<string, unknown>;
    if (o.no_coordinates === true) return [];
    const byType = o.by_type;
    if (!Array.isArray(byType)) return [];

    const out: NearestPoi[] = [];
    for (const raw of byType) {
        const grp = raw as PoiByTypeJson;
        const items = grp.items;
        if (!Array.isArray(items) || items.length === 0) continue;
        const first = items[0] as Record<string, unknown>;
        const d = numOrNull(first.distance_m);
        if (d === null) continue;
        const ptype =
            typeof grp.poi_type === "string" && grp.poi_type.trim()
                ? grp.poi_type.trim()
                : "poi";
        const label =
            typeof grp.label === "string" && grp.label.trim() ? grp.label.trim() : ptype;
        const rawName = first.name;
        const nm =
            typeof rawName === "string"
                ? rawName.trim() || null
                : rawName != null && String(rawName).trim()
                  ? String(rawName).trim()
                  : null;
        out.push({ type: ptype, label, name: nm, distance_m: d });
    }
    return out.sort((a, b) => a.distance_m - b.distance_m);
}

export function formatHorizontalDistanceM(metres: number): string {
    if (!Number.isFinite(metres)) return "—";
    if (metres >= 1000) return `${(metres / 1000).toFixed(metres >= 10000 ? 0 : 1)} km`;
    return `${Math.round(metres)} m`;
}

export function findPoiByType(pois: NearestPoi[], type: string): NearestPoi | null {
    return pois.find((p) => p.type === type) ?? null;
}

export function findPoiByTypePattern(pois: NearestPoi[], pattern: RegExp): NearestPoi | null {
    return pois.find((p) => pattern.test(p.type) || pattern.test(p.label)) ?? null;
}

/** Composite leisure amenities proxy for driver display (UI-only). */
export function buildAmenitiesCompositeProxy(pois: NearestPoi[]): string | null {
    const mall = findPoiByType(pois, "mall");
    const hawker = findPoiByType(pois, "market");
    const park = findPoiByType(pois, "park");
    const sports =
        findPoiByTypePattern(pois, /sport/i) ??
        findPoiByTypePattern(pois, /stadium|hub|complex/i);

    const parts: string[] = [];
    const push = (poi: NearestPoi | null) => {
        if (!poi?.name) return;
        parts.push(`${poi.name} · ${formatHorizontalDistanceM(poi.distance_m)}`);
    };
    push(mall);
    push(hawker);
    push(park);
    push(sports);

    return parts.length ? parts.join("  ·  ") : null;
}
