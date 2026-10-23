"""Load Arizona trustee-sale foreclosures (pipeline.scrape_az_trustee_sales) as sale listings.

One listing per foreclosure, keyed by its deed of trust (`dot:<recording number>`, or
`ns:<notice recording number>`), source_system 'az_county_recorder_trustee_sale', sale
type "Trustee sale (non-judicial foreclosure)". Statuses:
  noticed / postponed -> scheduled_unverified (read as date_passed_unverified once the date
                         passes; trustees publish no results); the dates a later notice or the
                         status checker moved it from are kept as 'adjourned' history rows
  cancelled           -> cancelled (a Cancellation of Notice of Trustee's Sale was recorded)
  sold                -> sold, with the trustee's deed's price and sale date, and whether the
                         foreclosing beneficiary ('plaintiff') or a third party bought it
The original principal balance is a loan amount, not a judgment or an opening bid, so no
equity is shown; an opening bid from the status checker is the upset price.

The assessor's full cash value is stored in property_valuations as provider
'az_assessor_full_cash_value' (with the legal class and the owner-occupied flag); it is the
county's assessed value, not a market estimate, and is shown in the notice details.

    python -m pipeline.load_az_trustee_sales [--county Maricopa] [--dry-run]
    python -m pipeline.load_az_trustee_sales --export upcoming.csv     # upcoming AZ sales from the database
"""
import argparse
import csv
import json
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.database.session import engine
from pipeline.az_recorder import county_config
from pipeline.sale_listing_loader import Sale, load_sales, usable_address
from pipeline.scrape_az_trustee_sales import SOURCE_SYSTEM, output_path

PROVIDER = "az_assessor_full_cash_value"
STATUSES = {"noticed": "scheduled_unverified", "postponed": "scheduled_unverified", "cancelled": "cancelled", "sold": "sold"}
BUYERS = {"beneficiary": "plaintiff", "third_party": "third_party", "not_stated": "not_stated"}


def long_date(value: str | None) -> str | None:
    return date.fromisoformat(value).strftime("%B %-d, %Y") if value else None


def details(record: dict, county: str) -> str:
    lines = [f"Trustee's sale (non-judicial foreclosure) under a deed of trust, {county} County, Arizona."]
    if record["sale_date"]:
        when = f"{long_date(record['sale_date'])}" + (f" at {record['sale_time']}" if record.get("sale_time") else "")
        lines.append(f"Sale: {when}" + (f", {record['sale_location']}" if record.get("sale_location") else "") + ".")
    if record["earlier_sale_dates"]:
        lines.append("Postponed from " + ", ".join(long_date(day) for day in record["earlier_sale_dates"]) + ".")
    if record.get("cancellation"):
        lines.append(f"Cancelled: Cancellation of Notice of Trustee's Sale recorded {long_date(record['cancellation']['recording_date'])}"
                     f" (recording no. {record['cancellation']['recording_number']}).")
    if deed := record.get("trustee_deed"):
        price = f" for ${deed['price']:,.2f}" if deed.get("price") else ""
        buyer = {"beneficiary": " to the foreclosing beneficiary", "third_party": " to a third-party bidder"}.get(deed.get("buyer"), "")
        lines.append(f"Sold{buyer}{price}" + (f" on {long_date(deed['sold_on'])}" if deed.get("sold_on") else "")
                     + f"; Trustee's Deed Upon Sale recorded {long_date(deed['recording_date'])} (no. {deed['recording_number']}).")
    if record.get("trustee"):
        lines.append(f"Trustee: {record['trustee']}" + (f", {record['trustee_phone']}" if record.get("trustee_phone") else "") + ".")
    if record.get("sale_info_websites"):
        lines.append("Sale status online: " + ", ".join(record["sale_info_websites"]) + ".")
    if record.get("beneficiary"):
        lines.append(f"Beneficiary: {record['beneficiary']}.")
    if record.get("original_principal"):
        lines.append(f"Original principal balance: ${record['original_principal']:,.2f} (a loan amount, not the opening bid).")
    if record.get("deed_of_trust"):
        lines.append(f"Deed of trust: recording no. {record['deed_of_trust']}"
                     + (f", recorded {long_date(record['deed_of_trust_recorded'])}" if record.get("deed_of_trust_recorded") else "") + ".")
    if record.get("ts_number"):
        lines.append(f"Trustee's sale no. {record['ts_number']}.")
    if assessor := record.get("assessor"):
        value = f"full cash value ${assessor['full_cash_value']:,}" if assessor.get("full_cash_value") else None
        occupied = {True: "owner-occupied (legal class 3)", False: f"not owner-occupied (legal class {assessor.get('legal_class')})"}.get(
            assessor.get("owner_occupied"))
        facts = [fact for fact in (value and f"{value} ({assessor.get('tax_year')})", occupied,
                                   assessor.get("use_code") and f"use code {assessor['use_code']}") if fact]
        lines.append(f"Assessor parcel {assessor['apn']}: " + "; ".join(facts) + "." if facts else f"Assessor parcel {assessor['apn']}.")
    notices = ", ".join(f"{n['recording_number']} ({long_date(n['recording_date'])})" for n in record["notices"])
    lines.append(f"Notice(s) of Trustee's Sale: {notices}. Address from the {record['address_source']}"
                 + (" (the notice's address is the trustee's; it disclaims its accuracy)." if record["address_source"] == "notice" else "."))
    lines.append("Opening bids are set by the beneficiary at the sale. Get a professional title search before bidding.")
    return "\n".join(lines)


def to_sale(record: dict) -> Sale:
    status = STATUSES[record["lifecycle"]]
    sale_date = date.fromisoformat(record["sale_date"]) if record.get("sale_date") else None
    if record["lifecycle"] == "sold" and record["trustee_deed"].get("sold_on"):
        sale_date = date.fromisoformat(record["trustee_deed"]["sold_on"])
    assessor = record.get("assessor") or {}
    return Sale(case=record["key"], street=record["street"].title() if record["street"].isupper() else record["street"],
                city=record["city"], zip_code=record.get("zip"), sale_date=sale_date, status=status, raw=record,
                raw_status=record["lifecycle"], parcel=record.get("apn"), upset=record.get("opening_bid"),
                attorney=record.get("trustee"), property_number=record.get("ts_number"),
                latitude=assessor.get("latitude"), longitude=assessor.get("longitude"))


def loadable(record: dict) -> bool:
    """An open foreclosure needs its sale date: a notice whose date OCR could not read is held back."""
    return record["lifecycle"] in ("cancelled", "sold") or bool(record.get("sale_date"))


def load(county: str, records: list[dict], source_url: str) -> dict:
    held = [record["notices"][-1]["recording_number"] for record in records if not loadable(record)]
    pairs = [(record, to_sale(record)) for record in records if loadable(record)]
    pairs = [(record, sale) for record, sale in pairs if usable_address(sale)]
    # complete=False: the recorder adds documents, it is not a list of every open sale, and a date
    # moved later by the status checker is kept.
    result = load_sales("AZ", county, SOURCE_SYSTEM, source_url, [sale for _, sale in pairs],
                        "az_county_recorder_trustee_sales", complete=False)
    now = datetime.now(timezone.utc)
    valued = 0
    with engine.begin() as connection:
        for record, sale in pairs:
            deed = record.get("trustee_deed") or {}
            row = connection.execute(text("""UPDATE sheriff_sales SET description_text=:details, current_status=:status,
                docket_number=:dot, sold_amount=:amount, sold_on=:sold_on, sold_buyer=:buyer, sold_raw_status=:raw
                WHERE state='AZ' AND county=:county AND source_system=:source AND sheriff_number=:number
                RETURNING id, property_id"""), {
                "details": details(record, county), "status": sale.status, "dot": record.get("deed_of_trust"),
                "amount": deed.get("price"), "sold_on": deed.get("sold_on"),
                "buyer": BUYERS.get(deed.get("buyer")) if deed else None,
                "raw": "trustee's deed upon sale" if deed else None, "county": county, "source": SOURCE_SYSTEM,
                "number": sale.case}).first()
            if row is None:
                continue
            for earlier in record["earlier_sale_dates"]:
                connection.execute(text("""INSERT INTO sheriff_sale_status_history(id,sheriff_sale_id,status,sale_date,
                    observed_at,source_url,raw_status) SELECT :id,:sale_id,'adjourned',:sale_date,:now,:url,'postponed'
                    WHERE NOT EXISTS(SELECT 1 FROM sheriff_sale_status_history WHERE sheriff_sale_id=:sale_id
                      AND status='adjourned' AND sale_date=:sale_date)"""),
                    {"id": str(uuid.uuid4()), "sale_id": row[0], "sale_date": earlier, "now": now, "url": source_url})
            assessor = record.get("assessor") or {}
            if assessor.get("full_cash_value"):
                valued += save_value(connection, row[1], assessor)
    return {**result, "assessor_values_saved": valued, "held_without_sale_date": held}


def save_value(connection, property_id, assessor: dict) -> int:
    response = {key: assessor.get(key) for key in ("tax_year", "limited_value", "legal_class", "owner_occupied", "use_code")}
    current = connection.execute(text("""SELECT estimated_value FROM property_valuations WHERE property_id=:id
        AND provider=:provider AND is_current"""), {"id": property_id, "provider": PROVIDER}).first()
    if current and float(current[0]) == float(assessor["full_cash_value"]):
        return 0
    connection.execute(text("""UPDATE property_valuations SET is_current=FALSE WHERE property_id=:id
        AND provider=:provider AND is_current"""), {"id": property_id, "provider": PROVIDER})
    connection.execute(text("""INSERT INTO property_valuations(property_id, provider, estimated_value, provider_property_id,
        provider_response, effective_date, is_current) VALUES(:id, :provider, :value, :apn, CAST(:response AS JSONB),
        :effective, TRUE)"""), {"id": property_id, "provider": PROVIDER, "value": assessor["full_cash_value"],
                                "apn": assessor.get("apn"), "response": json.dumps(response),
                                "effective": date(int(assessor["tax_year"]), 1, 1) if str(assessor.get("tax_year") or "").isdigit()
                                else date.today()})
    return 1


def export(path: str) -> int:
    """Upcoming Arizona recorder trustee sales: address, sale date, trustee, original principal, assessed value, status."""
    with engine.connect() as connection:
        rows = connection.execute(text("""SELECT p.street_address, p.city, p.zip_code, ss.county, ss.current_sale_date::date,
            r.raw_payload->>'trustee', r.raw_payload->>'original_principal', pv.estimated_value,
            pv.provider_response->>'owner_occupied', ss.map_number, r.raw_payload->>'lifecycle'
            FROM sheriff_sales ss JOIN properties p ON p.id=ss.property_id
            JOIN LATERAL (SELECT raw_payload FROM raw_scrape_records WHERE content_hash=ss.raw_source_hash LIMIT 1) r ON TRUE
            LEFT JOIN property_valuations pv ON pv.property_id=p.id AND pv.provider=:provider AND pv.is_current
            WHERE ss.state='AZ' AND ss.source_system=:source AND ss.current_status='scheduled_unverified'
              AND ss.current_sale_date >= CURRENT_DATE ORDER BY ss.current_sale_date, p.street_address"""),
            {"provider": PROVIDER, "source": SOURCE_SYSTEM}).all()
    handle = sys.stdout if path == "-" else open(path, "w", newline="")
    writer = csv.writer(handle)
    writer.writerow(["address", "city", "zip", "county", "sale_date", "trustee", "original_principal",
                     "assessor_full_cash_value", "owner_occupied", "apn", "status"])
    writer.writerows(rows)
    if handle is not sys.stdout:
        handle.close()
    print(f"{len(rows)} upcoming sales -> {path}", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--county", default="Maricopa")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--export", metavar="CSV", help="write upcoming sales from the database to CSV ('-' for stdout)")
    args = parser.parse_args(argv)
    if args.export:
        return export(args.export)
    county = county_config(args.county)
    snapshot = json.loads((args.input or output_path(county)).read_text())
    records = snapshot["foreclosures"]
    if args.dry_run:
        sales = [to_sale(record) for record in records]
        print(json.dumps({"foreclosures": len(records), "usable": sum(1 for sale in sales if usable_address(sale)),
                          "held_without_sale_date": sum(1 for record in records if not loadable(record)),
                          "by_status": {status: sum(1 for sale in sales if sale.status == status) for status in set(STATUSES.values())},
                          "sample": [{"case": sale.case, "address": f"{sale.street}, {sale.city} {sale.zip_code}",
                                      "sale_date": str(sale.sale_date), "status": sale.status} for sale in sales[:3]],
                          "sample_details": details(records[0], county.name) if records else None}, indent=2))
        return 0
    print(json.dumps({f"AZ {county.name}": load(county.name, records, snapshot["source_url"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
