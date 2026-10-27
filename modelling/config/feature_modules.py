"""Composable DB/build tags for training datasets (build-on-the-fly assembly).

Each registered ``feature_set_id`` maps to an ordered tuple of build modules:
``resale_baseline`` (always first when present), ``mrt_pit``, ``masterplan_landuse``.

Macro and POI features are engineered in Python from resale rows + sidecars/DB (no extra SQL pillar here).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet

# Tags used by modelling.data.dataset_builder
TAG_RESALE_BASELINE = "resale_baseline"
TAG_MRT_PIT = "mrt_pit"
TAG_MASTERPLAN_LANDUSE = "masterplan_landuse"
TAG_ESTATE_MATURITY = "estate_maturity"

KNOWN_BUILD_TAGS: FrozenSet[str] = frozenset(
    {TAG_RESALE_BASELINE, TAG_MRT_PIT, TAG_MASTERPLAN_LANDUSE, TAG_ESTATE_MATURITY}
)


@dataclass(frozen=True)
class FeatureModule:
    """Atomic pillar metadata (SQL assembly tags live in FEATURE_SET_BUILD_MODULES)."""

    id: str
    description: str


# Expected SQL column names after merges in ``dataset_builder.build_training_dataframe``
# (baseline + optional MRT pit + optional masterplan land-use pillars).
_BASELINE_SQL_COLUMNS: frozenset[str] = frozenset(
    {
        "month",
        "town",
        "flat_type",
        "block",
        "street_name",
        "storey_range",
        "floor_area_sqm",
        "flat_model",
        "lease_commence_date",
        "remaining_lease_years",
        "resale_price",
        "enriched_addr_id",
        "lat",
        "lon",
    }
)

_MRT_PIT_SQL_COLUMNS: frozenset[str] = frozenset(
    {
        "dist_to_nearest_op_mrt",
        "travel_time_to_active_mrt",
        "pt_time_savings_vs_walk",
        "line_connectivity_index",
        "nearest_op_lines",
        "days_since_mrt_announcement",
        "days_to_mrt_opening",
        "speculative_upside_score",
        "has_future_upside",
        "nearest_planned_lines",
        "is_proximity_nuisance",
        "num_unique_lines_within_1km",
        "nearest_planned_mrt_dist",
    }
)

_MASTERPLAN_SQL_COLUMNS: frozenset[str] = frozenset(
    {
        "nearby_high_density_score",
        "area_comm_500m",
        "area_comm_1000m",
        "area_comm_1500m",
        "area_park_500m",
        "area_park_1000m",
        "area_park_1500m",
        "area_sports_500m",
        "area_sports_1000m",
        "area_sports_1500m",
        "area_health_500m",
        "area_health_1000m",
        "area_health_1500m",
        "area_worship_500m",
        "area_worship_1000m",
        "area_worship_1500m",
        "dist_cbd",
        "dist_airport",
        "dist_to_nearest_b2_zone",
        "b2_zoning_ratio_1km",
        "dist_to_nearest_business_park",
        "dist_to_nearest_cemetery",
        "dist_to_nearest_special_use",
    }
)


_ESTATE_MATURITY_SQL_COLUMNS: frozenset[str] = frozenset(
    {
        "avg_residential_block_age_years",
        "town_completed_residential_units_stock",
        "town_land_area_km2",
        "town_dwelling_unit_density",
        "town_units_under_construction",
        "town_hdb_completed_units_roll36m",
        "town_supply_maturity_ratio",
    }
)


def expected_training_dataset_column_set(feature_set_id: str) -> frozenset[str]:
    """Union of baseline (+ merged pillar) SQL columns for cache/schema validation."""
    tags = feature_modules_for_feature_set(feature_set_id)
    out = set(_BASELINE_SQL_COLUMNS)
    if TAG_MRT_PIT in tags:
        out |= _MRT_PIT_SQL_COLUMNS
    if TAG_MASTERPLAN_LANDUSE in tags:
        out |= _MASTERPLAN_SQL_COLUMNS
    if TAG_ESTATE_MATURITY in tags:
        out |= _ESTATE_MATURITY_SQL_COLUMNS
    return frozenset(out)


def feature_modules_for_feature_set(feature_set_id: str) -> tuple[str, ...]:
    """Return ordered build tags for a registered feature set id."""
    if feature_set_id not in FEATURE_SET_BUILD_MODULES:
        raise KeyError(
            f"Unknown feature_set_id {feature_set_id!r} for dynamic dataset build. "
            f"Known ids: {sorted(FEATURE_SET_BUILD_MODULES)}"
        )
    return FEATURE_SET_BUILD_MODULES[feature_set_id]


# Every key in modelling.config.feature_sets.build_feature_set_registry(...) must appear here.
FEATURE_SET_BUILD_MODULES: dict[str, tuple[str, ...]] = {
    "baseline_v1": (TAG_RESALE_BASELINE,),
    "baseline_v1__months_since_2015": (TAG_RESALE_BASELINE,),
    "baseline_grouped_v1": (TAG_RESALE_BASELINE,),
    "baseline_v1__macro": (TAG_RESALE_BASELINE,),
    "mrt_pit__macro": (TAG_RESALE_BASELINE, TAG_MRT_PIT),
    "masterplan_landuse_pit": (TAG_RESALE_BASELINE, TAG_MASTERPLAN_LANDUSE),
    "baseline_v1__macro__masterplan_landuse_pit": (TAG_RESALE_BASELINE, TAG_MASTERPLAN_LANDUSE),
    "baseline_v1__macro__masterplan_landuse_pit__mrt_pit": (
        TAG_RESALE_BASELINE,
        TAG_MRT_PIT,
        TAG_MASTERPLAN_LANDUSE,
    ),
    "mrt_pit": (TAG_RESALE_BASELINE, TAG_MRT_PIT),
    "poi_distancing": (TAG_RESALE_BASELINE,),
    "poi_amenity_v2": (TAG_RESALE_BASELINE,),
    "mrt_pit__poi_distancing": (TAG_RESALE_BASELINE, TAG_MRT_PIT),
    "mrt_pit__poi_amenity_v2": (TAG_RESALE_BASELINE, TAG_MRT_PIT),
    "primary_school": (TAG_RESALE_BASELINE,),
    "mrt_pit__primary_school": (TAG_RESALE_BASELINE, TAG_MRT_PIT),
    "mrt_pit__primary_school__estate_maturity": (
        TAG_RESALE_BASELINE,
        TAG_MRT_PIT,
        TAG_ESTATE_MATURITY,
    ),
    "mrt_pit__masterplan_landuse_pit__primary_school": (
        TAG_RESALE_BASELINE,
        TAG_MRT_PIT,
        TAG_MASTERPLAN_LANDUSE,
    ),
    "mrt_pit__masterplan_area__primary_school": (
        TAG_RESALE_BASELINE,
        TAG_MRT_PIT,
        TAG_MASTERPLAN_LANDUSE,
    ),
    "mrt_pit__masterplan_proximity__primary_school": (
        TAG_RESALE_BASELINE,
        TAG_MRT_PIT,
        TAG_MASTERPLAN_LANDUSE,
    ),
    "mrt_pit__masterplan_area_proximity__primary_school": (
        TAG_RESALE_BASELINE,
        TAG_MRT_PIT,
        TAG_MASTERPLAN_LANDUSE,
    ),
    "mrt_pit__masterplan_area__primary_school__estate_maturity": (
        TAG_RESALE_BASELINE,
        TAG_MRT_PIT,
        TAG_MASTERPLAN_LANDUSE,
        TAG_ESTATE_MATURITY,
    ),
    "mrt_pit__masterplan_proximity__primary_school__estate_maturity": (
        TAG_RESALE_BASELINE,
        TAG_MRT_PIT,
        TAG_MASTERPLAN_LANDUSE,
        TAG_ESTATE_MATURITY,
    ),
    "mrt_pit__masterplan_landuse_pit__primary_school__estate_maturity": (
        TAG_RESALE_BASELINE,
        TAG_MRT_PIT,
        TAG_MASTERPLAN_LANDUSE,
        TAG_ESTATE_MATURITY,
    ),
    "poi_distancing__macro": (TAG_RESALE_BASELINE,),
    "mrt_pit__poi_distancing__macro": (TAG_RESALE_BASELINE, TAG_MRT_PIT),
    "mrt_pit__poi_distancing__macro__masterplan_landuse_pit": (
        TAG_RESALE_BASELINE,
        TAG_MRT_PIT,
        TAG_MASTERPLAN_LANDUSE,
    ),
    "mrt_pit__macro__masterplan_proximity__primary_school__estate_maturity": (
        TAG_RESALE_BASELINE,
        TAG_MRT_PIT,
        TAG_MASTERPLAN_LANDUSE,
        TAG_ESTATE_MATURITY,
    ),
    "mrt_pit__poi_distancing__macro__masterplan_landuse_pit__grouped": (
        TAG_RESALE_BASELINE,
        TAG_MRT_PIT,
        TAG_MASTERPLAN_LANDUSE,
    ),
    "baseline_v1__estate_maturity": (TAG_RESALE_BASELINE, TAG_ESTATE_MATURITY),
    "baseline_v1__macro__estate_maturity": (TAG_RESALE_BASELINE, TAG_ESTATE_MATURITY),
    "baseline_v1__macro__masterplan_landuse_pit__mrt_pit__estate_maturity": (
        TAG_RESALE_BASELINE,
        TAG_MRT_PIT,
        TAG_MASTERPLAN_LANDUSE,
        TAG_ESTATE_MATURITY,
    ),
}


def assert_feature_set_coverage_matches_registry(project_root) -> None:
    """Dev helper: ensure FEATURE_SET_BUILD_MODULES keys match get_feature_registry."""
    from modelling.config.feature_sets import get_feature_registry

    reg = get_feature_registry(project_root)
    missing = sorted(set(reg) - set(FEATURE_SET_BUILD_MODULES))
    extra = sorted(set(FEATURE_SET_BUILD_MODULES) - set(reg))
    if missing or extra:
        raise RuntimeError(
            "FEATURE_SET_BUILD_MODULES out of sync with feature set registry: "
            f"missing={missing} extra={extra}"
        )


__all__ = [
    "FEATURE_SET_BUILD_MODULES",
    "FeatureModule",
    "KNOWN_BUILD_TAGS",
    "TAG_MASTERPLAN_LANDUSE",
    "TAG_ESTATE_MATURITY",
    "TAG_MRT_PIT",
    "TAG_RESALE_BASELINE",
    "assert_feature_set_coverage_matches_registry",
    "expected_training_dataset_column_set",
    "feature_modules_for_feature_set",
]
