"use client";

import { useMemo } from "react";

export type VerdictLabel = "In line with sales" | "Below sales average" | "Above sales average" | "Insufficient data";

type NeighborComparison = {
    status?: string;
    average_price_per_sqm?: number | null;
    similar_properties?: unknown[];
};

type Props = {
    predictedPrice: number;
    floorAreaSqm: number | null;
    flatType: string;
    town: string;
    neighborComparison?: NeighborComparison | null;
    /** Latest-period median from comparison chart (town + flat type baseline). */
    chartMedianPrice?: number | null;
};

function verdictFromPctDiff(pct: number): VerdictLabel {
    if (Math.abs(pct) <= 5) return "In line with sales";
    if (pct < 0) return "Below sales average";
    return "Above sales average";
}

function verdictStyles(label: VerdictLabel): string {
    switch (label) {
        case "In line with sales":
            return "bg-emerald-500/15 text-emerald-700 border-emerald-200";
        case "Below sales average":
            return "bg-sky-500/15 text-sky-700 border-sky-200";
        case "Above sales average":
            return "bg-amber-500/15 text-amber-800 border-amber-200";
        case "Insufficient data":
            return "bg-slate-100 text-slate-600 border-slate-200";
    }
}

export default function ValuationVerdictBadge({
    predictedPrice,
    floorAreaSqm,
    flatType,
    town,
    neighborComparison,
    chartMedianPrice,
}: Props) {
    const { label, sentence, pctDiff } = useMemo(() => {
        const hasNearby = neighborComparison?.status === "ok" &&
            (neighborComparison.similar_properties?.length ?? 0) > 0 &&
            neighborComparison.average_price_per_sqm != null &&
            Number.isFinite(neighborComparison.average_price_per_sqm) &&
            neighborComparison.average_price_per_sqm > 0 && floorAreaSqm != null && floorAreaSqm > 0;
        const reference = hasNearby
            ? neighborComparison!.average_price_per_sqm! * floorAreaSqm!
            : chartMedianPrice ?? null;
        let pct: number | null = null;
        if (reference != null && reference > 0) {
            pct = ((predictedPrice - reference) / reference) * 100;
        }

        const verdict: VerdictLabel =
            pct != null ? verdictFromPctDiff(pct) : "Insufficient data";

        const townLabel = town?.trim()
            ? town
                  .split(/\s+/)
                  .map((w) => w.charAt(0) + w.slice(1).toLowerCase())
                  .join(" ")
            : "this town";

        let line: string;
        if (pct != null && reference != null) {
            const dir =
                Math.abs(pct) <= 5
                    ? "in line with"
                    : pct > 0
                      ? `${Math.abs(pct).toFixed(1)}% above`
                      : `${Math.abs(pct).toFixed(1)}% below`;
            line = hasNearby
                ? `Estimate per sqm is ${dir} the average of ${neighborComparison!.similar_properties!.length} selected nearby recorded sales.`
                : `Estimate is ${dir} the latest town resale baseline for ${flatType} in ${townLabel}.`;
        } else {
            line = `Model estimate for ${flatType} in ${townLabel}. Compare against the chart below.`;
        }

        return { label: verdict, sentence: line, pctDiff: pct };
    }, [predictedPrice, floorAreaSqm, neighborComparison, chartMedianPrice, flatType, town]);

    const psf =
        floorAreaSqm != null && floorAreaSqm > 0
            ? Math.round(predictedPrice / floorAreaSqm)
            : null;

    return (
        <div className="text-left space-y-2">
            <div className="flex flex-wrap items-center gap-2">
                <span
                    className={`inline-flex items-center px-3 py-1 rounded-full border text-xs font-bold ${verdictStyles(label)}`}
                >
                    {label}
                </span>
                {psf != null ? (
                    <span className="text-sm text-foreground/55 tabular-nums">
                        S${psf.toLocaleString()} / sqm
                    </span>
                ) : null}
            </div>
            <p className="text-sm text-foreground/65 leading-relaxed">{sentence}</p>
            {pctDiff != null && Math.abs(pctDiff) > 5 ? (
                <p className="text-xs text-foreground/45">
                    Comparison uses historical recorded prices; it is not a separate property valuation.
                </p>
            ) : null}
        </div>
    );
}
