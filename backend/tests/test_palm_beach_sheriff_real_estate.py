from datetime import date

from pipeline.load_palm_beach_sheriff_real_estate import validate
from pipeline.scrape_palm_beach_sheriff_real_estate import parse_search_response


REAL_ESTATE = """NOTICE OF SHERIFFS SALE
by virtue of a Writ of Execution, Case # 50-2024-CA-005371-XXXA-MB, issued out of the Circuit Court
on the 24th day of January, 2025 in that certain cause wherein, PRESCOTT RESOURCES INC., Plaintiff and
ELIZABETH J BECKLES; EMERSON BECKLES, Defendant, and on the 27th day of July, 2026 on behalf of the
Plaintiff have made levy upon the following described property:
All rights, title and interest of EMERSON BECKLES, the within named defendant, to wit:
A 25 PERCENT UNDIVIDED INTEREST IN THE FOLLOWING DESCRIBED REAL PROPERTY OF THE DEFENDANT LISTED BELOW:
LOT 10 OF BLOCK 42, ROLLING GREEN RIDGE FIRST ADDITION.
The property may be seen prior to the sale at 300 NW 16TH COURT BOYNTON BEACH, FL 33435. Further I shall
offer this property for sale on Tuesday the 22nd day of September, 2026, online at
https://www.Bid4Assets.com/pbsosheriffsales"""


def test_filters_vehicle_and_parses_real_estate():
    payload = {"_embedded": {"notices": [
        {"id": 1, "date": "2026-08-18", "notice": REAL_ESTATE},
        {"id": 2, "date": "2026-09-10", "notice": REAL_ESTATE.replace("REAL PROPERTY", "2020 WHITE MCLAREN")},
    ]}}
    snapshot = parse_search_response(payload, date(2026, 9, 21))
    assert len(snapshot["records"]) == 1
    row = snapshot["records"][0]
    assert row["street_address"] == "300 NW 16TH COURT"
    assert row["city"] == "Boynton Beach"
    assert row["defendant"] == "ELIZABETH J BECKLES; EMERSON BECKLES"
    assert row["distress_start_date"] == "2025-01-24"
    assert row["judgment_amount"] is None
    assert validate(snapshot, date(2026, 9, 21)) == [row]

