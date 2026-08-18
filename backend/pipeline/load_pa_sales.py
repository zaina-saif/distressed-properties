"""Load PA sheriff-sale snapshots without applying NJ address assumptions."""
import argparse,hashlib,json,uuid,re
from datetime import datetime,timezone
from pathlib import Path
from sqlalchemy import text
from app.database.session import engine

FILES={"Butler":Path("data/sheriff_sales/pa_butler_sheriff_sales.json"),
 "Centre":Path("data/sheriff_sales/pa_centre_sheriff_sales.json"),
 "Cumberland":Path("data/sheriff_sales/pa_cumberland_sheriff_sales.json"),
 "Franklin":Path("data/sheriff_sales/pa_franklin_sheriff_sales.json"),
 "Greene":Path("data/sheriff_sales/pa_greene_sheriff_sales.json"),
 "Lancaster":Path("data/sheriff_sales/pa_lancaster_sheriff_sales.json"),
 "Luzerne":Path("data/sheriff_sales/pa_luzerne_sheriff_sales.json"),
 "Susquehanna":Path("data/sheriff_sales/pa_susquehanna_sheriff_sales.json")}

def address_parts(raw):
 value=" ".join(raw.split()); match=re.search(r"\bPA\s+(\d{5})(?:-\d{4})?\b",value,re.I)
 zip_code=match.group(1) if match else None; before=value[:match.start()].strip(" ,") if match else value
 city_match=re.search(r"([A-Za-z][A-Za-z .'-]{1,30}),?$",before)
 city=city_match.group(1).strip() if city_match else "Unknown"
 return value,before,city,zip_code

def load(county,path):
 records=json.loads(path.read_text()); run=str(uuid.uuid4()); now=datetime.now(timezone.utc)
 created=updated=0
 with engine.begin() as c:
  c.execute(text("""INSERT INTO scrape_runs(id,job_name,county,source_system,started_at,status,records_found)
   VALUES(:id,:job,:county,'pa_sheriff_sale_listing',:now,'running',:count)"""),
   {"id":run,"job":f"pa_{county.lower()}_sheriff_scrape","county":county,"now":now,"count":len(records)})
  for record in records:
   raw_address=record["address"];normalized,street,city,zip_code=address_parts(raw_address)
   address_hash=hashlib.sha256(f"PA|{county}|{normalized.upper()}".encode()).hexdigest()
   property_id=c.execute(text("""INSERT INTO properties(id,normalized_address,street_address,city,
    municipality,county,state,zip_code,address_hash,data_quality_score) VALUES(:id,:normalized,:street,
    :city,:city,:county,'PA',:zip,:hash,70) ON CONFLICT(address_hash) DO UPDATE SET updated_at=NOW()
    RETURNING id"""),{"id":str(uuid.uuid4()),"normalized":normalized,"street":street,"city":city,
      "county":county,"zip":zip_code,"hash":address_hash}).scalar_one()
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
    "judgment":record.get("judgment_amount"),"url":record.get("source_url"),"now":now,"hash":content_hash}
   if existing:
    c.execute(text("""UPDATE sheriff_sales SET property_id=:property_id,court_case_number=:case,
     plaintiff=:plaintiff,defendant=:defendant,current_sale_date=:sale_date,current_status=:status,
     judgment_amount=:judgment,source_url=:url,last_seen_at=:now,last_scraped_at=:now,
     raw_source_hash=:hash,updated_at=NOW() WHERE id=:id"""),params);updated+=1
   else:
    c.execute(text("""INSERT INTO sheriff_sales(id,property_id,state,county,sheriff_number,court_case_number,
     plaintiff,defendant,current_sale_date,current_status,judgment_amount,source_url,source_system,
     first_seen_at,last_seen_at,last_scraped_at,raw_source_hash,is_active) VALUES(:id,:property_id,'PA',
     :county,:number,:case,:plaintiff,:defendant,:sale_date,:status,:judgment,:url,
     'pa_sheriff_sale_listing',:now,:now,:now,:hash,TRUE)"""),params);created+=1
  c.execute(text("""UPDATE scrape_runs SET completed_at=NOW(),status='completed',records_created=:created,
   records_updated=:updated WHERE id=:id"""),{"created":created,"updated":updated,"id":run})
 print(f"{county}: created {created}, updated {updated}")

def main():
 p=argparse.ArgumentParser();p.add_argument("--counties",nargs="+",choices=sorted(FILES));p.add_argument("--all",action="store_true");a=p.parse_args()
 for county in (sorted(FILES) if a.all else a.counties or []):load(county,FILES[county])
if __name__=="__main__":main()
