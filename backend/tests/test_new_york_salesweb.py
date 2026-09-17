from datetime import date
from decimal import Decimal

from pipeline.import_new_york_salesweb import parse


def test_parse_salesweb_export_row():
    parsed = parse({
        "County Name": "Albany", "SWIS Code": "010100", "Print Key": "65.10-2-14",
        "Sale Date": "08/15/2025", "Sale Price": "$325,000", "Book": "2025", "Page": "12345",
        "Property Address": "10 STATE ST", "Municipality Name": "Albany", "Property ZIP Code": "12207",
        "Property Class at Sale": "210", "Arms Length": "Yes",
    })
    assert parsed is not None
    sale, snapshot = parsed
    assert sale[3] == "NY:010100:6510214"
    assert sale[4] == "2025:12345"
    assert sale[5] == date(2025, 8, 15)
    assert sale[6] == Decimal("325000")
    assert sale[9] is True
    assert snapshot[5] == "10 STATE ST"


def test_parse_actual_salesweb_export_columns():
    parsed = parse({
        "swis_cd": "030200", "county_nam": "Broome", "muni_nam": "Binghamton",
        "school_cd": "030200", "school_nam": "Binghamton", "print_key": "143.59-1-14",
        "st_nbr": "9", "st_nam": "COLUMBUS ST", "zip5": "13905",
        "book": "2698", "page": "505", "deed_dte": "2022-08-15",
        "sale_dte": "2022-08-10", "sale_price": "73000", "arms_length_flag": "Y",
        "prop_class_at_sale": "210", "prop_class_cd_desc_sale": "One Family Year-Round Residence",
    })
    assert parsed is not None
    sale, snapshot = parsed
    assert sale[3:7] == ("NY:030200:14359114", "2698:505", date(2022, 8, 10), Decimal("73000"))
    assert snapshot[5:11] == ("9 COLUMBUS ST", "Binghamton", "13905",
                              "One Family Year-Round Residence", "210", "030200")
    assert snapshot[11] == "Binghamton"


def test_rejects_rows_without_core_fields():
    assert parse({"County": "Albany", "Sale Price": "100000"}) is None
