from pipeline import load_nj_parcels


def test_resolve_county_by_name_or_code():
    assert load_nj_parcels.resolve_county("Monmouth") == ("13", "Monmouth")
    assert load_nj_parcels.resolve_county("4") == ("04", "Camden")
    assert load_nj_parcels.resolve_county("Cape May") == ("05", "Cape May")


def test_find_modiv_file_handles_county_filename_variants(tmp_path, monkeypatch):
    for year, filename in (
        (2024, "Monmouth 24re.txt"),
        (2025, "Cape MayRE.txt"),
        (2026, "Camden 26 RE.txt"),
    ):
        directory = tmp_path / str(year)
        directory.mkdir()
        (directory / filename).touch()
    monkeypatch.setattr(load_nj_parcels, "RAW_MODIV", tmp_path)

    assert load_nj_parcels.find_modiv_file("Monmouth", 2024).name == "Monmouth 24re.txt"
    assert load_nj_parcels.find_modiv_file("Cape May", 2025).name == "Cape MayRE.txt"
    assert load_nj_parcels.find_modiv_file("Camden", 2026).name == "Camden 26 RE.txt"
