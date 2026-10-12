import pytest

import pipeline.scrape_ocean_county as ocean

PAGE = """                    REAL ESTATE LISTING FOR 10/20/2026
 CH   780768
                   PLAINTIFF    SIXTY ACRE RESERVE CONDOMINIUM ASSO            $7,767.94
   DJ00099625      DEFENDANT   JANE DOE
                   ATTORNEY    POLULAK LAW, LLC.                          732-858-0600

       SEQ   001     505 GERANIUM COURT                                                      JACKSON   NJ  08527
                     Lot: 5.431                                       Block: 8001
 CH   780800
                   PLAINTIFF    A BANK                                          $250,000.00
   F01234-25       DEFENDANT   JOHN DOE
       SEQ   001     12 MAIN STREET                                                          TOMS RIVER   NJ  08753
                     Lot: 3                                           Block: 7
 CH   780900
                   PLAINTIFF    NO ADDRESS LINE                                 $1.00
"""


class Page:
    def extract_text(self, extraction_mode=None):
        return PAGE


@pytest.fixture(autouse=True)
def fake_pdf(monkeypatch):
    monkeypatch.setattr(ocean, "PdfReader", lambda _: type("Reader", (), {"pages": [Page()]})())


def test_judgment_and_foreclosure_dockets_parse_and_bad_records_are_skipped():
    failures = []
    records = {record["sheriff_number"]: record for record in ocean.parse_pdf(b"%PDF", failures)}

    assert set(records) == {"CH-780768", "CH-780800"} and failures == ["CH 780900"]
    judgment = records["CH-780768"]
    assert judgment["address"] == "505 GERANIUM COURT JACKSON NJ 08527" and judgment["upset_price"] == "7767.94"
    assert judgment["raw_payload"]["parsed_description"]["docket_number"] == "DJ00099625"
    assert records["CH-780800"]["raw_payload"]["parsed_description"]["docket_number"] == "F01234-25"


def test_without_a_failure_list_a_bad_record_still_raises():
    with pytest.raises(ValueError, match="CH 780900"):
        ocean.parse_pdf(b"%PDF")
