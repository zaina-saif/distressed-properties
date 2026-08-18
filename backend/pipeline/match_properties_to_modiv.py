"""Conservatively match sheriff-sale properties to current Monmouth MOD-IV."""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import asdict
from difflib import SequenceMatcher
from pathlib import Path

from sqlalchemy import text

from app.database.session import engine
from pipeline.load_nj_property_history import MODIV_FILES
from pipeline.nj_property_records import parse_modiv

BACKEND=Path(__file__).resolve().parents[1]

SUFFIXES={"AVENUE":"AVE","BOULEVARD":"BLVD","COURT":"CT","DRIVE":"DR","HIGHWAY":"HWY",
          "LANE":"LN","PLACE":"PL","ROAD":"RD","STREET":"ST","TERRACE":"TER","TURNPIKE":"TPKE"}

def street_key(value: str | None) -> str:
    tokens=re.findall(r"[A-Z0-9]+",(value or "").upper())
    return "".join(SUFFIXES.get(token,token) for token in tokens)

def street_parts(value: str | None) -> tuple[str | None,str]:
    tokens=re.findall(r"[A-Z0-9]+",(value or "").upper())
    number=tokens[0] if tokens and re.fullmatch(r"\d+[A-Z]?",tokens[0]) else None
    name="".join(SUFFIXES.get(token,token) for token in tokens[1:] if token not in {"AKA","FKA"})
    return number,name

def similarity(subject: str | None,candidate: str | None) -> float:
    subject_number,subject_name=street_parts(subject); candidate_number,candidate_name=street_parts(candidate)
    if not subject_number or subject_number != candidate_number or not subject_name or not candidate_name: return 0
    return SequenceMatcher(None,subject_name,candidate_name).ratio()

def current_modiv_index():
    year=max(MODIV_FILES); path=MODIV_FILES[year]; index=defaultdict(list)
    with path.open(encoding="latin-1") as handle:
        for line_number,line in enumerate(handle,1):
            row=parse_modiv(line,year,str(path),line_number)
            if row.property_class.strip()=="2" and row.property_location:
                index[street_key(row.property_location)].append(row)
    return year,index

def candidates():
    with engine.connect() as connection:
        return [dict(r) for r in connection.execute(text("""
            SELECT DISTINCT p.id AS property_id,p.normalized_address,p.street_address,p.unit_number,
              p.city,p.zip_code,p.data_quality_score
            FROM properties p JOIN sheriff_sales s ON s.property_id=p.id
            WHERE p.block IS NULL OR p.lot IS NULL
        """)).mappings()]

def verified_city_codes():
    with engine.connect() as connection:
        rows=connection.execute(text("""SELECT p.city,f.municipality_code,count(*)
          FROM properties p JOIN property_avm_features f ON f.property_id=p.id
          GROUP BY p.city,f.municipality_code"""))
        grouped=defaultdict(list)
        for city,code,count in rows: grouped[city].append((code,count))
    return {city:max(values,key=lambda value:value[1])[0] for city,values in grouped.items()
            if len({value[0] for value in values})==1}

def ranked_candidates(prop,parcels,city_codes):
    code=city_codes.get(prop["city"]); eligible=parcels
    if code: eligible=[parcel for parcel in parcels if parcel.municipality_code==code]
    ranked=sorted(((similarity(prop["street_address"],parcel.property_location),parcel)
                   for parcel in eligible),key=lambda item:item[0],reverse=True)
    return [(score,parcel) for score,parcel in ranked[:5] if score>0]

def save(matches):
    property_sql=text("""UPDATE properties SET block=:block,lot=:lot,qualifier=:qualifier,
        pams_pin=:pams_pin,identity_confidence=:confidence,updated_at=NOW() WHERE id=:property_id""")
    feature_sql=text("""INSERT INTO property_avm_features
        (property_id,snapshot_year,municipality_code,block,lot,qualifier,property_class,
         property_location,acreage,zoning,building_class,year_built,land_assessed,
         improvement_assessed,total_assessed,annual_property_tax,census_tract,
         property_use_code,match_method,match_confidence,source_hash)
        VALUES (:property_id,:snapshot_year,:municipality_code,:block,:lot,:qualifier,:property_class,
         :property_location,:acreage,:zoning,:building_class,:year_built,:land_assessed,
         :improvement_assessed,:total_assessed,:annual_property_tax,:census_tract,
         :property_use_code,:match_method,:confidence,:source_hash)
        ON CONFLICT(property_id) DO UPDATE SET snapshot_year=EXCLUDED.snapshot_year,
         municipality_code=EXCLUDED.municipality_code,block=EXCLUDED.block,lot=EXCLUDED.lot,
         qualifier=EXCLUDED.qualifier,property_class=EXCLUDED.property_class,
         property_location=EXCLUDED.property_location,acreage=EXCLUDED.acreage,zoning=EXCLUDED.zoning,
         building_class=EXCLUDED.building_class,year_built=EXCLUDED.year_built,
         land_assessed=EXCLUDED.land_assessed,improvement_assessed=EXCLUDED.improvement_assessed,
         total_assessed=EXCLUDED.total_assessed,annual_property_tax=EXCLUDED.annual_property_tax,
         census_tract=EXCLUDED.census_tract,property_use_code=EXCLUDED.property_use_code,
         match_method=EXCLUDED.match_method,match_confidence=EXCLUDED.match_confidence,
         source_hash=EXCLUDED.source_hash,matched_at=NOW()""")
    with engine.begin() as connection:
        for property_row,parcel,confidence,method in matches:
            common={"property_id":property_row["property_id"],"block":parcel.block,"lot":parcel.lot,
                "qualifier":parcel.qualifier,"confidence":confidence,
                "pams_pin":f"{parcel.municipality_code}_{parcel.block}_{parcel.lot}"+(f"_{parcel.qualifier}" if parcel.qualifier else "")}
            connection.execute(property_sql,common)
            data=asdict(parcel); data.update(common); data["snapshot_year"]=parcel.source_year
            data["match_method"]=method
            connection.execute(feature_sql,data)

def save_review_candidates(review):
    statement=text("""INSERT INTO property_parcel_candidates
      (property_id,rank,match_score,municipality_code,block,lot,qualifier,
       property_location,parcel_features,source_hash)
      VALUES (:property_id,:rank,:score,:municipality_code,:block,:lot,:qualifier,
       :property_location,CAST(:features AS JSONB),:source_hash)
      ON CONFLICT(property_id,source_hash) DO UPDATE SET rank=EXCLUDED.rank,
       match_score=EXCLUDED.match_score,property_location=EXCLUDED.property_location,
       parcel_features=EXCLUDED.parcel_features
      WHERE property_parcel_candidates.review_status='PENDING'""")
    payload=[]
    for item in review:
        for rank,candidate in enumerate(item.get("candidate_records",[]),1):
            parcel=candidate[1]; features=asdict(parcel)
            for key,value in list(features.items()):
                if hasattr(value,"isoformat"): features[key]=value.isoformat()
                elif not isinstance(value,(str,int,float,bool,type(None))): features[key]=str(value)
            payload.append({"property_id":item["property_id"],"rank":rank,"score":candidate[0],
                "municipality_code":parcel.municipality_code,"block":parcel.block,"lot":parcel.lot,
                "qualifier":parcel.qualifier,"property_location":parcel.property_location,
                "features":json.dumps(features),"source_hash":parcel.source_hash})
    if payload:
        with engine.begin() as connection: connection.execute(statement,payload)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--apply-migration",action="store_true")
    parser.add_argument("--match",action="store_true"); args=parser.parse_args()
    if args.apply_migration:
        migration=BACKEND/"migrations/009_property_avm_features.sql"
        with engine.begin() as c: c.execute(text(migration.read_text()))
        print("Migration 009 applied")
    if args.match:
        _,index=current_modiv_index(); parcels=[p for group in index.values() for p in group]
        accepted=[]; ambiguous=unmatched=0; review=[]; city_codes=verified_city_codes()
        for prop in candidates():
            options=index.get(street_key(prop["street_address"]),[])
            if len(options)==1:
                accepted.append((prop,options[0],95,"unique countywide normalized street address")); continue
            ranked=ranked_candidates(prop,parcels,city_codes)
            best=ranked[0][0] if ranked else 0; runner=ranked[1][0] if len(ranked)>1 else 0
            if best>=.94 and best-runner>=.08:
                accepted.append((prop,ranked[0][1],90,"municipality-restricted exact-number fuzzy street")); continue
            if options or ranked: ambiguous+=1
            else: unmatched+=1
            review.append({"property_id":str(prop["property_id"]),"address":prop["normalized_address"],
                "reason":"ambiguous candidates" if options or ranked else "no candidates",
                "candidate_records":ranked,
                "candidates":[{"score":round(score,3),"municipality_code":parcel.municipality_code,
                    "address":parcel.property_location,"block":parcel.block,"lot":parcel.lot,
                    "qualifier":parcel.qualifier} for score,parcel in ranked]})
        save(accepted)
        save_review_candidates(review)
        serializable=[{k:v for k,v in item.items() if k!="candidate_records"} for item in review]
        (BACKEND/"property_parcel_manual_review.json").write_text(json.dumps(serializable,indent=2)+"\n")
        print(f"Matched: {len(accepted)}; ambiguous: {ambiguous}; unmatched: {unmatched}")

if __name__=="__main__": main()
