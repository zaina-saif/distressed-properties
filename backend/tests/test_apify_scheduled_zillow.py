from pipeline.apify_scheduled_zillow import clean_street, search_address


def test_alias_is_dropped():
    assert clean_street("856 Gibbons Court A/K/A 864-866") == "856 Gibbons Court"
    assert clean_street("116 Club House Drive Club House Drive Is Also Known As Clubhouse Drive") == "116 Club House Drive"


def test_trailing_municipality_is_dropped():
    assert clean_street("223 Pennsylvania Ave East Pennsboro - Township Enola") == "223 Pennsylvania Ave"
    assert clean_street("159 River Road Bridgeton (Hopewell Township)") == "159 River Road"


def test_unit_is_kept():
    assert clean_street("835 W ROSCOE ST. APT. 2E") == "835 W ROSCOE ST. APT. 2E"
    assert clean_street("107 RED BARN ROAD, UNIT 2-16") == "107 RED BARN ROAD UNIT 2-16"


def test_house_number_range_uses_first_number():
    assert clean_street("8155-57 S THROOP ST") == "8155 S THROOP ST"


def test_suffix_right_after_house_number_is_the_street_name():
    assert clean_street("830 Avenue A") == "830 Avenue A"


def test_search_address_uses_zip_or_city():
    assert search_address({"street_address": "8 Coachlight Drive", "state": "NJ", "zip_code": "08081",
                           "city": "Winslow Township"}) == "8 Coachlight Drive, NJ 08081"
    assert search_address({"street_address": "401 LEGION STREET", "state": "NY", "zip_code": None,
                           "city": "Brooklyn"}) == "401 LEGION STREET, Brooklyn, NY"


def test_consecutive_suffix_words_stay_in_the_street_name():
    assert clean_street("911 WEST TERRACE DRIVE") == "911 WEST TERRACE DRIVE"


def test_mailing_address_label_is_dropped():
    assert clean_street("Mailing Address: 12 Denhard Court") == "12 Denhard Court"
