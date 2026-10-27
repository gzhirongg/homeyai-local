"use client";

import { useEffect, useState } from "react";
import { Footprints, Loader2, MapPin, TrainFront } from "lucide-react";

import API_BASE from "@/lib/apiBase";
import type { PropertyLookupResult } from "@/components/PropertySearchInput";
import {
    extractNearestMrtsFromScore,
    extractNearestPois,
    formatHorizontalDistanceM,
    formatMrtAccessLine,
    type AmenitySummary,
} from "@/lib/poiExtract";

type Props = {
    selectedProperty: PropertyLookupResult;
    refreshNonce?: number;
};

export default function ValuationGeoAmenities({
    selectedProperty,
    refreshNonce = 0,
}: Props) {
    const [amenity, setAmenity] = useState<AmenitySummary | null>(null);
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        const postalDigits = selectedProperty.postal_code.replace(/\D/g, "");
        if (!/^\d{6}$/.test(postalDigits)) {
            setAmenity(null);
            return;
        }

        const loadAmenity = async () => {
            setLoading(true);
            try {
                const qs = new URLSearchParams({
                    postal_code: postalDigits,
                    radius_km: "1",
                });
                const [scoreRes, poiRes] = await Promise.all([
                    fetch(`${API_BASE}/api/geospatial/amenity_score?${qs.toString()}`),
                    fetch(
                        `${API_BASE}/api/geospatial/nearest_poi_per_type?postal_code=${encodeURIComponent(postalDigits)}`,
                    ),
                ]);

                const scoreJson = await scoreRes.json().catch(() => null);
                const poiJson = await poiRes.json().catch(() => null);

                setAmenity({
                    nearestMrts: extractNearestMrtsFromScore(scoreJson),
                    nearestPois: extractNearestPois(poiJson),
                });
            } catch {
                setAmenity(null);
            } finally {
                setLoading(false);
            }
        };

        void loadAmenity();
    }, [selectedProperty, refreshNonce]);

    if (loading) {
        return (
            <p className="text-sm text-foreground/50 flex items-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" /> Loading amenity profile…
            </p>
        );
    }

    if (
        !amenity ||
        (amenity.nearestMrts.length === 0 && amenity.nearestPois.length === 0)
    ) {
        return (
            <p className="text-sm text-foreground/45">
                Amenity profile unavailable for this address.
            </p>
        );
    }

    return (
        <div className="space-y-5">
            {amenity.nearestMrts.length > 0 && (
                <div>
                    <p className="text-[11px] text-foreground/45 font-semibold uppercase tracking-wide mb-2 flex items-center gap-1.5">
                        <TrainFront className="w-3.5 h-3.5 shrink-0" /> Nearest MRT
                    </p>
                    <ul className="space-y-3">
                        {amenity.nearestMrts.map((m, idx) => {
                            const { primary, transitHint } = formatMrtAccessLine(m);
                            return (
                                <li key={`${m.name}-${idx}`} className="text-sm">
                                    <div className="font-semibold text-foreground tracking-tight">
                                        {m.name}
                                    </div>
                                    <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-foreground/70">
                                        <Footprints
                                            className="w-3.5 h-3.5 text-secondary shrink-0"
                                            aria-hidden
                                        />
                                        <span className="tabular-nums">{primary}</span>
                                        {transitHint ? (
                                            <span className="text-foreground/50 tabular-nums">
                                                · faster by transit:{" "}
                                                <span className="text-secondary/90 font-medium">
                                                    {transitHint}
                                                </span>
                                            </span>
                                        ) : null}
                                    </div>
                                </li>
                            );
                        })}
                    </ul>
                </div>
            )}
            {amenity.nearestPois.length > 0 && (
                <div>
                    <p className="text-[11px] text-foreground/45 font-semibold uppercase tracking-wide mb-2 flex items-center gap-1.5">
                        <MapPin className="w-3.5 h-3.5 shrink-0 text-secondary" />
                        Nearest amenities
                    </p>
                    <ul className="space-y-2.5">
                        {amenity.nearestPois.map((p) => (
                            <li
                                key={`${p.type}-${p.distance_m}-${p.label}`}
                                className="flex gap-2 items-baseline text-sm"
                            >
                                <span className="w-[5.75rem] shrink-0 text-[11px] font-semibold uppercase tracking-wide text-foreground/50">
                                    {p.label}
                                </span>
                                <span className="min-w-0 flex-1 truncate text-foreground/85">
                                    {p.name ?? ""}
                                </span>
                                <span className="tabular-nums text-xs font-semibold text-foreground/55 shrink-0">
                                    {formatHorizontalDistanceM(p.distance_m)}
                                </span>
                            </li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    );
}
