"""Load PA sheriff-sale snapshots without applying NJ address assumptions."""
import argparse,hashlib,json,uuid,re
from datetime import datetime,timezone
from pathlib import Path
from sqlalchemy import text
from app.database.session import engine
from pipeline.pa_parcel_numbers import normalize_map_number

FILES={"Butler":Path("data/sheriff_sales/pa_butler_sheriff_sales.json"),
 "Centre":Path("data/sheriff_sales/pa_centre_sheriff_sales.json"),
 "Cumberland":Path("data/sheriff_sales/pa_cumberland_sheriff_sales.json"),
 "Franklin":Path("data/sheriff_sales/pa_franklin_sheriff_sales.json"),
 "Greene":Path("data/sheriff_sales/pa_greene_sheriff_sales.json"),
 "Lancaster":Path("data/sheriff_sales/pa_lancaster_sheriff_sales.json"),
 "Luzerne":Path("data/sheriff_sales/pa_luzerne_sheriff_sales.json"),
 "Monroe":Path("data/sheriff_sales/pa_monroe_sheriff_sales.json"),
 "Susquehanna":Path("data/sheriff_sales/pa_susquehanna_sheriff_sales.json")}

def address_parts(raw):
 value=" ".join(raw.split()); match=re.search(r"\bPA\s+(\d{5})(?:-\d{4})?\b",value,re.I)
 zip_code=match.group(1) if match else None; before=value[:match.start()].strip(" ,") if match else value
 city_match=re.search(r"([A-Za-z][A-Za-z .'-]{1,30}),?$",before)
 city=city_match.group(1).strip() if city_match else "Unknown"
 return value,before,city,zip_code

from pipeline.adapters.pa_sale_listing import PARCEL_LINE

def portal_address(lines):
 """Street, city, ZIP and municipality from a county portal's address lines:
 ["95 Greenwood Circle", "Wormleysburg - Borough", "Wormleysburg, PA 17043", "Wormleysburg Borough"]."""
 if not lines:return None
 for index,line in enumerate(lines[1:],1):
  match=re.match(r"\s*(.+?),\s*PA\b\s*(\d{5})?",line,re.I)
  if match:
   rest=[l for l in lines[index+1:] if not PARCEL_LINE.match(l)]
   return " ".join(lines[0].split()),match.group(1).strip(),match.group(2),(rest[-1].strip() if rest else None)
 return None

def load(county,path):
 records=json.loads(path.read_text()); run=str(uuid.uuid4()); now=datetime.now(timezone.utc)
 created=updated=0
 with engine.begin() as c:
  c.execute(text("""INSERT INTO scrape_runs(id,job_name,county,source_system,started_at,status,records_found)
   VALUES(:id,:job,:county,'pa_sheriff_sale_listing',:now,'running',:count)"""),
   {"id":run,"job":f"pa_{county.lower()}_sheriff_scrape","county":county,"now":now,"count":len(records)})
  for record in records:
   raw_payload=record.get("raw_payload") or {}
   raw_address=record["address"];normalized,street,city,zip_code=address_parts(raw_address)
   # The hash stays on the legacy one-line address so reloads match existing properties.
   address_hash=hashlib.sha256(f"PA|{county}|{normalized.upper()}".encode()).hexdigest()
   municipality=raw_payload.get("township") or city
   if (lines:=portal_address(raw_payload.get("address_lines"))):
    street,city,zip_code,municipality=lines;municipality=municipality or city
    normalized=f"{street}, {city}, PA {zip_code}" if zip_code else f"{street}, {city}, PA"
   property_id=c.execute(text("""INSERT INTO properties(id,normalized_address,street_address,city,
    municipality,county,state,zip_code,address_hash,data_quality_score) VALUES(:id,:normalized,:street,
    :city,:municipality,:county,'PA',:zip,:hash,70) ON CONFLICT(address_hash) DO UPDATE SET
    municipality=EXCLUDED.municipality,normalized_address=EXCLUDED.normalized_address,
    street_address=EXCLUDED.street_address,city=EXCLUDED.city,zip_code=EXCLUDED.zip_code,updated_at=NOW()
    RETURNING id"""),{"id":str(uuid.uuid4()),"normalized":normalized,"street":street,"city":city,
      "municipality":municipality,"county":county,"zip":zip_code,"hash":address_hash}).scalar_one()
   content_hash=hashlib.sha256(json.dumps(record,sort_keys=True,default=str).encode()).hexdigest()
   c.execute(text("""INSERT INTO raw_scrape_records(id,scrape_run_id,state,county,source_record_id,
    source_url,raw_payload,content_hash,parsing_status,scraped_at) VALUES(:id,:run,'PA',:county,
    :number,:url,CAST(:payload AS JSONB),:hash,'parsed',:now) ON CONFLICT DO NOTHING"""),
    {"id":str(uuid.uuid4()),"run":run,"county":county,"number":record["sheriff_number"],
     "url":record["source_url"],"payload":json.dumps(record),"hash":content_hash,"now":now})
   existing=c.execute(text("SELECT id FROM sheriff_sales WHERE state='PA' AND county=:county AND sheriff_number=:number"),
    {"county":county,"number":record["sheriff_number"]}).scalar()
   params={"id":existing or str(uuid.uuid4()),"property_id":property_id,"county":county,
    "number":record["sheriff_number"],"case":record.get("court_case_number"),"plaintiff":record.get("plaintiff"),
    "defendant":record.get("defendant"),"sale_date":record.get("sale_date"),"status":record.get("status") or "unknown",
    "judgment":record.get("judgment_amount"),"url":record.get("source_url"),"now":now,"hash":content_hash,
    "property_number":str(raw_payload.get("auction_id")) if raw_payload.get("auction_id") is not None else None,
    "map_number":raw_payload.get("parcel_number"),
    "normalized_map_number":normalize_map_number(raw_payload.get("parcel_number")),
    "attorney":raw_payload.get("attorney") or record.get("plaintiff_attorney"),
    "result":raw_payload.get("raw_status")}
   if existing:
    c.execute(text("""UPDATE sheriff_sales SET property_id=:property_id,court_case_number=:case,
     plaintiff=:plaintiff,defendant=:defendant,current_sale_date=:sale_date,current_status=:status,
     judgment_amount=:judgment,source_url=:url,last_seen_at=:now,last_scraped_at=:now,
     raw_source_hash=:hash,property_number=:property_number,map_number=:map_number,
     normalized_map_number=:normalized_map_number,sale_attorney=:attorney,sale_result=:result,
     updated_at=NOW() WHERE id=:id"""),params);updated+=1
   else:
    c.execute(text("""INSERT INTO sheriff_sales(id,property_id,state,county,sheriff_number,court_case_number,
     plaintiff,defendant,current_sale_date,current_status,judgment_amount,source_url,source_system,
     first_seen_at,last_seen_at,last_scraped_at,raw_source_hash,is_active,property_number,map_number,
     normalized_map_number,sale_attorney,sale_result) VALUES(:id,:property_id,'PA',
     :county,:number,:case,:plaintiff,:defendant,:sale_date,:status,:judgment,:url,
     'pa_sheriff_sale_listing',:now,:now,:now,:hash,TRUE,:property_number,:map_number,
     :normalized_map_number,:attorney,:result)"""),params);created+=1
   c.execute(text("""INSERT INTO sheriff_sale_status_history(id,sheriff_sale_id,status,sale_date,
    upset_price,observed_at,source_url,raw_status)
    SELECT :history_id,:sale_id,:status,:sale_date,:upset_price,:now,:url,:raw_status
    WHERE NOT EXISTS(SELECT 1 FROM sheriff_sale_status_history WHERE sheriff_sale_id=:sale_id
      AND status=:status AND sale_date IS NOT DISTINCT FROM :sale_date
      AND COALESCE(raw_status,'')=COALESCE(:raw_status,''))"""),
    {"history_id":str(uuid.uuid4()),"sale_id":params["id"],"status":params["status"],
     "sale_date":params["sale_date"],"upset_price":record.get("upset_price"),"now":now,
     "url":params["url"],"raw_status":raw_payload.get("raw_status")})
  # Portal snapshots list every upcoming sale, so an open case missing from one
  # has been sold, cancelled or pulled; the portal does not say which.
  dropped=0
  if records and all("listed_sale_date" in (r.get("raw_payload") or {}) for r in records):
   dropped_ids=c.execute(text("""UPDATE sheriff_sales SET current_status='sold_or_cancelled_unverified',
    updated_at=NOW() WHERE state='PA' AND county=:county AND source_system='pa_sheriff_sale_listing'
    AND current_status IN ('scheduled','adjourned') AND sheriff_number <> ALL(:numbers) RETURNING id"""),
    {"county":county,"numbers":[r["sheriff_number"] for r in records]}).scalars().all()
   for sale_id in dropped_ids:
    c.execute(text("""INSERT INTO sheriff_sale_status_history(id,sheriff_sale_id,status,observed_at,raw_status)
     VALUES(:id,:sale_id,'sold_or_cancelled_unverified',:now,'no longer on the sale listing')"""),
     {"id":str(uuid.uuid4()),"sale_id":sale_id,"now":now})
   dropped=len(dropped_ids)
  c.execute(text("""UPDATE scrape_runs SET completed_at=NOW(),status='completed',records_created=:created,
   records_updated=:updated WHERE id=:id"""),{"created":created,"updated":updated,"id":run})
 print(f"{county}: created {created}, updated {updated}, no longer listed {dropped}")

def main():
 p=argparse.ArgumentParser();p.add_argument("--counties",nargs="+",choices=sorted(FILES));p.add_argument("--all",action="store_true");a=p.parse_args()
 for county in (sorted(FILES) if a.all else a.counties or []):load(county,FILES[county])
if __name__=="__main__":main()
