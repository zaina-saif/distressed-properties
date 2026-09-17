from decimal import Decimal
from pipeline.import_illinois_kane_parcels import FIELDS,parse
def test_kane_mapping_and_privacy():
 row=parse({"PIN":"01-02-300-004","UseCode":"R","UseCodeDescription":"Residential","SiteAddress":"1 MAIN ST","SiteCity":"ELGIN","SiteZip":"60120","RecordedAcreage":"0.25"})
 assert row[3]=="IL:KANE:0102300004" and row[8:12]==("Residential","R",Decimal("0.25"),"acres")
 assert not any("mail" in f.lower() or "legal" in f.lower() for f in FIELDS)
