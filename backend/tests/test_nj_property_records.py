from decimal import Decimal
from pipeline.nj_property_records import normalize_component, parse_modiv, parse_sr1a

def put(line, start, end, value):
    line[start-1:end] = list(value.ljust(end-start+1)[:end-start+1])

def test_parse_modiv_uses_official_offsets():
    line=list(" "*700)
    for a,b,v in [(1,4,"1308"),(5,13,"00012.01"),(14,22,"000000007"),(23,33,"C0002"),
      (34,35,"01"),(56,58,"2"),(59,83,"11 MANOR DRIVE"),(307,312,"240415"),
      (313,321,"000450000"),(416,419,"1987"),(421,429,"000120000"),
      (430,438,"000280000"),(439,447,"000400000"),(601,612,"000000854321")]: put(line,a,b,v)
    row=parse_modiv("".join(line),2025,"MonmouthRE.txt",1)
    assert (row.municipality_code,row.block,row.lot,row.qualifier)==("1308","12.01","7","C0002")
    assert row.sale_price==Decimal("450000")
    assert row.annual_property_tax==Decimal("8543.21")
    assert row.deed_date.isoformat()=="2024-04-15"

def test_parse_sr1a_combines_suffixes():
    line=list(" "*663)
    for a,b,v in [(1,2,"13"),(3,4,"08"),(47,55,"000455000"),(298,322,"11 MANOR DRIVE"),
      (339,344,"240415"),(351,355,"00012"),(356,359,".01"),(360,364,"00007"),
      (625,626,"24"),(627,629,"2"),(653,656,"1987"),(657,663,"0002140")]: put(line,a,b,v)
    row=parse_sr1a("".join(line),2025,"Sales2025.txt",1)
    assert row.municipality_code=="1308" and (row.block,row.lot)==("12.01","7")
    assert row.verified_price==Decimal("455000") and row.living_space==2140
    assert row.deed_date.isoformat()=="2024-04-15"

def test_normalize_component_preserves_suffixes():
    assert normalize_component(" 00012 . 01 ")=="12.01"
