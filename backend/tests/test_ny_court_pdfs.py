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


def test_three_word_queens_neighborhoods_are_towns():
    assert split_address("133-44 122nd Street, South Ozone Park, New York 11420", None) == \
        ("133-44 122nd Street", "South Ozone Park", "11420")


def test_kings_notice_wordings_new_in_october_2026():
    from pipeline.parse_ny_court_pdfs import parse_notice_of_sale
    ordinal = ("REFEREE'S NOTICE OF SALE IN FORECLOSURE SUPREME COURT - COUNTY OF KINGS Pursuant to a Judgment, I, the "
               "undersigned Referee will sell at public auction in room 224, 360 Adams Street, Brooklyn, NY 11201 on the "
               "22nd day of October, 2026 at 2:30 PM. Premises known as 32 Example Avenue, Brooklyn, (City of New York) "
               "NY 11236. Index No. 504913/2020. Jane Example, Esq., Referee.")
    record, problems = parse_notice_of_sale(ordinal, "Kings")
    assert not problems and record["sale_date"] == "2026-10-22"
    assert (record["street"], record["zip_code"]) == ("32 Example Avenue", "11236")
    run_together = ("NOTICE OF SALE SUPREME COURT COUNTY OF KINGS. I, the undersigned Referee will sell at public auction "
                    "at Room 224, 360 Adams Street, Brooklyn, New York 112010n October 22, 2026 at 2:30 PM, premises known "
                    "as 1646 46TH STREET, BROOKLYN, NY 11204. Index # 509221/2025. JOHN EXAMPLE, Esq., Referee")
    record, problems = parse_notice_of_sale(run_together, "Kings")
    assert not problems and record["sale_date"] == "2026-10-22" and record["street"] == "1646 46th Street"
    heading = ("SUPREME COURT OF THE STATE OF NEW YORK COUNTY OF KINGS Index No. 507482/2025 NOTICE OF SALE Premises: "
               "216 Example Ave Brooklyn, New York 11238 Block 1965, Lot 39 PLEASE TAKE NOTICE THAT I will sell at public "
               "auction at the Kings County Courthouse, Room 224, on October 22, 2026 at 2:30 p.m., prem. k/a 216 Exampl "
               "Ave, Brooklyn. Approx. amt of judgment is $1,005,399.80, plus costs. Jane Example, Esq., Referee")
    record, problems = parse_notice_of_sale(heading, "Kings")
    assert not problems and (record["street"], record["zip_code"]) == ("216 Example Ave", "11238")
    assert record["judgment"] == 1005399.80
    designated = ordinal.replace("Premises known as 32 Example Avenue", "the liened premises designated as Block 1437, "
                                 "Lot 38 in the City of New York, and known as 32 Example Avenue")
    assert parse_notice_of_sale(designated, "Kings")[0]["street"] == "32 Example Avenue"
    several = heading.replace("prem. k/a", "the following properties in three separate sales: (1) prem. k/a")
    assert "several_properties" in parse_notice_of_sale(several, "Kings")[1]


def test_a_text_layer_without_spaces_is_spotted():
    from pipeline.load_ny_court_pdfs import spaceless
    assert spaceless("SUPREMECOURTOFTHESTATEOFNEWYORK" * 20)
    assert not spaceless("SUPREME COURT OF THE STATE OF NEW YORK " * 20)


def test_nassau_notice_wording():
    from pipeline.parse_ny_court_pdfs import parse_notice_of_sale
    text = ("SUPREME COURT - COUNTY OF NASSAU INDEX NO. 609669/2024. Pursuant to judgment of foreclosure and sale"
            " entered April 6, 2026, I will sell at public auction at the Nassau County Supreme Court, 100 Supreme"
            " Court Drive, Mineola, NY on Thursday, June 22, 2026 at 2:30 p.m., prem. k/a 616 Liberty Avenue,"
            " Williston Park, NY 11596 a/k/a Section 9, Block 144, Lot 54. Jane Roe, Esq., Referee.")
    record, problems = parse_notice_of_sale(text, "Nassau")
    assert problems == []
    assert record["sale_date"] == "2026-06-22"
    assert (record["street"], record["city"], record["zip_code"]) == ("616 Liberty Avenue", "Williston Park", "11596")


def test_summons_names_the_mortgaged_premises_only():
    from pipeline.parse_ny_court_pdfs import summons_premises
    text = ("SUMMONS Index No. Mortgaged Premises: 20 PARSONS DRIVE HEMPSTEAD, NY 11550 TO THE ABOVE NAMED"
            " DEFENDANT(S): YOU ARE HEREBY SUMMONED")
    assert summons_premises(text) == ("20 Parsons Drive", "Hempstead", "11550")


def test_summons_premises_skips_caption_words():
    from pipeline.parse_ny_court_pdfs import summons_premises
    text = "Mortgaged Premises: 2595 Merrick Avenue Plaintiff Merrick, New York 11566 -against- Section: 63"
    assert summons_premises(text) == ("2595 Merrick Avenue", "Merrick", "11566")


def test_summons_premises_in_other_wordings():
    from pipeline.parse_ny_court_pdfs import summons_premises
    assert summons_premises("SUMMONS Plaintiff, Premises Address: -against- 117 Martens Avenue Valley Stream, NY11580"
                            " DONOVAN") == ("117 Martens Avenue", "Valley Stream", "11580")
    assert summons_premises("place of trial Premises: 50 Clinton Street, Hempstead, New York Venue is based upon"
                            ) == ("50 Clinton Street", "Hempstead", None)
    assert summons_premises("Lot(s) 364-365 Upon information and belief, said premises are also known as and by street"
                            " number: 1765 Carroll Avenue, Merrick, NY 11566. FILED") == ("1765 Carroll Avenue", "Merrick", "11566")
    assert summons_premises("Lot(s)231 Uponinformationandbelief,saidpremisesarealsoknownasandbystreetnumber:5 AlbertCourt,"
                            "ValleyStream,NY11580. FILED") == ("5 Albert Court", "Valley Stream", "11580")


def test_nassau_addresses_split_into_street_town_and_zip():
    from pipeline.parse_ny_court_pdfs import split_address
    assert split_address("846 Bradley Street, West Hempstead, (Town of Hempstead) NY 11552", None) == (
        "846 Bradley Street", "West Hempstead", "11552")
    assert split_address("267 CREST AVE , FLORAL PARK , NY 11001", None) == ("267 Crest Ave", "Floral Park", "11001")
    assert split_address("342 LATTINGTOWN ROAD, LOCUST V ALLEY , NY 11560", None) == (
        "342 Lattingtown Road", "Locust Valley", "11560")
    assert split_address("11 Fruitledge Road, Glen Head", None) == ("11 Fruitledge Road", "Glen Head", None)
    assert split_address("11 Fruitledge Road, Glen Head A/K/A Brookville, NY11545", None) == (
        "11 Fruitledge Road", "Glen Head", "11545")
    assert split_address("230 West Pine Street, Long Beach, (City of Long Beach) NY 11561", None) == (
        "230 West Pine Street", "Long Beach", "11561")


def test_a_run_together_nassau_caption_is_recognised():
    from pipeline.load_ny_court_pdfs import county_of
    assert county_of("NOTICEOFSALE SUPREMECOURT.NASSAUCOUNTY.FNADZ,LLC,PItf.vs.SMYDZCORP.") == "Nassau"


def test_calendar_records_need_a_summons_address_and_no_notice():
    from pipeline.load_ny_court_pdfs import calendar_records
    summons = {"file": "618077-2024 Summons.pdf", "sha256": "ab", "method": "embedded_text",
               "text": "SUPREME COURT OF THE STATE OF NEW YORK COUNTY OF NASSAU SUMMONS Mortgaged Premises: "
                       "20 PARSONS DRIVE HEMPSTEAD, NY 11550 TO THE ABOVE NAMED DEFENDANT(S)"}
    history = {"county": "Nassau", "index_number": "618077/2024",
               "auctions": [{"date": "2026-12-04", "time": "02:00 PM", "outcome": None},
                            {"date": "2026-06-01", "time": "02:00 PM", "outcome": "Not Held"}]}
    [record] = calendar_records([summons], [], [history], date(2026, 10, 17))
    assert (record["street"], record["city"], record["sale_date"]) == ("20 Parsons Drive", "Hempstead", "2026-12-04")
    assert "No Notice of Sale" in details(record)
    noticed = [{"county": "Nassau", "index_number": "618077/2024"}]
    assert calendar_records([summons], noticed, [history], date(2026, 10, 17)) == []
