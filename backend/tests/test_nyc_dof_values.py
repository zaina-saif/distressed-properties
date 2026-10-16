from pipeline.load_nyc_dof_values import lots


def test_a_listing_on_several_lots_is_valued_on_all_of_them():
    assert lots({"property_number": "4-00809-0042", "map_number": "Block 809 Lots 42 and 43"}) == ("4", "809", ["42", "43"])
    assert lots({"property_number": "4-14005-0087", "map_number": "Block 14005 Lot 87"}) == ("4", "14005", ["87"])
    assert lots({"property_number": "3-07049-0116", "map_number": None}) == ("3", "7049", ["116"])
