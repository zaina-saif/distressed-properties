from datetime import date

from pipeline.load_columbia_foreclosures import validate
from pipeline.scrape_columbia_foreclosures import parse_page


HTML = """
<p>REVISED: 09/10/2026</p>
<div class="w-full grid md:grid-cols-3 gap-4 p-4 md:p-6">
 <div><label>Status</label><strong>SCHEDULED</strong></div>
 <div><label>Sale Date</label><strong>09/23/2026</strong></div>
 <div><label>Case Number</label><strong>2025-14-CA</strong></div>
 <div><label>Judgement Amount</label><strong>$27,202</strong></div>
 <div><label>Parties</label><strong>BANK, N.A. VS. JANE DOE, ET AL.</strong></div>
 <div><label>Address</label><a>272 SW VELVET GLN</a></div>
 <div><label>Parcel ID</label><strong>00227-001</strong></div>
</div>
"""


def test_parse_official_labeled_record():
    snapshot = parse_page(HTML, date(2026, 9, 21))
    row = snapshot["records"][0]
    assert snapshot["source_revised_date"] == "2026-09-10"
    assert row["judgment_amount"] == "27202.00"
    assert row["plaintiff"] == "BANK, N.A."
    assert row["defendant"] == "JANE DOE, ET AL."
    assert row["distress_start_year"] == 2025
    assert validate(snapshot, date(2026, 9, 21)) == [row]

