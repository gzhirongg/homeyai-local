"""Tests for slim POI amenity pack and optional ``hdb_poi_features`` blending."""

from __future__ import annotations

import pandas as pd
import pytest

from modelling.features.poi_amenity_v2 import append_poi_amenity_v2_features


def _minimal_hdb(lat: float = 1.35, lon: float = 103.85) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "month": ["2020-01"],
            "town": ["TAMPINES"],
            "flat_type": ["4 ROOM"],
            "flat_model": ["Model A"],
            "storey_range": ["10 TO 12"],
            "floor_area_sqm": [90.0],
            "lease_commence_date": [1999],
            "remaining_lease_years": [79.0],
            "lat": [lat],
            "lon": [lon],
        }
    )


def test_within_2km_primary_semantics_vs_legacy_band():
    """Legacy ``within_1km_2km_pri_school`` is (1k, 2k]; v2 ``is_within_2km`` is ``dist <= 2000``."""
    hdb = _minimal_hdb()
    schools = pd.DataFrame({"lat": [1.354], "lon": [103.85], "name": ["X"]})
    pois = {"schools": schools, "markets": pd.DataFrame(), "malls": pd.DataFrame()}
    out = append_poi_amenity_v2_features(hdb, pois)
    assert out["is_within_2km_primary_school"].iloc[0] == 1
    assert out["is_within_1km_primary_school"].iloc[0] == 1
    dist = float(out["dist_nearest_primary_school"].iloc[0])
    assert dist <= 1000
    legacy_band = int((dist > 1000) and (dist <= 2000))
    assert legacy_band == 0


def test_within_2km_includes_dist_between_1_and_2km_without_being_within_1km():
    hdb = _minimal_hdb(lat=1.352, lon=103.85)
    schools = pd.DataFrame({"lat": [1.362], "lon": [103.85], "name": ["Y"]})
    pois = {"schools": schools, "markets": pd.DataFrame(), "malls": pd.DataFrame()}
    out = append_poi_amenity_v2_features(hdb, pois)
    d = float(out["dist_nearest_primary_school"].iloc[0])
    assert 1000 < d <= 2000
    assert out["is_within_1km_primary_school"].iloc[0] == 0
    assert out["is_within_2km_primary_school"].iloc[0] == 1


def test_hdb_poi_features_blend_overrides_school_and_mall_distance():
    """Precomputed row wins for ``dist_nearest_any_school`` / ``dist_nearest_mall``."""
    hdb = _minimal_hdb()
    hdb["enriched_addr_id"] = [42]
    schools = pd.DataFrame({"lat": [1.46], "lon": [104.0], "name": ["Far"]})
    malls = pd.DataFrame({"lat": [1.46], "lon": [104.0], "name": ["FarMall"]})
    markets = pd.DataFrame({"lat": [1.352], "lon": [103.85], "name": ["Hawker"]})
    pois = {"schools": schools, "markets": markets, "malls": malls}
    lookup = pd.DataFrame(
        [
            {
                "hdb_addr_id": 42,
                "dist_nearest_any_school": 123.0,
                "within_1km_any_pri_school": 1,
                "within_1km_2km_pri_school": 0,
                "dist_nearest_mall": 456.0,
            }
        ]
    )
    out = append_poi_amenity_v2_features(hdb, pois, hdb_poi_lookup=lookup)
    assert float(out["dist_nearest_primary_school"].iloc[0]) == pytest.approx(123.0)
    assert int(out["is_within_1km_primary_school"].iloc[0]) == 1
    assert int(out["is_within_2km_primary_school"].iloc[0]) == 1
    assert float(out["dist_nearest_mall"].iloc[0]) == pytest.approx(456.0)
    assert int(out["hawker_count_within_1km"].iloc[0]) >= 1


def test_db_flags_within_2km_when_only_legacy_band_set():
    lookup = pd.DataFrame(
        [
            {
                "hdb_addr_id": 7,
                "dist_nearest_any_school": float("nan"),
                "within_1km_any_pri_school": 0,
                "within_1km_2km_pri_school": 1,
                "dist_nearest_mall": float("nan"),
            }
        ]
    )
    hdb = _minimal_hdb()
    hdb["enriched_addr_id"] = [7]
    schools = pd.DataFrame({"lat": [1.46], "lon": [104.0]})
    pois = {"schools": schools, "markets": pd.DataFrame(), "malls": pd.DataFrame()}
    out = append_poi_amenity_v2_features(hdb, pois, hdb_poi_lookup=lookup)
    assert int(out["is_within_2km_primary_school"].iloc[0]) == 1
    assert int(out["is_within_1km_primary_school"].iloc[0]) == 0
