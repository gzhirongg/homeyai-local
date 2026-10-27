#!/usr/bin/env python3
"""Smoke-check the standalone stack without installing host Python packages."""

import argparse
import json
import math
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:3001")
    parser.add_argument("--valuation", action="store_true", help="Also check imported data and the trained local model")
    parser.add_argument("--map", action="store_true", help="Also check imported URA and MRT map geometry")
    args = parser.parse_args()
    base = args.url.rstrip("/")

    def request(path, data=None, token=None, extra_headers=None):
        headers = dict(extra_headers or {})
        if data is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = Request(base + path, data=json.dumps(data).encode() if data is not None else None, headers=headers)
        with urlopen(req, timeout=45) as response:
            body = response.read()
            if "application/json" in response.headers.get("Content-Type", ""):
                return json.loads(body)
            return body

    for path in ("/", "/login", "/valuation", "/analytics", "/admin/health"):
        request(path)
        print(f"PASS page {path}")
    try:
        request("/api/user/profile")
        raise AssertionError("Unauthenticated profile request was accepted")
    except HTTPError as exc:
        assert exc.code == 401, exc.code
        print("PASS authentication required")

    login = request("/api/login", {"email": "admin@homeyai.com", "password": "admin123"})
    token = login["access_token"]
    assert login["user"]["role"] == "admin"
    print("PASS admin login through frontend proxy")
    for path in ("/api/user/profile", "/api/analytics/filters", "/api/admin/model/status", "/api/admin/ml/experiments"):
        request(path, token=token)
        print(f"PASS API {path}")

    health = request("/api/health", token=token)
    for service in ("api", "postgres", "minio", "prefect"):
        assert health[service]["status"] == "ok", health[service]
        print(f"PASS service {service}")

    if args.map:
        for endpoint, count in (("regions", 5), ("planning_areas", 55), ("planning_areas?region=WR", 12)):
            collection = request(f"/api/geospatial/{endpoint}")
            assert collection["type"] == "FeatureCollection"
            assert len(collection["features"]) == count, endpoint
            assert all(f["geometry"] and f["properties"]["region_c"] for f in collection["features"])
            if "region=WR" in endpoint:
                assert all(f["properties"]["region_c"] == "WR" for f in collection["features"])
            print(f"PASS map {endpoint}: {count} boundaries")
        stations = request("/api/geospatial/mrt_stations")
        assert len({f["properties"]["physical_station_id"] for f in stations["features"]}) >= 140
        for feature in stations["features"]:
            lon, lat = feature["geometry"]["coordinates"]
            assert 103.5 < lon < 104.2 and 1.1 < lat < 1.6
            if feature["properties"]["dates_source_type"] == "unavailable":
                assert feature["properties"]["pit_state"] == "UNKNOWN"
        print("PASS map MRT station geometry and honest temporal status")
        area = request("/api/geospatial/area_amenity_breakdown?region_c=WR")["mrts"]
        assert area["count"] > 0
        assert all(m["pit_state"] == "OPERATIONAL" for m in area["operational"])
        assert area["count"] == sum(len(area[k]) for k in ("operational", "upcoming", "unknown"))
        print("PASS area MRT summary keeps unknown status separate from operational")

    if args.valuation:
        status = request("/api/admin/model/status", token=token)
        assert status["is_ready"], status.get("load_error")
        postal = "600021"
        search = request(f"/api/analytics/properties/postal_search?postal_q={postal}")
        assert any(r["postal_code"] == postal for r in search["results"]), search
        prop = request(f"/api/properties/lookup?postal_code={postal}")
        option = next(o for o in prop["flat_options"] if o["flat_type"] == "4 ROOM")
        year = option["latest_lease_commence_year"] or prop["year_completed"]
        from datetime import datetime
        payload = {
            "postal_code": postal, "town": prop["town"], "region": prop["region"],
            "flat_type": option["flat_type"], "flat_model_grouped": option["flat_model_grouped"],
            "storey_midpoint": 8, "floor_area_sqm": option["avg_floor_area_sqm"] or 90,
            "remaining_lease_years": max(0, min(99, 99 - (datetime.now().year - year))),
            "latitude": prop["latitude"], "longitude": prop["longitude"],
            "lease_commence_year": year,
        }
        result = request("/api/valuation", payload, token=token)
        price = result["predicted_price"]
        assert math.isfinite(price) and price > 0, result
        print(f"PASS real property lookup and trained valuation: {postal}, SGD {price:,.2f}")
        analytics = request("/api/analytics/query", {"postal_code": postal})
        assert analytics["summary"]["total"] == prop["resale_transaction_count"]
        for key in ("time_series", "by_town", "by_flat_type"):
            assert sum(r["txn_count"] for r in analytics[key]) == prop["resale_transaction_count"], key
        print("PASS address-filtered analytics aggregates match actual resale records")
        premium = request("/api/valuation", payload, token=token,
                          extra_headers={"X-Homey-Preview-Role": "premium"})
        comparison = premium["neighbor_comparison"]
        assert comparison["source"]["name"] == "HDB recorded resale transactions"
        assert comparison["status"] == "ok", comparison
        assert comparison["similar_properties"]
        for sale in comparison["similar_properties"]:
            assert sale["transaction_id"] > 0 and sale["price"] > 0
            assert comparison["criteria"]["date_from"] <= sale["sale_month"] <= comparison["criteria"]["date_to"]
            assert sale["distance_m"] <= comparison["criteria"]["radius_m"]
        print(f"PASS recorded nearby comparables: {len(comparison['similar_properties'])} sales")


if __name__ == "__main__":
    main()
