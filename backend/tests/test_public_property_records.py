from decimal import Decimal

from pipeline.import_maryland_property_data import FIELDS, parse_row
from pipeline.backfill_maryland_addresses import (
    arcgis_location_record, arcgis_record, canonical_header, parse as parse_address_backfill,
)


def test_maryland_row_creates_snapshot_and_three_sales() -> None:
    row = {
        FIELDS["county"]: "Montgomery",
        FIELDS["parcel"]: "01-234567",
        FIELDS["tax_year"]: "2026",
        FIELDS["address"]: "1 Main St",
        FIELDS["city"]: "Rockville",
        FIELDS["zip"]: "20850",
        FIELDS["longitude"]: "-77.15",
        FIELDS["latitude"]: "39.08",
        FIELDS["land_use"]: "Residential",
        FIELDS["year_built"]: "1998",
        FIELDS["living_area"]: "2100",
        FIELDS["assessed"]: "550000",
        FIELDS["sale_1_id"]: "A1",
        FIELDS["sale_1_date"]: "2024.05.03",
        FIELDS["sale_1_price"]: "625000",
        FIELDS["sale_2_id"]: "A2",
        FIELDS["sale_2_date"]: "2018.01.12",
        FIELDS["sale_2_price"]: "410000",
        FIELDS["sale_3_id"]: "A3",
        FIELDS["sale_3_date"]: "2010.02.10",
        FIELDS["sale_3_price"]: "350000",
    }
    snapshot, sales = parse_row(row)
    assert snapshot is not None
    assert snapshot.source_parcel_id == "01-234567"
    assert snapshot.living_area == 2100
    assert snapshot.total_assessed_value == Decimal("550000")
    assert [sale.transaction_id for sale in sales] == ["A1", "A2", "A3"]


def test_maryland_row_skips_missing_identity_and_nonpositive_sales() -> None:
    assert parse_row({}) == (None, [])
    row = {
        FIELDS["county"]: "Allegany", FIELDS["parcel"]: "X", FIELDS["tax_year"]: "2026",
        FIELDS["sale_1_id"]: "bad", FIELDS["sale_1_date"]: "2024.01.01",
        FIELDS["sale_1_price"]: "0",
    }
    snapshot, sales = parse_row(row)
    assert snapshot is not None
    assert sales == []


def test_maryland_row_uses_record_update_year_when_tax_year_is_zero() -> None:
    row = {
        FIELDS["county"]: "St. Mary's County",
        FIELDS["parcel"]: "1908011893",
        FIELDS["tax_year"]: "0000",
        FIELDS["updated"]: "20240206",
    }
    snapshot, _ = parse_row(row)
    assert snapshot is not None
    assert snapshot.snapshot_year == 2024


def test_maryland_premise_fallback_marks_missing_house_number() -> None:
    row = {
        FIELDS["county"]: "Allegany County", FIELDS["parcel"]: "0101093649",
        FIELDS["tax_year"]: "2026", FIELDS["premise_number"]: "00000",
        FIELDS["premise_name"]: "WATSON", FIELDS["premise_type"]: "RD",
        FIELDS["premise_city"]: "LITTLE ORLEANS", FIELDS["premise_zip"]: "21766",
    }
    snapshot, _ = parse_row(row)
    assert snapshot is not None
    assert snapshot.street_address == "WATSON RD"
    assert snapshot.city == "LITTLE ORLEANS"
    assert snapshot.zip_code == "21766"
    assert snapshot.house_number_unavailable is True


def test_maryland_premise_fallback_normalizes_padded_house_number() -> None:
    row = {
        FIELDS["county"]: "Baltimore City", FIELDS["parcel"]: "24",
        FIELDS["tax_year"]: "2026", FIELDS["premise_number"]: "00834",
        FIELDS["premise_direction"]: "E", FIELDS["premise_name"]: "FORT",
        FIELDS["premise_type"]: "AVE",
    }
    snapshot, _ = parse_row(row)
    assert snapshot is not None
    assert snapshot.street_address == "834 E FORT AVE"
    assert snapshot.house_number_unavailable is False


def test_maryland_backfill_uses_same_conservative_address_parser() -> None:
    row = {
        FIELDS["county"]: "Allegany County", FIELDS["parcel"]: "0101093649",
        FIELDS["premise_number"]: "00000", FIELDS["premise_name"]: "WATSON",
        FIELDS["premise_type"]: "RD", FIELDS["premise_city"]: "LITTLE ORLEANS",
        FIELDS["premise_zip"]: "21766",
    }
    assert parse_address_backfill(row) == (
        "Allegany County", "0101093649", "WATSON RD", "LITTLE ORLEANS", "21766", True,
    )
    assert canonical_header("PREMISE ADDRESS: Name (MDP Field: PREMSNAM. SDAT Field #23)") == FIELDS["premise_name"]


def test_maryland_arcgis_partial_premise_address() -> None:
    assert arcgis_record({
        "ACCTID": "0101093649", "ADDRESS": None, "PREMSNUM": None,
        "PREMSNAM": "WATSON", "PREMSTYP": "RD",
        "PREMCITY": "LITTLE ORLEANS", "PREMZIP": "21766",
    }) == ("0101093649", "WATSON RD", "LITTLE ORLEANS", "21766", True)


def test_maryland_arcgis_combined_address_for_remaining_blank_parcel() -> None:
    assert arcgis_record({
        "ACCTID": "0122009303", "ADDRESS": "10800 AERIE RD NE",
        "CITY": "CUMBERLAND", "ZIPCODE": "21502",
    }) == ("0122009303", "10800 AERIE RD NE", "CUMBERLAND", "21502", False)


def test_maryland_arcgis_retains_partial_city_when_street_is_missing() -> None:
    attributes = {"ACCTID": "0102013703", "CITY": "OLDTOWN", "ZIPCODE": "21555"}
    assert arcgis_record(attributes) is None
    assert arcgis_location_record(attributes) == ("0102013703", None, "OLDTOWN", "21555", False)
