from pipeline.import_illinois_will_parcels import parcel_id, parsed


def test_will_pin_and_geometry_mapping() -> None:
    assert parcel_id("04-10-171-070-0100") == "IL:WILL:04101710700100"
    row=parsed("IL:WILL:04101710700100",8712.5,-88.1,41.5)
    assert row[5:9] == (-88.1,41.5,8712.5,"square feet")
