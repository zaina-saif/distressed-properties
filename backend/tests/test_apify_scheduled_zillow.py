from pipeline.apify_scheduled_zillow import clean_street, first_pass_address, queens_street, search_address, searchable


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


def test_search_address_drops_periods_and_placeholder_cities():
    assert search_address({"street_address": "3034 N. 56TH ST.", "state": "OK", "zip_code": "74107",
                           "city": "Tulsa"}) == "3034 N 56TH ST, OK 74107"
    assert search_address({"street_address": "4015 S DOBBS RD", "state": "OK", "zip_code": None,
                           "city": "Unincorporated"}) == "4015 S DOBBS RD, OK"
    assert search_address({"street_address": "1717 GLADSTONE TER", "state": "OK", "zip_code": None,
                           "city": "Village"}) == "1717 GLADSTONE TER, The Village, OK"


def test_first_pass_adds_a_filled_in_zip_and_skips_unsearchable_rows():
    row = {"normalized_address": "1319 LAUREL LN, Midwest City, OK", "zip_code": "73130", "street_address": "1319 LAUREL LN"}
    assert first_pass_address(row) == "1319 LAUREL LN Midwest City OK 73130"
    assert first_pass_address({**row, "normalized_address": "1 A St, Tulsa, OK 74103"}) == "1 A St Tulsa OK 74103"
    assert searchable(row)
    assert not searchable({"street_address": "0 UNKNOWN", "normalized_address": "0 UNKNOWN, Edmond, OK"})
    assert not searchable({"street_address": "205 NW 89TH ST",
                           "normalized_address": "205 NW 89TH ST, Oklahoma City & 432 Larkspur Ln, Edmond, OK"})


def test_queens_streets_keep_the_hyphenated_house_number_and_a_short_suffix():
    assert queens_street("37-46 79th Street") == "37-46 79th St"
    assert queens_street("9745 86TH ST") == "97-45 86TH ST"
    assert queens_street("101 - 20 Lefferts Boulevard") == "101-20 Lefferts Blvd"
    assert queens_street("123 Beach 120th Street") == "123 Beach 120th St"
    assert queens_street("21-10 Court Square") == "21-10 Court Square"


def test_queens_search_leaves_out_the_neighborhood():
    row = {"street_address": "37-46 79th Street", "city": "Jackson Heights", "state": "NY", "county": "Queens",
           "zip_code": "11372", "normalized_address": "37-46 79th Street, Jackson Heights, NY 11372"}

    assert first_pass_address(row) == search_address(row) == "37-46 79th St, NY 11372"
    # Brooklyn numbers are not Queens numbers: a range there still uses its first number.
    assert search_address({**row, "county": "Kings", "street_address": "8155-57 Throop Street"}) == \
        "8155 Throop Street, NY 11372"
