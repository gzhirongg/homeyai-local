"""Checks that the local map import accepts corroborated station locations only."""
import pytest

from scripts.bootstrap_local_map import station_name, station_rows


def exits(*names):
    return {"features": [
        {"properties": {"STATION_NA": name}, "geometry": {"coordinates": [103.85, 1.3]}}
        for name in names
    ]}


def address(name, lon="103.85", lat="1.3"):
    return {"name": name, "lon": lon, "lat": lat}


def test_interchange_has_one_physical_station_and_both_verified_codes():
    rows, unmatched = station_rows(exits("CITY HALL"), [
        address("CITY HALL MRT STATION (EW13 / NS25)"),
        address("CITY HALL MRT STATION (EW13 / NS25)"),
    ])
    assert unmatched == []
    assert len(rows) == 1
    assert rows[0]["codes"] == {"EW13": "East-West Line", "NS25": "North-South Line"}


def test_future_uncorroborated_and_lrt_stations_are_not_imported():
    rows, unmatched = station_rows(exits("CITY HALL", "SENJA LRT STATION"), [
        address("CITY HALL MRT STATION (NS25)"),
        address("FUTURE MRT STATION (CR99)"),
        address("SENJA LRT STATION (BP13)"),
    ])
    assert [r["name"] for r in rows] == ["CITY HALL"]
    assert unmatched == []


def test_unmatched_official_station_is_reported_instead_of_given_a_fake_code():
    rows, unmatched = station_rows(exits("NEW MRT STATION"), [])
    assert rows == []
    assert unmatched == ["NEW"]


@pytest.mark.parametrize("lon,lat", [(0, 0), (105, 1.3), (103.9, 1.4)])
def test_invalid_or_disagreeing_coordinates_fail_import(lon, lat):
    with pytest.raises(ValueError):
        station_rows(exits("CITY HALL"), [address("CITY HALL MRT STATION (NS25)", str(lon), str(lat))])


def test_normalization_preserves_names_and_removes_only_station_suffix():
    assert station_name("  one-north MRT STATION ") == "ONE-NORTH"
    assert station_name("GARDENS BY THE BAY") == "GARDENS BY THE BAY"


def test_area_summary_never_labels_unknown_stations_operational(monkeypatch):
    from services import geospatial_service as service
    states = ["OPERATIONAL", "COMMITTED_DATED", "COMMITTED_ESTIMATED", "ANNOUNCED_UNDATED", "UNKNOWN", None]
    stations = [{"id": i, "pit_state": state} for i, state in enumerate(states)]
    monkeypatch.setattr(service, "list_mrts_in_planning_union", lambda *args, **kwargs: stations)
    monkeypatch.setattr(service, "list_pois_in_planning_union", lambda *args, **kwargs: {
        "counts_by_type": {}, "by_type": {}, "pcn_capped": False, "poi_total": 0,
    })
    result = service.build_area_amenity_breakdown(None, region_c="WR")["mrts"]
    assert [row["id"] for row in result["operational"]] == [0]
    assert [row["id"] for row in result["upcoming"]] == [1, 2, 3]
    assert [row["id"] for row in result["unknown"]] == [4, 5]
    assert result["count"] == 6
