"""Resolve sheriff-sale parcels against the canonical statewide parcel index."""
from __future__ import annotations

import argparse
import json

from sqlalchemy import text

from app.database.session import engine
from pipeline.parcel_identity import address_corrobates,normalize_component,normalize_text
from pipeline.parse_sale_description import extract_parcel_identifiers, normalize_text as normalize_description

RESOLVER_VERSION = "nj-canonical-rules-v1"


def unresolved_sales(county: str) -> list[dict]:
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(text("""SELECT DISTINCT ON (p.id)
          ss.id sheriff_sale_id,p.id property_id,p.normalized_address,p.street_address,
          p.city,p.zip_code,ss.description_text
          FROM sheriff_sales ss JOIN properties p ON p.id=ss.property_id
          LEFT JOIN sheriff_sale_parcels ssp ON ssp.sheriff_sale_id=ss.id
            AND ssp.match_status IN ('VERIFIED','MANUALLY_VERIFIED')
          WHERE p.state='NJ' AND p.county=:county AND ss.current_sale_date>=CURRENT_DATE
            AND ssp.id IS NULL
          ORDER BY p.id,ss.current_sale_date"""),{"county":county}).mappings()]


def exact_candidates(sale: dict, county: str) -> tuple[list[dict], str | None]:
    alias=normalize_text(sale["city"]).casefold()
    address=normalize_text(sale["street_address"])
    with engine.connect() as connection:
        codes=[row[0] for row in connection.execute(text("""SELECT DISTINCT j.municipality_code
          FROM jurisdiction_aliases a JOIN jurisdictions j ON j.id=a.jurisdiction_id
          WHERE j.state='NJ' AND j.county=:county AND a.normalized_alias=:alias"""),
          {"county":county,"alias":alias})]
        if len(codes)!=1:
            return [], "municipality alias is missing or ambiguous"
        rows=connection.execute(text("""SELECT p.*,ps.source_year,ps.property_class,
          ps.property_location,ps.acreage,ps.zoning,ps.building_class,ps.year_built,
          ps.land_assessed,ps.improvement_assessed,ps.total_assessed,ps.annual_property_tax,
          ps.census_tract,ps.property_use_code,ps.source_hash
          FROM parcels p LEFT JOIN LATERAL(SELECT * FROM parcel_snapshots
            WHERE parcel_id=p.id ORDER BY source_year DESC,id DESC LIMIT 1)ps ON TRUE
          WHERE p.state='NJ' AND p.county=:county AND p.municipality_code=:code
            AND p.normalized_address=:address"""),
          {"county":county,"code":codes[0],"address":address}).mappings()
        return [dict(row) for row in rows],None


def legal_identifier_candidates(sale: dict, county: str) -> tuple[list[tuple[dict, list[dict]]], str | None]:
    identifiers=extract_parcel_identifiers(normalize_description(sale.get("description_text") or ""))
    if not identifiers:
        return [],"no legal parcel identifiers"
    address=sale["normalized_address"]
    results=[]
    inferred_code=None
    with engine.connect() as connection:
        for identifier in identifiers:
            conditions=["p.state='NJ'","p.county=:county","p.block=:block","p.lot=:lot"]
            params={"county":county,"block":normalize_component(identifier["block"]),
                    "lot":normalize_component(identifier["lot"])}
            if identifier.get("qualifier"):
                conditions.append("p.qualifier=:qualifier")
                params["qualifier"]=normalize_component(identifier["qualifier"])
            if inferred_code:
                conditions.append("p.municipality_code=:inferred_code")
                params["inferred_code"]=inferred_code
            rows=[dict(row) for row in connection.execute(text(f"""SELECT p.*,ps.source_year,
              ps.property_class,ps.property_location,ps.acreage,ps.zoning,ps.building_class,
              ps.year_built,ps.land_assessed,ps.improvement_assessed,ps.total_assessed,
              ps.annual_property_tax,ps.census_tract,ps.property_use_code,ps.source_hash
              FROM parcels p LEFT JOIN LATERAL(SELECT * FROM parcel_snapshots
                WHERE parcel_id=p.id ORDER BY source_year DESC,id DESC LIMIT 1)ps ON TRUE
              WHERE {' AND '.join(conditions)}"""),params).mappings()]
            if not rows and inferred_code and "." in identifier["lot"]:
                fallback_params={"county":county,"code":inferred_code,
                  "block":params["block"],
                  "lot":normalize_component(identifier["lot"].split(".",1)[0])}
                fallback=[dict(row) for row in connection.execute(text("""SELECT p.*,ps.source_year,
                  ps.property_class,ps.property_location,ps.acreage,ps.zoning,ps.building_class,
                  ps.year_built,ps.land_assessed,ps.improvement_assessed,ps.total_assessed,
                  ps.annual_property_tax,ps.census_tract,ps.property_use_code,ps.source_hash
                  FROM parcels p LEFT JOIN LATERAL(SELECT * FROM parcel_snapshots
                    WHERE parcel_id=p.id ORDER BY source_year DESC,id DESC LIMIT 1)ps ON TRUE
                  WHERE p.state='NJ' AND p.county=:county AND p.municipality_code=:code
                    AND p.block=:block AND p.lot=:lot"""),fallback_params).mappings()]
                if len(fallback)==1:
                    fallback[0]["legal_lot_alias"]=identifier["lot"]
                    rows=fallback
            if len(rows)>1:
                address_rows=[row for row in rows if address_corrobates(address,row["current_address"])]
                if address_rows: rows=address_rows
            if len(rows)==1 and address_corrobates(address,rows[0]["current_address"]):
                inferred_code=rows[0]["municipality_code"]
            results.append((identifier,rows))
    return results,None


def save_exact_match(sale: dict, parcel: dict,
                     match_method: str = "unique municipality-restricted exact address",
                     components: dict | None = None,
                     legal_identifier: dict | None = None) -> None:
    components=components or {"municipality_alias_verified":25,"address_exact":20,
                              "unique_exact_candidate":55}
    with engine.begin() as connection:
        connection.execute(text("""INSERT INTO parcel_match_candidates
          (sheriff_sale_id,parcel_id,rank,total_score,score_components,decision,resolver_version)
          VALUES(:sale,:parcel,1,100,CAST(:components AS JSONB),'ACCEPTED',:version)
          ON CONFLICT(sheriff_sale_id,parcel_id,resolver_version) DO UPDATE SET
            total_score=100,score_components=EXCLUDED.score_components,decision='ACCEPTED',reviewed_at=NOW()"""),
          {"sale":sale["sheriff_sale_id"],"parcel":parcel["id"],
           "components":json.dumps(components),"version":RESOLVER_VERSION})
        connection.execute(text("""INSERT INTO sheriff_sale_parcels
          (sheriff_sale_id,parcel_id,relationship,match_status,match_score,match_method,
           evidence_summary,resolver_version)
          VALUES(:sale,:parcel,'PRIMARY','VERIFIED',100,:method,
            CAST(:components AS JSONB),:version)
          ON CONFLICT(sheriff_sale_id,parcel_id) DO NOTHING"""),
          {"sale":sale["sheriff_sale_id"],"parcel":parcel["id"],"method":match_method,
           "components":json.dumps(components),"version":RESOLVER_VERSION})
        if legal_identifier:
            evidence=[]
            for evidence_type,key in (("LEGAL_BLOCK","block"),("LEGAL_LOT","lot"),
                                      ("LEGAL_QUALIFIER","qualifier")):
                if legal_identifier.get(key):
                    evidence.append({"sale":sale["sheriff_sale_id"],"type":evidence_type,
                      "raw":legal_identifier[key],"normalized":normalize_component(legal_identifier[key])})
            if evidence:
                connection.execute(text("""INSERT INTO parcel_identity_evidence
                  (sheriff_sale_id,evidence_type,raw_value,normalized_value,source_location,confidence)
                  VALUES(:sale,:type,:raw,:normalized,'sheriff_sales.description_text',100)
                  ON CONFLICT(sheriff_sale_id,evidence_type,normalized_value,source_location) DO NOTHING"""),evidence)
        connection.execute(text("""UPDATE properties SET block=:block,lot=:lot,
          qualifier=:qualifier,pams_pin=:pams_pin,identity_confidence=100,updated_at=NOW()
          WHERE id=:property"""),{**parcel,"property":sale["property_id"]})
        connection.execute(text("""UPDATE property_parcel_candidates SET review_status='REJECTED',
          reviewed_at=NOW() WHERE property_id=:property AND review_status='PENDING'"""),
          {"property":sale["property_id"]})
        if parcel.get("source_year") is not None:
            connection.execute(text("""INSERT INTO property_avm_features(property_id,snapshot_year,
              municipality_code,block,lot,qualifier,property_class,property_location,acreage,zoning,
              building_class,year_built,land_assessed,improvement_assessed,total_assessed,
              annual_property_tax,census_tract,property_use_code,match_method,match_confidence,source_hash)
              VALUES(:property,:source_year,:municipality_code,:block,:lot,:qualifier,:property_class,
              :property_location,:acreage,:zoning,:building_class,:year_built,:land_assessed,
              :improvement_assessed,:total_assessed,:annual_property_tax,:census_tract,
              :property_use_code,:method,100,:source_hash)
              ON CONFLICT(property_id) DO UPDATE SET snapshot_year=EXCLUDED.snapshot_year,
              municipality_code=EXCLUDED.municipality_code,block=EXCLUDED.block,lot=EXCLUDED.lot,
              qualifier=EXCLUDED.qualifier,property_location=EXCLUDED.property_location,
              match_method=EXCLUDED.match_method,match_confidence=EXCLUDED.match_confidence,
              source_hash=EXCLUDED.source_hash,matched_at=NOW()"""),
              {**parcel,"property":sale["property_id"],"method":match_method})


def save_multi_match(sale: dict, legal: list[tuple[dict,list[dict]]]) -> None:
    pairs=[(identifier,candidates[0]) for identifier,candidates in legal]
    primary_identifier,primary=max(pairs,key=lambda pair: pair[1].get("improvement_assessed") or 0)
    components={"all_legal_identifiers_exact":60,"single_municipality":20,
                "primary_address_corroborated":20,"parcel_count":len(pairs)}
    save_exact_match(sale,primary,"verified multi-parcel legal identifiers",components,primary_identifier)
    numeric_fields=("acreage","land_assessed","improvement_assessed","total_assessed",
                    "annual_property_tax")
    aggregates={name:sum((parcel.get(name) or 0 for _,parcel in pairs),0) for name in numeric_fields}
    with engine.begin() as connection:
        for rank,(identifier,parcel) in enumerate(pairs,1):
            if parcel["id"]==primary["id"]:
                continue
            connection.execute(text("""INSERT INTO parcel_match_candidates
              (sheriff_sale_id,parcel_id,rank,total_score,score_components,decision,resolver_version)
              VALUES(:sale,:parcel,:rank,95,CAST(:components AS JSONB),'ACCEPTED',:version)
              ON CONFLICT(sheriff_sale_id,parcel_id,resolver_version) DO UPDATE SET
                rank=EXCLUDED.rank,total_score=95,score_components=EXCLUDED.score_components,
                decision='ACCEPTED',reviewed_at=NOW()"""),{"sale":sale["sheriff_sale_id"],
                "parcel":parcel["id"],"rank":rank,"components":json.dumps(components),
                "version":RESOLVER_VERSION})
            connection.execute(text("""INSERT INTO sheriff_sale_parcels
              (sheriff_sale_id,parcel_id,relationship,match_status,match_score,match_method,
               evidence_summary,resolver_version)
              VALUES(:sale,:parcel,'ADDITIONAL','VERIFIED',95,'verified multi-parcel legal identifiers',
                CAST(:components AS JSONB),:version)
              ON CONFLICT(sheriff_sale_id,parcel_id) DO NOTHING"""),{"sale":sale["sheriff_sale_id"],
                "parcel":parcel["id"],"components":json.dumps(components),"version":RESOLVER_VERSION})
            evidence=[{"sale":sale["sheriff_sale_id"],"type":f"LEGAL_{key.upper()}",
              "raw":value,"normalized":normalize_component(value)}
              for key,value in identifier.items() if value]
            if evidence:
                connection.execute(text("""INSERT INTO parcel_identity_evidence
                  (sheriff_sale_id,evidence_type,raw_value,normalized_value,source_location,confidence)
                  VALUES(:sale,:type,:raw,:normalized,'sheriff_sales.description_text',100)
                  ON CONFLICT(sheriff_sale_id,evidence_type,normalized_value,source_location) DO NOTHING"""),evidence)
        connection.execute(text("""UPDATE property_avm_features SET acreage=:acreage,
          land_assessed=:land_assessed,improvement_assessed=:improvement_assessed,
          total_assessed=:total_assessed,annual_property_tax=:annual_property_tax,
          match_method='verified multi-parcel legal identifiers; numeric features aggregated',
          match_confidence=95,matched_at=NOW() WHERE property_id=:property"""),
          {**aggregates,"property":sale["property_id"]})


def resolve(county: str, save: bool) -> dict[str,int]:
    counts={"resolved":0,"multi_parcel_ready":0,"ambiguous":0,"no_alias_or_match":0}
    for sale in unresolved_sales(county):
        legal,legal_reason=legal_identifier_candidates(sale,county)
        legal_codes={candidates[0]["municipality_code"] for _,candidates in legal if len(candidates)==1}
        if legal and all(len(candidates)==1 for _,candidates in legal) and len(legal_codes)==1:
            if len(legal)==1:
                parcel=legal[0][1][0]; counts["resolved"]+=1
                print(f"LEGAL ID: {sale['normalized_address']} -> {parcel['pams_pin']}")
                if save: save_exact_match(sale,parcel,
                  "legal block/lot corroborated by address",
                  {"legal_block_exact":30,"legal_lot_exact":30,"address_corroborated":40},
                  legal[0][0])
            else:
                counts["multi_parcel_ready"]+=1
                pins=",".join(candidates[0]["pams_pin"] for _,candidates in legal)
                print(f"MULTI-PARCEL READY: {sale['normalized_address']} -> {pins}")
                if save: save_multi_match(sale,legal)
            continue
        if legal and (any(len(candidates)!=1 for _,candidates in legal) or len(legal_codes)!=1):
            counts["ambiguous"]+=1
            summary=",".join(f"{item['block']}/{item['lot']}={len(candidates)}" for item,candidates in legal)
            if len(legal_codes)>1: summary+=f",municipality_conflict={sorted(legal_codes)}"
            print(f"LEGAL REVIEW ({summary}): {sale['normalized_address']}")
            continue
        candidates,reason=exact_candidates(sale,county)
        if len(candidates)==1:
            counts["resolved"]+=1
            print(f"EXACT: {sale['normalized_address']} -> {candidates[0]['pams_pin']}")
            if save: save_exact_match(sale,candidates[0])
        elif len(candidates)>1:
            counts["ambiguous"]+=1
            print(f"REVIEW ({len(candidates)} exact candidates): {sale['normalized_address']}")
        else:
            counts["no_alias_or_match"]+=1
            print(f"UNRESOLVED ({legal_reason or reason or 'no exact address'}): {sale['normalized_address']}")
    return counts


def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument("--county",required=True)
    parser.add_argument("--save",action="store_true"); args=parser.parse_args()
    print(resolve(args.county,args.save))


if __name__ == "__main__": main()
