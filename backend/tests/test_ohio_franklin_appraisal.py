from pipeline.import_ohio_franklin_appraisal import parse_sale, parse_snapshot


def test_franklin_snapshot_maps_dwelling_fields() -> None:
    parsed = parse_snapshot({"PARCEL ID": "010-1", "ADRNOLOW": "12", "ADRSTR": "MAIN",
                             "ADRSUF": "ST", "PROPERTYCLASS": "R", "LUC": "510",
                             "COSTLAND": "50000", "COSTIMP": "150000", "COSTTOT": "200000"},
                            {"beds": 3, "baths": 2.5, "area": 1800, "year": 1999})
    assert parsed is not None and parsed[3] == "39049-010-1"
    assert parsed[8:12] == (1999, 1800, 3, 2.5)


def test_franklin_sale_maps_history() -> None:
    parsed = parse_sale({"PARCEL ID": "010-1", "SALEDT": "05/01/1986", "PRICE": "22000",
                         "VALID": "V", "CONDSALE_OTHER": "N"})
    assert parsed is not None and parsed[6] == 22000 and parsed[8] is True
