import type { PropertyLookupResult } from "@/components/PropertySearchInput";
import type {
    ShapExplanation,
    ShapExplanationRow,
} from "@/components/valuation/ValuationResultPanel";
import type { ValuationFormData } from "@/components/valuation/ValuationUnitFormPane";
import { buildAmenitiesCompositeProxy, formatHorizontalDistanceM } from "@/lib/poiExtract";
import type { NearestPoi } from "@/lib/poiExtract";

export type DriverCategoryId =
    | "unit_size"
    | "floor_level"
    | "flat_type"
    | "flat_model"
    | "lease_remaining"
    | "location_town"
    | "cbd_proximity"
    | "estate_maturity"
    | "market_timing"
    | "convenience_transport"
    | "future_transport"
    | "primary_school"
    | "convenience_amenities"
    | "landuse_nuisances"
    | "neighbourhood_amenities";

export const DRIVER_CATEGORY_LABELS: Record<DriverCategoryId, string> = {
    unit_size: "Unit size",
    floor_level: "Floor level",
    flat_type: "Flat type",
    flat_model: "Flat model",
    lease_remaining: "Lease remaining",
    location_town: "Location (Town)",
    cbd_proximity: "CBD & Urban Centrality",
    estate_maturity: "Estate Maturity",
    market_timing: "Market timing",
    convenience_transport: "Convenience (Transport)",
    future_transport: "Future Development (Transport)",
    primary_school: "Top Primary School Accessibility",
    convenience_amenities: "Convenience (Amenities)",
    landuse_nuisances: "Nuisance Land Use Nearby",
    neighbourhood_amenities: "Neighbourhood Facilities",
};

const FLAT_TYPE_FROM_ORDINAL: Record<number, string> = {
    1: "1 ROOM",
    2: "2 ROOM",
    3: "3 ROOM",
    4: "4 ROOM",
    5: "5 ROOM",
    6: "EXECUTIVE",
    7: "MULTI-GENERATION",
};

/** Map engineered column or raw SHAP feature name → category id. */
const SOURCE_COLUMN_TO_CATEGORY: Record<string, DriverCategoryId> = {
    floor_area_sqm: "unit_size",
    storey_mid: "floor_level",
    flat_type_encoded: "flat_type",
    remaining_lease_years: "lease_remaining",
    sale_year: "market_timing",
    sale_month_sin: "market_timing",
    sale_month_cos: "market_timing",
    months_since_2015: "market_timing",
    volume_lagged_3m: "market_timing",
    interest_rate_lagged: "market_timing",
    lat: "location_town",
    lon: "location_town",
    town: "location_town",
    region: "location_town",
    flat_model: "flat_model",
    flat_model_grouped: "flat_model",
    dist_to_nearest_op_mrt: "convenience_transport",
    travel_time_to_active_mrt: "convenience_transport",
    pt_time_savings_vs_walk: "convenience_transport",
    line_connectivity_index: "convenience_transport",
    num_unique_lines_within_1km: "convenience_transport",
    nearest_planned_mrt_dist: "future_transport",
    days_to_mrt_opening: "future_transport",
    days_since_mrt_announcement: "future_transport",
    speculative_upside_score: "future_transport",
    has_future_upside: "future_transport",
    project_completion_fraction: "future_transport",
    dist_nearest_primary_school: "primary_school",
    is_within_1km_primary_school: "primary_school",
    is_within_2km_primary_school: "primary_school",
    dist_nearest_mall: "convenience_amenities",
    mall_count_within_1_5km: "convenience_amenities",
    // Nuisance dis-amenities (heavy industry, cemeteries, depots / prisons)
    dist_to_nearest_b2_zone: "landuse_nuisances",
    b2_zoning_ratio_1km: "landuse_nuisances",
    dist_to_nearest_cemetery: "landuse_nuisances",
    dist_to_nearest_special_use: "landuse_nuisances",
    is_proximity_nuisance: "landuse_nuisances",
    // Positive neighbourhood facilities
    dist_to_nearest_business_park: "neighbourhood_amenities",
    // CBD / urban centrality
    dist_cbd: "cbd_proximity",
    dist_airport: "cbd_proximity",
    nearby_high_density_score: "cbd_proximity",
    hub_score: "cbd_proximity",
    density_age_interaction: "cbd_proximity",
    // Estate maturity (town-level supply/age aggregates)
    avg_residential_block_age_years: "estate_maturity",
    town_completed_residential_units_stock: "estate_maturity",
    town_land_area_km2: "estate_maturity",
    town_dwelling_unit_density: "estate_maturity",
    town_units_under_construction: "estate_maturity",
    town_hdb_completed_units_roll36m: "estate_maturity",
    town_supply_maturity_ratio: "estate_maturity",
    town_bto_velocity_36m: "estate_maturity",
    log1p_town_completed_residential_units_stock: "estate_maturity",
    log1p_town_hdb_roll36_completed: "estate_maturity",
    log1p_town_units_under_construction: "estate_maturity",
    log1p_town_dwelling_unit_density: "estate_maturity",
    log1p_town_supply_maturity_ratio: "estate_maturity",
};

const FEATURE_PREFIX_TO_CATEGORY: Array<[RegExp, DriverCategoryId]> = [
    // Estate maturity prefixes checked before the generic town_ rule
    [/^log1p_town_/, "estate_maturity"],
    [/^town_bto_/, "estate_maturity"],
    [/^town_/, "location_town"],
    [/^region_/, "location_town"],
    [/^flat_model_grouped_/, "flat_model"],
    [/^flat_model_/, "flat_model"],
    // Masterplan area buffers around home: parks, sports, commercial, health, worship
    [/^area_/, "neighbourhood_amenities"],
];

export type DriverContext = {
    transport_current?: string | null;
    transport_future?: string | null;
    primary_school?: string | null;
    landuse_negative?: string | null;
    coastline?: { distance_km: number; landmark: string } | null;
};

export type DriverRow = {
    id: DriverCategoryId;
    label: string;
    proxyText: string | null;
    /** Display value: rescaled share-of-gap SGD when baseline+predicted available, else marginal SGD. */
    contributionSgd?: number;
    /** Raw SHAP marginal SGD ("if only this feature contributed phi_i") for diagnostic tooltips. */
    marginalContributionSgd?: number;
    contributionLog: number;
    sourceFeatures: string[];
    note?: string;
};

export type SummarizeDriversContext = {
    formData: ValuationFormData;
    selectedProperty: PropertyLookupResult | null;
    driverContext?: DriverContext | null;
    amenitiesPois?: NearestPoi[];
    valuationMonth?: string;
    baselinePrice?: number | null;
    predictedPrice?: number | null;
};

function titleCaseWords(s: string): string {
    return s
        .split(/\s+/)
        .filter(Boolean)
        .map((w) => w.charAt(0) + w.slice(1).toLowerCase())
        .join(" ");
}

function titleCaseFlatType(ft: string): string {
    return ft
        .split(/\s+/)
        .map((w) => (w.length <= 2 && /ROOM/i.test(w) ? w : titleCaseWords(w)))
        .join(" ")
        .replace(/\bRoom\b/g, "Room");
}

function resolveCategoryId(row: ShapExplanationRow): DriverCategoryId | null {
    const src = row.source_column?.trim();
    if (src && SOURCE_COLUMN_TO_CATEGORY[src]) {
        return SOURCE_COLUMN_TO_CATEGORY[src];
    }
    const feat = row.feature?.trim() ?? "";
    if (feat && SOURCE_COLUMN_TO_CATEGORY[feat]) {
        return SOURCE_COLUMN_TO_CATEGORY[feat];
    }
    for (const [re, cat] of FEATURE_PREFIX_TO_CATEGORY) {
        if (re.test(feat)) return cat;
    }
    return null;
}

function formatDistanceMetresOrKm(metres: number): string {
    return formatHorizontalDistanceM(metres);
}

function formatDistanceKm(km: number): string {
    if (km < 1) return `${Math.round(km * 1000)} m`;
    return `${km.toFixed(1)} km`;
}

function formatFeatureValueFallback(
    categoryId: DriverCategoryId,
    value: number | string | null | undefined
): string | null {
    if (value == null || value === "") return null;
    if (typeof value === "string") return titleCaseWords(value.replace(/_/g, " "));
    if (typeof value !== "number" || !Number.isFinite(value)) return null;

    switch (categoryId) {
        case "unit_size":
            return `${value} sqm`;
        case "floor_level":
            return `${Math.round(value)}th floor`;
        case "flat_type": {
            const ft = FLAT_TYPE_FROM_ORDINAL[Math.round(value)];
            return ft ? titleCaseFlatType(ft) : String(value);
        }
        case "lease_remaining":
            return `${Math.round(value)} yrs left`;
        case "convenience_transport":
        case "primary_school":
        case "convenience_amenities":
            return formatDistanceMetresOrKm(value);
        case "future_transport":
            return formatDistanceMetresOrKm(value);
        case "landuse_nuisances":
        case "neighbourhood_amenities":
            return formatDistanceKm(value);
        default:
            return String(value);
    }
}

function buildProxyForCategory(
    categoryId: DriverCategoryId,
    ctx: SummarizeDriversContext,
    rowsInBucket: ShapExplanationRow[]
): { proxyText: string | null; note?: string } {
    const { formData, selectedProperty, driverContext, amenitiesPois, valuationMonth } = ctx;

    switch (categoryId) {
        case "unit_size":
            return {
                proxyText:
                    formData.floor_area_sqm != null
                        ? `${formData.floor_area_sqm} sqm`
                        : formatFeatureValueFallback(categoryId, rowsInBucket[0]?.feature_value),
            };
        case "floor_level":
            return {
                proxyText:
                    formData.storey_midpoint != null
                        ? `${formData.storey_midpoint}th floor`
                        : formatFeatureValueFallback(categoryId, rowsInBucket[0]?.feature_value),
            };
        case "flat_type":
            return {
                proxyText: formData.flat_type
                    ? titleCaseFlatType(formData.flat_type)
                    : formatFeatureValueFallback(categoryId, rowsInBucket[0]?.feature_value),
            };
        case "flat_model": {
            const fromRow = rowsInBucket.find((r) => r.feature_value != null)?.feature_value;
            const val =
                typeof fromRow === "string"
                    ? titleCaseWords(fromRow.replace(/_/g, " "))
                    : formData.flat_model_grouped
                      ? titleCaseWords(formData.flat_model_grouped)
                      : null;
            return { proxyText: val };
        }
        case "lease_remaining":
            return {
                proxyText:
                    formData.remaining_lease_years != null
                        ? `${formData.remaining_lease_years} yrs left`
                        : formatFeatureValueFallback(categoryId, rowsInBucket[0]?.feature_value),
            };
        case "location_town": {
            const town = selectedProperty?.town?.trim();
            const region = formData.region?.trim() || selectedProperty?.region?.trim();
            if (town) {
                const t = titleCaseWords(town);
                return {
                    proxyText: region ? `${t}, ${titleCaseWords(region)}` : t,
                };
            }
            return { proxyText: null };
        }
        case "market_timing": {
            const ym =
                valuationMonth ??
                new Date().toISOString().slice(0, 7);
            const [y, m] = ym.split("-");
            const monthNames = [
                "Jan",
                "Feb",
                "Mar",
                "Apr",
                "May",
                "Jun",
                "Jul",
                "Aug",
                "Sep",
                "Oct",
                "Nov",
                "Dec",
            ];
            const mi = parseInt(m ?? "1", 10) - 1;
            const label = monthNames[mi] ?? m;
            return { proxyText: `Valued in ${label} ${y}` };
        }
        case "convenience_transport":
            return {
                proxyText:
                    driverContext?.transport_current ??
                    formatFeatureValueFallback(
                        categoryId,
                        rowsInBucket.find((r) => r.source_column === "dist_to_nearest_op_mrt")
                            ?.feature_value
                    ),
            };
        case "future_transport":
            return {
                proxyText:
                    driverContext?.transport_future ??
                    formatFeatureValueFallback(
                        categoryId,
                        rowsInBucket.find((r) => r.source_column === "nearest_planned_mrt_dist")
                            ?.feature_value
                    ),
            };
        case "primary_school":
            return {
                proxyText:
                    driverContext?.primary_school ??
                    formatFeatureValueFallback(
                        categoryId,
                        rowsInBucket.find((r) => r.source_column === "dist_nearest_primary_school")
                            ?.feature_value
                    ),
            };
        case "convenience_amenities": {
            const composite =
                amenitiesPois && amenitiesPois.length
                    ? buildAmenitiesCompositeProxy(amenitiesPois)
                    : null;
            const mallDist = rowsInBucket.find((r) => r.source_column === "dist_nearest_mall")
                ?.feature_value;
            const fallback =
                typeof mallDist === "number"
                    ? `Nearest mall · ${formatDistanceMetresOrKm(mallDist)}`
                    : null;
            return {
                proxyText: composite ?? fallback,
                note: "Model attribution uses mall features; hawker, park, and sports-hub names are shown to round out the picture.",
            };
        }
        case "landuse_nuisances":
            return {
                proxyText:
                    driverContext?.landuse_negative ??
                    formatFeatureValueFallback(categoryId, rowsInBucket[0]?.feature_value),
                note: "Heavy industry (B2), cemeteries, and special-use zoning within walking distance.",
            };
        case "neighbourhood_amenities": {
            const bpRow = rowsInBucket.find(
                (r) => r.source_column === "dist_to_nearest_business_park"
            );
            const bpKm =
                bpRow?.feature_value != null && typeof bpRow.feature_value === "number"
                    ? bpRow.feature_value
                    : null;
            const areaParts: string[] = [];
            const labelMap: Record<string, string> = {
                comm: "commercial",
                park: "parks",
                sports: "sports",
                health: "health",
                worship: "places of worship",
            };
            for (const r of rowsInBucket) {
                const m = r.feature.match(/^area_(comm|park|sports|health|worship)_1000m$/);
                if (m && typeof r.feature_value === "number" && r.feature_value > 0) {
                    areaParts.push(labelMap[m[1]] ?? m[1]);
                }
            }
            const uniqueParts = Array.from(new Set(areaParts)).slice(0, 3);
            const segments: string[] = [];
            if (bpKm != null) {
                segments.push(`business park ${formatDistanceKm(bpKm)}`);
            }
            if (uniqueParts.length) {
                segments.push(`${uniqueParts.join(", ")} within 1 km`);
            }
            return {
                proxyText: segments.length ? segments.join(" · ") : null,
                note: "Masterplan buffers for parks, sports, health, commercial, and worship facilities around the unit.",
            };
        }
        case "cbd_proximity": {
            const cbdRow = rowsInBucket.find((r) => r.source_column === "dist_cbd");
            if (cbdRow?.feature_value != null && typeof cbdRow.feature_value === "number") {
                return { proxyText: `${formatDistanceKm(cbdRow.feature_value)} to CBD` };
            }
            return { proxyText: null };
        }
        case "estate_maturity": {
            const town = selectedProperty?.town?.trim() ?? formData.town?.trim();
            const ageRow = rowsInBucket.find(
                (r) => r.source_column === "avg_residential_block_age_years"
            );
            const townLabel = town ? titleCaseWords(town) : null;
            if (ageRow?.feature_value != null && typeof ageRow.feature_value === "number") {
                const yrs = Math.round(ageRow.feature_value);
                return {
                    proxyText: townLabel
                        ? `${townLabel} · avg block age ${yrs} yrs`
                        : `Avg block age ${yrs} yrs`,
                };
            }
            return { proxyText: townLabel ? `${townLabel} · estate supply & maturity` : null };
        }
        default:
            return { proxyText: null };
    }
}

export function summarizeShapDrivers(
    shapExplanation: ShapExplanation | null,
    ctx: SummarizeDriversContext,
    topN = 5
): DriverRow[] {
    if (!shapExplanation?.rows?.length) return [];

    const buckets = new Map<
        DriverCategoryId,
        { rows: ShapExplanationRow[]; sumSgd: number; sumLog: number; hasSgd: boolean }
    >();

    for (const row of shapExplanation.rows) {
        const cat = resolveCategoryId(row);
        if (!cat) continue;
        const b = buckets.get(cat) ?? {
            rows: [],
            sumSgd: 0,
            sumLog: 0,
            hasSgd: false,
        };
        b.rows.push(row);
        b.sumLog += row.contribution_log;
        if (row.contribution_sgd != null && Number.isFinite(row.contribution_sgd)) {
            b.sumSgd += row.contribution_sgd;
            b.hasSgd = true;
        }
        buckets.set(cat, b);
    }

    const dollarGap =
        typeof ctx.predictedPrice === "number" &&
        typeof ctx.baselinePrice === "number" &&
        Number.isFinite(ctx.predictedPrice) &&
        Number.isFinite(ctx.baselinePrice)
            ? ctx.predictedPrice - ctx.baselinePrice
            : null;

    const totalVisiblePhi = Array.from(buckets.values()).reduce(
        (acc, b) => acc + b.sumLog,
        0
    );

    const useRescale = dollarGap !== null && Math.abs(totalVisiblePhi) > 1e-6;

    // Rows whose summed log-space contribution is essentially zero are rounding noise.
    // ±0.005 in log space ≈ ±0.5% of price; smaller than that, the row adds visual
    // clutter without conveying a real signal.
    const LOG_PHI_NOISE_THRESHOLD = 0.005;

    const merged: DriverRow[] = [];
    for (const [id, b] of buckets) {
        if (Math.abs(b.sumLog) < LOG_PHI_NOISE_THRESHOLD) continue;
        const { proxyText, note } = buildProxyForCategory(id, ctx, b.rows);
        const contributionSgd = useRescale
            ? dollarGap! * (b.sumLog / totalVisiblePhi)
            : b.hasSgd
              ? b.sumSgd
              : undefined;
        merged.push({
            id,
            label: DRIVER_CATEGORY_LABELS[id],
            proxyText,
            contributionSgd,
            marginalContributionSgd: b.hasSgd ? b.sumSgd : undefined,
            contributionLog: b.sumLog,
            sourceFeatures: b.rows.map((r) => r.feature),
            note,
        });
    }

    merged.sort((a, b) => {
        const ia = Math.abs(a.contributionSgd ?? a.contributionLog);
        const ib = Math.abs(b.contributionSgd ?? b.contributionLog);
        return ib - ia;
    });

    return merged.slice(0, topN);
}

export function formatDriverImpactSgd(value: number): string {
    const sign = value >= 0 ? "+" : "−";
    const mag = Math.abs(Math.round(value));
    if (mag >= 1_000_000) return `${sign}S$${(mag / 1_000_000).toFixed(2)}M`;
    if (mag >= 1_000) return `${sign}S$${Math.round(mag / 1_000)}k`;
    return `${sign}S$${mag.toLocaleString()}`;
}

export function driverImpactMagnitude(row: DriverRow): number {
    return Math.abs(row.contributionSgd ?? row.contributionLog);
}
