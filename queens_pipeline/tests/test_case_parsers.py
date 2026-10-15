"""Case-file parsers, on text taken from the saved Queens filings (Oct 2026)."""
import os
from pathlib import Path

import pytest

from case_parsers import (Document, _split_justice_part, block_lot, classify, index_from_file_name,
                          parse_appearances, parse_case_detail, parse_notice_of_sale, parse_summons,
                          split_address, split_documents)

STAMP = "FILED: QUEENS COUNTY CLERK 09/16/2026 10:19 AM INDEX NO. 713725/2021\nNYSCEF DOC. NO. {n} RECEIVED NYSCEF: 09/16/2026\n"


def test_file_names_map_to_index_numbers():
    assert index_from_file_name("713725-2021 Notice_of_sales.pdf") == "713725/2021"
    assert index_from_file_name(" 705527- 2014  Notice_of_sales.pdf") == "705527/2014"
    assert index_from_file_name("710760:2021 Summons.pdf") == "710760/2021"
    assert index_from_file_name("713725-2021_2.pdf") == "713725/2021"
    assert index_from_file_name("5393-2008 appearances.pdf") == "5393/2008"
    assert index_from_file_name("CourtCalendar.pdf") is None
    assert index_from_file_name("1312 MYRTLE AVENUE.pdf") is None


def test_documents_are_split_by_stamp_and_classified_by_title():
    pages = [STAMP.format(n=1) + "SUMMONS ... VERIFIED COMPLAINT ... judgment of foreclosure and sale",
             STAMP.format(n=1) + "page two of the complaint",
             STAMP.format(n=133) + "NOTICE OF SALE ... I, the undersigned Referee will sell at public auction",
             "10/14/26, 2:38 PM WebCivil Supreme - Appearance Detail\nWebCivil Supreme - Appearance Detail"]
    documents = split_documents(pages)
    assert [(d.section, d.doc_number, d.pages) for d in documents] == [
        ("summons_complaint", 1, [0, 1]), ("notice_of_sale", 133, [2]), ("appearances", None, [3])]
    assert documents[0].filed_date == "2026-09-16"
    assert classify("JUDGMENT OF FORECLOSURE AND SALE ... the summons and complaint were served") == "judgment_of_foreclosure"
    assert classify("SUMMONSANDNOTICE U.S.BankNationalAssociation") == "summons_complaint"
    assert classify("MEMORANDUM SUPREME COURT - QUEENS COUNTY") == "other"


def test_addresses_survive_ocr_and_layout_noise():
    assert split_address("93-08 76THSTREET, WOODHAVENN,Y 11421; and the following", "Queens") == {
        "property_address": "93-08 76th Street", "city": "Woodhaven", "zip": "11421"}
    assert split_address("119- 04 l44th St, Jamaica, New York 11436, and desuibed", "Queens")["property_address"] == "119-04 144th St"
    assert split_address("78 12 31ST AVENUE,EAST ELMHURST, NY 11370;", "Queens")["property_address"] == "78-12 31st Avenue"
    assert split_address("11116 167th Street, Jamaica, NY11433. Block", "Queens")["zip"] == "11433"
    assert split_address("140-22 Beech Avenue, Unit 5A, Flushing, NY 11355", "Queens")["property_address"] == "140-22 Beech Avenue, Unit 5A"
    assert split_address("192-17 Jamaica Avenue a/k/a 192-19 Jamaica Ave, Jamaica a/k/a Hollis, NY 11423.", "Queens") == {
        "property_address": "192-17 Jamaica Avenue", "city": "Jamaica", "zip": "11423"}
    assert split_address("119-19 198th Street Plaintiff, Saint Albans, NY 11412", "Queens")["property_address"] == "119-19 198th Street"


def test_block_and_lot_in_every_wording():
    assert block_lot("City and State of New York. Block ll742Lot 64 The approximate", "Queens") == "4-11742-64"
    assert block_lot("and the following tax map identification: 10334-5. ALL THAT", "Queens") == "4-10334-5"
    assert block_lot("The tax map designation is Block 12073 Lots 429 and 430.", "Queens") == "4-12073-429/430"
    assert block_lot("New York, BLOCK: 10448, LOT: 16. Approximate", "Queens") == "4-10448-16"


def test_notice_of_sale_fields():
    text = ("NOTICE OF SALE SUPREME COURT COUNTY OF QUEENS ... I, the undersigned Referee will sell at public auction "
            "in Courtroom 25 on October 16, 2026 at 10:00 AM, premises known as 37-46 79th Street, Jackson Heights, "
            "NY 11372. Block 1289 Lot 29. Approximate amount of judgment $961,285.38. "
            "Index Number 713725/2021. MARTHA TAYLOR, ESQ., Referee DRUCKMAN LAW GROUP PLLC")
    assert parse_notice_of_sale(text, "Queens") == {
        "property_address": "37-46 79th Street", "city": "Jackson Heights", "zip": "11372",
        "borough_block_lot": "4-1289-29", "referee_name": "Martha Taylor", "notice_auction_date": "2026-10-16",
        "approximate_judgment": 961285.38}
    lien = parse_notice_of_sale("premises known as 3321 102ND STREET, CORONA, NY 11368 Approximate amount of lien "
                                "$866,961.45 plus interest. JJais A. Forde, Esq. - Referee.", "Queens")
    assert (lien["property_address"], lien["approximate_lien_amount"], lien["referee_name"]) == (
        "33-21 102nd Street", 866961.45, "Jais A. Forde")
    assert "approximate_judgment" not in lien
    assert parse_notice_of_sale("The approximate amount of the cunent Judgment lien is $1,091,830.08 plus interest. "
                                "NedaM. Melamed, Esq. -Referee", "Queens") == {
        "approximate_judgment": 1091830.08, "referee_name": "Neda M. Melamed"}
    assert parse_notice_of_sale("Judgment Index No.: 721003/2022. & Gerald Chiariello, II, Esq. - Referee. Robertson",
                                "Queens")["referee_name"] == "Gerald Chiariello, II"


def summons(text: str) -> dict:
    return parse_summons(Document(section="summons_complaint", pages=[0], text=text, doc_number=1), "Queens")


def test_summons_principal_lender_and_address():
    assert summons("ENTIRE PRINCIPAL BALANCE: $271,397.12 INTEREST THEREON FROM")["unpaid_principal"] == 271397.12
    assert summons("there is now due and owing to the plaintiff, the principal sum of $439, 196.59 with interest"
                   )["unpaid_principal"] == 439196.59
    assert summons("there is now justly due and payable. to the Plaintiff by virtue of such acceleration, the principal "
                   "sum of $197,924.37 plus interest")["unpaid_principal"] == 197924.37
    # The original note amount is not the unpaid principal.
    assert "unpaid_principal" not in summons("promised to pay the sum of $622,500.00 plus interest")
    assert summons("CARLOS ZHAGNAY duly executed and delivered to COUNTRYWIDE HOME LOANS, INC. a Note whereby"
                   )["original_mortgagee"] == "COUNTRYWIDE HOME LOANS, INC."
    assert summons('CRAIG SAMUELS, (hereinafter "SAMUELS") duly executed and delivered Long Beach Mortgage Company, '
                   "a note bearing")["original_mortgagee"] == "Long Beach Mortgage Company"
    assert "original_mortgagee" not in summons("duly executed, acknowledged, and delivered to Plaintiff s assignor a Note")
    found = summons("Mortgage Premises: 119-19 198th Street Plaintiff, Saint Albans, NY 11412 County: Queens")
    assert (found["property_address"], found["zip"]) == ("119-19 198th Street", "11412")


def test_justice_and_part_share_one_column():
    assert _split_justice_part(["Mayersohn, Hon.", "Lee A.", "PART 22 MOTIONS"]) == ("Mayersohn, Hon. Lee A.", "PART 22 MOTIONS")
    assert _split_justice_part(["Cohanim", "Lancman, Hon.", "Mojgan", "PART 20 MOTIONS"]) == (
        "Cohanim Lancman, Hon. Mojgan", "PART 20 MOTIONS")
    assert _split_justice_part(["Kerrigan, Hon.", "Kevin", "Centralized", "Motion Part"]) == (
        "Kerrigan, Hon. Kevin", "Centralized Motion Part")
    assert _split_justice_part(["(Master Foreclosure", "Part), MFJ", "FORECLOSURE", "AUCTION PART"]) == (
        "(Master Foreclosure Part), MFJ", "FORECLOSURE AUCTION PART")
    assert _split_justice_part(["FORECLOSURE", "CONFERENCE PART"]) == (None, "FORECLOSURE CONFERENCE PART")


def test_case_detail():
    text = ("WebCivil Supreme - Case Detail\nIndex Number: 713725/2021\nCMS Index Number: 0017567/2009\n"
            "Case Name: US BANK NATIONAL ASSOCIATION vs. TELLO, JONNI R. ETAL\nDisposition Date: 10/04/2024\n"
            "Justice Name: Fern, Hon. Ilene\nNOI Filed:\n")
    assert parse_case_detail(text) == {"index_number": "713725/2021", "cms_index": "0017567/2009",
                                       "justice": "Fern, Hon. Ilene", "case_status": "Disposed 10/04/2024",
                                       "caption": "US BANK NATIONAL ASSOCIATION vs. TELLO, JONNI R. ETAL"}


CASES_DIR = os.environ.get("QUEENS_CASES_DIR")


@pytest.mark.skipif(not CASES_DIR, reason="set QUEENS_CASES_DIR to the folder of saved case files")
def test_appearance_table_of_713725():
    import pdfplumber
    path = next(p for p in Path(CASES_DIR).iterdir()
                if index_from_file_name(p.name) == "713725/2021" and "appearance" in p.name.lower())
    with pdfplumber.open(path) as pdf:
        rows = parse_appearances(pdf.pages)
    assert len(rows) == 35
    sold = next(row for row in rows if row["appearance_date"] == "2024-04-12")
    assert (sold["purpose"], sold["outcome"], sold["court_date_type"]) == (
        "Auction-Foreclosed Property", "Sold", "Administrative - No Appearance Required")
    motion = next(row for row in rows if row["appearance_date"] == "2025-04-02")
    assert (motion["outcome"], motion["justice"], motion["part"]) == (
        "Fully Submitted - No Opposition", "Mayersohn, Hon. Lee A.", "PART 22 MOTIONS")
