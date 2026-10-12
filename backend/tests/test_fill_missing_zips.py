from pipeline.fill_missing_zips import clean_street, pick_match, search_city


def match(address, zip_code="73130"):
    return {"matchedAddress": address, "addressComponents": {"zip": zip_code}, "coordinates": {"x": -97.35, "y": 35.45}}


def test_one_match_on_the_same_house_number():
    assert pick_match("1319 LAUREL LN", [match("1319 LAUREL LN, MIDWEST CITY, OK, 73130")]) == ("73130", 35.45, -97.35)


def test_ambiguous_or_different_matches_are_rejected():
    assert pick_match("1319 LAUREL LN", []) is None
    assert pick_match("1319 LAUREL LN", [match("1319 LAUREL LN, A, OK, 73130"), match("1319 LAUREL LN, B, OK, 73110")]) is None
    assert pick_match("1319 LAUREL LN", [match("1391 LAUREL LN, MIDWEST CITY, OK, 73130")]) is None
    assert pick_match("1319 LAUREL LN", [match("1319 LAUREL LN, MIDWEST CITY, OK", zip_code="")]) is None


def test_placeholder_cities_and_street_cleanup():
    assert search_city("Unincorporated") is None and search_city(None) is None
    assert search_city("Village") == "The Village" and search_city("Del City") == "Del City"
    assert clean_street("6306 E. 24TH PL. ST.") == "6306 E 24TH PL ST"
