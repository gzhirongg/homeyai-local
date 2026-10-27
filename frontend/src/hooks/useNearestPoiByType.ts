"use client";

import { useEffect, useState } from "react";

import API_BASE from "@/lib/apiBase";
import type { PropertyLookupResult } from "@/components/PropertySearchInput";
import { extractNearestPois, type NearestPoi } from "@/lib/poiExtract";

export function useNearestPoiByType(
    selectedProperty: PropertyLookupResult | null,
    refreshNonce = 0
): { pois: NearestPoi[]; loading: boolean } {
    const [pois, setPois] = useState<NearestPoi[]>([]);
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        if (!selectedProperty) {
            setPois([]);
            return;
        }
        const postalDigits = selectedProperty.postal_code.replace(/\D/g, "");
        if (!/^\d{6}$/.test(postalDigits)) {
            setPois([]);
            return;
        }

        let cancelled = false;
        const load = async () => {
            setLoading(true);
            try {
                const res = await fetch(
                    `${API_BASE}/api/geospatial/nearest_poi_per_type?postal_code=${encodeURIComponent(postalDigits)}`
                );
                const json = await res.json().catch(() => null);
                if (cancelled) return;
                setPois(extractNearestPois(json));
            } catch {
                if (!cancelled) setPois([]);
            } finally {
                if (!cancelled) setLoading(false);
            }
        };
        void load();
        return () => {
            cancelled = true;
        };
    }, [selectedProperty, refreshNonce]);

    return { pois, loading };
}
