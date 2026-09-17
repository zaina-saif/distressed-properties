"""Import Will County's openly licensed current tax-map parcel archive."""
from __future__ import annotations

import argparse
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Iterator

import httpx
import pyogrio
from pyogrio.raw import read
from pyproj import Transformer
from psycopg2.extras import execute_values
from shapely import from_wkb, transform
from sqlalchemy import text

from app.database.session import warehouse_engine
from pipeline.public_property_records import stable_hash, text_value

SOURCE_ID = "il_will_open_parcels_2026"
SOURCE_PAGE = "https://willcounty.gov/County-Offices/Administration/GIS-Division/Data/Vector"
DOWNLOAD_URL = "https://webapp.willcountyillinois.com/WebsiteDataStore/WillCounty_Tax_Map_Parcels_LY.zip"
COLUMNS = ("source_id","state","county","source_parcel_id","snapshot_year","longitude","latitude",
           "land_area","land_area_unit","source_hash")
SQL = f"""INSERT INTO public_property_snapshots ({','.join(COLUMNS)}) VALUES %s
ON CONFLICT(source_id,source_parcel_id,snapshot_year) DO UPDATE SET longitude=EXCLUDED.longitude,
 latitude=EXCLUDED.latitude,land_area=EXCLUDED.land_area,land_area_unit=EXCLUDED.land_area_unit,
 source_hash=EXCLUDED.source_hash,imported_at=NOW()
WHERE public_property_snapshots.source_hash<>EXCLUDED.source_hash"""


def parcel_id(value: Any) -> str | None:
    value = text_value(value)
    return f"IL:WILL:{''.join(c for c in value.upper() if c.isalnum())}" if value else None


def parsed(identity: str, area: float, longitude: float, latitude: float) -> tuple[Any, ...]:
    core = {"source_id":SOURCE_ID,"state":"IL","county":"Will","source_parcel_id":identity,
            "snapshot_year":2026,"longitude":longitude,"latitude":latitude,"land_area":area,
            "land_area_unit":"square feet"}
    return tuple(core[name] for name in COLUMNS[:-1]) + (stable_hash(core),)


def rows(path: Path, chunk_size: int) -> Iterator[tuple[Any, ...]]:
    count = pyogrio.read_info(path)["features"]
    projection = Transformer.from_crs("EPSG:3435", "EPSG:4326", always_xy=True).transform
    for offset in range(0, count, chunk_size):
        meta, _, geometries, arrays = read(path, columns=["PIN"], read_geometry=True,
                                           skip_features=offset, max_features=chunk_size)
        pins = arrays[list(meta["fields"]).index("PIN")]
        for pin, wkb in zip(pins, geometries):
            identity = parcel_id(pin)
            if not identity or wkb is None: continue
            geometry = from_wkb(wkb)
            if geometry.is_empty: continue
            centroid = transform(geometry.centroid, projection, interleaved=False)
            yield parsed(identity, float(geometry.area), centroid.x, centroid.y)


def download(path: Path) -> None:
    with httpx.stream("GET", DOWNLOAD_URL, follow_redirects=True, timeout=300) as response:
        response.raise_for_status()
        with path.open("wb") as output:
            for chunk in response.iter_bytes(1024 * 1024): output.write(chunk)


def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument("--archive",type=Path)
    parser.add_argument("--batch-size",type=int,default=10000); args=parser.parse_args()
    with warehouse_engine.begin() as connection:
        connection.execute(text("""INSERT INTO public_data_sources(source_id,state,county,source_name,source_url,access_method,coverage_notes,last_checked_at)
          VALUES(:id,'IL','Will','Will County Tax Map Parcels',:url,'zip shapefile',
          'Current openly licensed PIN, parcel area and derived centroid; personal fields excluded; attribution: Contains information licensed under the Open Geo-Spatial Data License - Will County',NOW())
          ON CONFLICT(source_id) DO UPDATE SET last_checked_at=NOW(),updated_at=NOW()"""),{"id":SOURCE_ID,"url":SOURCE_PAGE})
    with tempfile.TemporaryDirectory(prefix="will_parcels_") as temporary:
        archive=args.archive or Path(temporary)/"parcels.zip"
        if not args.archive: download(archive)
        with zipfile.ZipFile(archive) as zipped: zipped.extractall(temporary)
        shape=next(Path(temporary).glob("*.shp")); raw=warehouse_engine.raw_connection(); loaded=0; batch={}
        try:
            cursor=raw.cursor()
            for row in rows(shape,args.batch_size):
                batch[row[3]]=row
                if len(batch)>=args.batch_size:
                    execute_values(cursor,SQL,list(batch.values()),page_size=args.batch_size); loaded+=len(batch); batch.clear(); raw.commit(); print(f"Will parcels: {loaded:,}",flush=True)
            if batch: execute_values(cursor,SQL,list(batch.values()),page_size=args.batch_size); loaded+=len(batch); raw.commit()
        finally: raw.close()
    print(f"complete Will parcel snapshots={loaded:,}")


if __name__=="__main__": main()
