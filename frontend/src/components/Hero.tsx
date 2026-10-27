"use client";

import { useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { MapPin, TrendingUp, ShieldCheck, FileText } from "lucide-react";
import { useRouter } from "next/navigation";
import PropertySearchInput, {
    type PropertyLookupResult,
} from "@/components/PropertySearchInput";

/** Min/max resale price signals from lookup aggregates (median / latest by flat type). */
function operationalResaleRange(
    lookup: PropertyLookupResult | null
): { low: number; high: number } | null {
    if (!lookup?.flat_options?.length) return null;
    const values: number[] = [];
    for (const o of lookup.flat_options) {
        const m = o.median_resale_price_sgd;
        if (m != null && Number.isFinite(m) && m > 0) {
            values.push(m);
            continue;
        }
        const l = o.latest_resale_price_sgd;
        if (l != null && Number.isFinite(l) && l > 0) {
            values.push(l);
        }
    }
    if (values.length === 0) return null;
    return { low: Math.min(...values), high: Math.max(...values) };
}

function resaleSnapshotFootnote(p: PropertyLookupResult): string | null {
    const bits: string[] = [];
    if (p.resale_transaction_count > 0) {
        const n = p.resale_transaction_count;
        bits.push(
            `${n.toLocaleString()} resale transaction${n === 1 ? "" : "s"} in sample`
        );
    }
    if (p.resale_month_range_start && p.resale_month_range_end) {
        bits.push(
            `Data window ${p.resale_month_range_start} — ${p.resale_month_range_end}`
        );
    }
    return bits.length > 0 ? bits.join(" · ") : null;
}

export default function Hero() {
    const router = useRouter();
    const [selectedProperty, setSelectedProperty] =
        useState<PropertyLookupResult | null>(null);

    const resaleRange = useMemo(
        () => operationalResaleRange(selectedProperty),
        [selectedProperty]
    );

    const snapshotFootnote = useMemo(
        () =>
            selectedProperty ? resaleSnapshotFootnote(selectedProperty) : null,
        [selectedProperty]
    );

    const pushValuationForProperty = (property: PropertyLookupResult) => {
        const pc = (property.postal_code || "").replace(/\D/g, "");
        try {
            sessionStorage.setItem(
                "pendingValuation",
                JSON.stringify(property)
            );
        } catch {
            /* ignore */
        }
        if (pc.length === 6) {
            router.push(`/valuation?postal=${encodeURIComponent(pc)}`);
        } else {
            router.push("/valuation");
        }
    };

    const goDetailed = () => {
        if (!selectedProperty) return;
        pushValuationForProperty(selectedProperty);
    };

    return (
        <section className="relative pt-32 pb-20 overflow-hidden">
            {/* Background Decorative Elements */}
            <div className="absolute top-0 left-1/2 -translate-x-1/2 w-full max-w-7xl h-full -z-10 pointer-events-none">
                <div className="absolute top-20 left-10 w-72 h-72 bg-accent/20 rounded-full blur-[120px]" />
                <div className="absolute bottom-10 right-10 w-72 h-72 bg-secondary/20 rounded-full blur-[120px]" />
            </div>

            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.6 }}
                >
                    <span className="inline-block px-3 py-1 rounded-full bg-accent/10 text-accent text-xs font-bold tracking-wider uppercase mb-6 border border-accent/20">
                        Real Estate Valuations Redefined
                    </span>
                    <h1 className="text-5xl md:text-7xl font-extrabold tracking-tight mb-6 leading-tight">
                        Unlock the Real Value of <br />
                        <span className="text-gradient">Your Home in Singapore</span>
                    </h1>
                    <p className="text-lg md:text-xl text-foreground/60 max-w-2xl mx-auto mb-10 leading-relaxed">
                        Harness the power of AI and geospatial intelligence to get precise,
                        explainable property valuations in seconds.
                    </p>
                </motion.div>

                <motion.div
                    initial={{ opacity: 0, y: 30 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.6, delay: 0.2 }}
                    className="max-w-3xl mx-auto"
                >
                    <div className="relative group p-1.5 rounded-2xl bg-gradient-to-r from-accent/30 to-secondary/30 shadow-2xl transition-all hover:scale-[1.01]">
                        <div className="relative flex flex-col sm:flex-row sm:items-center gap-3 bg-background rounded-xl px-4 md:px-6 py-3 shadow-sm border border-foreground/5 mb-4 group-hover:border-accent/20 transition-colors text-left">
                            <MapPin className="hidden sm:block w-5 h-5 text-accent shrink-0 self-start sm:self-center mt-2 sm:mt-0" />
                            <div className="flex-1 min-w-0 w-full">
                                <PropertySearchInput
                                    selection={selectedProperty}
                                    onSelectionChange={(v) => {
                                        setSelectedProperty(v);
                                    }}
                                />
                            </div>
                        </div>
                    </div>

                    <AnimatePresence mode="sync">
                        {selectedProperty && (
                            <motion.div
                                key="hero-property-summary"
                                initial={{ opacity: 0, y: -6 }}
                                animate={{ opacity: 1, y: 0 }}
                                exit={{ opacity: 0, y: -6 }}
                                transition={{ duration: 0.2 }}
                                className="mt-4 rounded-2xl border border-foreground/10 bg-white p-6 shadow-xl text-left"
                            >
                                <div className="flex flex-wrap items-start justify-between gap-3">
                                    <div>
                                        <span className="inline-block text-xs font-bold uppercase tracking-wider text-accent mb-2">
                                            HDB · Market snapshot
                                        </span>
                                        <p className="font-semibold text-foreground text-lg">
                                            {selectedProperty.address_label}
                                        </p>
                                        <p className="text-foreground/60 text-sm mt-0.5">
                                            Postal {selectedProperty.postal_code}
                                            {selectedProperty.town
                                                ? ` · ${selectedProperty.town}`
                                                : ""}
                                            {selectedProperty.region
                                                ? ` · ${selectedProperty.region}`
                                                : ""}
                                        </p>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={goDetailed}
                                        className="shrink-0 inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-3 text-sm font-bold text-white shadow-md hover:bg-accent/90 transition-colors"
                                    >
                                        <FileText className="w-4 h-4" />
                                        Get Detailed Valuation
                                    </button>
                                </div>

                                {resaleRange ? (
                                    <div className="mt-5 rounded-xl border border-accent/15 bg-accent/5 px-4 py-4">
                                        <p className="text-xs font-semibold uppercase tracking-wide text-foreground/50">
                                            Estimated resale range (operational data)
                                        </p>
                                        <p className="mt-1 text-xs text-foreground/55">
                                            Based on median and latest resale prices by flat type
                                            recorded for this postal.
                                        </p>
                                        <p className="mt-3 text-2xl sm:text-3xl font-extrabold text-gradient tabular-nums">
                                            S${resaleRange.low.toLocaleString()}
                                            {resaleRange.high !== resaleRange.low
                                                ? ` – S$${resaleRange.high.toLocaleString()}`
                                                : ""}
                                        </p>
                                        {snapshotFootnote ? (
                                            <p className="mt-2 text-xs text-foreground/50">
                                                {snapshotFootnote}
                                            </p>
                                        ) : null}
                                    </div>
                                ) : (
                                    <p className="mt-4 text-sm text-foreground/60">
                                        No aggregated resale price statistics are available for this
                                        building yet. You can still open the detailed valuation flow to
                                        enter your unit and run the model.
                                    </p>
                                )}
                            </motion.div>
                        )}
                    </AnimatePresence>
                    <div className="mt-6 flex flex-wrap justify-center gap-8 text-sm font-medium text-foreground/50">
                        <div className="flex items-center gap-2">
                            <ShieldCheck className="w-4 h-4 text-secondary" />
                            <span>AI-Powered Precision</span>
                        </div>
                        <div className="flex items-center gap-2">
                            <TrendingUp className="w-4 h-4 text-accent" />
                            <span>Real-time Market Data</span>
                        </div>
                        <div className="flex items-center gap-2">
                            <MapPin className="w-4 h-4 text-warning" />
                            <span>Geospatial Intelligence</span>
                        </div>
                    </div>
                </motion.div>
            </div>
        </section>
    );
}
