"use client";

import { useMemo, useState, type ReactNode } from "react";
import { motion } from "framer-motion";
import { ChevronDown, FileText, Layers, MapPin, TrendingUp } from "lucide-react";
import { useRouter } from "next/navigation";

import type { PropertyLookupResult } from "@/components/PropertySearchInput";
import type { ValuationFormData } from "@/components/valuation/ValuationUnitFormPane";
import ValuationGeoAmenities from "@/components/valuation/ValuationGeoAmenities";
import ValuationMarketSentiment from "@/components/valuation/ValuationMarketSentiment";
import ValuationPriceComparisonChart from "@/components/valuation/ValuationPriceComparisonChart";
import ValuationResaleByFlatType from "@/components/valuation/ValuationResaleByFlatType";
import ValuationVerdictBadge from "@/components/valuation/ValuationVerdictBadge";
import { useNearestPoiByType } from "@/hooks/useNearestPoiByType";
import {
    type DriverContext,
    driverImpactMagnitude,
    formatDriverImpactSgd,
    summarizeShapDrivers,
} from "@/lib/shapDrivers";

export type ShapExplanationRow = {
    feature: string;
    chart_value: number;
    contribution_log: number;
    contribution_sgd?: number;
    source_column?: string | null;
    feature_value?: number | string | null;
};

export type ShapExplanation = {
    baseline?: {
        expected_value_log1p: number;
        price_sgd: number;
    };
    predicted_log1p?: number;
    rows: ShapExplanationRow[];
};

type NeighborComparison = {
    status: "ok" | "no_matches" | "unavailable";
    reason?: string;
    source: { name: string; url: string };
    criteria: {
        radius_m: number;
        date_from: string;
        date_to: string;
        flat_type: string;
        area_tolerance_pct: number;
        lease_tolerance_years: number;
        storey_midpoint_tolerance: number;
        max_per_building: number;
    };
    subject_property: {
        price: number;
        price_per_sqm: number;
    };
    market_position: string | null;
    price_percentile: number | null;
    average_neighbor_price: number | null;
    average_price_per_sqm: number | null;
    match_count: number;
    similar_properties: {
        transaction_id: number;
        address: string;
        postal_code: string | null;
        sale_month: string;
        storey_range: string;
        distance_m: number;
        same_building: boolean;
        floor_area: number;
        price: number;
        difference_pct: number;
    }[];
};

type Props = {
    result: Record<string, unknown> & {
        predicted_price: number;
        confidence_interval: number[];
        confidence_interval_method?: string;
        interval_coverage?: number;
        interval_calibration?: { test_coverage?: number; calibration_count?: number };
        shap_values?: unknown;
        neighbor_comparison?: unknown;
    };
    shapExplanation: ShapExplanation | null;
    formData: ValuationFormData;
    user: { role?: string } | null | undefined;
    isPremiumExperience: boolean;
    onNewSearch: () => void;
    handleSave: () => void;
    saveState: "idle" | "saving" | "saved" | "error";
    saveError: string;
    selectedProperty: PropertyLookupResult | null;
    analyticsRefreshNonce?: number;
    driverContext?: DriverContext | null;
};

function formatSgdCompact(value: number): string {
    if (!Number.isFinite(value)) return "—";
    const mag = Math.abs(Math.round(value));
    if (mag >= 1_000_000) return `S$${(mag / 1_000_000).toFixed(2)}M`;
    if (mag >= 1_000) return `S$${Math.round(mag / 1_000)}k`;
    return `S$${mag.toLocaleString()}`;
}

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

function BaselineContextStrip({
    baselinePrice,
    predictedPrice,
    chartMedian,
    town,
    flatType,
}: {
    baselinePrice: number;
    predictedPrice: number;
    chartMedian: number | null;
    town: string;
    flatType: string;
}) {
    const townLabel = town?.trim() ? titleCaseWords(town) : "Town";
    const flatLabel = flatType?.trim() ? titleCaseFlatType(flatType) : "flat type";

    return (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 rounded-xl border border-foreground/10 bg-foreground/[0.02] p-4">
            <div>
                <p className="text-[11px] text-foreground/45 font-semibold uppercase tracking-wide">
                    Model baseline
                </p>
                <p
                    className="font-bold text-lg tabular-nums"
                    title="Average predicted price across all HDB flats in the model's training data. Your property's attributes adjust this estimate up or down."
                >
                    {formatSgdCompact(baselinePrice)}
                </p>
                <p className="text-[10px] text-foreground/40 mt-0.5 leading-snug">
                    All-HDB training average
                </p>
            </div>
            <div>
                <p className="text-[11px] text-foreground/45 font-semibold uppercase tracking-wide">
                    Your estimate
                </p>
                <p className="font-bold text-lg text-accent tabular-nums">
                    {formatSgdCompact(predictedPrice)}
                </p>
                <p className="text-[10px] text-foreground/40 mt-0.5 leading-snug">
                    Model training average → your estimate
                </p>
            </div>
            {chartMedian != null ? (
                <div className="col-span-2 sm:col-span-1">
                    <p className="text-[11px] text-foreground/45 font-semibold uppercase tracking-wide">
                        {townLabel} {flatLabel} recent avg
                    </p>
                    <p
                        className="font-bold text-lg tabular-nums"
                        title="Latest resale average from the comparison chart above"
                    >
                        {formatSgdCompact(chartMedian)}
                    </p>
                    <p className="text-[10px] text-foreground/40 mt-0.5 leading-snug">
                        From chart above
                    </p>
                </div>
            ) : null}
        </div>
    );
}

function CollapsibleCard({
    title,
    icon,
    defaultOpen = false,
    children,
}: {
    title: string;
    icon: ReactNode;
    defaultOpen?: boolean;
    children: ReactNode;
}) {
    const [open, setOpen] = useState(defaultOpen);
    return (
        <details
            open={open}
            onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
            className="rounded-2xl border border-foreground/10 bg-white/80 group"
        >
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4 font-bold text-sm [&::-webkit-details-marker]:hidden">
                <span className="flex items-center gap-2">
                    {icon}
                    {title}
                </span>
                <ChevronDown className="w-4 h-4 text-foreground/40 transition-transform group-open:rotate-180" />
            </summary>
            <div className="px-5 pb-5 border-t border-foreground/5 pt-4">{children}</div>
        </details>
    );
}

export default function ValuationResultPanel({
    result,
    shapExplanation,
    formData,
    user,
    isPremiumExperience,
    onNewSearch,
    handleSave,
    saveState,
    saveError,
    selectedProperty,
    analyticsRefreshNonce = 0,
    driverContext = null,
}: Props) {
    const router = useRouter();
    const [chartMedian, setChartMedian] = useState<number | null>(null);
    const [showAllComparables, setShowAllComparables] = useState(false);
    const [collapseDrivers, setCollapseDrivers] = useState(false);
    const { pois: amenitiesPois } = useNearestPoiByType(
        selectedProperty,
        analyticsRefreshNonce
    );

    const rawComparison = result.neighbor_comparison as NeighborComparison | undefined;
    // Old cached results contain fabricated rows without provenance or match criteria.
    const nc = rawComparison?.criteria && rawComparison?.source ? rawComparison : undefined;

    const priceDrivers = useMemo(
        () =>
            summarizeShapDrivers(
                shapExplanation,
                {
                    formData,
                    selectedProperty,
                    driverContext,
                    amenitiesPois,
                    baselinePrice: shapExplanation?.baseline?.price_sgd ?? null,
                    predictedPrice: result.predicted_price,
                },
                16
            ),
        [
            shapExplanation,
            formData,
            selectedProperty,
            driverContext,
            amenitiesPois,
            result.predicted_price,
        ]
    );

    const visibleDrivers = useMemo(
        () => (collapseDrivers ? priceDrivers.slice(0, 5) : priceDrivers),
        [priceDrivers, collapseDrivers]
    );

    const maxDriverImpact = useMemo(() => {
        if (!visibleDrivers.length) return 1;
        return Math.max(...visibleDrivers.map(driverImpactMagnitude), 1);
    }, [visibleDrivers]);

    const baselinePrice = shapExplanation?.baseline?.price_sgd;

    const [lo, hi] = result.confidence_interval;
    const bandWidth = hi - lo;
    const subjectOffset =
        bandWidth > 0 ? ((result.predicted_price - lo) / bandWidth) * 100 : 50;

    const comparables = nc?.similar_properties ?? [];
    const visibleComparables = showAllComparables
        ? comparables
        : comparables.slice(0, 5);

    return (
        <motion.div
            key="result"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="text-left space-y-5"
        >
            <section className="rounded-2xl border border-foreground/10 bg-white/90 p-5 md:p-6 space-y-4">
                <div>
                    <span className="text-accent font-bold uppercase tracking-widest text-xs">
                        Estimated value
                    </span>
                    <h2 className="text-2xl min-[400px]:text-4xl sm:text-5xl font-extrabold mt-1 text-gradient tabular-nums">
                        S${result.predicted_price.toLocaleString()}
                    </h2>
                </div>

                <div className="space-y-2">
                    <div className="grid grid-cols-2 gap-1 text-[11px] text-foreground/45 tabular-nums sm:flex sm:justify-between">
                        <span>S${lo.toLocaleString()}</span>
                        <span className="col-span-2 row-start-1 text-center font-semibold text-foreground/60">{result.interval_coverage ? `${Math.round(result.interval_coverage * 100)}% target interval` : 'Estimated range'}</span>
                        <span className="text-right">S${hi.toLocaleString()}</span>
                    </div>
                    <div className="relative h-2 rounded-full bg-gradient-to-r from-secondary/20 via-accent/25 to-accent/20 overflow-hidden">
                        <div
                            className="absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full bg-accent border-2 border-white shadow"
                            style={{ left: `clamp(0%, ${subjectOffset}%, 100%)` }}
                            aria-hidden
                        />
                    </div>
                    {result.confidence_interval_method === "fixed_percentage_band" ? (
                        <p className="text-[10px] text-foreground/45">
                            Bounds are a simple ±10% heuristic around the point estimate (not a
                            calibrated prediction interval).
                        </p>
                    ) : null}
                    {result.confidence_interval_method === "split_conformal_relative" && (
                        <p className="text-[10px] text-foreground/45">
                            Calibrated on {result.interval_calibration?.calibration_count?.toLocaleString()} held-out sales.
                            Later test coverage: {((result.interval_calibration?.test_coverage ?? 0) * 100).toFixed(1)}%.
                            Market shifts can change future coverage.
                        </p>
                    )}
                </div>

                {selectedProperty ? (
                    <ValuationVerdictBadge
                        predictedPrice={result.predicted_price}
                        floorAreaSqm={formData.floor_area_sqm}
                        flatType={formData.flat_type}
                        town={selectedProperty.town}
                        neighborComparison={nc}
                        chartMedianPrice={chartMedian}
                    />
                ) : null}
            </section>

            {selectedProperty ? (
                <ValuationPriceComparisonChart
                    selectedProperty={selectedProperty}
                    formData={formData}
                    predictedPrice={result.predicted_price}
                    refreshKey={analyticsRefreshNonce}
                    onBaselineMedianChange={setChartMedian}
                />
            ) : null}

            {visibleDrivers.length > 0 ? (
                <section className="rounded-2xl border border-accent/20 bg-accent/5 p-5 space-y-4">
                    <div>
                        <h3 className="font-bold text-sm flex items-center gap-2">
                            <Layers className="w-4 h-4 text-accent" /> Why this price?
                        </h3>
                        <p className="text-xs text-foreground/55 mt-1">
                            The model starts from a training-set average, then your unit&apos;s
                            attributes push the estimate up or down.
                        </p>
                    </div>
                    {baselinePrice != null && Number.isFinite(baselinePrice) ? (
                        <BaselineContextStrip
                            baselinePrice={baselinePrice}
                            predictedPrice={result.predicted_price}
                            chartMedian={chartMedian}
                            town={selectedProperty?.town ?? formData.town}
                            flatType={formData.flat_type}
                        />
                    ) : null}
                    <ul className="space-y-3">
                        {visibleDrivers.map((driver) => {
                            const impact =
                                driver.contributionSgd ?? driver.contributionLog;
                            const positive = impact >= 0;
                            const barPct = Math.min(
                                100,
                                (driverImpactMagnitude(driver) / maxDriverImpact) * 100
                            );
                            const tooltipLines: string[] = [];
                            if (driver.contributionSgd != null) {
                                tooltipLines.push(
                                    `Share of move: ${formatDriverImpactSgd(driver.contributionSgd)}`
                                );
                            }
                            tooltipLines.push(
                                `Log SHAP: ${driver.contributionLog >= 0 ? "+" : ""}${driver.contributionLog.toFixed(3)}`
                            );
                            if (driver.marginalContributionSgd != null) {
                                tooltipLines.push(
                                    `Marginal-only effect: ${formatDriverImpactSgd(driver.marginalContributionSgd)}`
                                );
                            }
                            if (driver.sourceFeatures.length) {
                                tooltipLines.push(
                                    `Features: ${driver.sourceFeatures.slice(0, 8).join(", ")}${driver.sourceFeatures.length > 8 ? ", …" : ""}`
                                );
                            }
                            return (
                                <li
                                    key={driver.id}
                                    className="rounded-xl border border-foreground/10 bg-white/80 px-4 py-3"
                                    title={tooltipLines.join("\n")}
                                >
                                    <div className="flex flex-wrap items-start justify-between gap-3">
                                        <div className="min-w-0 flex-1">
                                            <p className="font-semibold text-sm text-foreground">
                                                {driver.label}
                                            </p>
                                            {driver.proxyText ? (
                                                <p className="text-xs text-foreground/60 mt-0.5 leading-snug">
                                                    {driver.proxyText}
                                                </p>
                                            ) : null}
                                            {driver.note ? (
                                                <p className="text-[10px] text-foreground/45 mt-1 leading-snug">
                                                    {driver.note}
                                                </p>
                                            ) : null}
                                        </div>
                                        {driver.contributionSgd != null ? (
                                            <span
                                                className={`shrink-0 inline-flex items-center px-2.5 py-1 rounded-full text-xs font-bold tabular-nums ${
                                                    positive
                                                        ? "bg-emerald-500/15 text-emerald-700"
                                                        : "bg-red-500/15 text-red-600"
                                                }`}
                                            >
                                                {formatDriverImpactSgd(driver.contributionSgd)}
                                            </span>
                                        ) : null}
                                    </div>
                                    <div className="mt-2.5 h-1.5 rounded-full bg-foreground/10 overflow-hidden">
                                        <div
                                            className={`h-full rounded-full transition-all ${
                                                positive ? "bg-emerald-500" : "bg-red-500"
                                            }`}
                                            style={{ width: `${barPct}%` }}
                                        />
                                    </div>
                                </li>
                            );
                        })}
                    </ul>
                    {priceDrivers.length > 5 ? (
                        <button
                            type="button"
                            onClick={() => setCollapseDrivers((v) => !v)}
                            className="text-xs font-semibold text-accent hover:underline"
                        >
                            {collapseDrivers
                                ? `Show all ${priceDrivers.length} factors`
                                : "Show top 5 only"}
                        </button>
                    ) : null}
                    <p className="text-xs text-foreground/45 mt-1 leading-relaxed">
                        {!collapseDrivers && visibleDrivers.length === priceDrivers.length
                            ? `All ${priceDrivers.length} factor${priceDrivers.length === 1 ? "" : "s"} above sum to the baseline → estimate move shown at the top. `
                            : `Showing ${visibleDrivers.length} of ${priceDrivers.length} factors. The full list sums to the baseline → estimate move shown at the top. `}
                        Each factor&apos;s SGD is its signed share of the log-space SHAP movement,
                        rescaled to the dollar gap.
                    </p>
                </section>
            ) : (
                (!user || !isPremiumExperience) && (
                    <section className="rounded-2xl border border-orange-500/20 bg-orange-500/5 p-5">
                        <h3 className="font-bold text-sm text-orange-600">Locked feature</h3>
                        <p className="text-sm text-foreground/70 mt-2">
                            Upgrade to Premium to see why the model priced your unit this way.
                        </p>
                    </section>
                )
            )}

            {nc ? (
                <section className="rounded-2xl border border-foreground/10 bg-white/80 p-5 space-y-3">
                    <h3 className="font-bold text-sm flex items-center gap-2">
                        <TrendingUp className="w-4 h-4 text-accent" /> Nearby comparables
                    </h3>
                    <p className="text-xs text-foreground/55">
                        Recorded {nc.criteria.flat_type} sales within {nc.criteria.radius_m / 1000} km,
                        {" "}{nc.criteria.date_from} to {nc.criteria.date_to}. Size ±{nc.criteria.area_tolerance_pct}%,
                        {" "}floor-band midpoint ±{nc.criteria.storey_midpoint_tolerance} floors,
                        {" "}estimated current lease ±{nc.criteria.lease_tolerance_years} years.
                    </p>
                    {comparables.length > 0 && nc.average_neighbor_price != null ? (
                        <p className="text-xs text-foreground/65">
                            Average across {comparables.length} selected sales: S${nc.average_neighbor_price.toLocaleString()}
                            {nc.average_price_per_sqm != null ? ` · S$${Math.round(nc.average_price_per_sqm).toLocaleString()} / sqm` : ""}.
                            {" "}Up to {nc.criteria.max_per_building} sales per building.
                        </p>
                    ) : (
                        <p className="text-sm text-foreground/65" role="status">
                            {nc.reason === "location_missing"
                                ? "A reliable building location is required to find nearby comparable sales."
                                : "No recorded sales match these criteria. There are not enough comparable records to show a comparison."}
                        </p>
                    )}
                    {comparables.length > 0 && <>
                    <ul className="space-y-3 sm:hidden">
                        {visibleComparables.map((prop) => (
                            <li key={prop.transaction_id} className="rounded-xl border border-foreground/10 p-3 space-y-2">
                                <p className="text-sm font-semibold">{prop.address}</p>
                                <p className="text-xs text-foreground/55">
                                    {prop.postal_code} · {prop.same_building ? "Same building" : `${prop.distance_m} m away`}
                                </p>
                                <p className="text-xs text-foreground/65">
                                    Sold {prop.sale_month} · {prop.floor_area} sqm · Floors {prop.storey_range}
                                </p>
                                <p className="text-xs text-foreground/55">Recorded price</p>
                                <p className="font-bold tabular-nums">S${prop.price.toLocaleString()}</p>
                                <p className="text-xs tabular-nums text-foreground/60">
                                    {prop.difference_pct >= 0 ? "+" : ""}{prop.difference_pct}% vs estimate
                                </p>
                            </li>
                        ))}
                    </ul>
                    <div className="hidden sm:block overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="border-b border-foreground/10 text-[11px] uppercase tracking-wide text-foreground/45">
                                    <th className="text-left py-2 pr-3 font-semibold">Address</th>
                                    <th className="text-left py-2 px-2 font-semibold">Sale / floors</th>
                                    <th className="text-right py-2 px-2 font-semibold">Distance</th>
                                    <th className="text-right py-2 px-2 font-semibold">Size</th>
                                    <th className="text-right py-2 px-2 font-semibold">Recorded price</th>
                                    <th className="text-right py-2 pl-2 font-semibold">
                                        vs estimate
                                    </th>
                                </tr>
                            </thead>
                            <tbody>
                                {visibleComparables.map((prop) => (
                                    <tr
                                        key={prop.transaction_id}
                                        className="border-b border-foreground/5 last:border-0"
                                    >
                                        <td className="py-2.5 pr-3 font-medium">
                                            {prop.address}
                                            <span className="block text-xs font-normal text-foreground/50">{prop.postal_code}</span>
                                        </td>
                                        <td className="py-2.5 px-2 whitespace-nowrap text-foreground/60">
                                            {prop.sale_month}
                                            <span className="block text-xs">Floors {prop.storey_range}</span>
                                        </td>
                                        <td className="text-right py-2.5 px-2 whitespace-nowrap text-foreground/60 tabular-nums">
                                            {prop.same_building ? "Same building" : `${prop.distance_m} m`}
                                        </td>
                                        <td className="text-right py-2.5 px-2 text-foreground/60 tabular-nums">
                                            {prop.floor_area} sqm
                                        </td>
                                        <td className="text-right py-2.5 px-2 font-bold tabular-nums">
                                            S${prop.price.toLocaleString()}
                                        </td>
                                        <td
                                            className={`text-right py-2.5 pl-2 font-bold tabular-nums ${
                                                prop.difference_pct >= 0
                                                    ? "text-red-500"
                                                    : "text-green-500"
                                            }`}
                                        >
                                            {prop.difference_pct >= 0 ? "+" : ""}
                                            {prop.difference_pct}%
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                    {comparables.length > 5 ? (
                        <button
                            type="button"
                            onClick={() => setShowAllComparables((v) => !v)}
                            className="text-xs font-semibold text-accent hover:underline"
                        >
                            {showAllComparables
                                ? "Show fewer comparables"
                                : `Show all ${comparables.length} comparables`}
                        </button>
                    ) : null}
                    <p className="text-xs text-foreground/45">
                        Recorded sale prices are unadjusted historical amounts. Percentages compare each sale&apos;s
                        total price with your model estimate; they do not adjust for size or market changes.
                    </p>
                    </>}
                    <a href={nc.source.url} target="_blank" rel="noopener noreferrer"
                        className="inline-block text-xs text-accent hover:underline">
                        Source: {nc.source.name}
                    </a>
                </section>
            ) : isPremiumExperience ? (
                <section className="rounded-2xl border border-foreground/10 bg-white/80 p-5">
                    <h3 className="font-bold text-sm">Nearby comparables</h3>
                    <p className="text-sm text-foreground/65 mt-2">Recalculate the valuation to load recorded comparable sales.</p>
                </section>
            ) : (
                (!user || !isPremiumExperience) && (
                    <section className="rounded-2xl border border-orange-500/20 bg-orange-500/5 p-5">
                        <h3 className="font-bold text-sm text-orange-600">Locked feature</h3>
                        <p className="text-sm text-foreground/70 mt-2">
                            Upgrade to Premium to compare against similar nearby units.
                        </p>
                    </section>
                )
            )}

            {selectedProperty ? (
                <>
                    <CollapsibleCard
                        title="Location quality"
                        icon={<MapPin className="w-4 h-4 text-secondary" />}
                    >
                        <ValuationGeoAmenities
                            selectedProperty={selectedProperty}
                            refreshNonce={analyticsRefreshNonce}
                        />
                    </CollapsibleCard>
                    <CollapsibleCard title="Market sentiment" icon={<TrendingUp className="w-4 h-4 text-accent" />}>
                        <ValuationMarketSentiment refreshNonce={analyticsRefreshNonce} />
                    </CollapsibleCard>
                    <CollapsibleCard title="Resale by flat type (this building)" icon={<TrendingUp className="w-4 h-4 text-foreground/50" />}>
                        <ValuationResaleByFlatType selectedProperty={selectedProperty} />
                    </CollapsibleCard>
                </>
            ) : null}

            <section className="rounded-2xl border border-foreground/10 bg-white/80 p-5 space-y-3">
                <div className="flex flex-col sm:flex-row gap-3">
                    <button
                        type="button"
                        onClick={onNewSearch}
                        className="flex-1 border border-foreground/10 py-3 rounded-xl font-bold hover:bg-black/5 transition-all"
                    >
                        New search
                    </button>
                    {isPremiumExperience ? (
                        <a
                            href="/valuation-report"
                            className="flex-1 bg-accent text-white py-3 rounded-xl font-bold hover:shadow-lg transition-all flex items-center justify-center gap-2 text-center"
                        >
                            <FileText className="w-4 h-4" />
                            Download report
                        </a>
                    ) : null}
                    <button
                        type="button"
                        onClick={() => router.push("/dashboard")}
                        className="flex-1 bg-secondary text-white py-3 rounded-xl font-bold hover:shadow-lg transition-all"
                    >
                        Dashboard
                    </button>
                </div>

                {saveState === "error" ? (
                    <div className="bg-red-50 text-red-600 p-3 rounded-lg text-sm border border-red-100">
                        {saveError}
                    </div>
                ) : null}
                {saveState === "saved" ? (
                    <div className="bg-emerald-50 text-emerald-700 p-3 rounded-lg text-sm border border-emerald-100">
                        Saved to your properties.
                    </div>
                ) : null}
                <button
                    type="button"
                    onClick={handleSave}
                    disabled={saveState === "saving" || saveState === "saved"}
                    className="w-full border border-foreground/10 py-3 rounded-xl font-bold hover:bg-black/5 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    {saveState === "saving"
                        ? "Saving…"
                        : saveState === "saved"
                          ? "Saved"
                          : "Save property"}
                </button>
            </section>
        </motion.div>
    );
}
