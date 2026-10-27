"use client";

import { useMemo } from "react";

import {
    AlertCircle,
    AlertTriangle,
    Calculator,
    CheckCircle2,
    Layers,
} from "lucide-react";

import type { PropertyLookupResult } from "@/components/PropertySearchInput";
import {
    formatFlatTypeCatalogueShort,
    formatFlatTypeWithUnits,
} from "@/lib/hdbFlatTypeDisplay";

export type ValuationFormData = {
    postal_code: string;
    town: string;
    flat_type: string;
    flat_model_grouped: string;
    region: string;
    storey_midpoint: number | null;
    floor_area_sqm: number | null;
    remaining_lease_years: number;
};

type FormSetter = (next: ValuationFormData) => void;

function RequiredMark() {
    return (
        <span className="text-red-500 ml-0.5 font-semibold" aria-hidden="true">
            *
        </span>
    );
}

export default function ValuationUnitFormPane({
    selectedProperty,
    formData,
    setFormData,
    flatTypeChoices,
    floorAreaPlaceholder,
    storeyPlaceholder,
    selectedFlatOption,
    areaMin,
    areaMax,
    buildingMaxStorey,
    areaOutOfRange,
    storeyOutOfRange,
    submitError,
    onSubmit,
    loading,
    remainingLeaseFromCommenceYear,
    step2FrozenAfterValuation,
    onEditStep2Details,
    isNested = false,
}: {
    selectedProperty: PropertyLookupResult | null;
    formData: ValuationFormData;
    setFormData: FormSetter;
    flatTypeChoices: string[];
    floorAreaPlaceholder: string;
    storeyPlaceholder: string;
    selectedFlatOption:
        | {
              flat_type: string;
              flat_model_grouped: string;
              latest_lease_commence_year: number | null;
          }
        | null
        | undefined;
    areaMin: number | null;
    areaMax: number | null;
    buildingMaxStorey: number | null;
    areaOutOfRange: boolean;
    storeyOutOfRange: boolean;
    submitError: string;
    onSubmit: () => void;
    loading: boolean;
    remainingLeaseFromCommenceYear: (leaseYear: number | null | undefined) => number;
    step2FrozenAfterValuation?: boolean;
    onEditStep2Details?: () => void;
    isNested?: boolean;
}) {
    const canSubmit = !!selectedProperty && !loading;
    const faVal = formData.floor_area_sqm;
    const storeyVal = formData.storey_midpoint;
    const hasFlatType = Boolean(formData.flat_type?.trim());
    const floorNum = formData.floor_area_sqm;
    const storeyNum = formData.storey_midpoint;
    const hasValidFloorArea =
        floorNum != null &&
        Number.isFinite(Number(floorNum)) &&
        Number(floorNum) > 0;
    const hasValidStorey =
        storeyNum != null &&
        Number.isFinite(Number(storeyNum)) &&
        Number(storeyNum) >= 1;
    const needsUnitInput = !hasFlatType || !hasValidFloorArea || !hasValidStorey;

    const isStep2Complete = !needsUnitInput;

    const storeyHint =
        buildingMaxStorey != null &&
        typeof buildingMaxStorey === "number" &&
        Number.isFinite(buildingMaxStorey) &&
        buildingMaxStorey >= 1
            ? `This block has ${buildingMaxStorey} residential storey${
                  buildingMaxStorey === 1 ? "" : "s"
              } per HDB Property Information (floors 1–${buildingMaxStorey}).`
            : "Official storey count is not on file for this postal—use your flat level with ground floor as 1.";

    const frozen = step2FrozenAfterValuation === true;

    const summaryItems = useMemo(() => {
        let flatDisplay = "—";
        if (formData.flat_type?.trim()) {
            const opt = selectedProperty?.flat_options?.find(
                (o) => o.flat_type === formData.flat_type
            );
            if (opt != null && typeof opt.units_sold === "number") {
                flatDisplay = formatFlatTypeWithUnits(formData.flat_type, opt.units_sold);
            } else {
                flatDisplay = formatFlatTypeCatalogueShort(formData.flat_type);
            }
        }
        return [
            { label: "Flat type", value: flatDisplay },
            {
                label: "Flat model",
                value: formData.flat_model_grouped || "—",
            },
            {
                label: "Floor area",
                value:
                    formData.floor_area_sqm != null
                        ? `${formData.floor_area_sqm} sqm`
                        : "—",
            },
            {
                label: "Floor level",
                value:
                    formData.storey_midpoint != null
                        ? String(formData.storey_midpoint)
                        : "—",
            },
        ];
    }, [
        formData.flat_type,
        formData.flat_model_grouped,
        formData.floor_area_sqm,
        formData.storey_midpoint,
        selectedProperty?.flat_options,
    ]);

    return (
        <section
            className={
                isNested
                    ? "space-y-5"
                    : "rounded-2xl border border-foreground/10 bg-background p-5 md:p-6 space-y-5"
            }
        >
            <div className="flex items-center justify-between gap-3 flex-wrap">
                <h3 className="text-xl font-bold flex items-center gap-2">
                    <Layers className="text-accent w-5 h-5" />
                    Step 2 · Enter Unit Details
                    {isStep2Complete ? (
                        <CheckCircle2
                            className="w-4 h-4 text-emerald-600"
                            aria-label="Step complete"
                        />
                    ) : (
                        <AlertCircle
                            className="w-4 h-4 text-amber-500"
                            aria-label="Step incomplete"
                        />
                    )}
                </h3>
                <div className="flex items-center gap-2 shrink-0">
                    {frozen ? (
                        <button
                            type="button"
                            onClick={() => onEditStep2Details?.()}
                            className="shrink-0 text-sm font-semibold px-3 py-1.5 rounded-lg border border-foreground/15 bg-white text-foreground hover:bg-foreground/5 transition-colors"
                        >
                            Edit
                        </button>
                    ) : (
                        <span
                            className={`text-xs font-semibold px-2.5 py-1 rounded-full ${
                                isStep2Complete
                                    ? "bg-emerald-100 text-emerald-700"
                                    : "bg-amber-100 text-amber-700"
                            }`}
                        >
                            {isStep2Complete ? "Complete" : "Incomplete"}
                        </span>
                    )}
                </div>
            </div>

            {frozen ? (
                <div className="rounded-xl border border-foreground/10 bg-white/70 px-4 py-4 space-y-3">
                    <p className="text-xs font-medium text-foreground/60">
                        Inputs used for your estimate (tap Edit to change or recalculate):
                    </p>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        {summaryItems.map((item) => (
                            <div
                                key={item.label}
                                className="rounded-lg border border-foreground/10 bg-background px-3 py-2"
                            >
                                <p className="text-[11px] uppercase tracking-wide text-foreground/45">
                                    {item.label}
                                </p>
                                <p className="text-sm font-semibold text-foreground mt-0.5">
                                    {item.value}
                                </p>
                            </div>
                        ))}
                    </div>
                </div>
            ) : (
                <>
                    <div className="space-y-4">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 md:items-end">
                        <div>
                            <label className="block text-sm font-medium mb-2">
                                Flat Type
                                <RequiredMark />
                            </label>
                            <select
                                className="w-full bg-background border border-foreground/10 rounded-xl px-4 py-3 focus:ring-2 focus:ring-accent outline-none appearance-none"
                                value={
                                    flatTypeChoices.includes(formData.flat_type)
                                        ? formData.flat_type
                                        : ""
                                }
                                onChange={(e) => {
                                    const nextType = e.target.value;
                                    if (!nextType) return;
                                    const opt = selectedProperty?.flat_options.find(
                                        (o) => o.flat_type === nextType
                                    );
                                    setFormData({
                                        ...formData,
                                        flat_type: nextType,
                                        flat_model_grouped:
                                            opt?.flat_model_grouped ??
                                            formData.flat_model_grouped,
                                        remaining_lease_years: remainingLeaseFromCommenceYear(
                                            opt?.latest_lease_commence_year ??
                                                selectedProperty?.year_completed ??
                                                null
                                        ),
                                        floor_area_sqm: null,
                                        storey_midpoint: null,
                                    });
                                }}
                                disabled={!selectedProperty}
                            >
                                <option value="" disabled></option>
                                {flatTypeChoices.map((ft) => {
                                    const opt = selectedProperty?.flat_options?.find(
                                        (o) => o.flat_type === ft
                                    );
                                    const units =
                                        typeof opt?.units_sold === "number"
                                            ? opt.units_sold
                                            : 0;
                                    const label =
                                        selectedProperty?.flat_options?.length && opt
                                            ? formatFlatTypeWithUnits(ft, units)
                                            : ft;
                                    return (
                                        <option key={ft} value={ft}>
                                            {label}
                                        </option>
                                    );
                                })}
                            </select>
                        </div>
                        <div>
                            <label className="block text-sm font-medium mb-2 text-foreground/90">
                                Flat model
                                <RequiredMark />
                                <span className="text-foreground/45 font-normal text-xs ml-1">
                                    (from flat type)
                                </span>
                            </label>
                            {selectedProperty?.flat_options?.length ? (
                                <input
                                    type="text"
                                    readOnly
                                    disabled
                                    title="Derived from the selected flat type"
                                    className="w-full bg-slate-100 border border-foreground/10 rounded-xl px-4 py-3 text-foreground/80 cursor-not-allowed outline-none placeholder:text-foreground/40 disabled:opacity-90"
                                    value={
                                        formData.flat_type
                                            ? formData.flat_model_grouped
                                            : ""
                                    }
                                    placeholder="Select a flat type first"
                                />
                            ) : (
                                <input
                                    type="text"
                                    readOnly
                                    disabled
                                    title="Derived from building lookup"
                                    className="w-full bg-slate-100 border border-foreground/10 rounded-xl px-4 py-3 text-foreground/70 cursor-not-allowed outline-none disabled:opacity-90"
                                    value={
                                        selectedFlatOption?.flat_model_grouped ?? "Model A"
                                    }
                                />
                            )}
                        </div>
                    </div>

                    <div>
                        <label className="block text-sm font-medium mb-2">
                            Floor area (sqm)
                            <RequiredMark />
                        </label>
                        <input
                            type="number"
                            step="0.1"
                            min={0}
                            placeholder={floorAreaPlaceholder}
                            className={`w-full bg-background border rounded-xl px-4 py-3 focus:ring-2 focus:ring-accent outline-none ${
                                areaOutOfRange
                                    ? "border-amber-400 ring-amber-100"
                                    : "border-foreground/10"
                            }`}
                            value={formData.floor_area_sqm ?? ""}
                            onChange={(e) => {
                                const v = e.target.value;
                                setFormData({
                                    ...formData,
                                    floor_area_sqm: v === "" ? null : Number(v),
                                });
                            }}
                            disabled={!selectedProperty}
                        />
                        <p className="mt-1 text-xs text-foreground/50">
                            Operational resale range for this flat type at this address:{" "}
                            {areaMin != null && areaMax != null
                                ? `${areaMin}–${areaMax} sqm`
                                : "not available"}
                        </p>
                        {areaOutOfRange ? (
                            <div className="mt-3 flex items-start gap-2 bg-amber-50 border border-amber-200 text-amber-900 rounded-xl px-4 py-3 text-sm">
                                <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0 text-amber-600" />
                                <span>
                                    Floor area <strong>{faVal}</strong> sqm is outside the
                                    range seen in resale data for{" "}
                                    <strong>{formData.flat_type || "—"}</strong> at this
                                    address (
                                    <strong>{areaMin}</strong>–<strong>{areaMax}</strong> sqm).
                                    The prediction may be less accurate.
                                </span>
                            </div>
                        ) : null}
                    </div>

                    <div>
                        <label className="block text-sm font-medium mb-2">
                            Floor level
                            <RequiredMark />
                        </label>
                        <input
                            type="number"
                            min={1}
                            max={
                                buildingMaxStorey != null &&
                                buildingMaxStorey >= 1
                                    ? buildingMaxStorey
                                    : undefined
                            }
                            placeholder={storeyPlaceholder}
                            className={`w-full bg-background border rounded-xl px-4 py-3 focus:ring-2 focus:ring-accent outline-none ${
                                storeyOutOfRange
                                    ? "border-amber-400 ring-amber-100"
                                    : "border-foreground/10"
                            }`}
                            value={formData.storey_midpoint ?? ""}
                            onChange={(e) => {
                                const v = e.target.value;
                                setFormData({
                                    ...formData,
                                    storey_midpoint: v === "" ? null : Number(v),
                                });
                            }}
                            disabled={!selectedProperty}
                        />
                        <p className="mt-1 text-xs text-foreground/50">{storeyHint}</p>
                        {storeyOutOfRange &&
                        buildingMaxStorey != null &&
                        buildingMaxStorey >= 1 ? (
                            <div className="mt-3 flex items-start gap-2 bg-amber-50 border border-amber-200 text-amber-900 rounded-xl px-4 py-3 text-sm">
                                <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0 text-amber-600" />
                                <span>
                                    Floor level <strong>{storeyVal}</strong> is outside the
                                    documented range{" "}
                                    <strong>{`1–${buildingMaxStorey}`}</strong> for this
                                    building (HDB Property Information). The prediction may be
                                    less accurate.
                                </span>
                            </div>
                        ) : null}
                    </div>
                    </div>
                </>
            )}

            {!frozen && submitError && (
                <div className="bg-red-50 text-red-600 p-4 rounded-xl text-sm border border-red-100 font-medium">
                    {submitError}
                </div>
            )}

            {!frozen && (
                <button
                    type="button"
                    onClick={onSubmit}
                    disabled={!canSubmit || needsUnitInput}
                    className="w-full bg-accent text-white py-4 rounded-xl font-bold hover:shadow-lg transition-all flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    Calculate Valuation <Calculator className="w-4 h-4" />
                </button>
            )}
        </section>
    );
}
