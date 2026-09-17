"""Import non-personal fields from McHenry County's official tax parcels."""
from __future__ import annotations

import argparse
from decimal import Decimal
from typing import Any, Iterator

import httpx
from psycopg2.extras import execute_values
from sqlalchemy import text

from app.database.session import warehouse_engine
from pipeline.public_property_records import decimal_value, stable_hash, text_value

SOURCE_ID="il_mchenry_open_parcels_2026"
SOURCE_PAGE="https://www.arcgis.com/home/item.html?id=723960c3086940dd9784f69d897c1c7b"
QUERY_URL="https://services1.arcgis.com/6iYC5AXXYapRVNzl/arcgis/rest/services/McHenry_County_TaxParcels/FeatureServer/0/query"
FIELDS=("OBJECTID","ParcelNumber","Township","TaxStatus","PropertyClass","SiteAddress","SiteCity","SiteZip","Latitude","Longitude","ParcelArea")
COLUMNS=("source_id","state","county","source_parcel_id","snapshot_year","street_address","city","zip_code","longitude","latitude","property_type","land_use_code","land_area","land_area_unit","source_hash")
SQL=f"""INSERT INTO public_property_snapshots ({','.join(COLUMNS)}) VALUES %s
ON CONFLICT(source_id,source_parcel_id,snapshot_year) DO UPDATE SET street_address=EXCLUDED.street_address,
 city=EXCLUDED.city,zip_code=EXCLUDED.zip_code,longitude=EXCLUDED.longitude,latitude=EXCLUDED.latitude,
 property_type=EXCLUDED.property_type,land_use_code=EXCLUDED.land_use_code,land_area=EXCLUDED.land_area,
 land_area_unit=EXCLUDED.land_area_unit,source_hash=EXCLUDED.source_hash,imported_at=NOW()
WHERE public_property_snapshots.source_hash<>EXCLUDED.source_hash"""


def parcel_id(value:Any)->str|None:
    value=text_value(value); return f"IL:MCHENRY:{''.join(c for c in value.upper() if c.isalnum())}" if value else None


def parse(row:dict[str,Any])->tuple[Any,...]|None:
    identity=parcel_id(row.get("ParcelNumber")); area=decimal_value(row.get("ParcelArea"))
    if not identity:return None
    if area is not None and not Decimal(0)<=area<Decimal("1000000000000"):area=None
    prop=text_value(row.get("PropertyClass")); core={"source_id":SOURCE_ID,"state":"IL","county":"McHenry",
      "source_parcel_id":identity,"snapshot_year":2026,"street_address":text_value(row.get("SiteAddress")),
      "city":text_value(row.get("SiteCity")),"zip_code":text_value(row.get("SiteZip")),
      "longitude":decimal_value(row.get("Longitude")),"latitude":decimal_value(row.get("Latitude")),
      "property_type":prop,"land_use_code":prop,"land_area":area,"land_area_unit":"square feet"}
    return tuple(core[n] for n in COLUMNS[:-1])+(stable_hash(core),)


def pages(client:httpx.Client,size:int)->Iterator[list[dict[str,Any]]]:
    after=0
    while True:
      response=client.get(QUERY_URL,params={"where":f"OBJECTID>{after}","outFields":','.join(FIELDS),"returnGeometry":"false","orderByFields":"OBJECTID","resultRecordCount":size,"f":"json"})
      response.raise_for_status(); payload=response.json()
      if payload.get("error"):raise RuntimeError(payload["error"])
      rows=[f["attributes"] for f in payload.get("features",[])]
      if not rows:break
      yield rows; after=rows[-1]["OBJECTID"]
      if len(rows)<size:break


def main()->None:
    ap=argparse.ArgumentParser();ap.add_argument("--page-size",type=int,default=2000);ap.add_argument("--batch-size",type=int,default=10000);args=ap.parse_args()
    with warehouse_engine.begin() as c:c.execute(text("""INSERT INTO public_data_sources(source_id,state,county,source_name,source_url,access_method,coverage_notes,last_checked_at)
      VALUES(:id,'IL','McHenry','McHenry County Tax Parcels',:url,'ArcGIS FeatureServer','Current parcel class, situs, area and coordinates; owner and mailing fields excluded',NOW())
      ON CONFLICT(source_id) DO UPDATE SET last_checked_at=NOW(),updated_at=NOW()"""),{"id":SOURCE_ID,"url":SOURCE_PAGE})
    raw=warehouse_engine.raw_connection();loaded=0;batch={}
    try:
      cursor=raw.cursor()
      with httpx.Client(timeout=180,follow_redirects=True) as client:
       for page in pages(client,args.page_size):
        for source in page:
         row=parse(source)
         if row:batch[row[3]]=row
        if len(batch)>=args.batch_size:
         execute_values(cursor,SQL,list(batch.values()),page_size=args.batch_size);loaded+=len(batch);batch.clear();raw.commit();print(f"McHenry parcels: {loaded:,}",flush=True)
      if batch:execute_values(cursor,SQL,list(batch.values()),page_size=args.batch_size);loaded+=len(batch);raw.commit()
    finally:raw.close()
    print(f"complete McHenry parcel snapshots={loaded:,}")


if __name__=="__main__":main()
