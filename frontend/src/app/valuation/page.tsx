"use client";

import { useState, useEffect, useLayoutEffect, useMemo, useCallback, useRef, Suspense } from "react";
import Navbar from "@/components/Navbar";
import { useAuth } from "@/context/AuthContext";
import { AnimatePresence, motion } from "framer-motion";
import { AlertCircle, Building2, CheckCircle2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";

import API_BASE from "@/lib/apiBase";
import { subscriptionAwareHeaders } from "@/lib/subscriptionPreview";
import PropertySearchInput, {
    normalizePropertyLookup,
    type PropertyLookupResult,
} from "@/components/PropertySearchInput";
import ValuationBuildingSummary from "@/components/valuation/ValuationBuildingSummary";
import ValuationResultPanel, {
    type ShapExplanation,
} from "@/components/valuation/ValuationResultPanel";
import type { DriverContext } from "@/lib/shapDrivers";
import ValuationInputRecapBar from "@/components/valuation/ValuationInputRecapBar";
import ValuationUnitFormPane, {
    type ValuationFormData,
} from "@/components/valuation/ValuationUnitFormPane";

const DEFAULT_FORM = {
    postal_code: "",
    town: "",
    flat_type: "",
    flat_model_grouped: "Model A",
    region: "",
    storey_midpoint: null as number | null,
    floor_area_sqm: null as number | null,
    remaining_lease_years: 75,
};

const FALLBACK_FLAT_TYPES = [
    "1 ROOM",
    "2 ROOM",
    "3 ROOM",
    "4 ROOM",
    "5 ROOM",
    "EXECUTIVE",
    "MULTI-GENERATION",
] as const;

function remainingLeaseFromCommenceYear(
    leaseYear: number | null | undefined
): number {
    if (leaseYear == null || !Number.isFinite(leaseYear)) return 75;
    const yearsPassed = new Date().getFullYear() - leaseYear;
    const remaining = 99 - yearsPassed;
    return Math.max(1, Math.min(99, remaining));
}

export default function ValuationPage() {
    return (
        <Suspense
            fallback={
                <main className="min-h-screen bg-slate-50">
                    <Navbar />
                    <div className="flex flex-col items-center justify-center pt-40 px-4">
                        <div className="w-12 h-12 border-4 border-accent border-t-transparent rounded-full animate-spin mb-4" />
                        <p className="text-lg font-semibold text-foreground/70">Loading valuation…</p>
                    </div>
                </main>
            }
        >
            <ValuationPageContent />
        </Suspense>
    );
}

function ValuationPageContent() {
    const { user, isPremiumExperience, refreshProfile } = useAuth();
    const router = useRouter();
    const searchParams = useSearchParams();
    const postalFromQuery = useMemo(() => {
        const raw =
            searchParams.get("postal") ?? searchParams.get("postal_code") ?? "";
        const digits = raw.replace(/\D/g, "");
        return digits.length === 6 ? digits : "";
    }, [searchParams]);
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState<any>(null);
    const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
    const [saveError, setSaveError] = useState("");
    const [submitError, setSubmitError] = useState("");
    const [formData, setFormData] = useState<ValuationFormData>(DEFAULT_FORM);
    const [selectedProperty, setSelectedProperty] =
        useState<PropertyLookupResult | null>(null);
    const [paneRefreshNonce, setPaneRefreshNonce] = useState(0);
    const [addressEditOpen, setAddressEditOpen] = useState(false);
    const unitFormRef = useRef<HTMLDivElement>(null);
    const [step2FormExpanded, setStep2FormExpanded] = useState(true);

    const syncFormFromLookup = (lookup: PropertyLookupResult | null) => {
        if (!lookup) {
            setFormData((prev) => ({
                ...prev,
                postal_code: "",
                town: "",
                region: "",
                flat_type: "",
                flat_model_grouped: "Model A",
                floor_area_sqm: null,
                storey_midpoint: null,
                remaining_lease_years: 75,
            }));
            return;
        }
        const hasOpts = !!lookup.flat_options?.length;
        setFormData((prev) => ({
            ...prev,
            postal_code: lookup.postal_code,
            town: lookup.town,
            region: lookup.region,
            flat_type: "",
            flat_model_grouped: hasOpts ? "" : prev.flat_model_grouped,
            floor_area_sqm: null,
            storey_midpoint: null,
            remaining_lease_years: remainingLeaseFromCommenceYear(
                lookup.year_completed ??
                    lookup.flat_options[0]?.latest_lease_commence_year ??
                    null
            ),
        }));
    };

    useLayoutEffect(() => {
        try {
            const raw = sessionStorage.getItem("pendingValuation");
            if (!raw) return;
            const data = normalizePropertyLookup(
                JSON.parse(raw) as PropertyLookupResult
            );
            sessionStorage.removeItem("pendingValuation");
            setSelectedProperty(data);
            syncFormFromLookup(data);
        } catch {
            sessionStorage.removeItem("pendingValuation");
        }
    }, []);

    useEffect(() => {
        if (!postalFromQuery) return;
        const digits = (selectedProperty?.postal_code || "").replace(/\D/g, "");
        if (digits !== postalFromQuery) return;
        const qs = searchParams.get("postal") || searchParams.get("postal_code");
        if (!qs) return;
        router.replace("/valuation");
    }, [selectedProperty, postalFromQuery, searchParams, router]);

    /** Backend returns ``{ baseline, predicted_log1p, contributions[] }``; older saved runs may still be arrays. */
    const shapExplanation = useMemo((): ShapExplanation | null => {
        const sv = result?.shap_values as unknown;
        if (sv == null) return null;
        if (Array.isArray(sv)) {
            const legacy = sv as Array<{
                feature: string;
                contribution: number;
                contribution_sgd?: number;
                contribution_log?: number;
                source_column?: string | null;
                feature_value?: number | string | null;
            }>;
            if (!legacy.length) return null;
            return {
                rows: legacy.map((row) => {
                    const clog =
                        typeof row.contribution_log === "number"
                            ? row.contribution_log
                            : row.contribution;
            const hasSgd =
                typeof row.contribution_sgd === "number" &&
                Number.isFinite(row.contribution_sgd);
            return {
                feature: row.feature,
                contribution_log: clog,
                chart_value: hasSgd ? row.contribution_sgd! : clog,
                contribution_sgd: hasSgd ? row.contribution_sgd : undefined,
                source_column:
                    typeof row.source_column === "string" ? row.source_column : null,
                feature_value:
                    row.feature_value === undefined || row.feature_value === null
                        ? null
                        : (row.feature_value as number | string),
            };
                }),
            };
        }
        const obj = sv as Record<string, unknown>;
        const contribs = obj.contributions;
        if (!Array.isArray(contribs) || contribs.length === 0) return null;
        let parsedBaseline: ShapExplanation["baseline"];
        const baseline = obj.baseline;
        if (
            baseline &&
            typeof baseline === "object" &&
            baseline !== null &&
            typeof (baseline as { price_sgd?: unknown }).price_sgd === "number" &&
            typeof (baseline as { expected_value_log1p?: unknown }).expected_value_log1p ===
                "number"
        ) {
            parsedBaseline = {
                price_sgd: (baseline as { price_sgd: number }).price_sgd,
                expected_value_log1p: (baseline as { expected_value_log1p: number })
                    .expected_value_log1p,
            };
        }
        const pred = obj.predicted_log1p;
        const predicted_log1p =
            typeof pred === "number" && Number.isFinite(pred) ? pred : undefined;
        const rows = (contribs as Array<Record<string, unknown>>).map((c) => {
            const feature = String(c.feature ?? "");
            const clog =
                typeof c.contribution_log === "number"
                    ? (c.contribution_log as number)
                    : typeof c.contribution === "number"
                      ? (c.contribution as number)
                      : 0;
            const hasSgd =
                typeof c.contribution_sgd === "number" && Number.isFinite(c.contribution_sgd);
            const srcCol = c.source_column;
            const featVal = c.feature_value;
            return {
                feature,
                contribution_log: clog,
                chart_value: hasSgd ? (c.contribution_sgd as number) : clog,
                contribution_sgd: hasSgd ? (c.contribution_sgd as number) : undefined,
                source_column: typeof srcCol === "string" ? srcCol : null,
                feature_value:
                    featVal === undefined || featVal === null
                        ? null
                        : (featVal as number | string),
            };
        });
        rows.sort((a, b) => Math.abs(b.chart_value) - Math.abs(a.chart_value));
        return {
            baseline: parsedBaseline,
            predicted_log1p,
            rows,
        };
    }, [result?.shap_values]);

    const flatTypeChoices = useMemo(
        () =>
            selectedProperty?.flat_options?.length &&
            selectedProperty.flat_options.length > 0
                ? selectedProperty.flat_options.map((o) => o.flat_type)
                : [...FALLBACK_FLAT_TYPES],
        [selectedProperty]
    );

    const selectedFlatOpt = useMemo(() => {
        if (!selectedProperty?.flat_options?.length) return null;
        return (
            selectedProperty.flat_options.find(
                (o) => o.flat_type === formData.flat_type
            ) ?? null
        );
    }, [selectedProperty, formData.flat_type]);

    const buildingYearCompleted =
        selectedProperty?.year_completed ?? null;
    const buildingLeaseRemaining =
        buildingYearCompleted != null
            ? remainingLeaseFromCommenceYear(buildingYearCompleted)
            : null;

    const areaMin = selectedFlatOpt?.min_floor_area_sqm ?? null;
    const areaMax = selectedFlatOpt?.max_floor_area_sqm ?? null;
    const buildingMaxStorey = selectedProperty?.building_max_storey ?? null;

    const faVal = formData.floor_area_sqm;
    const areaOutOfRange =
        faVal != null &&
        Number.isFinite(faVal) &&
        areaMin != null &&
        areaMax != null &&
        (faVal < areaMin || faVal > areaMax);

    const storeyVal = formData.storey_midpoint;
    const storeyOutOfRange =
        storeyVal != null &&
        Number.isFinite(storeyVal) &&
        buildingMaxStorey != null &&
        buildingMaxStorey >= 1 &&
        (storeyVal < 1 || storeyVal > buildingMaxStorey);

    const floorAreaPlaceholder =
        areaMin != null && areaMax != null
            ? `e.g. ${areaMin}–${areaMax} sqm`
            : "Floor area (sqm)";
    const storeyPlaceholder =
        buildingMaxStorey != null && buildingMaxStorey >= 1
            ? `e.g. 1–${buildingMaxStorey} (floor level)`
            : "Floor level (storey)";

    const hasValidFlatType = !!formData.flat_type?.trim();
    const hasValidFloorArea =
        formData.floor_area_sqm != null &&
        Number.isFinite(Number(formData.floor_area_sqm)) &&
        Number(formData.floor_area_sqm) > 0;
    const hasValidStorey =
        formData.storey_midpoint != null &&
        Number.isFinite(Number(formData.storey_midpoint)) &&
        Number(formData.storey_midpoint) >= 1;

    const completedRequiredCount = [
        !!selectedProperty,
        hasValidFlatType,
        hasValidFloorArea,
        hasValidStorey,
    ].filter(Boolean).length;
    const requiredFieldCount = 4;
    const completionPct = Math.round(
        (completedRequiredCount / requiredFieldCount) * 100
    );
    const isStep1Complete = !!selectedProperty;

    const freezeStep2AsSummary = result != null && !step2FormExpanded;

    const formCompletionCheckpoints = useMemo(
        () => [
            {
                id: "building",
                label: "Building",
                shortLabel: "Building",
                done: !!selectedProperty,
            },
            {
                id: "flat",
                label: "Flat type",
                shortLabel: "Flat type",
                done: hasValidFlatType,
            },
            {
                id: "area",
                label: "Floor area",
                shortLabel: "Area",
                done: hasValidFloorArea,
            },
            {
                id: "storey",
                label: "Floor level",
                shortLabel: "Floor",
                done: hasValidStorey,
            },
        ],
        [
            selectedProperty,
            hasValidFlatType,
            hasValidFloorArea,
            hasValidStorey,
        ]
    );

    const handleSubmit = async () => {
        if (!formData.flat_type?.trim()) {
            setSubmitError("Please select a flat type.");
            return;
        }
        if (
            formData.floor_area_sqm == null ||
            formData.storey_midpoint == null
        ) {
            setSubmitError(
                "Please enter floor area and floor level."
            );
            return;
        }
        const nfa = Number(formData.floor_area_sqm);
        const nsm = Number(formData.storey_midpoint);
        if (
            !Number.isFinite(nfa) ||
            nfa <= 0 ||
            !Number.isFinite(nsm) ||
            nsm < 1
        ) {
            setSubmitError(
                "Please enter valid positive numbers for floor area and floor level."
            );
            return;
        }

        setLoading(true);
        setSubmitError("");
        try {
            const token = localStorage.getItem('token');
            const headers: Record<string, string> = {
                "Content-Type": "application/json",
                ...subscriptionAwareHeaders(token),
            };

            const payload = {
                ...formData,
                floor_area_sqm: nfa,
                storey_midpoint: Math.round(nsm),
                latitude: selectedProperty?.latitude ?? null,
                longitude: selectedProperty?.longitude ?? null,
                lease_commence_year:
                    selectedProperty?.flat_options?.find(
                        (o) => o.flat_type === formData.flat_type
                    )?.latest_lease_commence_year ??
                    selectedProperty?.year_completed ??
                    null,
            };

            const response = await fetch(`${API_BASE}/api/valuation`, {
                method: "POST",
                headers,
                body: JSON.stringify(payload),
            });
            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.detail || "Failed to calculate valuation");
            }

            setResult(data);
            setStep2FormExpanded(false);
            // Store data for report generation
            localStorage.setItem('lastValuationProperty', JSON.stringify(payload));
            localStorage.setItem('lastValuationResult', JSON.stringify(data));
            
            // Refresh the user profile to update remaining_valuations
            if (user?.role === 'free') {
                refreshProfile().catch(() => {});
            }
            
            setSaveState("idle");
            setSaveError("");
        } catch (error: any) {
            console.error("Valuation failed:", error);
            setSubmitError(error.message || "Failed to connect to the server.");
        } finally {
            setLoading(false);
        }
    };

    const handleSave = async () => {
        if (!user) {
            router.push("/login?next=/valuation");
            return;
        }
        const token = localStorage.getItem("token");
        if (!token) {
            router.push("/login?next=/valuation");
            return;
        }
        if (!result?.predicted_price) return;

        setSaveState("saving");
        setSaveError("");
        try {
            const res = await fetch(`${API_BASE}/api/user/saved-properties`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    ...subscriptionAwareHeaders(token),
                },
                body: JSON.stringify({
                    postal_code: formData.postal_code,
                    property_type: "HDB",
                    predicted_price: Math.round(Number(result.predicted_price)),
                }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || "Failed to save property");
            }
            setSaveState("saved");
        } catch (e: any) {
            setSaveState("error");
            setSaveError(e?.message || "Failed to save property");
        }
    };

    const hasSelection = !!selectedProperty;

    const handleValuationNewSearch = () => {
        setResult(null);
        setStep2FormExpanded(true);
        setSelectedProperty(null);
        setFormData(DEFAULT_FORM);
        setSubmitError("");
        setAddressEditOpen(false);
    };

    const handleEditInputs = useCallback(() => {
        setStep2FormExpanded(true);
        requestAnimationFrame(() => {
            unitFormRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
        });
    }, []);

    const handlePropertySelectionChange = useCallback(
        (v: PropertyLookupResult | null) => {
            setSelectedProperty(v);
            syncFormFromLookup(v);
            setSubmitError("");
            setResult(null);
            setStep2FormExpanded(true);
            setSaveState("idle");
            setSaveError("");
            setPaneRefreshNonce((n) => n + 1);
            setAddressEditOpen(false);
        },
        []
    );

    return (
        <main className="min-h-screen bg-slate-50">
            <Navbar />

            <div className="max-w-7xl mx-auto pt-32 pb-20 px-4 sm:px-6">
                <div className="mb-12 text-center">
                    <h1 className="text-4xl font-extrabold mb-4 tracking-tight">Property Valuation</h1>
                    <p className="text-foreground/50 max-w-3xl mx-auto">
                        Select a building, review its details in Step 1, complete unit fields, then
                        open the Valuation tab for your estimate and location analytics.
                    </p>
                    {(!user || user.role === 'free') && (
                        <div className="mt-4 inline-block bg-accent/10 border border-accent/20 px-4 py-2 rounded-full text-accent font-semibold text-sm">
                            {user?.remaining_valuations ?? 3}/3 Free Valuations Remaining
                        </div>
                    )}
                </div>

                <div className="relative overflow-visible">
                    {loading && (
                        <div className="absolute inset-0 bg-background/80 backdrop-blur-sm z-50 flex flex-col items-center justify-center rounded-3xl">
                            <div className="w-12 h-12 border-4 border-accent border-t-transparent rounded-full animate-spin mb-4" />
                            <p className="font-semibold text-accent animate-pulse">Analyzing Market Data...</p>
                        </div>
                    )}

                    <div className="space-y-6">
                        {!hasSelection && (
                            <motion.section
                                layout
                                transition={{ type: "spring", stiffness: 145, damping: 24, mass: 0.9 }}
                                className="glass rounded-3xl p-6 md:p-8 shadow-2xl max-w-3xl mx-auto"
                            >
                                <motion.div layout className="flex items-start justify-between gap-3">
                                    <h2 className="text-xl font-bold flex items-center gap-2 mb-4">
                                        <Building2 className="w-5 h-5 text-accent" />
                                        Step 1 · Find Your Building
                                        <AlertCircle
                                            className="w-4 h-4 text-amber-500"
                                            aria-label="Step incomplete"
                                        />
                                    </h2>
                                </motion.div>
                                <PropertySearchInput
                                    key="valuation-search-landing"
                                    selection={selectedProperty}
                                    onSelectionChange={handlePropertySelectionChange}
                                    initialPostal={postalFromQuery || formData.postal_code}
                                />
                            </motion.section>
                        )}

                        <AnimatePresence initial={false}>
                            {hasSelection ? (
                                <motion.section
                                    key="valuation-workspace"
                                    initial={{ opacity: 0, y: 18, scale: 0.985 }}
                                    animate={{ opacity: 1, y: 0, scale: 1 }}
                                    exit={{ opacity: 0, y: 12, scale: 0.99 }}
                                    transition={{ duration: 0.5, ease: "easeInOut" }}
                                    className="max-w-4xl mx-auto w-full"
                                >
                                    <motion.div
                                        initial={{ opacity: 0, x: -14 }}
                                        animate={{ opacity: 1, x: 0 }}
                                        transition={{ duration: 0.42, ease: "easeOut" }}
                                        className="glass rounded-3xl p-6 md:p-8 shadow-2xl space-y-5"
                                    >
                                        {!result ? (
                                            <div
                                                className="rounded-xl border border-foreground/10 bg-background/70 px-4 py-4"
                                                aria-label="Form completion progress"
                                            >
                                                <div className="mb-3 flex items-center justify-between gap-3 text-xs">
                                                    <span className="font-semibold uppercase tracking-wide text-foreground/55">
                                                        Form completion
                                                    </span>
                                                    <span className="font-semibold text-foreground/70 tabular-nums shrink-0">
                                                        {completedRequiredCount}/{requiredFieldCount} · {completionPct}%
                                                    </span>
                                                </div>
                                                <div className="mb-3 flex gap-1.5" role="list">
                                                    {formCompletionCheckpoints.map((c) => (
                                                        <div
                                                            key={c.id}
                                                            role="listitem"
                                                            className="flex-1 min-w-0"
                                                            title={`${c.label}: ${c.done ? "complete" : "pending"}`}
                                                        >
                                                            <div className="h-2 w-full rounded-full bg-foreground/10 overflow-hidden">
                                                                <div
                                                                    className={`h-full rounded-full transition-all duration-300 ${
                                                                        c.done ? "w-full bg-emerald-500" : "w-0 bg-transparent"
                                                                    }`}
                                                                />
                                                            </div>
                                                        </div>
                                                    ))}
                                                </div>
                                                <div className="grid grid-cols-4 gap-2 sm:gap-3">
                                                    {formCompletionCheckpoints.map((c) => (
                                                        <div
                                                            key={c.id}
                                                            className="flex flex-col items-center gap-1 text-center min-w-0"
                                                        >
                                                            {c.done ? (
                                                                <CheckCircle2
                                                                    className="w-4 h-4 text-emerald-600 shrink-0"
                                                                    aria-hidden
                                                                />
                                                            ) : (
                                                                <span
                                                                    className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full border-2 border-foreground/20 bg-background"
                                                                    aria-hidden
                                                                />
                                                            )}
                                                            <span
                                                                className={`text-[10px] sm:text-xs font-semibold leading-snug ${
                                                                    c.done ? "text-emerald-800" : "text-foreground/45"
                                                                }`}
                                                            >
                                                                <span className="sm:hidden">{c.shortLabel}</span>
                                                                <span className="hidden sm:inline">{c.label}</span>
                                                            </span>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        ) : null}

                                        {result && selectedProperty ? (
                                            <ValuationInputRecapBar
                                                selectedProperty={selectedProperty}
                                                formData={formData}
                                                onEditInputs={handleEditInputs}
                                            />
                                        ) : null}

                                        <div className="space-y-5">
                                            <div className="flex items-start justify-between gap-3">
                                                <h2 className="text-xl font-bold flex items-center gap-2 min-w-0 flex-1">
                                                    <Building2 className="w-5 h-5 text-accent shrink-0" />
                                                    <span className="min-w-0">Step 1 · Choose HDB</span>
                                                    {isStep1Complete ? (
                                                        <CheckCircle2
                                                            className="w-4 h-4 text-emerald-600 shrink-0"
                                                            aria-label="Step complete"
                                                        />
                                                    ) : (
                                                        <AlertCircle
                                                            className="w-4 h-4 text-amber-500 shrink-0"
                                                            aria-label="Step incomplete"
                                                        />
                                                    )}
                                                </h2>
                                                {selectedProperty ? (
                                                    addressEditOpen ? (
                                                        <button
                                                            type="button"
                                                            onClick={() => setAddressEditOpen(false)}
                                                            className="shrink-0 text-sm font-semibold px-3 py-1.5 rounded-lg border border-foreground/15 bg-white text-foreground hover:bg-foreground/5 transition-colors"
                                                        >
                                                            Cancel
                                                        </button>
                                                    ) : (
                                                        <button
                                                            type="button"
                                                            onClick={() => setAddressEditOpen(true)}
                                                            className="shrink-0 text-sm font-semibold px-3 py-1.5 rounded-lg border border-foreground/15 bg-white text-foreground hover:bg-foreground/5 transition-colors"
                                                        >
                                                            Edit
                                                        </button>
                                                    )
                                                ) : null}
                                            </div>
                                            <PropertySearchInput
                                                key="valuation-search-workspace"
                                                selection={selectedProperty}
                                                onSelectionChange={handlePropertySelectionChange}
                                                initialPostal={postalFromQuery || formData.postal_code}
                                                selectionPresentation={
                                                    selectedProperty
                                                        ? addressEditOpen
                                                            ? "search"
                                                            : "tag"
                                                        : "tag"
                                                }
                                            />
                                            {addressEditOpen ? (
                                                <p className="text-xs text-foreground/50">
                                                    Search for a different building, or cancel to keep the
                                                    current address.
                                                </p>
                                            ) : null}
                                            <ValuationBuildingSummary
                                                selectedProperty={selectedProperty}
                                                buildingYearCompleted={buildingYearCompleted}
                                                buildingLeaseRemaining={buildingLeaseRemaining}
                                            />
                                            <div ref={unitFormRef}>
                                                <ValuationUnitFormPane
                                                    selectedProperty={selectedProperty}
                                                    formData={formData}
                                                    setFormData={setFormData}
                                                    flatTypeChoices={flatTypeChoices}
                                                    floorAreaPlaceholder={floorAreaPlaceholder}
                                                    storeyPlaceholder={storeyPlaceholder}
                                                    selectedFlatOption={selectedFlatOpt}
                                                    areaMin={areaMin}
                                                    areaMax={areaMax}
                                                    buildingMaxStorey={buildingMaxStorey}
                                                    areaOutOfRange={areaOutOfRange}
                                                    storeyOutOfRange={storeyOutOfRange}
                                                    submitError={submitError}
                                                    onSubmit={() => void handleSubmit()}
                                                    loading={loading}
                                                    remainingLeaseFromCommenceYear={
                                                        remainingLeaseFromCommenceYear
                                                    }
                                                    step2FrozenAfterValuation={
                                                        freezeStep2AsSummary
                                                    }
                                                    onEditStep2Details={() =>
                                                        setStep2FormExpanded(true)
                                                    }
                                                    isNested
                                                />
                                            </div>
                                        </div>

                                        {result ? (
                                            <ValuationResultPanel
                                                result={result}
                                                shapExplanation={shapExplanation}
                                                formData={formData}
                                                user={user}
                                                isPremiumExperience={isPremiumExperience}
                                                onNewSearch={handleValuationNewSearch}
                                                handleSave={handleSave}
                                                saveState={saveState}
                                                saveError={saveError}
                                                selectedProperty={selectedProperty}
                                                analyticsRefreshNonce={paneRefreshNonce}
                                                driverContext={
                                                    result?.driver_context &&
                                                    typeof result.driver_context === "object"
                                                        ? (result.driver_context as DriverContext)
                                                        : null
                                                }
                                            />
                                        ) : null}
                                    </motion.div>
                                </motion.section>
                            ) : null}
                        </AnimatePresence>

                    </div>
                </div>
            </div>
        </main>
    );
}
