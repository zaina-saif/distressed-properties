from decimal import Decimal

from pipeline.import_illinois_dupage_assessment import FIELDS, parse_snapshot


def test_maps_dupage_full_cash_values() -> None:
    parsed = parse_snapshot({"PIN":"0710405022", "ACREAGE":0.21, "PROPADDRL1":"919 STONEHENGE CT",
                             "PROPCITY":"NAPERVILLE", "PROPZIP":"60563", "PROPCLASS":"R",
                             "FCVLAND":54423, "FCVIMP":140030, "FCVTOTAL":194453})
    assert parsed[3] == "IL:DUPAGE:0710405022" and parsed[4] == 2025
    assert parsed[10:15] == (Decimal("0.21"), "acres", Decimal("54423"), Decimal("140030"), Decimal("194453"))


def test_private_fields_are_not_requested() -> None:
    assert not any(field.startswith("BILL") or "OWNER" in field for field in FIELDS)
