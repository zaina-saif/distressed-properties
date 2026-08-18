"""Scrape configured NJ CivilView counties and optionally load each snapshot."""
from __future__ import annotations
import argparse,asyncio,json
from dataclasses import asdict
from pathlib import Path

from pipeline.adapters.civilview_county import CountyCivilViewAdapter
from pipeline.load_to_supabase import load_into_supabase
from pipeline.scrape_civilview import json_serializer

# IDs verified against live official county listing links.
CIVILVIEW_COUNTIES={"Camden":1,"Monmouth":8,"Cape May":52}

async def scrape(county: str,county_id: int,output_dir: Path) -> Path:
    adapter=CountyCivilViewAdapter(county,county_id); ids=await adapter.fetch_sale_index()
    records=[asdict(await adapter.fetch_sale(source_id)) for source_id in ids]
    output_dir.mkdir(parents=True,exist_ok=True)
    path=output_dir/f"{county.lower().replace(' ','_')}_all_sheriff_sales.json"
    path.write_text(json.dumps(records,indent=2,default=json_serializer)+"\n")
    print(f"{county}: {len(records)} records saved to {path}")
    return path

async def run(counties,output_dir,load):
    for county in counties:
        path=await scrape(county,CIVILVIEW_COUNTIES[county],output_dir)
        if load: load_into_supabase(path)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--counties",nargs="+",choices=sorted(CIVILVIEW_COUNTIES))
    parser.add_argument("--all",action="store_true"); parser.add_argument("--load",action="store_true")
    parser.add_argument("--output-dir",type=Path,default=Path("data/sheriff_sales")); args=parser.parse_args()
    counties=sorted(CIVILVIEW_COUNTIES) if args.all else args.counties
    if not counties: parser.error("select --all or --counties")
    asyncio.run(run(counties,args.output_dir,args.load))

if __name__=="__main__": main()
