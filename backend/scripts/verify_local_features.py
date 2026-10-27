#!/usr/bin/env python3
"""Exercise local feature contracts using the real database and active model."""
from datetime import datetime
import json
import math
from pathlib import Path

import requests


def main():
    base = "http://localhost:8000"
    session = requests.Session()
    login = session.post(base + "/api/login", json={"email": "premium@homeyai.com", "password": "premium123"}, timeout=15)
    login.raise_for_status()
    session.headers["Authorization"] = "Bearer " + login.json()["access_token"]
    prop = session.get(base + "/api/properties/lookup?postal_code=600021", timeout=30).json()
    option = next(o for o in prop["flat_options"] if o["flat_type"] == "4 ROOM")
    year = option["latest_lease_commence_year"] or prop["year_completed"]
    inputs = dict(postal_code="600021", town=prop["town"], region=prop["region"], flat_type="4 ROOM",
        flat_model_grouped=option["flat_model_grouped"], floor_area_sqm=89, storey_midpoint=8,
        remaining_lease_years=max(0, min(99, 99-(datetime.now().year-year))), lease_commence_year=year,
        latitude=prop["latitude"], longitude=prop["longitude"])
    response = session.post(base + "/api/valuation", json=inputs, timeout=90)
    response.raise_for_status()
    valuation = response.json()
    shap = valuation["shap_values"]
    baseline = shap["baseline"]["expected_value_log1p"]
    phi_total = sum(c["contribution_log"] for c in shap["contributions"])
    assert math.isclose(baseline + phi_total, shap["predicted_log1p"], abs_tol=1e-5)
    assert valuation["confidence_interval_method"] == "split_conformal_relative"
    assert valuation["confidence_interval"][0] < valuation["predicted_price"] < valuation["confidence_interval"][1]
    print(f"PASS real valuation, calibrated interval, and {len(shap['contributions'])} SHAP contributions (log-space additivity)", flush=True)

    config = session.get(base + "/api/reports/config/default", timeout=15)
    config.raise_for_status()
    assert len(config.json()) == 6
    payload = {"property_data": inputs, "valuation_data": valuation, "report_config": config.json()}
    for suffix in ("preview", "preview/html"):
        response = session.post(base + "/api/reports/valuation/" + suffix, json=payload, timeout=90)
        response.raise_for_status()
        assert "95%" not in response.text
        if suffix.endswith("html"):
            html = response.json()["html"]
            assert "AI REASONING (SHAP VALUES)" in html
            assert str(valuation["neighbor_comparison"]["similar_properties"][0]["address"]) in html
            assert f"{valuation['interval_calibration']['test_coverage']*100:.1f}%" in html
        print(f"PASS valuation report {suffix}", flush=True)
    response = session.post(base + "/api/reports/valuation/pdf", json=payload, timeout=90)
    response.raise_for_status()
    assert response.content.startswith(b"%PDF") and len(response.content) > 5000
    output = Path("/workspace/data")
    (output / "local_verified_valuation.pdf").write_bytes(response.content)
    print(f"PASS PDF download ({len(response.content):,} bytes)", flush=True)
    payload["report_config"].update(include_property_details=False, include_amenities=False,
        include_market_insights=False, include_comparative_analysis=False, include_market_sentiment=False)
    response = session.post(base + "/api/reports/valuation/preview/html", json=payload, timeout=60)
    response.raise_for_status()
    assert response.json()["page_count"] == 2
    print("PASS custom report sections", flush=True)

    response = session.post(base + "/api/ai/chat", json={"message": "Sembawang 4-room prices?"}, timeout=60)
    response.raise_for_status()
    chat = response.json()
    assert chat["mode"] == "local_data" and chat["confidence"] is None
    from services import analytics_service
    summary = analytics_service.query_transactions(towns=["SEMBAWANG"], flat_types=["4 ROOM"], group_by="year")["summary"]
    assert f"{summary['total']:,}" in chat["response"]
    print("PASS assistant returns actual filtered HDB statistics without invented confidence", flush=True)
    response = session.get(base + "/api/market/sentiment", timeout=30)
    response.raise_for_status()
    sentiment = response.json()
    assert sentiment["rsi_raw"] is not None and sentiment["txn_volume"] > 0
    assert sentiment["interest_rate"] is None and sentiment["interest_rate_label"] is None
    print("PASS database-backed RPI/volume and honest unavailable interest-rate signal", flush=True)
    nearby = session.get(base + "/api/geospatial/amenity_score?postal_code=600021&radius_km=2", timeout=30)
    nearby.raise_for_status()
    assert nearby.json()["mrt"]["operational"] == [] and nearby.json()["mrt"]["unknown"]
    print("PASS address MRT explorer keeps undated stations separate from operational", flush=True)
    report = {"valuation": {k: valuation[k] for k in ("predicted_price", "confidence_interval", "interval_calibration")},
        "shap_contribution_count": len(shap["contributions"]), "sentiment": sentiment,
        "assistant_mode": chat["mode"], "pdf_bytes": len((output / "local_verified_valuation.pdf").read_bytes())}
    (output / "local_feature_verification.json").write_text(json.dumps(report, indent=2)+"\n")


if __name__ == "__main__":
    main()
