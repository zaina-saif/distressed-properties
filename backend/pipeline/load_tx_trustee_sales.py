"""Load Texas trustee-sale notices (scrape_harris_trustee_notices) as sale listings.

A notice says a sale is planned, not that it will happen: many are cancelled on the
morning of the sale, and the clerk publishes no results. Listings are therefore
'scheduled_unverified' and read as 'date_passed_unverified' once the sale day has
passed (app/api/properties.py). They are labeled trustee sales, not sheriff sales.

Only notices with a street address are loaded. The others (a legal description only)
are written to .local/harris-trustee-notices/without_address.json for matching to
appraisal-district records later.

    python -m pipeline.load_tx_trustee_sales                 # data/sheriff_sales/tx_harris_trustee_notices.json
    python -m pipeline.load_tx_trustee_sales --dry-run
"""
import argparse
import json
from datetime import date
from pathlib import Path

from sqlalchemy import text

from app.database.session import engine
from pipeline.sale_listing_loader import Sale, load_sales, usable_address
from pipeline.scrape_harris_trustee_notices import CACHE, OUTPUT

SOURCE_SYSTEM = "tx_county_clerk_trustee_sale"


def money(value: float | None) -> str | None:
    return f"${value:,.2f}" if value else None


def notice_details(notice: dict, county: str) -> str:
    sale_date = date.fromisoformat(notice["sale_date"]).strftime("%B %-d, %Y")
    filed = date.fromisoformat(notice["file_date"]).strftime("%B %-d, %Y") if notice.get("file_date") else None
    lines = [f"Notice of Trustee's Sale {notice['doc_id']}, filed with the {county} County Clerk"
             + (f" on {filed}" if filed else "") + ".",
             f"Sale: {sale_date} (the first Tuesday of the month), between 10 AM and 4 PM at the place the"
             f" {county} County Commissioners Court designates. Highest bidder for cash; many sales are cancelled"
             " or postponed on the day."]
    if notice.get("notice_kind") == "association_assessment_lien":
        lines.append("Owners' association assessment lien foreclosure: the buyer usually takes the property subject to"
                     " the mortgage and any other senior liens.")
    if notice.get("lender"):
        lines.append(f"Foreclosing lender: {notice['lender']}.")
    if notice.get("original_principal"):
        lines.append(f"Original loan amount: {money(notice['original_principal'])} (from the notice; not the amount"
                     " owed and not an opening bid).")
    if notice.get("legal_description"):
        lines.append(f"Legal description: {notice['legal_description']}")
    if notice.get("address_source") == "inferred":
        lines.append("The street address was read from the notice without a label; check it against the legal"
                     " description.")
    lines.append(f"Search {notice['doc_id']} at the {county} County Clerk's foreclosure search to read the notice.")
    return "\n".join(lines)


def sales_from(snapshot: dict) -> tuple[list[Sale], list[dict]]:
    sales, without_address = [], []
    for notice in snapshot["notices"]:
        raw = {key: value for key, value in notice.items() if key != "ocr_chars"}
        sale = Sale(case=notice["doc_id"], street=notice.get("street") or "", city=notice.get("city"),
                    zip_code=notice.get("zip_code"), sale_date=date.fromisoformat(notice["sale_date"]),
                    status="scheduled_unverified", raw=raw, raw_status="notice of trustee's sale filed",
                    plaintiff=notice.get("lender"))
        (sales if usable_address(sale) else without_address).append(sale if usable_address(sale) else notice)
    return sales, without_address


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    snapshot = json.loads(args.input.read_text())
    state, county = snapshot["state"], snapshot["county"]
    sales, without_address = sales_from(snapshot)
    report = {"notices": len(snapshot["notices"]), "with_address": len(sales), "without_address": len(without_address),
              "association_liens": sum(n.get("notice_kind") == "association_assessment_lien" for n in snapshot["notices"])}
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "without_address.json").write_text(json.dumps(without_address, indent=2))
    if args.dry_run:
        print(json.dumps(report | {"sample": [vars(sale) | {"raw": None} for sale in sales[:3]]}, indent=2, default=str))
        return 0
    # complete=False: the clerk's list only grows until the sale day, and a notice that
    # drops off is not a result; a past sale day reads as date_passed_unverified instead.
    report |= load_sales(state, county, SOURCE_SYSTEM, snapshot["source_url"], sales,
                         f"tx_{county.lower()}_trustee_notices", complete=False)
    notices = {notice["doc_id"]: notice for notice in snapshot["notices"]}
    with engine.begin() as connection:
        for sale in sales:
            connection.execute(text("""UPDATE sheriff_sales SET description_text=:details
                WHERE state=:state AND county=:county AND source_system=:source AND sheriff_number=:number"""),
                {"details": notice_details(notices[sale.case], county), "state": state, "county": county,
                 "source": SOURCE_SYSTEM, "number": sale.case})
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
