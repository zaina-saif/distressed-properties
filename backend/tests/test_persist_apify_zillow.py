from pipeline.persist_apify_zillow import mismatch_reason

ROW = {"street_address": "830 Avenue A", "city": "Bayonne", "state": "NJ", "zip_code": "07002"}


def _item(street, city, state, zip_code):
    return {"listingAddress": {"street": street, "city": city, "state": state, "zipCode": zip_code}}


def test_same_house_is_a_match():
    assert mismatch_reason(ROW, _item("830 Avenue A", "Bayonne", "NJ", "07002")) is None


def test_neighbouring_zip_in_same_town_is_still_a_match():
    assert mismatch_reason(ROW, _item("830 Avenue A", "Bayonne", "NJ", "07003")) is None


def test_other_state_is_invalid():
    assert "state" in mismatch_reason(ROW, _item("828 W Snow King Ave", "Jackson", "WY", "83001"))


def test_different_house_number_is_invalid():
    assert "house number" in mismatch_reason(ROW, _item("828 Avenue A", "Bayonne", "NJ", "07002"))


def test_missing_submitted_house_number_is_invalid():
    row = {**ROW, "street_address": "Lakeside Road"}
    assert mismatch_reason(row, _item("487 Lakeside Rd", "Bayonne", "NJ", "07002"))


def test_different_zip_and_town_is_invalid():
    row = {**ROW, "street_address": "128 Mount Pleasant Avenue West", "city": "Paterson", "zip_code": "07424"}
    assert "ZIP and city" in mismatch_reason(row, _item("128 Mount Pleasant Ave", "West Orange", "NJ", "07052"))


def test_result_without_address_is_not_flagged():
    assert mismatch_reason(ROW, {"zpid": 1}) is None
