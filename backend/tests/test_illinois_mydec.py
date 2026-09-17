from datetime import date
from decimal import Decimal

from pipeline.import_illinois_mydec import FIELDS, parse_sale, parse_snapshot


def sample() -> dict[str, str]:
    return {"declaration_id": "2026000123", "document_number": "DOC-1",
            "date_recorded": "2026-06-12T00:00:00.000", "line_4_instrument_date": "2026-06-10",
            "line_1_county": "Cook", "line_1_primary_pin": "12-34-567-890-0000",
            "line_1_street": "1 Main St", "line_1_city": "Chicago", "line_1_zip_code": "60601",
            "line_1_lot_size_or_acreage": "0.25", "line_1_unit": "Acres",
            "line_8_current_use": "Residential", "line_7_property_advertised": "true",
            "line_13_net_consideration": "275000"}


def test_maps_sale_and_sparse_historical_snapshot() -> None:
    row = sample()
    sale = parse_sale(row, date(2026, 9, 14)); snapshot = parse_snapshot(row, date(2026, 9, 14))
    assert sale is not None and sale[3] == "IL:COOK:12-34-567-890-0000"
    assert sale[5] == date(2026, 6, 10) and sale[6] == date(2026, 6, 12)
    assert sale[7] == Decimal("275000") and sale[9] is True
    assert snapshot is not None and snapshot[4] == 2026 and snapshot[8] == "Residential"
    assert snapshot[10:12] == (Decimal("0.25"), "Acres")


def test_distress_condition_is_not_arms_length() -> None:
    row = sample(); row["line_10g_short_sale"] = "true"
    sale = parse_sale(row, date(2026, 9, 14))
    assert sale is not None and sale[8] == "short-sale" and sale[9] is False


def test_net_real_property_price_precedes_full_consideration() -> None:
    row = sample(); row["line_11_full_consideration"] = "300000"; row["line_13_net_consideration"] = "250000"
    assert parse_sale(row, date(2026, 9, 14))[7] == Decimal("250000")


def test_impossible_land_area_is_discarded() -> None:
    row = sample(); row["line_1_lot_size_or_acreage"] = "99999999999999999"
    assert parse_snapshot(row, date(2026, 9, 14))[10] is None


def test_private_party_fields_are_never_requested() -> None:
    # Line 10 buyer/seller flags describe transaction conditions, not identities.
    assert not any(field.startswith("step_4_") or field in {"additional_buyers", "additional_sellers"}
                   for field in FIELDS)
