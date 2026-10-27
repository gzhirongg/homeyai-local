"use client";

import ValuationGeoAmenities from "@/components/valuation/ValuationGeoAmenities";
import ValuationMarketSentiment from "@/components/valuation/ValuationMarketSentiment";
import ValuationResaleByFlatType from "@/components/valuation/ValuationResaleByFlatType";

export default function ValuationPropertyAnalytics({
    selectedProperty,
    refreshNonce = 0,
}: {
    selectedProperty: import("@/components/PropertySearchInput").PropertyLookupResult;
    refreshNonce?: number;
}) {
    return (
        <section className="space-y-6 text-left text-foreground">
            <ValuationGeoAmenities
                selectedProperty={selectedProperty}
                refreshNonce={refreshNonce}
            />
            <ValuationResaleByFlatType selectedProperty={selectedProperty} />
            <ValuationMarketSentiment refreshNonce={refreshNonce} />
        </section>
    );
}
