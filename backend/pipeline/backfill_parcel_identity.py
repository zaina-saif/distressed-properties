"""Bridge verified legacy AVM parcel matches into the canonical identity layer."""
from __future__ import annotations

import argparse

from sqlalchemy import text

from app.database.session import engine
from pipeline.parcel_identity import normalize_text


def eligible_count() -> int:
    with engine.connect() as connection:
        return connection.execute(text("""SELECT count(DISTINCT ss.id)
          FROM sheriff_sales ss JOIN properties p ON p.id=ss.property_id
          JOIN property_avm_features f ON f.property_id=p.id
          JOIN parcels cp ON cp.state='NJ' AND cp.municipality_code=trim(f.municipality_code)
            AND cp.block=f.block AND cp.lot=f.lot AND cp.qualifier=f.qualifier
          WHERE p.state='NJ' AND p.county='Monmouth' AND f.match_confidence>=90""")).scalar_one()


def backfill() -> tuple[int, int]:
    with engine.begin() as connection:
        addresses = [dict(row) for row in connection.execute(text("""SELECT DISTINCT
          ss.id sheriff_sale_id,p.normalized_address
          FROM sheriff_sales ss JOIN properties p ON p.id=ss.property_id
          WHERE p.state='NJ' AND p.county='Monmouth'""")).mappings()]
        if addresses:
            connection.execute(text("""INSERT INTO parcel_identity_evidence
              (sheriff_sale_id,evidence_type,raw_value,normalized_value,source_location,confidence)
              VALUES(:sheriff_sale_id,'PROPERTY_ADDRESS',:normalized_address,
                :normalized_value,'properties.normalized_address',90)
              ON CONFLICT(sheriff_sale_id,evidence_type,normalized_value,source_location) DO NOTHING"""),
              [{**row,"normalized_value":normalize_text(row["normalized_address"])} for row in addresses])
        result = connection.execute(text("""INSERT INTO sheriff_sale_parcels
          (sheriff_sale_id,parcel_id,relationship,match_status,match_score,match_method,
           evidence_summary,resolver_version)
          SELECT DISTINCT ss.id,cp.id,'PRIMARY','VERIFIED',f.match_confidence,f.match_method,
            jsonb_build_object('municipality_code',trim(f.municipality_code),'block',f.block,
              'lot',f.lot,'qualifier',f.qualifier,'source_hash',f.source_hash),
            'legacy-avm-backfill-v1'
          FROM sheriff_sales ss JOIN properties p ON p.id=ss.property_id
          JOIN property_avm_features f ON f.property_id=p.id
          JOIN parcels cp ON cp.state='NJ' AND cp.municipality_code=trim(f.municipality_code)
            AND cp.block=f.block AND cp.lot=f.lot AND cp.qualifier=f.qualifier
          WHERE p.state='NJ' AND p.county='Monmouth' AND f.match_confidence>=90
          ON CONFLICT(sheriff_sale_id,parcel_id) DO NOTHING"""))
        alias_rows = [dict(row) for row in connection.execute(text("""SELECT
          lower(regexp_replace(p.city,'[^A-Za-z0-9]','','g')) normalized_alias,
          min(cp.jurisdiction_id) jurisdiction_id,min(p.city) alias
          FROM sheriff_sale_parcels ssp JOIN sheriff_sales ss ON ss.id=ssp.sheriff_sale_id
          JOIN properties p ON p.id=ss.property_id JOIN parcels cp ON cp.id=ssp.parcel_id
          WHERE ssp.match_status IN ('VERIFIED','MANUALLY_VERIFIED') AND p.city IS NOT NULL
          GROUP BY lower(regexp_replace(p.city,'[^A-Za-z0-9]','','g'))
          HAVING count(DISTINCT cp.jurisdiction_id)=1""")).mappings()]
        if alias_rows:
            connection.execute(text("""INSERT INTO jurisdiction_aliases
              (jurisdiction_id,alias,normalized_alias,source)
              VALUES(:jurisdiction_id,:alias,:normalized_alias,'verified_sheriff_sale_match')
              ON CONFLICT(jurisdiction_id,normalized_alias) DO NOTHING"""),alias_rows)
        connection.execute(text("""UPDATE property_parcel_candidates c
          SET review_status='REJECTED',reviewed_at=NOW()
          FROM sheriff_sales ss JOIN sheriff_sale_parcels ssp ON ssp.sheriff_sale_id=ss.id
          WHERE ss.property_id=c.property_id AND c.review_status='PENDING'
            AND ssp.match_status IN ('VERIFIED','MANUALLY_VERIFIED')"""))
        return len(addresses), result.rowcount


def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument("--save",action="store_true")
    args=parser.parse_args(); count=eligible_count()
    print(f"Eligible verified sheriff-sale parcel links: {count}")
    if args.save:
        addresses,links=backfill(); print(f"Address evidence processed: {addresses}; links inserted: {links}")


if __name__ == "__main__":
    main()
