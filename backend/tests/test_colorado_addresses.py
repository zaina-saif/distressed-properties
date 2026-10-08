from pipeline.colorado_addresses import choose, street_key


def test_street_key_skips_directions_and_half_numbers():
    assert street_key("4328 Yellow Dock Point") == ("4328", "YELLOW")
    assert street_key("1261 W 71st Pl") == ("1261", "71ST")
    assert street_key("2703 1/2 RINCON DR") == ("2703", "RINCON")
    assert street_key("LOT 5 PINE ACRES") is None


def _feature(city, zip_code):
    return {"attributes": {"PlaceName": city, "Zipcode": zip_code}}


def test_only_an_unambiguous_match_is_used():
    assert choose([_feature("COLORADO SPRINGS", "80911")]) == ("Colorado Springs", "80911")
    assert choose([_feature("COLORADO SPRINGS", "80911"), _feature("COLORADO SPRINGS", "80911-1234")]) == (
        "Colorado Springs", "80911")
    assert choose([_feature("FRUITA", "81521"), _feature("GRAND JUNCTION", "81504")]) is None
    assert choose([_feature(None, None)]) is None
    assert choose([]) is None
