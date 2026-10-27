# Valuation UI design

Post-valuation intelligence layout for `/valuation`: single scroll, no Form/Valuation tabs. Inputs stay visible via a sticky recap; results stack below as self-contained cards.

## Page flow

```
Sticky input recap (address, flat type, area, floor, lease · Edit inputs)
  → Step 1 building search + Step 2 unit form (frozen summary after first valuation)
  → Estimated value + confidence band + verdict pill
  → Filterable price comparison chart (town + flat type baseline, optional spec filters)
  → Why this price? (human-readable price drivers)
  → Nearby comparables (compact)
  → Collapsible: Location quality · Market sentiment · Resale by flat type
  → Save / download / new search
```

Key files:

| Area | Path |
|------|------|
| Page shell | `frontend/src/app/valuation/page.tsx` |
| Result layout | `frontend/src/components/valuation/ValuationResultPanel.tsx` |
| Input recap | `frontend/src/components/valuation/ValuationInputRecapBar.tsx` |
| Comparison chart | `frontend/src/components/valuation/ValuationPriceComparisonChart.tsx` |
| Verdict | `frontend/src/components/valuation/ValuationVerdictBadge.tsx` |
| Driver grouping | `frontend/src/lib/shapDrivers.ts` |
| POI composite (amenities proxy) | `frontend/src/lib/poiExtract.ts`, `frontend/src/hooks/useNearestPoiByType.ts` |

## Why this price? (price drivers)

Premium valuations expose SHAP from `POST /api/valuation` (`result.shap_values`). Raw preprocessor names (e.g. `flat_type_encoded`, `dist_to_nearest_op_mrt`) are **not** shown to users.

Instead, `summarizeShapDrivers()` in `shapDrivers.ts`:

1. Maps each SHAP row to a **category** via `source_column` (preferred) or feature-name pattern.
2. **Sums** SGD marginal impacts per category.
3. Shows the **top 5** by absolute impact.
4. Renders each row as: **category label · proxy text · ±S$ pill** and a signed impact bar.

Hover a row (`title` attribute) to see underlying model feature names for audit/debug.

### Category scheme

| Category | Typical SHAP sources | Proxy text source |
|----------|---------------------|-------------------|
| Unit size | `floor_area_sqm` | User input (`formData.floor_area_sqm`) |
| Floor level | `storey_mid` | User input (`formData.storey_midpoint`) |
| Flat type | `flat_type_encoded` | User input (`formData.flat_type`) |
| Flat model | `flat_model_*`, `flat_model_grouped_*` | Engineered / form model group |
| Lease remaining | `remaining_lease_years` | User input |
| Location (Town) | `town_*`, `region_*`, `lat`, `lon` | Town + region from lookup |
| Market timing | `sale_year`, `sale_month_*`, `months_since_2015` | Valuation month |
| Convenience (Transport) | MRT distance, travel time, connectivity | `driver_context.transport_current` |
| Future Development (Transport) | Planned MRT dist, opening days, upside flags | `driver_context.transport_future` |
| Top Primary School Accessibility | Primary school distance / within-1km flags | `driver_context.primary_school` |
| Convenience (Amenities) | `dist_nearest_mall`, `mall_count_within_1_5km` | UI composite from `/api/geospatial/nearest_poi_per_type` (mall · hawker · park · sports); SHAP attribution is mall-only — see note on row |
| Land use surroundings | B2, cemetery, special-use, nuisance | `driver_context.landuse_negative` |

### Backend payloads

**SHAP rows** (`backend/services/ml_service.py` → `compute_shap_top_features`):

- `feature`, `contribution`, `contribution_log`, `contribution_sgd`
- `source_column`, `feature_value` — engineered value for proxy fallback

**Driver context** (`backend/main.py` → `_build_driver_context`, premium only):

```json
{
  "transport_current": "Marine Parade MRT (TE26) — 412m",
  "transport_future": "Planned MRT (TEL) — 250m, opens ~3 yrs",
  "primary_school": "Tao Nan School (0.4 km)",
  "landuse_negative": "Cemetery 1.4 km · B2 industrial 2.1 km",
  "coastline": { "distance_km": 1.2, "landmark": "East Coast Park" }
}
```

Frontend passes `driver_context` into `ValuationResultPanel` unchanged from `result.driver_context`.

## Nearby comparables: recorded sales

`backend/services/comparable_service.py` reads actual resale transactions joined
to address coordinates. The previous implementation fabricated three addresses
and calculated their prices as fixed percentages of the estimate; those rows,
the hard-coded percentile, and the automatic pricing verdict have been removed.

Candidates must have the same flat type, fall within 1 km, occur within the last
12 calendar months through the valuation month, have area within ±15%, current
lease within ±10 years, and floor-band midpoint within ±6 floors. Current lease
is estimated from the lease commencement year (or aged from the recorded lease
at sale if that year is missing). Unknown coordinates, floor bands, or lease
information do not qualify. The bounding-box SQL filter is followed by an exact
great-circle radius check. No wider radius or older-date fallback is silently used.

Rank by normalized size/floor/lease differences, distance, recency, and flat-model
match, then transaction ID for deterministic ties. Return at most 10 recorded
sales with at most two per building. Selection never depends on predicted price.
Each row retains its transaction ID, actual total price, address, postcode,
sale month, floor band, size, distance, and same-building flag.

Summaries use the selected records. The top comparison badge uses mean recorded
price per sqm to avoid mistaking a larger unit's total price for a pricing premium.
The row's `% vs estimate` is an explicitly labelled raw total-price comparison;
historical prices are not adjusted for size or market changes. The UI links to
the HDB public source and shows the matching criteria. Empty matches have empty
rows and null summary values; absent location gets a distinct explanation.
No evidence means no default “fairly priced” verdict. Old cached placeholder
payloads lack provenance/criteria and are hidden with a recalculate prompt.

Premium access remains unchanged. Verification includes database-backed tests
for exclusion criteria, missing data, building diversity, date boundaries, and
independence from the model estimate; the local smoke check exercises the real
premium API through the same-origin frontend proxy.

## Deferred: sea view / coastline

### Current state (model)

The trained valuation pipeline has **no coastline or sea-view feature**. Proximity to the coast is captured only implicitly through `lat`/`lon`, `town`, and related spatial splits. SHAP cannot attribute a separate SGD impact to “sea view” today.

### Current state (API)

`_nearest_coastline_landmark()` in `backend/main.py` still computes `driver_context.coastline` for premium valuations (great-circle distance to reference landmarks: East Coast Park, West Coast Park, Punggol Promenade, Pasir Ris Beach, Changi Beach, Sembawang Park). This is **available in the API** but **not rendered** in the UI.

### When sea is model-ready

1. **Modelling** — Add an engineered column (e.g. `dist_to_coastline_km` or a sea-view score) to the feature pack; retrain and pin a new `model.pkl`.
2. **SHAP registry** — In `frontend/src/lib/shapDrivers.ts`, map the new column to a category (suggested label: **Sea view / coastline proximity**). Add proxy formatting (distance km or landmark name).
3. **Optional UI** — If the feature is SHAP-attributable, it appears automatically in **Why this price?** like other categories. Remove or repurpose the old informational-only card pattern (intentionally removed from `ValuationResultPanel` to avoid implying model attribution).
4. **Backend cleanup** — Either merge coastline proxy into the new feature’s `feature_value`, or stop populating `driver_context.coastline` if redundant.
5. **Docs** — Update this section and `docs/reference/api-endpoints.md` if response shape changes.

### Informational card (removed)

An earlier design showed a non-SHAP “Sea view / coastline proximity” informational card below the driver list. That was removed so users are not shown a price-adjacent signal the model does not isolate. Reintroduce only after the model supports attributable coastline/sea-view features, or as a clearly labelled non-pricing amenity elsewhere (e.g. Location quality collapsible).

## Related

- API: `docs/reference/api-endpoints.md` (`POST /api/valuation`, geospatial POI)
- POI types for amenities composite: `docs/knowledge/poi-data-km.md`
- Modelling feature packs: `modelling/Modelling_System_Design.md`
