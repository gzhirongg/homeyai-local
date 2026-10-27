/** Storey midpoint → analytics ``floor_levels`` band (matches backend STOREY_LEVEL_MAP keys). */
export type FloorLevelBand = "Low" | "Mid" | "High" | "Very High";

export function storeyMidpointToFloorLevelBand(storey: number): FloorLevelBand {
    if (storey <= 6) return "Low";
    if (storey <= 12) return "Mid";
    if (storey <= 18) return "High";
    return "Very High";
}

export type AnalyticsTimeSeriesPoint = {
    period: string;
    txn_count: number;
    avg_price: number;
    avg_psf: number;
    min_price: number;
    max_price: number;
};

export type AnalyticsQueryResponse = {
    time_series: AnalyticsTimeSeriesPoint[];
    summary: {
        total: number;
        avg_price: number;
        avg_psf?: number;
        min_price?: number;
        max_price?: number;
    };
};

export type GroupByPeriod = "month" | "quarter" | "year";

export type ComparisonFilterState = {
    similarFloorArea: boolean;
    similarFloorLevel: boolean;
    similarLease: boolean;
    sameBlockOnly: boolean;
};

export function defaultDateFromYearsAgo(years = 8): string {
    const y = new Date().getFullYear() - years;
    return `${y}-01`;
}

export function buildAnalyticsQueryBody(params: {
    town: string;
    flatType: string;
    dateFrom: string;
    groupBy: GroupByPeriod;
    floorAreaSqm?: number | null;
    storeyMidpoint?: number | null;
    remainingLeaseYears?: number | null;
    postalCode?: string | null;
    filters: ComparisonFilterState;
}): Record<string, unknown> {
    const body: Record<string, unknown> = {
        towns: [params.town.toUpperCase()],
        flat_types: [params.flatType],
        date_from: params.dateFrom,
        group_by: params.groupBy,
    };

    if (params.filters.sameBlockOnly && params.postalCode) {
        body.postal_code = params.postalCode.replace(/\D/g, "").slice(0, 6);
        return body;
    }

    if (params.filters.similarFloorArea && params.floorAreaSqm != null) {
        const fa = params.floorAreaSqm;
        body.floor_area_min = Math.max(0, fa - 10);
        body.floor_area_max = fa + 10;
    }
    if (params.filters.similarFloorLevel && params.storeyMidpoint != null) {
        body.floor_levels = [storeyMidpointToFloorLevelBand(params.storeyMidpoint)];
    }
    if (params.filters.similarLease && params.remainingLeaseYears != null) {
        const lr = params.remainingLeaseYears;
        body.lease_remaining_min = Math.max(1, lr - 10);
        body.lease_remaining_max = Math.min(99, lr + 10);
    }

    return body;
}

/** Promote grouping when series is too sparse for chart readability. */
export function nextGroupBy(current: GroupByPeriod): GroupByPeriod | null {
    if (current === "month") return "quarter";
    if (current === "quarter") return "year";
    return null;
}

export function isSeriesTooSparse(
    series: AnalyticsTimeSeriesPoint[],
    minPeriods = 6,
    minTxnPerPeriod = 3
): boolean {
    if (series.length < minPeriods) return true;
    return series.some((p) => p.txn_count < minTxnPerPeriod);
}

export function latestPeriodMedianPrice(
    series: AnalyticsTimeSeriesPoint[]
): number | null {
    if (!series.length) return null;
    const sorted = [...series].sort((a, b) => a.period.localeCompare(b.period));
    const last = sorted[sorted.length - 1];
    return last?.avg_price ?? null;
}
