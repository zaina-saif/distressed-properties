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


QUEENS = {"street_address": "37-46 79th Street", "city": "Jackson Heights", "state": "NY", "county": "Queens",
          "zip_code": "11372"}


def test_queens_house_number_matches_with_or_without_its_hyphen():
    assert mismatch_reason(QUEENS, _item("37-46 79th Street", "Flushing", "NY", "11372")) is None
    assert mismatch_reason({**QUEENS, "street_address": "9745 86TH ST"}, _item("97-45 86th St", "Ozone Park", "NY", "11372")) is None
    assert mismatch_reason(QUEENS, _item("37-48 79th Street", "Flushing", "NY", "11372")) == "house number 37-48 != 37-46"


def test_one_apartment_is_not_a_queens_building():
    assert mismatch_reason(QUEENS, _item("37-46 79th St #2", "Jackson Heights", "NY", "11372")) == \
        "matched one unit (37-46 79th St #2) of the building"
    assert mismatch_reason({**QUEENS, "street_address": "37-46 79th Street #2"},
                           _item("37-46 79th St #2", "Jackson Heights", "NY", "11372")) is None
    # Elsewhere a unit answer stays a match (condos listed without their unit).
    assert mismatch_reason(ROW, _item("830 Avenue A #2", "Bayonne", "NJ", "07002")) is None
