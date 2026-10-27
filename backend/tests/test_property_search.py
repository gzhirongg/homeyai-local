"""Property search autocomplete, lookup validation, and analytics filter alignment."""

import pytest

import models
from models import HdbAddressEnrichmentOnemap, HdbResaleTransaction
from services.analytics_service import query_transactions

from tests.conftest import TestingSessionLocal, engine


@pytest.fixture()
def enrichment_rows():
    models.HdbAddressEnrichmentOnemap.__table__.create(bind=engine, checkfirst=True)
    db = TestingSessionLocal()
    rows = [
        HdbAddressEnrichmentOnemap(
            postal_code="541326",
            latitude=1.35,
            longitude=103.89,
            query_sent="34 CROSS STREET",
            raw_response="{}",
        ),
        HdbAddressEnrichmentOnemap(
            postal_code="541327",
            latitude=1.351,
            longitude=103.891,
            query_sent="36 CROSS STREET",
            raw_response="{}",
        ),
    ]
    db.add_all(rows)
    db.commit()
    ids = [r.id for r in rows]
    db.close()
    yield ids
    db = TestingSessionLocal()
    db.query(HdbAddressEnrichmentOnemap).delete()
    db.commit()
    db.close()
    models.HdbAddressEnrichmentOnemap.__table__.drop(bind=engine, checkfirst=True)


def test_search_properties_min_length(client):
    r = client.get("/api/analytics/properties/search?q=a")
    assert r.status_code == 200
    assert r.json()["results"] == []


def test_postal_search_min_length(client):
    r = client.get("/api/analytics/properties/postal_search?postal_q=5")
    assert r.status_code == 200
    assert r.json()["results"] == []


def test_postal_search_rejects_non_digits(client):
    r = client.get("/api/analytics/properties/postal_search?postal_q=54a")
    assert r.status_code == 200
    assert r.json()["results"] == []


def test_search_properties_finds_address(client, enrichment_rows):
    r = client.get("/api/analytics/properties/search?q=cross")
    assert r.status_code == 200
    names = [x["name"] for x in r.json()["results"]]
    assert "34 CROSS STREET" in names


def test_postal_search_prefix(client, enrichment_rows):
    r = client.get("/api/analytics/properties/postal_search?postal_q=541")
    assert r.status_code == 200
    postals = [x["postal_code"] for x in r.json()["results"]]
    assert "541326" in postals
    assert "541327" in postals


def test_lookup_requires_six_digits(client):
    r = client.get("/api/properties/lookup?postal_code=54132")
    assert r.status_code == 400


def test_lookup_not_found(client, enrichment_rows):
    r = client.get("/api/properties/lookup?postal_code=999999")
    assert r.status_code == 404


def test_analytics_property_name_case_insensitive(client, enrichment_rows):
    addr_id = enrichment_rows[0]
    db = TestingSessionLocal()
    db.add(
        HdbResaleTransaction(
            month="2024-01",
            town="SERANGOON",
            flat_type="4 ROOM",
            block="34",
            street_name="CROSS STREET",
            storey_range="07 TO 09",
            floor_area_sqm=95,
            flat_model="Model A",
            lease_commence_date=1990,
            resale_price=500000,
            enriched_addr_id=addr_id,
        )
    )
    db.commit()
    db.close()

    result = query_transactions(property_name="34 cross street")
    assert result["summary"]["total"] == 1

    db = TestingSessionLocal()
    db.query(HdbResaleTransaction).filter(
        HdbResaleTransaction.enriched_addr_id == addr_id
    ).delete()
    db.commit()
    db.close()


def test_analytics_postal_strips_non_digits(client, enrichment_rows):
    addr_id = enrichment_rows[0]
    db = TestingSessionLocal()
    db.add(
        HdbResaleTransaction(
            month="2024-02",
            town="SERANGOON",
            flat_type="4 ROOM",
            block="34",
            street_name="CROSS STREET",
            storey_range="10 TO 12",
            floor_area_sqm=95,
            flat_model="Model A",
            lease_commence_date=1990,
            resale_price=510000,
            enriched_addr_id=addr_id,
        )
    )
    db.commit()
    db.close()


    result = query_transactions(postal_code="541-326")
    assert result["summary"]["total"] == 1

    db = TestingSessionLocal()
    db.query(HdbResaleTransaction).filter(
        HdbResaleTransaction.enriched_addr_id == addr_id
    ).delete()
    db.commit()
    db.close()


@pytest.mark.parametrize("scope", [{"postal_code": "541326"}, {"property_name": "34 cross street"}])
def test_address_scoped_aggregates_exclude_other_properties(client, enrichment_rows, scope):
    db = TestingSessionLocal()
    records = [
        HdbResaleTransaction(month="2024-01", town="SERANGOON", flat_type="4 ROOM",
                             floor_area_sqm=95, resale_price=500000,
                             enriched_addr_id=enrichment_rows[0]),
        HdbResaleTransaction(month="2024-02", town="BEDOK", flat_type="5 ROOM",
                             floor_area_sqm=120, resale_price=900000,
                             enriched_addr_id=enrichment_rows[1]),
    ]
    db.add_all(records)
    db.commit()
    ids = [r.id for r in records]
    try:
        result = query_transactions(**scope)
        assert result["summary"]["total"] == 1
        assert result["time_series"][0]["period"] == "2024-01"
        assert result["time_series"][0]["avg_price"] == 500000
        assert result["by_town"] == [{"town": "SERANGOON", "txn_count": 1, "avg_price": 500000}]
        assert result["by_flat_type"] == [{"flat_type": "4 ROOM", "txn_count": 1, "avg_price": 500000}]
        for key in ("time_series", "by_town", "by_flat_type"):
            assert sum(r["txn_count"] for r in result[key]) == 1
    finally:
        db.query(HdbResaleTransaction).filter(HdbResaleTransaction.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
        db.close()

