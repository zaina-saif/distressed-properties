from pipeline.load_nj_parcels import find_modiv_file, resolve_county


def test_resolve_county_by_name_or_code():
    assert resolve_county("Monmouth") == ("13", "Monmouth")
    assert resolve_county("4") == ("04", "Camden")
    assert resolve_county("Cape May") == ("05", "Cape May")


def test_find_modiv_file_handles_county_filename_variants():
    assert find_modiv_file("Monmouth", 2024).name == "Monmouth 24re.txt"
    assert find_modiv_file("Cape May", 2025).name == "Cape MayRE.txt"
    assert find_modiv_file("Camden", 2026).name == "Camden 26 RE.txt"
