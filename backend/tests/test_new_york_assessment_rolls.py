from decimal import Decimal

from pipeline.import_new_york_assessment_rolls import FIELDS, parse


def test_new_york_assessment_mapping_and_privacy() -> None:
    row = parse({"roll_year": "2025", "county_name": "Albany", "municipality_name": "Colonie",
                 "swis_code": "012689", "print_key_code": "16.2-3-4", "property_class": "210",
                 "property_class_description": "One Family Year-Round Residence",
                 "parcel_address_number": "12", "parcel_address_street": "MAIN ST",
                 "assessment_land": "50000", "assessment_total": "225000",
                 "full_market_value": "250000"})
    assert row[3:8] == ("NY:012689:16234", 2025, "12 MAIN ST", "Colonie", "One Family Year-Round Residence")
    assert row[8:12] == ("210", Decimal("50000"), Decimal("175000"), Decimal("225000"))
    assert not any(any(term in field for term in ("owner", "mailing", "deed", "exemption")) for field in FIELDS)
