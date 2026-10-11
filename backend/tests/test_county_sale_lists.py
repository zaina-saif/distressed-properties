import json
from datetime import date

from pipeline.load_county_sale_lists import bid4assets_sale, ky_sale, tulsa_sale, wi_sale
from pipeline.scrape_county_sale_lists import (
    parse_bid4assets_rows, parse_dane_detail, parse_dane_list, parse_ky_jefferson, parse_tulsa_cases,
    split_detail_address, split_style,
)

TODAY = date(2026, 10, 11)

KY_CSV = '''"CASE","DIV","expr5","ATTORNEY","Expr1","NewDocket","exp4","COUNT","Expr3"
"25ci401309",5,"CITY OF MIDDLETOWN, KENTUCKY vs. JANE DOE, ET AL.","WETTERER & CLARE","10/23/2026","1","1547 West Ormsby Avenue 40210","",""
"25CI400710",11,"SIMS COACHING LLC vs. JOHN DOE","SMITH LAW","11/6/2026","2","12 Main Street 40210","2","WITHDRAWN"
"24CI400677",11,"BANK vs. DOE","X","10/9/2026","3","12026 Ancient Spring Drive 40299","",""
'''

B4A_ROW = {"AuctionID": 1314010, "SaleDate": "2026-10-13T00:00:00", "Address": "1904 N MOULTON CT, OKLAHOMA CITY",
           "CourtCase": "CJ-19-7062", "SheriffNumber": "CJ-19-7062", "MinimumBid": 46667, "Plaintiff": "Deutsche Bank",
           "Defendant": "DOE JOHN", "Attorney": "Kivell Rayment and Francis", "AuctionStatusString": "Stayed",
           "IsStayed": True, "IsPostponed": False, "AttorneyHasSetMinBid": True, "Apn": ""}

DANE_LIST = '''<table id="tblSales"><thead><tr><th>Details</th></tr></thead><tbody>
<tr><td><a href="/Sales/Detail/27144">View Detail</a></td><td>10/13/2026</td><td>26CV389</td>
<td translate="no">1524 LINCOLN AVE<br/>STOUGHTON, WI 53589</td><td>Adjourned</td></tr>
<tr><td><a href="/Sales/Detail/27165">View Detail</a></td><td>10/20/2026</td><td>25CV1263</td>
<td translate="no">4509 TEXAS TRL<br/>CITY OF MADISON, WI 53704</td><td>Cancelled</td></tr>
</tbody></table>'''

DANE_DETAIL = '''<table><tbody><tr><th colspan="2">Sale Details</th></tr>
<tr><td>Sale #</td><td>26_0089</td></tr><tr><td>Plaintiff</td><td>WINTRUST MORTGAGE</td></tr>
<tr><td>Plaintiff's Attorney</td><td>CODILIS MOODY &amp; CIRCELLI PC</td></tr><tr id="trStatus"><td>Status</td><td>Open</td></tr>
<tr><td>Opening Bid</td><td>$197,600.00</td></tr>
<tr><td>Links</td><td><a href="/Sales/GetNotice/27162">Notice of Sheriff Sale</a></td></tr></tbody></table>'''


def test_split_style():
    assert split_style("A BANK vs. JOHN DOE, ET AL.") == ("A BANK", "JOHN DOE, ET AL.")
    assert split_style("NO DEFENDANT") == ("NO DEFENDANT", None)


def test_kentucky_rows_statuses_and_parcel_counts():
    records = parse_ky_jefferson(KY_CSV)
    first, withdrawn, past = (ky_sale(record, TODAY) for record in records)

    assert (first.case, first.street, first.city, first.zip_code) == ("25CI401309", "1547 West Ormsby Avenue", "Louisville", "40210")
    assert first.sale_date == date(2026, 10, 23) and first.status == "scheduled"
    assert first.plaintiff == "CITY OF MIDDLETOWN, KENTUCKY" and first.attorney == "WETTERER & CLARE"
    assert withdrawn.case == "25CI400710-2" and withdrawn.status == "cancelled"
    assert past.status == "sold_or_cancelled_unverified"


def test_oklahoma_bid4assets_row():
    sale = bid4assets_sale(parse_bid4assets_rows([B4A_ROW])[0], TODAY)

    assert (sale.case, sale.street, sale.city) == ("CJ-19-7062", "1904 N MOULTON CT", "Oklahoma City")
    assert sale.upset == 46667 and sale.status == "cancelled" and sale.raw_status == "Stayed"
    preview = bid4assets_sale(parse_bid4assets_rows([{**B4A_ROW, "AuctionStatusString": "Preview", "IsStayed": False}])[0], TODAY)
    assert preview.status == "scheduled"


def test_dane_list_and_detail():
    adjourned, cancelled = parse_dane_list(DANE_LIST)
    assert adjourned["detail_url"] == "https://danesheriff.com/Sales/Detail/27144"
    assert (adjourned["street"], adjourned["city"], adjourned["zip_code"]) == ("1524 LINCOLN AVE", "Stoughton", "53589")
    assert cancelled["city"] == "Madison"

    fields = parse_dane_detail(DANE_DETAIL)
    assert fields["Opening Bid"] == "$197,600.00" and fields["Plaintiff's Attorney"] == "CODILIS MOODY & CIRCELLI PC"
    assert fields["notice_url"] == "https://danesheriff.com/Sales/GetNotice/27162"

    record = {**adjourned, "sale_number": fields["Sale #"], "opening_bid": fields["Opening Bid"], "raw": {"Status": "Open"},
              "plaintiff": fields["Plaintiff"], "defendant": None, "attorney": fields["Plaintiff's Attorney"]}
    sale = wi_sale({**record, "raw": {}}, TODAY)
    assert sale.status == "adjourned" and sale.upset == 197600.0 and sale.property_number == "26_0089"


def test_bid4assets_city_from_detail_and_placeholder_minimum():
    row = {**B4A_ROW, "Address": "4129 - 4131 North Sherman Boulevard", "MinimumBid": 1, "AttorneyHasSetMinBid": False,
           "Apn": "2480806000", "AuctionStatusString": "Preview", "IsStayed": False}
    details = {row["AuctionID"]: "4129 - 4131 North Sherman Boulevard  South Milwaukee, WI 53172"}
    record = parse_bid4assets_rows([row], details)[0]

    assert (record["city"], record["zip_code"], record["parcel"]) == ("South Milwaukee", "53172", "2480806000")
    assert record["minimum_bid"] is None  # the $1 placeholder is not a minimum bid
    assert split_detail_address("1 Main St", "9 Other St Tulsa, OK 74103") == (None, None)


def test_tulsa_keeps_only_public_report_fields():
    cases = [
        {"caseNumber": "cj-2025-1", "variantTag": "", "saleDate": "2026-10-28", "status": "complete", "plaintiff": "BANK",
         "defendant": "DOE", "address": "1 MAIN ST", "city": "TULSA", "zipCode": "74103", "attorney": "LAW FIRM",
         "appraisedValue": "100000", "salePrice": "", "recalled": False, "noSale": False, "noBid": False,
         "buyerName": "PRIVATE", "buyerEmail": "private@example.com", "buyerPhone": "555"},
        {"caseNumber": "CJ-2025-2", "saleDate": "2026-10-07", "status": "complete", "address": "2 MAIN ST", "city": "TULSA",
         "salePrice": "85000", "recalled": False},
        {"caseNumber": "CJ-2025-3", "saleDate": "2026-10-28", "status": "complete", "hideFromReports": True, "address": "3 MAIN ST"},
        {"caseNumber": "CJ-2020-4", "saleDate": "2020-01-01", "status": "complete", "address": "4 MAIN ST"},
        {"caseNumber": "CJ-2025-5", "saleDate": "2026-10-28", "status": "complete", "address": "*RECALLED* 6737 S. PEORIA AVE"},
    ]
    upcoming, sold, noted = parse_tulsa_cases(cases, TODAY)
    assert noted["street"] == "6737 S. PEORIA AVE" and tulsa_sale(noted, TODAY).status == "cancelled"

    assert "buyerName" not in json.dumps(upcoming) and "private@example.com" not in json.dumps(upcoming)
    assert tulsa_sale(upcoming, TODAY).status == "scheduled" and upcoming["case"] == "CJ-2025-1"
    sale = tulsa_sale(sold, TODAY)
    assert sale.status == "sold" and sale.result == "Sold for $85,000.00"
