from datetime import date

from pipeline.load_ny_court_pdfs import (
    bbl, calendar_note, county_of, details, parse_appearances, parse_documents, to_sales,
)
from pipeline.parse_ny_court_pdfs import (
    kind, parse_auction_part_list, parse_calendar_summary, parse_notice_of_sale, parse_webcivil_appearances, split_address,
)

# Text as OCR returns it from saved court PDFs (party names shortened).
MYRTLE = """FILED: KINGS COUNTY CLERK 08/31/2026 10:58 AM
INDEX NO. 522549/2023
NOTICE OF SALE
SUPREME COURT COUNTY OF KINGS, WILMINGTON SAVINGS FUND SOCIETY, FSB, Plaintiff, vs. JOHN DOE, ET AL.,
Defendant(s).
Pursuant to a Judgment of Foreclosure and Sale duly entered on November 1, 2024, I, the undersigned
Referee will sell at public auction at the Kings County Supreme Court, Courtroom 224, 360 Adams
Street, Brooklyn, NY 11201 on October 15, 2026 at 2:30 p.m., premises known as 1312 Myrtle Avenue,
Brooklyn, NY 11221. All that certain plot, Block 3255 and Lot 19. Approximate amount of judgment is $1,002,448.69 plus interest and
costs. Premises will be sold subject to provisions of filed Judgment Index #522549/2023.
Jeffrey H. Schwartz, Esq., Referee
Friedman Vartolo LLP, 85 Broad Street, Suite 501, New York, New York 10004, Attorneys for Plaintiff.
"""

# OCR clipped the page edge: "publi / uction", "tober", "35T1 / TREET".
CLIPPED = """FILED: KINGS COUNTY CLERK 08/25/2026 12:04 PM
INDEX NO. 20280/2010
COUNTY OF KINGS
WELLS FARGO BANK NA. AS TRUSTEE
-against-
JANE DOE, ET AL.
NOTICE OF SALE
NOTICE IS HEREBY GIVEN pursuant to a Final Judgment of Foreclosure entered in the Office of the Clerk of the
County of Kings on June 16, 2026, wherein WELLS FARGO BANK N.A. is the Plaintiff and JANE DOE are the
Defendant(s). I, the undersigned Referee, will sell at publi
uction at the KINGS COUNTY COURTHOUSE, 360 ADAMS STREET, ROOM 22
BROOKLYN, NY 11201, on
tober 15, 2026 at 2:30PM, premises known as 152 E 35T1
TREET, BROOKLYN, NY 11203; and the following tax map identification: 15-4871-21
Scott H. Siller, Esq. - Referee. Robertson, Anschutz, Schneid, Crane & Partners, PLLC, 900
"""

POSTPONED = """KINGS COUNTY CLERK
INDEX NO. 538056/2022
NOTICE OF LEGAL POSTPONEMENT OF SALE
SUPREME COURT COUNTY OF KINGS, WILMINGTON TRUST, Plaintiff, vs. ECD CAPITAL LLC, ET AL., Defendant(s).
Pursuant to a Judgment of Foreclosure and Sale entered on December 16, 2024, I, the undersigned
Referee will sell at public auction at the Kings County Supreme Court on October 15, 2026 at 2:30 p.m.,
premises known as 544 Schenck Avenue, Brooklyn, NY 11207. Block 4075 and Lot 20. Approximate amount of
judgment is $826,594.60 plus interest and costs. The original sale was scheduled for September 17, 2026.
Stephen A. Spinelli, Esq., Referee
"""

BRONX = """Calendar Summary Report
County: Bronx (Supreme) Calendar Date: 9/21/2026
215PM
CITIMORTGAGE, INC. (1 For Party)
Vs.
PARRIS,NIGEL (1 Against Party)
Index #: 380926/2010E
Purpose: Auction - Foreclosed Property
Calendar Remarks: Premises: 3651 Holland Avenue, Bronx, NY 10467
Block: 4662; Lot: 13
Referee: RICARDO E. OQUENDO, ESQ. (212) 209-7147
Calendar Summary Report
County: Bronx (Supreme) Calendar Date: 10/19/2026
U.S.BANK NATIONAL ASSOC. (1 For Party)
Vs.
Index #: 7278/2007E
Calendar Remarks: Premises: 621 EAST 237 STREET, BRONX, NY 10466
Block: 5040; Lot: 11
Referee: Louis Russo, Esq 718-555-0100
U.S. BANK (1 For Party)
Index #: 380020/2011E
Calendar Remarks:
Referee: Someone, Esq
"""

MANHATTAN = """NEW YORK STATE SUPREME COURT
FORECLOSURE AUCTION PART
Tuesday October 13, 2026
850020/2024 - WILMINGTON TRUST, NATIONAL ASSOCIATION vs. NYACK 2 WASHINGTON LLC et al
 Time: 14:15
---------------------------------------------------------------
850159/2024 - JPMorgan Chase Bank vs. Schwartz, Kenneth L. et al
 Court Date Purpose: / Outcome: Not Held
---------------------------------------------------------------
"""


def test_notice_of_sale_fields():
    record, problems = parse_notice_of_sale(MYRTLE, "Kings", "1312 MYRTLE AVENUE")

    assert problems == []
    assert record["index_number"] == "522549/2023"
    assert record["sale_date"] == "2026-10-15" and record["sale_time"] == "2:30 p.m."
    assert (record["street"], record["city"], record["zip_code"]) == ("1312 Myrtle Avenue", "Brooklyn", "11221")
    assert (record["block"], record["lot"]) == ("3255", "19")
    assert record["judgment"] == 1002448.69
    assert record["referee"] == "Jeffrey H. Schwartz"
    assert record["plaintiff_attorney"] == "Friedman Vartolo LLP"


def test_clipped_ocr_uses_the_court_file_name_and_completes_the_month():
    record, problems = parse_notice_of_sale(CLIPPED, "Kings", "152 E 35 STREET")

    assert problems == []
    assert record["sale_date"] == "2026-10-15"
    assert record["street"] == "152 E 35 Street" and record["address_source"] == "court_file_name"
    assert record["zip_code"] == "11203"
    assert record["referee"] == "Scott H. Siller"
    assert record["plaintiff"] == "WELLS FARGO BANK N.A."
    assert record["judgment"] is None  # This notice states no amount; nothing is invented.


def test_postponed_notice_keeps_the_earlier_date():
    record, problems = parse_notice_of_sale(POSTPONED, "Kings", "544 SCHENCK AVENUE")

    assert problems == [] and kind(POSTPONED) == "notice_of_sale"
    assert record["postponed_from"] == "2026-09-17"
    sales = to_sales([{**record, "county": "Kings"}], date(2026, 10, 11))["Kings"]
    assert [(s.sale_date.isoformat(), s.status) for s in sales] == [
        ("2026-09-17", "adjourned"), ("2026-10-15", "scheduled")]


def test_approximate_lien_amount_is_not_reported_as_judgment():
    text = MYRTLE.replace("Approximate amount of judgment is $1,002,448.69",
                          "Approximate amount of lien $961,285.38")
    record, problems = parse_notice_of_sale(text, "Kings", "1312 MYRTLE AVENUE")

    assert problems == []
    assert record["judgment"] is None
    assert record["approximate_lien_amount"] == 961285.38


def test_bronx_calendar_cases_dates_and_failures():
    rows = parse_calendar_summary(BRONX, "Bronx")

    first, second, broken = rows
    assert first[0]["index_number"] == "380926/2010" and first[0]["sale_date"] == "2026-09-21"
    assert first[0]["street"] == "3651 Holland Avenue" and first[0]["zip_code"] == "10467"
    assert first[0]["referee"] == "RICARDO E. OQUENDO" and first[1] == []
    assert second[0]["sale_date"] == "2026-10-19" and second[0]["street"] == "621 East 237 Street"
    assert broken[1] == ["premises_address_missing"]


def test_manhattan_list_is_reported_not_loaded():
    rows = parse_auction_part_list(MANHATTAN, "New York")

    assert [r["index_number"] for r, _ in rows] == ["850020/2024", "850159/2024"]
    assert rows[1][0]["outcome"] == "Not Held"
    assert all(problems == ["premises_address_not_published"] for _, problems in rows)


def test_documents_split_into_records_failures_and_reported():
    documents = [{"file": name, "sha256": name, "method": "test", "file_address": address, "text": body}
                 for name, address, body in (("a.pdf", "1312 MYRTLE AVENUE", MYRTLE), ("b.pdf", "bronx", BRONX),
                                             ("c.pdf", "list", MANHATTAN), ("d.pdf", "x", "unrelated text"))]
    records, failures, reported = parse_documents(documents)

    assert [r["index_number"] for r in records] == ["522549/2023", "380926/2010", "7278/2007"]
    assert {tuple(f["problems"]) for f in failures} == {("premises_address_missing",), ("county_not_recognised",)}
    assert len(reported) == 2


def test_past_auction_dates_are_not_shown_as_scheduled():
    record, _ = parse_calendar_summary(BRONX, "Bronx")[0]
    sale = to_sales([record], date(2026, 10, 11))["Bronx"][0]

    assert sale.status == "sold_or_cancelled_unverified"
    assert sale.case == "380926/2010" and sale.property_number == "2-04662-0013"


def test_helpers():
    assert county_of(MYRTLE) == "Kings" and county_of(BRONX) == "Bronx" and county_of(MANHATTAN) == "New York"
    assert split_address("2065 Tumbul Avenue, Bronx, N. . 10473", "Bronx") == ("2065 Tumbul Avenue", "Bronx", "10473")
    assert split_address("1328 Chisholm Street, Bronx, New York 10459", "Bronx") == ("1328 Chisholm Street", "Bronx", "10459")
    assert split_address("69 Conklin Avenue, Brooklyn, NY", "Brooklyn") == ("69 Conklin Avenue", "Brooklyn", None)
    assert bbl("Kings", "3255", "19") == "3-03255-0019" and bbl("Kings", None, "19") is None
    text = details({"sale_date": "2026-10-15", "sale_time": "2:30 p.m.", "index_number": "522549/2023",
                    "judgment": 1002448.69, "referee": "Jeffrey H. Schwartz"})
    assert "Referee: Jeffrey H. Schwartz." in text and "$1,002,448.69" in text and "522549/2023" in text


def test_street_corrections_survive_reparsing():
    text = BRONX.replace("Index #: 380926/2010E", "Index #: 804535/2024E")
    records, _, _ = parse_documents([{"file": "b.pdf", "sha256": "b", "method": "test", "file_address": "b", "text": text}])

    assert records[0]["street"] == "2065 Turnbull Avenue" and records[0]["address_source"] == "manual_correction"


# A WebCivil Appearance Detail page printed to PDF (rows shortened), across a page break.
APPEARANCES = """WebCivil Supreme - Appearance Detail
Court: Queens Supreme Court
Index Number:  713725/2021
Case Name:US BANK NATIONAL ASSOCIATION vs. TELLO, JONNI R. ETAL
Case Type: RP-Mortgage Foreclosure-Residential
Appearance Information:
10/16/2026 10:00 AM Auction-
Foreclosed
Property
No Courtroom  (Master Foreclosure
Part), MFJ
FORECLOSURE
AUCTION PART
07/17/2026 10:00 AM Auction-
Foreclosed
Property
No Courtroom Not Held (Master Foreclosure
Part), MFJ
FORECLOSURE
AUCTION PART
04/02/2025  Motion-Notice of
Motion
No Courtroom Fully Submitted -
No Opposition
PART 22 MOTIONS
 9
11/15/2024 11:00 AM Auction-
Foreclosed
Property
No Administrative - No
Appearance
Required
Not Held (Master Foreclosure
Part), MFJ
10/14/26, 10:53 AM WebCivil Supreme - Appearance Detail
https://iapps.courts.state.ny.us/webcivil/FCASCaseInfo?parm=Appearance 1/2
STATUS
04/12/2024 10:45 AM Auction-
Foreclosed
Property
No Administrative - No
Appearance
Required
Sold (Master Foreclosure
Part), MFJ
07/28/2021 03:15 PM Conference-
Status
No None Held Gordon, Daniel S.
"""


def test_webcivil_appearances_keep_auctions_and_outcomes():
    record, problems = parse_webcivil_appearances(APPEARANCES)

    assert kind(APPEARANCES) == "webcivil_appearances" and problems == []
    assert record["county"] == "Queens" and record["index_number"] == "713725/2021"
    assert [(a["date"], a["outcome"]) for a in record["auctions"]] == [
        ("2026-10-16", None), ("2026-07-17", "Not Held"), ("2024-11-15", "Not Held"), ("2024-04-12", "Sold")]


def test_webcivil_pages_are_histories_not_listings():
    case_detail = "WebCivil Supreme - Case Detail\nCourt: Queens Supreme Court\nIndex Number: 713725/2021"
    documents = [{"file": name, "sha256": name, "method": "test", "file_address": name, "text": body}
                 for name, body in (("a.pdf", APPEARANCES), ("b.pdf", case_detail))]
    records, failures, reported = parse_documents(documents)
    histories, history_failures = parse_appearances(documents)

    assert records == failures == reported == history_failures == []
    assert [h["index_number"] for h in histories] == ["713725/2021"]


def test_calendar_note_lists_past_auctions_only():
    record, _ = parse_webcivil_appearances(APPEARANCES)
    note = calendar_note(record["auctions"], date(2026, 10, 14))

    assert note == ("Court calendar (WebCivil): 2 earlier auction dates not held (2024-11-15, 2026-07-17); "
                    "the 2024-04-12 auction is recorded as sold, and the case was put back on the auction "
                    "calendar afterwards.")
    assert calendar_note(record["auctions"][:1], date(2026, 10, 14)) is None
