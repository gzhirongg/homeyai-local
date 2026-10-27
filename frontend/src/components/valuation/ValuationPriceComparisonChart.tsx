"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import {
    CartesianGrid,
    Legend,
    Line,
    LineChart,
    ReferenceDot,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from "recharts";

import API_BASE from "@/lib/apiBase";
import type { PropertyLookupResult } from "@/components/PropertySearchInput";
import type { ValuationFormData } from "@/components/valuation/ValuationUnitFormPane";
import {
    type AnalyticsQueryResponse,
    type AnalyticsTimeSeriesPoint,
    type ComparisonFilterState,
    buildAnalyticsQueryBody,
    defaultDateFromYearsAgo,
    isSeriesTooSparse,
    latestPeriodMedianPrice,
    nextGroupBy,
    type GroupByPeriod,
} from "@/lib/valuationAnalyticsQuery";

const MIN_TOTAL_TXNS_FOR_CHIP = 30;

type ChartRow = {
    period: string;
    broad?: number;
    filtered?: number;
    broadCount?: number;
    filteredCount?: number;
    broadMin?: number;
    broadMax?: number;
    filteredMin?: number;
    filteredMax?: number;
};

type Props = {
    selectedProperty: PropertyLookupResult;
    formData: ValuationFormData;
    predictedPrice: number;
    /** Bump when valuation re-runs to refetch baseline. */
    refreshKey?: number;
    onBaselineMedianChange?: (median: number | null) => void;
};

async function fetchAnalytics(body: Record<string, unknown>): Promise<AnalyticsQueryResponse> {
    const res = await fetch(`${API_BASE}/api/analytics/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    if (!res.ok) {
        return { time_series: [], summary: { total: 0, avg_price: 0 } };
    }
    return (await res.json()) as AnalyticsQueryResponse;
}

function mergeSeries(
    broad: AnalyticsTimeSeriesPoint[],
    filtered: AnalyticsTimeSeriesPoint[] | null
): ChartRow[] {
    const periods = new Set<string>();
    for (const p of broad) periods.add(p.period);
    if (filtered) for (const p of filtered) periods.add(p.period);
    const broadMap = new Map(broad.map((p) => [p.period, p]));
    const filtMap = filtered ? new Map(filtered.map((p) => [p.period, p])) : null;

    return [...periods]
        .sort()
        .map((period) => {
            const b = broadMap.get(period);
            const f = filtMap?.get(period);
            return {
                period,
                broad: b?.avg_price,
                broadCount: b?.txn_count,
                broadMin: b?.min_price,
                broadMax: b?.max_price,
                filtered: f?.avg_price,
                filteredCount: f?.txn_count,
                filteredMin: f?.min_price,
                filteredMax: f?.max_price,
            };
        });
}

function formatPrice(v: number): string {
    if (v >= 1_000_000) return `S$${(v / 1_000_000).toFixed(2)}M`;
    if (v >= 1_000) return `S$${Math.round(v / 1_000)}k`;
    return `S$${Math.round(v)}`;
}

export default function ValuationPriceComparisonChart({
    selectedProperty,
    formData,
    predictedPrice,
    refreshKey = 0,
    onBaselineMedianChange,
}: Props) {
    const [filters, setFilters] = useState<ComparisonFilterState>({
        similarFloorArea: false,
        similarFloorLevel: false,
        similarLease: false,
        sameBlockOnly: false,
    });
    const [groupBy, setGroupBy] = useState<GroupByPeriod>("month");
    const [sparsityNote, setSparsityNote] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [broadSeries, setBroadSeries] = useState<AnalyticsTimeSeriesPoint[]>([]);
    const [filteredSeries, setFilteredSeries] = useState<AnalyticsTimeSeriesPoint[] | null>(
        null
    );
    const [filteredTotal, setFilteredTotal] = useState<number | null>(null);
    const [chipDisabled, setChipDisabled] = useState<Partial<Record<keyof ComparisonFilterState, boolean>>>({});

    const dateFrom = useMemo(() => defaultDateFromYearsAgo(8), []);
    const hasActiveFilters =
        filters.similarFloorArea ||
        filters.similarFloorLevel ||
        filters.similarLease ||
        filters.sameBlockOnly;

    const fetchWithRollup = useCallback(
        async (
            filterState: ComparisonFilterState,
            startGroupBy: GroupByPeriod
        ): Promise<{ series: AnalyticsTimeSeriesPoint[]; total: number; usedGroupBy: GroupByPeriod; note: string | null }> => {
            let gb: GroupByPeriod = startGroupBy;
            let note: string | null = null;
            for (;;) {
                const body = buildAnalyticsQueryBody({
                    town: selectedProperty.town,
                    flatType: formData.flat_type,
                    dateFrom,
                    groupBy: gb,
                    floorAreaSqm: formData.floor_area_sqm,
                    storeyMidpoint: formData.storey_midpoint,
                    remainingLeaseYears: formData.remaining_lease_years,
                    postalCode: selectedProperty.postal_code,
                    filters: filterState,
                });
                const data = await fetchAnalytics(body);
                const series = data.time_series ?? [];
                if (!isSeriesTooSparse(series) || nextGroupBy(gb) === null) {
                    if (note === null && gb !== startGroupBy) {
                        note =
                            gb === "quarter"
                                ? "Showing quarterly averages — monthly view too sparse for these filters."
                                : "Showing yearly averages — finer periods too sparse for these filters.";
                    }
                    return { series, total: data.summary?.total ?? 0, usedGroupBy: gb, note };
                }
                const next = nextGroupBy(gb);
                if (!next) {
                    return { series, total: data.summary?.total ?? 0, usedGroupBy: gb, note };
                }
                gb = next;
                note = "Aggregating to coarser periods due to sparse sales.";
            }
        },
        [
            selectedProperty.town,
            selectedProperty.postal_code,
            formData.flat_type,
            formData.floor_area_sqm,
            formData.storey_midpoint,
            formData.remaining_lease_years,
            dateFrom,
        ]
    );

    useEffect(() => {
        if (!formData.flat_type?.trim() || !selectedProperty.town?.trim()) return;

        let cancelled = false;
        const run = async () => {
            setLoading(true);
            try {
                const broadResult = await fetchWithRollup(
                    {
                        similarFloorArea: false,
                        similarFloorLevel: false,
                        similarLease: false,
                        sameBlockOnly: false,
                    },
                    "month"
                );
                if (cancelled) return;
                setBroadSeries(broadResult.series);
                onBaselineMedianChange?.(latestPeriodMedianPrice(broadResult.series));

                if (hasActiveFilters) {
                    const filtResult = await fetchWithRollup(filters, groupBy);
                    if (cancelled) return;
                    setFilteredSeries(filtResult.series);
                    setFilteredTotal(filtResult.total);
                    setSparsityNote(filtResult.note);
                    if (filtResult.usedGroupBy !== groupBy) {
                        setGroupBy(filtResult.usedGroupBy);
                    }
                } else {
                    setFilteredSeries(null);
                    setFilteredTotal(null);
                    setSparsityNote(null);
                }
            } finally {
                if (!cancelled) setLoading(false);
            }
        };
        void run();
        return () => {
            cancelled = true;
        };
    }, [
        selectedProperty.town,
        selectedProperty.postal_code,
        formData,
        filters,
        groupBy,
        hasActiveFilters,
        refreshKey,
        fetchWithRollup,
        onBaselineMedianChange,
    ]);

    const toggleFilter = async (key: keyof ComparisonFilterState) => {
        if (key !== "sameBlockOnly" && filters.sameBlockOnly) return;

        const next: ComparisonFilterState = { ...filters, [key]: !filters[key] };
        if (key === "sameBlockOnly" && next.sameBlockOnly) {
            next.similarFloorArea = false;
            next.similarFloorLevel = false;
            next.similarLease = false;
        }

        if (!next[key]) {
            setFilters(next);
            setChipDisabled((d) => ({ ...d, [key]: false }));
            return;
        }

        const probe = await fetchWithRollup(next, groupBy);
        if (probe.total < MIN_TOTAL_TXNS_FOR_CHIP && key !== "sameBlockOnly") {
            setChipDisabled((d) => ({ ...d, [key]: true }));
            return;
        }
        setChipDisabled((d) => ({ ...d, [key]: false }));
        setFilters(next);
    };

    const chartData = useMemo(
        () => mergeSeries(broadSeries, hasActiveFilters ? filteredSeries : null),
        [broadSeries, filteredSeries, hasActiveFilters]
    );

    const subjectPeriod = useMemo(() => {
        const now = new Date();
        const y = now.getFullYear();
        const m = String(now.getMonth() + 1).padStart(2, "0");
        if (groupBy === "year") return String(y);
        if (groupBy === "quarter") {
            const q = Math.ceil((now.getMonth() + 1) / 3);
            return `${y}-Q${q}`;
        }
        return `${y}-${m}`;
    }, [groupBy]);

    const chipClass = (active: boolean, disabled?: boolean) =>
        `inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border transition-colors ${
            disabled
                ? "opacity-40 cursor-not-allowed border-foreground/10 bg-foreground/5 text-foreground/40"
                : active
                  ? "bg-accent/15 text-accent border-accent/30"
                  : "bg-white border-foreground/15 text-foreground/70 hover:bg-foreground/5 cursor-pointer"
        }`;

    return (
        <section className="rounded-2xl border border-foreground/10 bg-white/80 p-5 text-left space-y-4">
            <div>
                <h3 className="font-bold text-sm">How does this compare?</h3>
                <p className="text-xs text-foreground/55 mt-1">
                    Historical resale averages for {formData.flat_type} in {selectedProperty.town}.
                    Toggle filters to zoom toward your unit specs.
                </p>
            </div>

            <div className="flex flex-wrap gap-2">
                <span className={chipClass(true)} aria-disabled>
                    {selectedProperty.town}
                </span>
                <span className={chipClass(true)} aria-disabled>
                    {formData.flat_type}
                </span>
                <button
                    type="button"
                    disabled={filters.sameBlockOnly || chipDisabled.similarFloorArea}
                    title={
                        chipDisabled.similarFloorArea
                            ? "Too few comparable sales with this filter"
                            : undefined
                    }
                    className={chipClass(filters.similarFloorArea, chipDisabled.similarFloorArea)}
                    onClick={() => void toggleFilter("similarFloorArea")}
                >
                    Similar floor area
                    {filters.similarFloorArea && filteredTotal != null
                        ? ` · ${filteredTotal} txns`
                        : ""}
                </button>
                <button
                    type="button"
                    disabled={filters.sameBlockOnly || chipDisabled.similarFloorLevel}
                    className={chipClass(filters.similarFloorLevel, chipDisabled.similarFloorLevel)}
                    onClick={() => void toggleFilter("similarFloorLevel")}
                >
                    Similar floor level
                </button>
                <button
                    type="button"
                    disabled={filters.sameBlockOnly || chipDisabled.similarLease}
                    className={chipClass(filters.similarLease, chipDisabled.similarLease)}
                    onClick={() => void toggleFilter("similarLease")}
                >
                    Similar lease
                </button>
                <button
                    type="button"
                    className={chipClass(filters.sameBlockOnly)}
                    onClick={() => void toggleFilter("sameBlockOnly")}
                >
                    Same block
                    {filters.sameBlockOnly && filteredTotal != null
                        ? ` · ${filteredTotal} txns`
                        : ""}
                </button>
            </div>

            {sparsityNote ? (
                <p className="text-xs text-amber-800 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
                    {sparsityNote}
                </p>
            ) : null}

            {hasActiveFilters && filteredSeries?.length === 0 ? (
                <p className="text-xs text-foreground/55 bg-foreground/[0.03] rounded-lg px-3 py-2">
                    No same-spec sales in this window. Try fewer filters — the town + flat type
                    baseline remains visible.
                </p>
            ) : null}

            <div className="h-64 w-full min-w-0 relative">
                {loading ? (
                    <div className="absolute inset-0 flex items-center justify-center">
                        <Loader2 className="w-6 h-6 animate-spin text-accent" />
                    </div>
                ) : chartData.length === 0 ? (
                    <p className="text-sm text-foreground/45 py-8 text-center">
                        No resale history for this town and flat type in the selected window.
                    </p>
                ) : (
                    <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={chartData} margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                            <XAxis
                                dataKey="period"
                                tick={{ fontSize: 10 }}
                                interval="preserveStartEnd"
                            />
                            <YAxis
                                tick={{ fontSize: 10 }}
                                tickFormatter={(v) => formatPrice(Number(v))}
                                width={56}
                            />
                            <Tooltip
                                labelFormatter={(label) => `Period: ${label}`}
                                content={({ active, payload, label }) => {
                                    if (!active || !payload?.length) return null;
                                    const row = payload[0]?.payload as ChartRow;
                                    return (
                                        <div className="bg-white border border-foreground/10 rounded-lg px-3 py-2 text-xs shadow-lg">
                                            <p className="font-semibold mb-1">{label}</p>
                                            {row.broad != null ? (
                                                <p>
                                                    Town avg: {formatPrice(row.broad)}
                                                    {row.broadCount != null
                                                        ? ` (${row.broadCount} sales)`
                                                        : ""}
                                                </p>
                                            ) : null}
                                            {row.filtered != null ? (
                                                <p>
                                                    Filtered: {formatPrice(row.filtered)}
                                                    {row.filteredCount != null
                                                        ? ` (${row.filteredCount} sales)`
                                                        : ""}
                                                </p>
                                            ) : null}
                                        </div>
                                    );
                                }}
                            />
                            <Legend wrapperStyle={{ fontSize: 11 }} />
                            <Line
                                type="monotone"
                                dataKey="broad"
                                name="Town + flat type"
                                stroke="#6366f1"
                                strokeWidth={2}
                                dot={false}
                                connectNulls
                            />
                            {hasActiveFilters ? (
                                <Line
                                    type="monotone"
                                    dataKey="filtered"
                                    name="Same-as-mine filters"
                                    stroke="#22c55e"
                                    strokeWidth={2}
                                    dot={false}
                                    connectNulls
                                />
                            ) : null}
                            <ReferenceDot
                                x={subjectPeriod}
                                y={predictedPrice}
                                r={6}
                                fill="#f59e0b"
                                stroke="#fff"
                                strokeWidth={2}
                                label={{
                                    value: "Your estimate",
                                    position: "top",
                                    fontSize: 10,
                                    fill: "#b45309",
                                }}
                            />
                        </LineChart>
                    </ResponsiveContainer>
                )}
            </div>
        </section>
    );
}
