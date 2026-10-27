import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.analytics_service import get_singapore_summary, get_district_analytics

def test_get_singapore_summary():
    summary = get_singapore_summary()
    assert "top_growth_districts" in summary
    assert "stats" in summary

def test_get_district_analytics():
    data = get_district_analytics("Bedok")
    assert data["district"] == "BEDOK"
    assert "historical_trend" in data
    assert "projects" in data
