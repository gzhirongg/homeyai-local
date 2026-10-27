"use client";

import { useMemo, type ReactNode } from "react";
import { Building2, Image as ImageIcon, MapPin } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type { PropertyLookupResult } from "@/components/PropertySearchInput";
import {
    compareFlatTypesCatalogueOrder,
    formatFlatTypeWithUnits,
} from "@/lib/hdbFlatTypeDisplay";

const labelClass = "text-[11px] text-foreground/45 font-medium";
const valueClass = "text-sm font-semibold text-foreground";
const addressTitleClass = "text-lg font-bold tracking-tight text-foreground leading-snug";
const subsectionTitleClass = "text-base font-bold tracking-tight text-foreground";
const fieldsGridClass = "grid grid-cols-2 gap-x-6 gap-y-3";
const containerClass =
    "rounded-xl border border-foreground/10 bg-background/70 px-4 py-5 mt-4 text-foreground text-sm";

function formatCoord(value: number | null | undefined): string {
    if (value == null || Number.isNaN(value)) return "—";
    return value.toFixed(6);
}

/** e.g. ``ANG MO KIO`` → ``Ang Mo Kio`` */
function toProperCase(value: string): string {
    return value
        .trim()
        .split(/\s+/)
        .filter(Boolean)
        .map((word) =>
            word
                .split("-")
                .map((part) =>
                    part.length > 0
                        ? part.charAt(0).toUpperCase() + part.slice(1).toLowerCase()
                        : part
                )
                .join("-")
        )
        .join(" ");
}

type Props = {
    selectedProperty: PropertyLookupResult;
    /** Block ``year_completed`` from HDB Property Information (99-year lease math uses this proxy). */
    buildingYearCompleted: number | null;
    buildingLeaseRemaining: number | null;
};

function SubsectionHeader({ icon: Icon, title }: { icon: LucideIcon; title: string }) {
    return (
        <div className="flex items-center gap-2 mb-4">
            <Icon className="w-5 h-5 text-accent shrink-0" strokeWidth={2} aria-hidden />
            <h3 className={subsectionTitleClass}>{title}</h3>
        </div>
    );
}

function PropertySubsection({
    icon,
    title,
    children,
}: {
    icon: LucideIcon;
    title: string;
    children: ReactNode;
}) {
    return (
        <div>
            <SubsectionHeader icon={icon} title={title} />
            {children}
        </div>
    );
}

function InfoLine({
    label,
    children,
    mono,
}: {
    label: string;
    children: ReactNode;
    mono?: boolean;
}) {
    return (
        <div>
            <p className={labelClass}>{label}</p>
            <p className={`${valueClass} mt-0.5 ${mono ? "font-mono tabular-nums" : ""}`}>
                {children}
            </p>
        </div>
    );
}

function StreetViewPlaceholder() {
    return (
        <div className="flex flex-col shrink-0 w-[36%] min-w-[9.5rem] max-w-[14rem] sm:max-w-[16rem] self-stretch min-h-0">
            <SubsectionHeader icon={ImageIcon} title="Street view" />
            <div
                role="img"
                aria-label="Street view (not yet available)"
                className="relative flex-1 min-h-[12rem] w-full overflow-hidden rounded-xl border border-dashed border-sky-300/55 bg-gradient-to-br from-white via-sky-50/40 to-indigo-50/30 flex items-center justify-center"
            >
                <ImageIcon
                    className="w-9 h-9 text-sky-400/50 shrink-0"
                    strokeWidth={1.25}
                    aria-hidden
                />
            </div>
        </div>
    );
}

export default function ValuationBuildingSummary({
    selectedProperty,
    buildingYearCompleted,
    buildingLeaseRemaining,
}: Props) {
    const floorsCaption = useMemo(() => {
        const n = selectedProperty.building_max_storey;
        if (typeof n !== "number" || !Number.isFinite(n) || n < 1) return null;
        if (n <= 1) return "1";
        return `1 to ${n}`;
    }, [selectedProperty.building_max_storey]);

    const flatTypeTags = useMemo(() => {
        const opts = [...(selectedProperty.flat_options ?? [])];
        opts.sort((a, b) =>
            compareFlatTypesCatalogueOrder(a.flat_type, b.flat_type)
        );
        return opts.map((o) => ({
            key: o.flat_type,
            label: formatFlatTypeWithUnits(
                o.flat_type,
                typeof o.units_sold === "number" ? o.units_sold : 0
            ),
        }));
    }, [selectedProperty.flat_options]);

    const lat = selectedProperty.latitude;
    const lng = selectedProperty.longitude;
    const hasCoords =
        lat != null &&
        lng != null &&
        !Number.isNaN(lat) &&
        !Number.isNaN(lng);

    return (
        <section className={containerClass}>
            <div className="flex gap-5 sm:gap-6 items-stretch">
                <div className="flex-1 min-w-0 space-y-6">
                    <p className={addressTitleClass}>{selectedProperty.address_label}</p>

                    <PropertySubsection icon={MapPin} title="Location Information">
                        <div className={fieldsGridClass}>
                            <InfoLine label="Town">
                                {selectedProperty.town?.trim()
                                    ? toProperCase(selectedProperty.town)
                                    : "—"}
                            </InfoLine>
                            <InfoLine label="Region">
                                {selectedProperty.region?.trim() || "—"}
                            </InfoLine>
                            <div className="col-span-2">
                                <InfoLine label="Postal code">
                                    {selectedProperty.postal_code?.trim() || "—"}
                                </InfoLine>
                            </div>
                            <InfoLine label="Latitude" mono>
                                {hasCoords ? formatCoord(lat) : "—"}
                            </InfoLine>
                            <InfoLine label="Longitude" mono>
                                {hasCoords ? formatCoord(lng) : "—"}
                            </InfoLine>
                        </div>
                    </PropertySubsection>

                    <PropertySubsection icon={Building2} title="Building Information">
                        <div className="space-y-4">
                            <div className={fieldsGridClass}>
                                <InfoLine label="Year completed">
                                    {buildingYearCompleted != null ? buildingYearCompleted : "—"}
                                </InfoLine>
                                <InfoLine label="Lease remaining">
                                    {buildingLeaseRemaining != null
                                        ? `~${buildingLeaseRemaining} yrs`
                                        : "—"}
                                </InfoLine>
                                <div className="col-span-2">
                                    <InfoLine label="Floors">{floorsCaption ?? "—"}</InfoLine>
                                </div>
                            </div>
                            <div>
                                <p className={`${labelClass} mb-1.5`}>Available flat types</p>
                                {flatTypeTags.length > 0 ? (
                                    <div className="flex flex-wrap gap-1.5">
                                        {flatTypeTags.map((tag) => (
                                            <span
                                                key={tag.key}
                                                className="text-xs font-semibold px-2.5 py-1 rounded-full bg-accent/10 text-accent border border-accent/20"
                                            >
                                                {tag.label}
                                            </span>
                                        ))}
                                    </div>
                                ) : (
                                    <p className={`${valueClass} text-foreground/40 font-normal`}>
                                        No flat type data
                                    </p>
                                )}
                            </div>
                        </div>
                    </PropertySubsection>
                </div>

                <StreetViewPlaceholder />
            </div>
        </section>
    );
}
