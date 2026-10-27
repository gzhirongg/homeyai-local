import numpy as np
import pytest

from modelling.evaluation.prediction_intervals import calibrate_relative_interval, relative_interval_bounds
from services import report_service, ml_service


def test_interval_uses_finite_sample_rank_without_interpolation():
    calibration = calibrate_relative_interval(np.arange(101, 111), np.full(10, 100), coverage=.8)
    assert calibration["relative_error_quantile"] == pytest.approx(.09)
    assert relative_interval_bounds(1000, calibration) == [910, 1090]


@pytest.mark.parametrize("truth,prediction", [([], []), ([100], [100]), ([0]*10, [100]*10),
    ([100]*10, [0]*10), ([float("nan")]*10, [100]*10), ([100]*10, [100]*9)])
def test_invalid_calibration_cannot_publish_an_interval(truth, prediction):
    with pytest.raises(ValueError):
        calibrate_relative_interval(truth, prediction)


def test_serving_interval_is_bound_to_loaded_model_metadata(monkeypatch):
    monkeypatch.setattr(ml_service, "_manifest_meta", {"prediction_interval": {
        "method": "split_conformal_relative", "coverage": .9, "relative_error_quantile": .08}})
    result = ml_service.prediction_interval_payload(500000)
    assert result["confidence_interval"] == [460000, 540000]
    assert result["interval_coverage"] == .9
    monkeypatch.setattr(ml_service, "_manifest_meta", {})
    assert ml_service.prediction_interval_payload(500000)["confidence_interval_method"] == "fixed_percentage_band"


@pytest.fixture
def premium_headers(client):
    login = client.post("/api/login", json={"email": "admin@homeyai.com", "password": "admin123"})
    return {"Authorization": "Bearer " + login.json()["access_token"], "X-Homey-Preview-Role": "premium"}


@pytest.fixture
def report_payload():
    return {"property_data": {"postal_code": "600021", "town": "JURONG EAST", "flat_type": "4 ROOM",
        "flat_model_grouped": "Model A", "region": "West", "storey_midpoint": 8,
        "floor_area_sqm": 89, "remaining_lease_years": 86},
        "valuation_data": {"predicted_price": 600000, "confidence_interval": [540000, 660000],
            "confidence_interval_method": "fixed_percentage_band"},
        "report_config": {"include_market_sentiment": False, "include_comparative_analysis": False}}


def test_report_default_and_json_preview_use_actual_property_schema(client, premium_headers, report_payload):
    assert len(client.get("/api/reports/config/default").json()) == 6
    result = client.post("/api/reports/valuation/preview", json=report_payload, headers=premium_headers)
    assert result.status_code == 200
    assert result.json()["sections"][0]["metadata"]["floor_area"] == "89.0 sqm"
    assert "95%" not in result.text


def test_report_html_labels_heuristic_and_supports_custom_sections(client, premium_headers, report_payload):
    report_payload["report_config"].update(include_property_details=False, include_amenities=False)
    result = client.post("/api/reports/valuation/preview/html", json=report_payload, headers=premium_headers)
    assert result.status_code == 200
    html = result.json()["html"]
    assert "fixed +/-10% heuristic" in html
    assert "95%" not in html and "PROPERTY SPECIFICATIONS" not in html
    assert "LOCATION &amp;" not in html


def test_report_preview_enforces_same_premium_gate_as_pdf(client, report_payload):
    login = client.post("/api/login", json={"email": "free@homeyai.com", "password": "free123"})
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    for suffix in ("preview", "preview/html", "pdf"):
        assert client.post("/api/reports/valuation/" + suffix, json=report_payload, headers=headers).status_code == 403


def test_report_preserves_calibration_limits_and_actual_comparable_prices():
    values = {"predicted_price": 500000, "confidence_interval": [450000, 550000],
        "confidence_interval_method": "split_conformal_relative", "interval_coverage": .9,
        "interval_calibration": {"test_coverage": .866},
        "neighbor_comparison": {"status": "ok", "similar_properties": [
            {"address": "21 EXAMPLE ROAD", "sale_month": "2026-06", "floor_area": 89, "price": 512345}]}}
    html, _ = report_service.generate_html_preview({}, values, {"include_comparative_analysis": True}, "test@example.com",
        comparative_data={"projects": [{"name": "WRONG AGGREGATE"}]})
    assert "86.6%" in html and "S$512,345" in html and "WRONG AGGREGATE" not in html
    assert "95%" not in html


def test_legacy_chat_reuses_database_analysis_and_has_no_fake_confidence(client, premium_headers, monkeypatch):
    from services import analytics_service
    import ai_service
    monkeypatch.setattr(ai_service, "_get_openai", lambda: None)
    monkeypatch.setattr(analytics_service, "get_filter_options", lambda: {"towns": ["SEMBAWANG"]})
    calls = []
    def query(**kwargs):
        calls.append(kwargs)
        return {"summary": {"total": 1234, "avg_price": 567890, "avg_psf": 500,
            "min_price": 300000, "max_price": 800000}, "time_series": []}
    monkeypatch.setattr(analytics_service, "query_transactions", query)
    result = client.post("/api/ai/chat", json={"message": "Sembawang 4-room prices?"}, headers=premium_headers)
    assert result.status_code == 200
    assert "1,234" in result.json()["response"] and result.json()["confidence"] is None
    assert calls[0]["towns"] == ["SEMBAWANG"] and calls[0]["flat_types"] == ["4 ROOM"]


def test_missing_rates_are_not_called_stable(monkeypatch):
    import pandas as pd
    from services import sentiment_service as service
    monkeypatch.setattr(service, "fetch_rpi_data", lambda: pd.DataFrame([
        {"quarter": "2026-Q1", "index": 200., "rpi_qoq_pct": 1.},
        {"quarter": "2026-Q2", "index": 202., "rpi_qoq_pct": 1.}]))
    monkeypatch.setattr(service, "fetch_interest_rates", lambda: pd.DataFrame())
    monkeypatch.setattr(service, "get_txn_volume_signal", lambda: {
        "txn_volume": 2000, "txn_volume_z": .1, "txn_volume_label": "Normal Activity"})
    result = service.get_market_sentiment()
    assert result["interest_rate"] is None and result["interest_rate_label"] is None
    assert "excluded" in result["composite_insight"]


def test_missing_rpi_does_not_become_a_fabricated_neutral_score(monkeypatch):
    import pandas as pd
    from services import sentiment_service as service
    monkeypatch.setattr(service, "fetch_rpi_data", lambda: pd.DataFrame())
    with pytest.raises(RuntimeError, match="price-index data is unavailable"):
        service.get_market_sentiment()
