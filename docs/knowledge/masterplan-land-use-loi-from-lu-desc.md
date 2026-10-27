# Master Plan LOI features from `LU_DESC` (B2, business park)

URA Master Plan land-use GeoJSON includes `LU_DESC` labels. We use **distance / exposure** signals for heavy industrial (B2) and business parks—not intersection *area* in amenity buffers (that approach was reverted).

## Implemented columns (`masterplan_landuse_pit_scalars`)

| Column | `LU_DESC` sources | Definition |
| --- | --- | --- |
| `dist_to_nearest_b2_zone` | `BUSINESS 2`, `BUSINESS 2 - WHITE` | Planar distance (km, EPSG:3414) from the unit to the nearest B2 zoning polygon. |
| `b2_zoning_ratio_1km` | same | Share of a **1 km** disk around the unit overlapping B2 polygons: \(\text{area}(B2 \cap disk) / (\pi \cdot 1000^2)\). |
| `dist_to_nearest_business_park` | `BUSINESS PARK`, `BUSINESS PARK - WHITE` | Planar distance (km) to the nearest business-park polygon. |
| `dist_to_nearest_cemetery` | `CEMETERY` | Planar distance (km) to the nearest cemetery polygon. |
| `dist_to_nearest_special_use` | `SPECIAL USE` | Planar distance (km) to the nearest special-use polygon (e.g. utilities, major infrastructure). |

Snapshot: `modelling/runners/build_masterplan_landuse_pit_snapshot.py --write-db`. Alembic: `e9a0b1c2d3e4` (B2/BP), `f1a2b3c4d5e7` (cemetery/special use). Engineering: `modelling/features/masterplan_loi_proximity.py`.

## Feature-pack split (training)

- **Area pack:** `area_{comm,park,sports,health,worship}_{500,1000,1500}m` only.  
- **Proximity / scalars pack:** `nearby_high_density_score`, `dist_cbd`, `dist_airport`, the LOI distance/ratio columns above, and derived `density_age_interaction`, `hub_score`.

Registered feature sets include `mrt_pit__masterplan_area__primary_school`, `mrt_pit__masterplan_proximity__primary_school`, `mrt_pit__masterplan_area_proximity__primary_school` (+ estate variants). Batch: `CORE35_Y5_MASTERPLAN_AREA_PROXIMITY_AB`.

## Not available from this GeoJSON alone

- **CBD / airport** — still fixed reference points in `masterplan_landuse_pit` (Haversine), not CBD polygons from this layer.
- **Sea / coastline** — needs a coastline dataset; future: `dist_to_sea`, `sea_proximity_decay`, `is_coastal_boundary_buffer`.
- **Commercial GFA in buffers** — needs parcel GFA attributes or another layer (future: `commercial_gfa_500m`, `commercial_zoning_ratio_1km`).
