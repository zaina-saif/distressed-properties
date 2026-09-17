from datetime import date

from app.api.warehouse_valuations import apply_address_matches, score_current_rows
from app.main import app


def test_untrained_model_never_fabricates_property_price():
    rows = [{"street_address": "10 MAIN ST", "estimated_price": None}]
    score_current_rows(rows, None, date(2026, 9, 16))
    assert rows[0]["estimated_price"] is None
    assert rows[0]["estimate_status"] == "MODEL_NOT_AVAILABLE"


def test_warehouse_review_routes_are_registered():
    routes = set(app.openapi()["paths"])
    assert "/api/v1/warehouse-valuations/coverage" in routes
    assert "/api/v1/warehouse-valuations/counties" in routes
    assert "/api/v1/warehouse-valuations/months" in routes
    assert "/api/v1/warehouse-valuations/properties" in routes


def test_exact_parcel_address_fallback_preserves_existing_values():
    items = [
        {"source_parcel_id": "P1", "street_address": None, "city": None,
         "zip_code": None, "house_number_unavailable": False},
        {"source_parcel_id": "P2", "street_address": "12 MAIN ST", "city": "Town",
         "zip_code": None, "house_number_unavailable": False},
    ]
    matches = [
        {"source_parcel_id": "P1", "source_id": "official_parcels", "snapshot_year": 2025,
         "street_address": "WATSON RD", "city": "Little Orleans", "zip_code": "21766",
         "house_number_unavailable": True},
        {"source_parcel_id": "P2", "source_id": "other", "snapshot_year": 2025,
         "street_address": "WRONG RD", "city": "Elsewhere", "zip_code": "00000",
         "house_number_unavailable": True},
    ]
    apply_address_matches(items, matches)
    assert items[0]["street_address"] == "WATSON RD"
    assert items[0]["house_number_unavailable"] is True
    assert items[0]["address_source_id"] == "official_parcels"
    assert items[1]["street_address"] == "12 MAIN ST"


def test_exact_parcel_fallback_can_supply_city_without_street() -> None:
    items = [{"source_parcel_id": "P3", "street_address": None, "city": None,
              "zip_code": None, "house_number_unavailable": False}]
    matches = [{"source_parcel_id": "P3", "source_id": "county_gis", "snapshot_year": 2026,
                "street_address": None, "city": "Cumberland", "zip_code": "21502",
                "house_number_unavailable": False}]
    apply_address_matches(items, matches)
    assert items[0]["street_address"] is None
    assert items[0]["city"] == "Cumberland"
    assert items[0]["zip_code"] == "21502"
    assert items[0]["address_source_id"] == "county_gis"
