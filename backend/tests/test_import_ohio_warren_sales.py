from pipeline.import_ohio_warren_sales import normalize_status, parse_html


def test_parse_official_table_row():
    html = """<table id="slsgrid"><tbody><tr>
    <td><input onclick="LoadDetails('17005', '314+CHERRY')"/></td><td>BANK LLC</td><td>PERSON, ET AL.</td>
    <td>Alias 23CV096728</td><td>$400,000.00</td><td>$65,440.23</td><td>$266,667.00</td>
    <td>17-36-365-022</td><td><div>314 CHERRY LAUREL CT<br/>MAINEVILLE, OH 45039</div></td>
    <td>09/22/2026<br/><span>Sale Cancelled 09/09/2026</span></td><td>Cancelled</td>
    </tr></tbody></table>"""
    record = parse_html(html)[0]
    assert record["sheriff_number"] == "WARREN-17005"
    assert record["court_case_number"] == "23CV096728"
    assert record["sale_date"] == "2026-09-22"
    assert record["status"] == "cancelled"
    assert record["upset_price"] == "266667.00"


def test_stayed_is_postponed():
    assert normalize_status("Stayed") == "postponed"
