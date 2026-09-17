"""Import safe fields from Kane County's official 2025 parcel layers."""
from __future__ import annotations
import argparse
from decimal import Decimal
from typing import Any,Iterator
import httpx
from psycopg2.extras import execute_values
from sqlalchemy import text
from app.database.session import warehouse_engine
from pipeline.public_property_records import decimal_value,stable_hash,text_value

SOURCE_ID="il_kane_open_parcels_2025";SOURCE_PAGE="https://www.arcgis.com/home/item.html?id=20eece40e17e4fb5b613602baa74b6fe"
URLS=("https://services1.arcgis.com/oRKmdBXD6EbdmVgJ/arcgis/rest/services/KaneCo_IL_Parcels/FeatureServer/0/query","https://services1.arcgis.com/oRKmdBXD6EbdmVgJ/arcgis/rest/services/KaneCo_IL_Parcels_Condos/FeatureServer/1/query")
FIELDS=("OBJECTID","PIN","Township","TaxCode","UseCode","UseCodeDescription","SiteAddress","SiteCity","SiteZip","RecordedAcreage")
COLUMNS=("source_id","state","county","source_parcel_id","snapshot_year","street_address","city","zip_code","property_type","land_use_code","land_area","land_area_unit","source_hash")
SQL=f"""INSERT INTO public_property_snapshots ({','.join(COLUMNS)}) VALUES %s ON CONFLICT(source_id,source_parcel_id,snapshot_year) DO UPDATE SET street_address=EXCLUDED.street_address,city=EXCLUDED.city,zip_code=EXCLUDED.zip_code,property_type=EXCLUDED.property_type,land_use_code=EXCLUDED.land_use_code,land_area=EXCLUDED.land_area,land_area_unit=EXCLUDED.land_area_unit,source_hash=EXCLUDED.source_hash,imported_at=NOW() WHERE public_property_snapshots.source_hash<>EXCLUDED.source_hash"""

def parcel_id(v:Any)->str|None:
 v=text_value(v);return f"IL:KANE:{''.join(c for c in v.upper() if c.isalnum())}" if v else None
def parse(r:dict[str,Any])->tuple[Any,...]|None:
 identity=parcel_id(r.get("PIN"));area=decimal_value(r.get("RecordedAcreage"))
 if not identity:return None
 if area is not None and not Decimal(0)<=area<Decimal("1000000000000"):area=None
 core={"source_id":SOURCE_ID,"state":"IL","county":"Kane","source_parcel_id":identity,"snapshot_year":2025,"street_address":text_value(r.get("SiteAddress")),"city":text_value(r.get("SiteCity")),"zip_code":text_value(r.get("SiteZip")),"property_type":text_value(r.get("UseCodeDescription")),"land_use_code":text_value(r.get("UseCode")),"land_area":area,"land_area_unit":"acres"}
 return tuple(core[n] for n in COLUMNS[:-1])+(stable_hash(core),)
def pages(client:httpx.Client,url:str,size:int)->Iterator[list[dict[str,Any]]]:
 after=0
 while True:
  response=client.get(url,params={"where":f"OBJECTID>{after}","outFields":','.join(FIELDS),"returnGeometry":"false","orderByFields":"OBJECTID","resultRecordCount":size,"f":"json"});response.raise_for_status();payload=response.json()
  if payload.get("error"):raise RuntimeError(payload["error"])
  rows=[x["attributes"] for x in payload.get("features",[])]
  if not rows:break
  yield rows;after=rows[-1]["OBJECTID"]
  if len(rows)<size:break
def main()->None:
 ap=argparse.ArgumentParser();ap.add_argument("--page-size",type=int,default=2000);ap.add_argument("--batch-size",type=int,default=10000);a=ap.parse_args()
 with warehouse_engine.begin() as c:c.execute(text("""INSERT INTO public_data_sources(source_id,state,county,source_name,source_url,access_method,coverage_notes,last_checked_at) VALUES(:id,'IL','Kane','Kane County 2025 Parcels and Condos',:url,'ArcGIS FeatureServer','2025 parcel and condo PIN, situs, use and recorded acreage; mailing and legal fields excluded',NOW()) ON CONFLICT(source_id) DO UPDATE SET last_checked_at=NOW(),updated_at=NOW()"""),{"id":SOURCE_ID,"url":SOURCE_PAGE})
 raw=warehouse_engine.raw_connection();loaded=0;batch={}
 try:
  cursor=raw.cursor()
  with httpx.Client(timeout=180,follow_redirects=True) as client:
   for url in URLS:
    for page in pages(client,url,a.page_size):
     for source in page:
      row=parse(source)
      if row:batch[row[3]]=row
     if len(batch)>=a.batch_size:execute_values(cursor,SQL,list(batch.values()),page_size=a.batch_size);loaded+=len(batch);batch.clear();raw.commit();print(f"Kane parcels: {loaded:,}",flush=True)
   if batch:execute_values(cursor,SQL,list(batch.values()),page_size=a.batch_size);loaded+=len(batch);raw.commit()
 finally:raw.close()
 print(f"complete Kane parcel snapshots={loaded:,}")
if __name__=="__main__":main()
