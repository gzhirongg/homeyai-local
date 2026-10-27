"use client";

import type { PropertyLookupResult } from "@/components/PropertySearchInput";
import type { ValuationFormData } from "@/components/valuation/ValuationUnitFormPane";
import { formatFlatTypeWithUnits } from "@/lib/hdbFlatTypeDisplay";

type Props = {
    selectedProperty: PropertyLookupResult;
    formData: ValuationFormData;
    onEditInputs: () => void;
};

export default function ValuationInputRecapBar({
    selectedProperty,
    formData,
    onEditInputs,
}: Props) {
    const flatOpt = selectedProperty.flat_options?.find(
        (o) => o.flat_type === formData.flat_type
    );
    const flatLabel = formData.flat_type
        ? flatOpt != null
            ? formatFlatTypeWithUnits(formData.flat_type, flatOpt.units_sold ?? 0)
            : formData.flat_type
        : "—";

    const parts = [
        selectedProperty.address_label,
        flatLabel,
        formData.floor_area_sqm != null ? `${formData.floor_area_sqm} sqm` : null,
        formData.storey_midpoint != null ? `Floor ${formData.storey_midpoint}` : null,
        formData.remaining_lease_years != null
            ? `~${formData.remaining_lease_years} yrs lease`
            : null,
    ].filter(Boolean);

    return (
        <div className="sticky top-20 z-30 -mx-1 px-1 py-2 bg-slate-50/95 backdrop-blur-sm border-b border-foreground/10 mb-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-foreground/80 min-w-0 flex-1 leading-snug">
                    <span className="font-semibold text-foreground">Your inputs: </span>
                    {parts.join(" · ")}
                </p>
                <button
                    type="button"
                    onClick={onEditInputs}
                    className="shrink-0 text-sm font-semibold px-3 py-1.5 rounded-lg border border-foreground/15 bg-white text-foreground hover:bg-foreground/5 transition-colors"
                >
                    Edit inputs
                </button>
            </div>
        </div>
    );
}
