from collections import defaultdict

from pipeline.match_hcad_legal import hcad_key, match, notice_key, similar_names


def parcel(acct, address, lgl_1, lgl_2, city="HOUSTON", zip_code="77041"):
    return {"acct": acct, "site_addr_1": address, "site_addr_2": city, "site_addr_3": zip_code, "state_class": "A1",
            "lgl_1": lgl_1, "lgl_2": lgl_2, "lgl_3": "", "lgl_4": "", "tot_mkt_val": "250000"}


def index_of(*rows):
    index = defaultdict(list)
    for row in rows:
        index[hcad_key(row)].append(row)
    return index


def test_notice_key_reads_lot_block_subdivision_and_section():
    assert notice_key("LOT ONE (1), IN BLOCK THREE (3), OF STONE CREEK RANCH SEC. 2, A SUBDIVISION IN HARRIS COUNTY, TEXAS") == {
        "lot": "1", "block": "3", "name": "STONE CRK RNCH", "section": "2"}
    assert notice_key('LOT TWENTY-THREE (23), BLOCK "E", OF JERSEY ACRES ADDITION, AN ADDITION IN HARRIS COUNTY')["block"] == "E"
    assert notice_key("COUNTRY LAKE ESTATES SEC. I") is None
    assert notice_key("UNIT 12, BUILDING C, OF WILLOW CONDOMINIUM, LOT 1 BLOCK 1 OF X") is None


def test_names_allow_ocr_slips_but_not_different_words():
    assert similar_names("LAKEWOOD XING", "LAKEWOOI XING")
    assert not similar_names("LINDALE PK", "LINDALE PL")
    assert not similar_names("WILLOWBROOK", "WILLOWOOD")


def test_match_needs_exactly_one_parcel():
    notice = {"legal_description": "LOT 174, BLOCK G, OF CARVERDALE, SECTION TWO (2), A SUBDIVISION IN HARRIS COUNTY, TEXAS"}
    found = match(notice, index_of(parcel("0803150000174", "10012 TANGIERS RD", "LT 174 BLK G", "CARVERDALE SEC 2"),
                                   parcel("0803150000999", "1 OTHER RD", "LT 174 BLK G", "CARVERDALE SEC 3")))
    assert found["street"] == "10012 Tangiers Rd" and found["hcad_account"] == "0803150000174"
    assert found["zip_code"] == "77041" and found["address_source"] == "hcad_legal_description"
    # Two sections fit a notice that names none: no match rather than a guess.
    unsectioned = {"legal_description": "LOT 174, BLOCK G, OF CARVERDALE, A SUBDIVISION IN HARRIS COUNTY, TEXAS"}
    assert match(unsectioned, index_of(parcel("1", "1 A ST", "LT 174 BLK G", "CARVERDALE SEC 2"),
                                       parcel("2", "2 B ST", "LT 174 BLK G", "CARVERDALE SEC 3"))) is None
