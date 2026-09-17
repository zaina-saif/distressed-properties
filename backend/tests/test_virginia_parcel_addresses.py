from pipeline.import_virginia_parcel_addresses import COLUMNS, FIELDS, parse


def test_public_virginia_address_matches_qpid_without_personal_fields() -> None:
    parsed = parse({"VGIN_QPID": 5119500028492.0, "VGIN_Locality_Name": "Wise County",
                    "Address": "CAMERON RD", "City": None, "Zip": None})
    assert parsed is not None
    row = dict(zip(COLUMNS, parsed))
    assert row["source_parcel_id"] == "51-5119500028492"
    assert row["street_address"] == "CAMERON RD"
    assert row["house_number_unavailable"] is True
    assert "OWNER" not in FIELDS and "MAIL" not in FIELDS
    assert parse({"VGIN_QPID": 1, "VGIN_Locality_Name": "Wise County", "Address": None}) is None
