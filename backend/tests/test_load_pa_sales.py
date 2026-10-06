from pipeline.load_pa_sales import portal_address


def test_portal_address_lines():
    lines = ["95 Greenwood Circle", "Wormleysburg - Borough", "Wormleysburg, PA 17043", "Wormleysburg Borough"]
    assert portal_address(lines) == ("95 Greenwood Circle", "Wormleysburg", "17043", "Wormleysburg Borough")


def test_portal_address_without_zip_or_municipality():
    assert portal_address(["12 Main St", "Waynesboro, PA"]) == ("12 Main St", "Waynesboro", None, None)


def test_portal_address_missing():
    assert portal_address(None) is None
    assert portal_address(["12 Main St"]) is None


def test_parcel_line_is_not_the_municipality():
    lines = ["648 YOHE AVE", "COLUMBIA, PA 17512", "UPI#: 110-86678-0-0000"]
    assert portal_address(lines) == ("648 YOHE AVE", "COLUMBIA", "17512", None)
