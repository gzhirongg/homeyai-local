"use client";

import { useMemo } from "react";

import type { PropertyLookupResult } from "@/components/PropertySearchInput";
import { formatFlatTypeCatalogueShort } from "@/lib/hdbFlatTypeDisplay";

function formatSgdWhole(value: number | null | undefined): string {
    if (value == null || Number.isNaN(value)) return "—";
    return new Intl.NumberFormat("en-SG", {
        style: "currency",
        currency: "SGD",
        maximumFractionDigits: 0,
    }).format(value);
}

type Props = {
    selectedProperty: PropertyLookupResult;
};

export default function ValuationResaleByFlatType({ selectedProperty }: Props) {
    const resaleMonthCaption = useMemo(() => {
        const a = selectedProperty.resale_month_range_start;
        const b = selectedProperty.resale_month_range_end;
        if (a && b) return a === b ? a : `${a} → ${b}`;
        return a || b || "";
    }, [selectedProperty]);

    return (
        <div className="space-y-4">
            <div className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
                <div>
                    <p className="text-[11px] text-foreground/45 font-medium">
                        Records (this postal)
                    </p>
                    <p className="font-semibold mt-0.5">
                        {selectedProperty.resale_transaction_count}
                    </p>
                </div>
                <div>
                    <p className="text-[11px] text-foreground/45 font-medium">Month span</p>
                    <p className="font-semibold mt-0.5">{resaleMonthCaption || "—"}</p>
                </div>
            </div>
            <p className="text-[11px] text-foreground/38">
                Derived from registered HDB resale transactions linked to this address in our
                dataset. Median uses sales with recorded prices only.
            </p>
            {selectedProperty.flat_options.length > 0 ? (
                <div className="overflow-x-auto rounded-xl border border-foreground/10">
                    <table className="w-full text-sm text-left border-collapse min-w-[320px]">
                        <thead>
                            <tr className="border-b border-foreground/10 bg-foreground/[0.03] text-[11px] uppercase tracking-wide text-foreground/50">
                                <th className="py-2.5 px-3 font-semibold">Flat type</th>
                                <th className="py-2.5 px-2 font-semibold text-right whitespace-nowrap">
                                    Units
                                </th>
                                <th className="py-2.5 px-2 font-semibold text-right whitespace-nowrap">
                                    Sales
                                </th>
                                <th className="py-2.5 px-2 font-semibold text-right whitespace-nowrap">
                                    Median
                                </th>
                                <th className="py-2.5 px-3 font-semibold whitespace-nowrap">
                                    Latest
                                </th>
                            </tr>
                        </thead>
                        <tbody>
                            {selectedProperty.flat_options.map((opt) => (
                                <tr
                                    key={opt.flat_type}
                                    className="border-b border-foreground/[0.06] last:border-0"
                                >
                                    <td className="py-2.5 px-3 font-semibold text-foreground/90 align-top">
                                        {formatFlatTypeCatalogueShort(opt.flat_type)}
                                    </td>
                                    <td className="py-2.5 px-2 text-right tabular-nums align-top">
                                        {typeof opt.units_sold === "number" &&
                                        Number.isFinite(opt.units_sold)
                                            ? Math.round(opt.units_sold).toLocaleString()
                                            : "—"}
                                    </td>
                                    <td className="py-2.5 px-2 text-right tabular-nums align-top">
                                        {opt.resale_transaction_count}
                                    </td>
                                    <td className="py-2.5 px-2 text-right tabular-nums align-top whitespace-nowrap">
                                        {formatSgdWhole(opt.median_resale_price_sgd)}
                                    </td>
                                    <td className="py-2.5 px-3 align-top text-foreground/80">
                                        {opt.latest_resale_month &&
                                        opt.latest_resale_price_sgd != null ? (
                                            <span className="tabular-nums">
                                                <span className="text-foreground/55">
                                                    {opt.latest_resale_month}
                                                </span>
                                                {" · "}
                                                {formatSgdWhole(opt.latest_resale_price_sgd)}
                                            </span>
                                        ) : (
                                            "—"
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            ) : (
                <p className="text-sm text-foreground/45">
                    No flat-type resale breakdown available.
                </p>
            )}
        </div>
    );
}
