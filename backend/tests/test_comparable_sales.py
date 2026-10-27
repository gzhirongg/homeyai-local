"""Verify comparables are recorded, genuinely nearby sales independent of the estimate."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import HdbAddressEnrichmentOnemap as Address, HdbResaleTransaction as Sale
from services.comparable_service import find_comparable_sales


@pytest.fixture()
def sales_db():
    engine = create_engine("sqlite:///:memory:")
    Address.__table__.create(engine)
    Sale.__table__.create(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def add_sale(db, *, latitude=1.3, longitude=103.8, postal="123456", **overrides):
    address = db.query(Address).filter_by(postal_code=postal).first()
    if address is None:
        address = Address(postal_code=postal, latitude=latitude, longitude=longitude,
                          query_sent="21 REAL STREET", raw_response="{}")
        db.add(address)
        db.flush()
    values = dict(month="2026-09", town="CLEMENTI", flat_type="4 ROOM", flat_model="Model A",
                  block="21", street_name="REAL ST", storey_range="07 TO 09",
                  floor_area_sqm=90, lease_commence_date=2013, remaining_lease_years=86,
                  resale_price=500000, enriched_addr_id=address.id)
    values.update(overrides)
    sale = Sale(**values)
    db.add(sale)
    db.flush()
    return sale


def compare(db, **overrides):
    values = dict(predicted_price=550000, floor_area_sqm=90, flat_type="4 ROOM", flat_model="Model A",
                  storey_midpoint=8, remaining_lease_years=86, latitude=1.3, longitude=103.8,
                  valuation_month="2026-10", subject_postal_code="123456")
    values.update(overrides)
    return find_comparable_sales(db, **values)


def test_returns_recorded_prices_and_recomputes_summary_without_changing_sales(sales_db):
    first = add_sale(sales_db)
    second = add_sale(sales_db, postal="123457", latitude=1.301, resale_price=600000, block="22")
    lower = compare(sales_db)
    higher = compare(sales_db, predicted_price=800000)
    assert lower["status"] == "ok"
    assert lower["average_neighbor_price"] == 550000
    assert lower["average_neighbor_price"] == higher["average_neighbor_price"]
    assert lower["price_percentile"] == 50
    assert higher["price_percentile"] == 100
    assert lower["market_position"] == "In line with comparable sales"
    assert higher["market_position"] == "Above comparable sales"
    for result in (lower, higher):
        assert {r["transaction_id"]: r["price"] for r in result["similar_properties"]} == {
            first.id: 500000, second.id: 600000,
        }
        assert [r["transaction_id"] for r in result["similar_properties"]] == [first.id, second.id]
        assert result["similar_properties"][0]["sale_month"] == "2026-09"
        assert result["similar_properties"][0]["same_building"] is True
        assert result["similar_properties"][1]["same_building"] is False
    assert lower["similar_properties"][0]["difference_pct"] == -9.1
    assert higher["similar_properties"][0]["difference_pct"] == -37.5


@pytest.mark.parametrize("changes", [
    {"month": "2025-10"}, {"month": "2026-11"}, {"flat_type": "5 ROOM"},
    {"floor_area_sqm": 130}, {"lease_commence_date": 1980}, {"storey_range": "28 TO 30"},
    {"latitude": 1.307, "longitude": 103.807},  # inside bounding square, outside radius
    {"latitude": None}, {"storey_range": "UNKNOWN"},
    {"lease_commence_date": None, "remaining_lease_years": None}, {"resale_price": 0},
])
def test_excludes_unsuitable_sales_without_fabricating_replacements(sales_db, changes):
    add_sale(sales_db, **changes)
    result = compare(sales_db)
    assert result["status"] == "no_matches"
    assert result["similar_properties"] == []
    assert result["average_neighbor_price"] is None
    assert result["market_position"] is None
    assert result["price_percentile"] is None


def test_no_location_does_not_query_or_claim_comparables():
    result = compare(None, latitude=None, longitude=None)
    assert result["status"] == "unavailable"
    assert result["reason"] == "location_missing"
    assert result["similar_properties"] == []


def test_date_boundaries_and_building_diversity(sales_db):
    add_sale(sales_db, month="2025-11", postal="123450")
    add_sale(sales_db, month="2026-10", postal="123451")
    for month in ("2026-06", "2026-07", "2026-08"):
        add_sale(sales_db, month=month)
    result = compare(sales_db)
    assert result["criteria"]["date_from"] == "2025-11"
    assert result["criteria"]["date_to"] == "2026-10"
    assert result["match_count"] == 5
    assert len(result["similar_properties"]) == 4
    assert sum(r["postal_code"] == "123456" for r in result["similar_properties"]) == 2
    assert {r["sale_month"] for r in result["similar_properties"]} == {"2025-11", "2026-10", "2026-07", "2026-08"}


def test_price_per_sqm_comparison_accounts_for_different_sizes(sales_db):
    add_sale(sales_db, floor_area_sqm=100, resale_price=600000)
    result = compare(sales_db, predicted_price=540000)
    assert result["average_price_per_sqm"] == 6000
    assert result["market_position"] == "In line with comparable sales"
