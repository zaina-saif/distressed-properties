from datetime import date

import pytest

from pipeline.load_nyc_referee_sales import validate
from pipeline.scrape_nyc_referee_sales import parse_listing


HTML = """<div class="entry-content"><table>
<tr><td><h3>1536 E NEW YORK AVENUE, Brooklyn, NY, 11212</h3></td>
<td><h3>October 8th, 2026, 2:30 PM</h3></td></tr>
<tr><td><img src="x"></td><td>BBL: 3-03489-0117<br/>
Sale Location: Brooklyn (Kings County)<br/>Referee: Someone<br/>
Upset Price: $4,354,200<br/>Building Class: Commercial, Vacant</td></tr>
</table></div>"""


def test_parse_source_labels_referee_auction_and_not_sheriff_sale() -> None:
    records = parse_listing(HTML, date(2026, 9, 16))
    assert len(records) == 1
    assert records[0]["county"] == "Kings"
    assert records[0]["sale_type"] == "Referee tax-lien auction"
    assert records[0]["sale_date"] == "2026-10-08"
    assert records[0]["upset_price"] == 4354200
    assert records[0]["street_address"] == "1536 E NEW YORK AVENUE"
    validate(records, date(2026, 9, 16))


def test_past_dates_and_malformed_table_are_not_loaded() -> None:
    assert parse_listing(HTML, date(2026, 11, 1)) == []
    with pytest.raises(ValueError, match="sale table"):
        parse_listing("<html></html>")
    wrong = parse_listing(HTML, date(2026, 9, 16))
    wrong[0]["county"] = "Queens"
    with pytest.raises(ValueError, match="County does not match"):
        validate(wrong, date(2026, 9, 16))
