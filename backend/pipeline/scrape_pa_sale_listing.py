import argparse,asyncio,json
from dataclasses import asdict
from pathlib import Path
from pipeline.adapters.pa_sale_listing import PASaleListingAdapter
from pipeline.scrape_civilview import json_serializer

SOURCES={"Butler":"https://civil.co.butler.pa.us/Sheriff.SaleListing/",
 "Centre":"https://civil.centrecountypa.gov/Sheriff.SaleListing/",
 "Cumberland":"https://sheriff.cumberlandcountypa.gov/Sheriff.SaleListing/",
 "Franklin":"https://sheriffportal.franklincountypa.gov/Sheriff.SaleListing/",
 "Greene":"https://www.greenecountypa.gov/salelisting/",
 "Lancaster":"https://portal.lancaster.pa.countysuite-azuregov.us/Sheriff.SaleListing/",
 "Luzerne":"https://sheriffsale.luzernecounty.org/Sheriff.SaleListing/",
 "Susquehanna":"https://sheriff.susqco.com/Sheriff.SaleListing/"}
async def run(counties):
 out=Path("data/sheriff_sales");out.mkdir(parents=True,exist_ok=True)
 for county in counties:
  records=await PASaleListingAdapter(county,SOURCES[county]).fetch()
  path=out/f"pa_{county.lower()}_sheriff_sales.json"
  path.write_text(json.dumps([asdict(r) for r in records],indent=2,default=json_serializer)+"\n")
  print(f"{county}: {len(records)} records saved to {path}")
def main():
 p=argparse.ArgumentParser();p.add_argument("--counties",nargs="+",choices=sorted(SOURCES));p.add_argument("--all",action="store_true");a=p.parse_args()
 asyncio.run(run(sorted(SOURCES) if a.all else a.counties or []))
if __name__=="__main__":main()
