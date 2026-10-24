import json
from datetime import date
from pathlib import Path

import pytest

from pipeline import ocr_engines
from pipeline.az_assessor import ParcelLayer
from pipeline.az_recorder import index_row, weeks
from pipeline.az_trustee_lifecycle import link, ts_key
from pipeline.load_az_trustee_sales import details, to_sale
from pipeline.parse_az_trustee_documents import apn, buyer_type, parse_cancellation, parse_notice, parse_trustee_deed

FIXTURES = Path(__file__).parent / "fixtures" / "az_trustee"


def lines(name: str) -> list[str]:
    return (FIXTURES / f"{name}.txt").read_text().splitlines()


def notice(name: str, recorded: date = date(2026, 10, 15)) -> dict:
    return parse_notice(lines(name), name, recorded)


@pytest.mark.parametrize("name, recorded, expected", [
    ("20260573151", date(2026, 10, 1), {
        "address": {"street": "12918 N 72ND AVE", "city": "Peoria", "zip": "85381"}, "apn": "200-77-406",
        "sale_date": "2027-01-12", "sale_time": "12:00 PM", "original_principal": 365682.0,
        "deed_of_trust": "20180075881", "deed_of_trust_recorded": "2018-01-31",
        "beneficiary": "Freedom Mortgage Corporation", "trustee": "Quality Loan Service Corporation",
        "ts_number": "AZ-26-1063954-SH"}),
    ("20260596116", date(2026, 10, 15), {  # labels and values in two columns
        "address": {"street": "2009 E TONOPAH DR", "city": "Phoenix", "zip": "85024"}, "apn": "213-08-009F",
        "sale_date": "2027-01-26", "original_principal": 547000.0, "beneficiary": "Navy Federal Credit Union"}),
    ("20260605494", date(2026, 10, 20), {  # street and city on separate lines; two-column beneficiary/trustee
        "address": {"street": "21259 E Lords Way", "city": "Queen Creek", "zip": "85142"}, "apn": "304-66-301",
        "sale_date": "2027-01-21", "sale_time": "10:00 AM", "deed_of_trust": "20240440627",
        "trustee": "TIFFANY & BOSCO, P.A.", "original_principal": 431393.0}),
    ("20260602439", date(2026, 10, 15), {  # "in 2023-0385166" instrument form, sale date in the prose
        "address": {"street": "253 S. Winterhaven", "city": "Mesa", "zip": "85204"}, "apn": "140-26-353",
        "sale_date": "2027-01-19", "sale_time": "11:00 AM", "deed_of_trust": "20230385166",
        "sale_location": "Main entrance of the Superior Court Building, 201 W. Jefferson St., Phoenix, AZ 85003"}),
    ("20260608081", date(2026, 10, 20), {  # "Street address or identifiable location", trustee d/b/a over two lines
        "address": {"street": "2038 E. Orange Street", "city": "Tempe", "zip": "85281"}, "apn": "132-68-054",
        "sale_date": "2027-01-21", "trustee": "TOLESOAZ Corp. d/b/a Total Lender Solutions",
        "beneficiary": "SESD LLC, an Oklahoma limited liability company", "ts_number": None}),
])
def test_parse_notice(name, recorded, expected):
    result = parse_notice(lines(name), name, recorded)
    for field, value in expected.items():
        assert result[field] == value, field
    assert result["confidence"] >= 0.95


@pytest.mark.parametrize("name", ["20260573151", "20260596116", "20260605494", "20260602439", "20260608081"])
def test_notice_never_returns_trustor(name):
    assert "TRUSTOR" not in json.dumps(notice(name)).upper()


def test_notice_names_its_sale_status_sites():
    assert notice("20260573151", date(2026, 10, 1))["sale_info_websites"] == ["www.qualityloan.com", "www.xome.com"]


def test_sale_date_outside_the_notice_window_is_ignored():
    assert notice("20260573151", date(2027, 2, 1))["sale_date"] is None


def test_parse_cancellation_references_the_notice_and_deed_of_trust():
    result = parse_cancellation(lines("20260601048"), "20260601048")
    assert result["references"] == ["20260444544", "20210796425"]
    assert result["ts_number"] == "2026-25611-AZ" and result["apn"] == "509-09-651" and result["dated"] == "2026-10-14"
    assert "[TRUSTOR]" not in json.dumps(result)


def test_parse_trustee_deed_upon_sale():
    result = parse_trustee_deed(lines("20260399413"), "20260399413", date(2026, 7, 2))
    assert result["upon_sale"] and result["references"] == ["20230653325"]
    assert result["sold_on"] == "2026-06-30" and result["price"] == 443304.76 and result["apn"] == "133-31-137"
    assert "OBX" not in json.dumps(result)  # the grantee's name is never returned


def test_trustee_deed_says_the_beneficiary_bought_it():
    result = parse_trustee_deed(lines("20260608261"), "20260608261", date(2026, 10, 20))
    assert result["buyer"] == "beneficiary" and result["price"] == 330672.23 and result["sold_on"] == "2026-10-13"


def test_trustee_deed_amount_bid():
    result = parse_trustee_deed(lines("20260600648"), "20260600648", date(2026, 10, 15))
    assert result["price"] == 315000.0 and result["references"] == ["20220643318"] and result["sold_on"] == "2026-10-08"


def test_other_trustee_deeds_are_not_sales():
    assert parse_trustee_deed(lines("20260591313"), "20260591313", date(2026, 10, 15)) == {
        "upon_sale": False, "confidence": 1.0, "missing": []}


@pytest.mark.parametrize("text, expected", [
    ("Tax Parcel Number: 200-77-406-5", "200-77-406"), ("APN 133-44-047 4", "133-44-047"),
    ("Tax Parcel No.: 301-61-4189", "301-61-418"), ("213-08-009F, 213-08-009F9", "213-08-009F"),
    ("A.P.N.: 132-68-054", "132-68-054"), ("no parcel", None)])
def test_apn(text, expected):
    assert apn(text) == expected


def test_buyer_type_compares_companies_without_returning_names():
    assert buyer_type("Freedom Mortgage Corporation", "FREEDOM MORTGAGE CORP") == "beneficiary"
    assert buyer_type("Desert Homes LLC", "Freedom Mortgage Corporation") == "third_party"
    assert buyer_type(None, "Freedom Mortgage Corporation") == "not_stated"


def n(number, recorded, dot=None, ts=None, parcel=None, sale=None):
    return {"recording_number": number, "recording_date": recorded, "deed_of_trust": dot, "ts_number": ts,
            "apn": parcel, "sale_date": sale}


def event(number, recorded, references=(), ts=None, parcel=None):
    return {"recording_number": number, "recording_date": recorded, "references": list(references), "ts_number": ts,
            "apn": parcel}


def test_link_by_notice_reference_and_deed_of_trust():
    notices = [n("20260444544", "2026-07-27", dot="20210796425"), n("20260500000", "2026-08-01", dot="20190000001")]
    foreclosures, unlinked = link(notices, [event("20260601048", "2026-10-14", ["20260444544"])],
                                  [event("20260600000", "2026-10-20", ["20190000001"])])
    assert foreclosures["dot:20210796425"].lifecycle == "cancelled"
    assert foreclosures["dot:20190000001"].lifecycle == "sold"
    assert foreclosures["dot:20190000001"].links == ["deed 20260600000 by deed_of_trust"]
    assert unlinked == []


def test_link_by_ts_number_then_apn():
    notices = [n("20260400001", "2026-07-01", ts="AZ-26-1063954-SH"), n("20260400002", "2026-07-02", parcel="140-26-353")]
    foreclosures, _ = link(notices, [event("20260600001", "2026-10-01", ts="AZ 26 1063954 SH")],
                           [event("20260600002", "2026-10-02", parcel="140-26-353")])
    assert foreclosures["ns:20260400001"].links == ["cancellation 20260600001 by ts_number"]
    assert foreclosures["ns:20260400002"].links == ["deed 20260600002 by apn"]


def test_event_recorded_before_the_notice_is_not_linked():
    foreclosures, unlinked = link([n("20260500000", "2026-08-01", parcel="140-26-353")], [],
                                  [event("20260300000", "2026-06-01", parcel="140-26-353")])
    assert foreclosures["ns:20260500000"].lifecycle == "noticed" and [e["kind"] for e in unlinked] == ["deed"]


def test_a_later_notice_postpones_the_sale():
    notices = [n("20260400000", "2026-07-01", dot="20200000001", sale="2026-10-05"),
               n("20260500000", "2026-09-01", dot="20200000001", sale="2026-12-07")]
    foreclosure = link(notices, [], [])[0]["dot:20200000001"]
    assert foreclosure.lifecycle == "postponed" and foreclosure.notice["sale_date"] == "2026-12-07"
    assert foreclosure.earlier_sale_dates == ["2026-10-05"]


def test_re_noticed_after_a_cancellation_is_open_again():
    notices = [n("20260400000", "2026-07-01", dot="20200000001", sale="2026-10-05"),
               n("20260600000", "2026-10-01", dot="20200000001", sale="2027-01-05")]
    foreclosure = link(notices, [event("20260500000", "2026-08-01", ["20200000001"])], [])[0]["dot:20200000001"]
    assert foreclosure.lifecycle == "postponed" and foreclosure.cancellation is None


def test_ts_key_needs_a_number():
    assert ts_key("SESD, LLC v [TRUSTOR]") is None and ts_key("2026-00345-AZ-REV") == "202600345AZREV"


def test_index_row_drops_party_names():
    row = index_row({"names": "SMITH JOHN", "recordingNumber": 20260573151, "recordingSuffix": "",
                     "recordingDate": "10-01-2026", "documentCode": "N/TR SALE"}, "notice")
    assert row == {"recording_number": "20260573151", "recording_date": "2026-10-01", "document_code": "N/TR SALE",
                   "kind": "notice"}


def test_weeks_cover_the_range():
    assert list(weeks(date(2026, 10, 1), date(2026, 10, 16), 7)) == [
        (date(2026, 10, 1), date(2026, 10, 7)), (date(2026, 10, 8), date(2026, 10, 14)), (date(2026, 10, 15), date(2026, 10, 16))]


def test_text_lines_join_pieces_on_the_same_line():
    boxes = [(1, 0.55, 0.800, 0.01, "12918 N 72ND AVE"), (1, 0.10, 0.801, 0.01, "Purported Street Address:"),
             (1, 0.10, 0.900, 0.01, "Notice of Trustee's Sale")]
    assert ocr_engines.text_lines(boxes) == ["Notice of Trustee's Sale", "Purported Street Address: | 12918 N 72ND AVE"]


def test_tesseract_tsv_lines():
    tsv = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
           "5\t1\t1\t1\t1\t1\t100\t200\t50\t20\t95\tTax\n5\t1\t1\t1\t1\t2\t160\t200\t60\t20\t95\tParcel\n")
    assert ocr_engines.TesseractOcr.lines(tsv, 1, 1000, 1000) == [(1, 0.1, 0.78, 0.02, "Tax Parcel")]


def test_parcel_record_reads_values_and_legal_class():
    layer = ParcelLayer({"layer": "x", "fields": {"apn": "APN_DASH", "street": "PHYSICAL_ADDRESS", "city": "PHYSICAL_CITY",
                                                  "zip": "PHYSICAL_ZIP", "full_cash_value": "FCV_CUR",
                                                  "legal_class": "LC_CUR", "deed_number": "DEED_NUMBER"}}, client=None)
    record = layer.record({"APN_DASH": "200-54-142", "PHYSICAL_ADDRESS": "8913 W MARCONI AVE   PEORIA  85382",
                           "PHYSICAL_CITY": "PEORIA", "PHYSICAL_ZIP": "85382", "FCV_CUR": "     355,200",
                           "LC_CUR": "3.1", "DEED_NUMBER": "20260397587"})
    assert record["street"] == "8913 W MARCONI AVE" and record["city"] == "Peoria" and record["full_cash_value"] == 355200
    assert record["owner_occupied"] is True and record["deed_number"] == "20260397587"


def foreclosure_record(**changes) -> dict:
    record = {"key": "dot:20180075881", "lifecycle": "noticed", "street": "12918 N 72ND AVE", "city": "Peoria",
              "zip": "85381", "address_source": "assessor", "apn": "200-77-406", "sale_date": "2027-01-12",
              "sale_time": "12:00 PM", "sale_location": None, "earlier_sale_dates": [], "original_principal": 365682.0,
              "opening_bid": None, "deed_of_trust": "20180075881", "deed_of_trust_recorded": "2018-01-31",
              "ts_number": "AZ-26-1063954-SH", "trustee": "Quality Loan Service Corporation", "trustee_phone": None,
              "beneficiary": "Freedom Mortgage Corporation", "sale_info_websites": ["www.xome.com"],
              "notices": [{"recording_number": "20260573151", "recording_date": "2026-10-01", "sale_date": "2027-01-12"}],
              "cancellation": None, "trustee_deed": None, "assessor": None}
    return {**record, **changes}


def test_to_sale_statuses():
    assert to_sale(foreclosure_record()).status == "scheduled_unverified"
    sold = to_sale(foreclosure_record(lifecycle="sold", trustee_deed={
        "recording_number": "20260600000", "recording_date": "2027-01-20", "sold_on": "2027-01-12", "price": 300000.0,
        "buyer": "third_party"}))
    assert sold.status == "sold" and sold.sale_date == date(2027, 1, 12)
    assert to_sale(foreclosure_record(lifecycle="cancelled")).status == "cancelled"
    assert to_sale(foreclosure_record()).street == "12918 N 72Nd Ave"


def test_details_label_the_principal_and_postponement():
    text = details(foreclosure_record(lifecycle="postponed", earlier_sale_dates=["2026-12-01"]), "Maricopa")
    assert "Postponed from December 1, 2026." in text
    assert "a loan amount, not the opening bid" in text


def test_import_folder_matches_by_file_name_or_printed_number(tmp_path, monkeypatch):
    from pipeline import scrape_az_trustee_sales
    from pipeline.az_recorder import CountyConfig

    class Config(CountyConfig):
        cache = tmp_path / "cache"

    class Engine:
        def boxes(self, pdf):
            return [(1, 0.1, 0.5, 0.01, "20260573151" if pdf.stem == "unofficialpdfdocs" else "no number")]

    monkeypatch.setattr(scrape_az_trustee_sales.ocr_engines, "engine", lambda name: Engine())
    saved = tmp_path / "saved"
    saved.mkdir()
    for name in ("20260596116.pdf", "unofficialpdfdocs.pdf", "other.pdf"):
        (saved / name).write_bytes(b"%PDF-1.4")
    index = {number: {"recording_number": number, "recording_date": "2026-10-01", "kind": "notice"}
             for number in ("20260573151", "20260596116")}
    result = scrape_az_trustee_sales.import_folder(Config("Maricopa", {}, {}, {}), index, saved, "macos")
    assert result == {"imported": 2, "unmatched": ["other.pdf"]}
    assert sorted(path.name for path in (tmp_path / "cache" / "pdf").iterdir()) == ["20260573151.pdf", "20260596116.pdf"]
    assert (tmp_path / "cache" / "ocr" / "20260573151.txt").read_text() == "20260573151"


@pytest.mark.parametrize("text, expected", [
    ("Building, Phoenix, AZ 85003 at 12:00 PM on January 19, 2027:", ("2027-01-19", "12:00 PM")),
    ("Phoenix, AZ 85003, on 1/28/2027 10:00 AM of said day:", ("2027-01-28", "10:00 AM")),
    ("Phoenix, AZ, 85003 on 01/21/2026 at 10:00 A.M. of said day:", (None, None)),  # before the recording: a typo
])
def test_sale_when_wordings(text, expected):
    from pipeline.parse_az_trustee_documents import sale_when
    day, clock = sale_when(text, date(2026, 10, 20))
    assert (day.isoformat() if day else None, clock) == expected


def test_open_foreclosures_without_a_sale_date_are_held_back():
    from pipeline.load_az_trustee_sales import loadable
    assert not loadable(foreclosure_record(sale_date=None))
    assert loadable(foreclosure_record(sale_date=None, lifecycle="cancelled")) and loadable(foreclosure_record())


# Pima: fixtures transcribed from screenshots of the recorder's viewer (2026-10-24), trustors redacted.
PIMA_RULES = {"apn_format": "pima", "sale_location": {
    "pattern": r"110\s+W(?:est|\.)?\s+Congress",
    "text": "Superior Court Building, Pima County Courthouse, 110 W. Congress St., Tucson, AZ 85701"}}


@pytest.mark.parametrize("name, expected", [
    ("20262940537", {  # Quality Loan: labelled fields, "Sale Date and Time" on one line
        "address": {"street": "3733 S AVENIDA DE LAS PALMAS", "city": "Tucson", "zip": "85730"}, "apn": "136-17-5140",
        "sale_date": "2027-02-10", "sale_time": "10:00 AM", "original_principal": 176739.0,
        "deed_of_trust": "20182610619", "beneficiary": "NewRez LLC", "ts_number": "AZ-26-1064299-AB"}),
    ("20262940520", {  # "Sale Date:" and "Sale Time:" on separate lines, APN without dashes
        "address": {"street": "1921 S TILTING T PLACE", "city": "Tucson", "zip": "85713"}, "apn": "212-17-4380",
        "sale_date": "2027-01-27", "sale_time": "11:30 AM", "original_principal": 218010.0,
        "deed_of_trust": "20220600019", "deed_of_trust_recorded": "2022-03-01"}),
    ("20262940505", {  # sale date in the prose, address "purported to be:" on the next lines
        "address": {"street": "2301 S Hohokam Dr", "city": "Tucson", "zip": "85735"}, "apn": "211-31-0030",
        "sale_date": "2027-01-27", "sale_time": "10:00 AM", "deed_of_trust": "20150820431",
        "beneficiary": "Guild Mortgage Company LLC", "ts_number": "26-17330-GM-AZ"}),
    ("20262940385", {  # a private trust as beneficiary is not kept; no TS number with digits
        "address": {"street": "8840 S. Nogales Hwy", "city": "Tucson", "zip": "85756"}, "apn": "140-50-0300",
        "sale_date": "2027-01-21", "sale_time": "11:30 AM", "beneficiary": None, "ts_number": None,
        "trustee": "TOLESOAZ Corp. d/b/a Total Lender Solutions"}),
    ("20262940325", {
        "address": {"street": "6981 E Calle Tolosa", "city": "Tucson", "zip": "85750"}, "apn": "114-35-1340",
        "sale_date": "2027-02-02", "original_principal": 366750.0, "beneficiary": "Athene Annuity and Life Company"}),
])
def test_parse_pima_notice(name, expected):
    result = parse_notice(lines(name), name, date(2026, 10, 21), PIMA_RULES)
    for field, value in expected.items():
        assert result[field] == value, field
    assert result["sale_location"] == PIMA_RULES["sale_location"]["text"]
    assert result["confidence"] >= 0.95
    assert "TRUSTOR" not in json.dumps(result).upper()


@pytest.mark.parametrize("text, labelled, expected", [
    ("Tax Parcel Number: 136-17-5140", False, "136-17-5140"), ("212174380", True, "212-17-4380"),
    ("Loan 212174380", False, None), ("APN 123-45-678A", False, "123-45-678A")])
def test_pima_apn(text, labelled, expected):
    assert apn(text, "pima", labelled) == expected


def test_recorder_stamp_and_document_kind():
    from pipeline.scrape_az_trustee_sales import document_kind, recorder_stamp
    assert recorder_stamp(lines("20262940537")) == ("20262940537", date(2026, 10, 21))
    assert document_kind(lines("20262940537")) == "notice"
    assert document_kind(["20262950100", "CANCELLATION OF NOTICE OF TRUSTEE'S SALE"]) == "cancellation"
    assert document_kind(["TRUSTEE'S DEED UPON SALE", "pursuant to the Notice of Trustee's Sale"]) == "trustee_deed"
    assert document_kind(["DEED OF TRUST"]) is None


def test_import_exported_indexes_saved_pdfs(tmp_path, monkeypatch):
    from pipeline import scrape_az_trustee_sales
    from pipeline.az_recorder import CountyConfig

    class Config(CountyConfig):
        cache = tmp_path / "cache"

    pages = {"20262940537": ["20262940537", "10/21/2026 03:52 PM | Page 1 of 3", "Notice of Trustee's Sale"],
             "download (3)": ["20262950100", "10/22/2026 08:06 AM | Page 1 of 1",
                              "CANCELLATION OF NOTICE OF TRUSTEE'S SALE"],
             "scan": ["DEED OF TRUST"]}

    class Engine:
        def boxes(self, pdf):
            return [(1, 0.1, 0.9 - index * 0.05, 0.01, text) for index, text in enumerate(pages[pdf.stem])]

    monkeypatch.setattr(scrape_az_trustee_sales.ocr_engines, "engine", lambda name: Engine())
    saved = tmp_path / "saved"
    saved.mkdir()
    for name in pages:
        (saved / f"{name}.pdf").write_bytes(b"%PDF-1.4")
    index = {}
    result = scrape_az_trustee_sales.import_exported(Config("Pima", {}, {}, {}), index, saved, "macos")
    assert result == {"notice": 1, "cancellation": 1, "unrecognised": ["scan.pdf: no recording number, recording date, title"]}
    assert index["20262950100"] == {"recording_number": "20262950100", "recording_date": "2026-10-22",
                                    "document_code": "manual_export", "kind": "cancellation"}
    assert sorted(path.name for path in (tmp_path / "cache" / "pdf").iterdir()) == ["20262940537.pdf", "20262950100.pdf"]
    again = scrape_az_trustee_sales.import_exported(Config("Pima", {}, {}, {}), index, saved, "macos")
    assert again["already_imported"] == 1  # matched by file name; the renamed download is read again


def test_pima_parcel_layer_keys_and_values():
    asked = []

    class Client:
        def get(self, url, params):
            asked.append(params["where"])

            class Response:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {"features": [{"attributes": {"PARCEL": "136175140", "ADDRESS_OL": "3733 S AVENIDA DE LAS PALMAS",
                                                         "ZIP": "85730", "FCV": 227931.0, "TAXYR": "2026"}}]}
            return Response()

    layer = ParcelLayer({"layer": "x", "apn_digits": True, "fields": {
        "apn": "PARCEL", "street": "ADDRESS_OL", "zip": "ZIP", "full_cash_value": "FCV", "tax_year": "TAXYR"}}, Client())
    found = layer.by_apn(["136-17-5140"])
    assert asked == ["PARCEL IN ('136175140')"]
    assert found["136-17-5140"]["full_cash_value"] == 227931 and found["136-17-5140"]["city"] is None


def test_place_takes_the_notice_city_when_the_parcel_has_none():
    from pipeline.az_trustee_lifecycle import Foreclosure
    from pipeline.scrape_az_trustee_sales import place
    foreclosure = Foreclosure("dot:20182610619", notices=[{
        "apn": "136-17-5140", "address": {"street": "3733 S Avenida de las Palmas", "city": "Tucson", "zip": "85730"}}])
    parcel = {"apn": "136-17-5140", "street": "3733 S AVENIDA DE LAS PALMAS", "city": None, "zip": "85730"}
    address, source, _ = place(foreclosure, {"136-17-5140": parcel}, layer=None)
    assert source == "assessor" and address == {"street": "3733 S AVENIDA DE LAS PALMAS", "city": "Tucson", "zip": "85730"}


@pytest.mark.parametrize("ocr_lines, field, expected", [
    (["Original Principal Balanoe: | $176,739.00"], "original_principal", 176739.0),
    (["Original Principal Balance: 5366,750.00"], "original_principal", 366750.0),  # "$" read as "5"
    (["ORIGINAL PRINCIPAL BALANCE AS SHOWN ON DEED OF TRUST: | $216,015.00 | Copy"], "original_principal", 216015.0),
    (["Sale Date and Time: | 2/102027 at 10:00 AM"], "sale_date", "2027-02-10"),
    (["Sale Location: | Superior Court, 110 West Congress, Tucson, AZ 85701",
      "Purported Strset Address: | 3733 S AVENIDA DE LAS PALMAS, TUCSON, AZ 85730"], "address",
     {"street": "3733 S AVENIDA DE LAS PALMAS", "city": "Tucson", "zip": "85730"}),
    (["at the East Entrance, 110 West Congress, Tucson, AZ 85701"], "address", None),  # never the courthouse
])
def test_pima_ocr_misreads(ocr_lines, field, expected):
    assert parse_notice(ocr_lines, "20262940537", date(2026, 10, 21), PIMA_RULES)[field] == expected


def test_place_uses_the_parcel_when_the_notice_street_is_debris():
    from pipeline.az_trustee_lifecycle import Foreclosure
    from pipeline.scrape_az_trustee_sales import place
    stated = {"street": "18 THEREOF. Purported Streer Address: 1221 E. PARK ESTATES CIR", "city": "Tucson", "zip": "85706"}
    parcel = {"apn": "140-18-2510", "street": "1221 E PARK ESTATES CI", "city": None, "zip": "85706"}
    address, source, _ = place(Foreclosure("dot:1", notices=[{"apn": "140-18-2510", "address": stated}]),
                               {"140-18-2510": parcel}, layer=None)
    assert source == "assessor" and address["street"] == "1221 E PARK ESTATES CI"
