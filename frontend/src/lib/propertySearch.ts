import API_BASE from "@/lib/apiBase";

export const MIN_QUERY_LEN = 2;
export const FULL_POSTAL_LEN = 6;
export const AUTOCOMPLETE_DEBOUNCE_MS = 300;

export type PropertySearchHit = {
    name: string;
    postal_code: string;
};

export type SearchRoute = "postal" | "address";

export type FlatOption = {
    flat_type: string;
    flat_model_grouped: string;
    units_sold: number;
    avg_floor_area_sqm: number | null;
    min_floor_area_sqm: number | null;
    max_floor_area_sqm: number | null;
    latest_lease_commence_year: number | null;
    min_storey_midpoint: number | null;
    max_storey_midpoint: number | null;
    resale_transaction_count: number;
    median_resale_price_sgd: number | null;
    latest_resale_month: string | null;
    latest_resale_price_sgd: number | null;
};

export type PropertyLookupResult = {
    address_label: string;
    postal_code: string;
    town: string;
    region: string;
    latitude: number | null;
    longitude: number | null;
    resale_transaction_count: number;
    resale_month_range_start: string | null;
    resale_month_range_end: string | null;
    flat_options: FlatOption[];
    year_completed: number | null;
    building_max_storey: number | null;
};

/** Coerce optional API / cached fields so UI always sees null instead of undefined. */
export function normalizePropertyLookup(
    raw: PropertyLookupResult
): PropertyLookupResult {
    const flat_options = (raw.flat_options ?? []).map((o) => ({
        ...o,
        units_sold:
            typeof o.units_sold === "number" && Number.isFinite(o.units_sold)
                ? Math.max(0, Math.round(o.units_sold))
                : 0,
        resale_transaction_count: o.resale_transaction_count ?? 0,
        median_resale_price_sgd: o.median_resale_price_sgd ?? null,
        latest_resale_month: o.latest_resale_month ?? null,
        latest_resale_price_sgd: o.latest_resale_price_sgd ?? null,
    }));

    let building_max_storey: number | null =
        typeof raw.building_max_storey === "number" &&
        Number.isFinite(raw.building_max_storey)
            ? Math.round(raw.building_max_storey)
            : null;
    if (building_max_storey !== null && building_max_storey < 1) {
        building_max_storey = null;
    }

    let year_completed: number | null = null;
    if (
        typeof raw.year_completed === "number" &&
        Number.isFinite(raw.year_completed)
    ) {
        const y = Math.round(raw.year_completed);
        if (y >= 1937 && y <= 2100) year_completed = y;
    }

    return {
        ...raw,
        latitude: raw.latitude ?? null,
        longitude: raw.longitude ?? null,
        resale_transaction_count: raw.resale_transaction_count ?? 0,
        resale_month_range_start: raw.resale_month_range_start ?? null,
        resale_month_range_end: raw.resale_month_range_end ?? null,
        flat_options,
        year_completed,
        building_max_storey,
    };
}

/** All-digit trimmed query → postal prefix search; otherwise address search. */
export function routeSearchQuery(q: string): SearchRoute {
    const t = q.trim();
    return /^\d+$/.test(t) ? "postal" : "address";
}

/** Digits to highlight in postal code for the current query. */
export function postalHighlightForQuery(query: string, route: SearchRoute): string {
    const t = query.trim();
    if (route === "postal") return t.replace(/\D/g, "");
    const digits = t.replace(/\D/g, "");
    return digits.length >= MIN_QUERY_LEN ? digits : "";
}

export async function searchProperties(q: string): Promise<PropertySearchHit[]> {
    const t = q.trim();
    if (t.length < MIN_QUERY_LEN) return [];

    const route = routeSearchQuery(t);
    const url =
        route === "postal"
            ? `${API_BASE}/api/analytics/properties/postal_search?postal_q=${encodeURIComponent(t.replace(/\D/g, ""))}`
            : `${API_BASE}/api/analytics/properties/search?q=${encodeURIComponent(t)}`;

    const res = await fetch(url);
    if (!res.ok) return [];

    const data = (await res.json()) as { results?: PropertySearchHit[] };
    return (data.results ?? []).map((h) => ({
        name: h.name ?? "",
        postal_code: h.postal_code ?? "",
    }));
}

export async function lookupProperty(postal: string): Promise<PropertyLookupResult> {
    const q = encodeURIComponent(postal.replace(/\D/g, ""));
    const res = await fetch(`${API_BASE}/api/properties/lookup?postal_code=${q}`);
    if (res.status === 404) {
        throw new Error("No records found");
    }
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail || "Lookup failed");
    }
    const data = (await res.json()) as PropertyLookupResult;
    return normalizePropertyLookup(data);
}
