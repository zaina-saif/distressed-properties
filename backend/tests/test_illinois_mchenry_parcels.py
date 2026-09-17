from decimal import Decimal
from pipeline.import_illinois_mchenry_parcels import FIELDS,parse

def test_mchenry_mapping_and_privacy()->None:
 row=parse({"ParcelNumber":"14-21-301-003","PropertyClass":"0040","SiteAddress":"6008 PLEASANT HILL RD","SiteCity":"CRYSTAL LAKE","SiteZip":"60012","Latitude":42.27,"Longitude":-88.31,"ParcelArea":87394.03})
 assert row[3]=="IL:MCHENRY:1421301003" and row[5:8]==("6008 PLEASANT HILL RD","CRYSTAL LAKE","60012")
 assert row[10:14]==("0040","0040",Decimal("87394.03"),"square feet")
 assert not any("owner" in f.lower() or "mail" in f.lower() for f in FIELDS)
