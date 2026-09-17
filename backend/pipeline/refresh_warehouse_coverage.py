"""Refresh fast, source-record coverage counts for the seven-state QA screen."""
from __future__ import annotations

from sqlalchemy import text

from app.database.session import warehouse_engine

STATES = ("MD", "NY", "IL", "FL", "OH", "VA", "DC")

YEARLY_SQL = text("""
WITH sales AS (
  SELECT state,EXTRACT(YEAR FROM sale_date)::smallint AS year,COUNT(*) AS sale_count,
         COUNT(DISTINCT county) AS sale_counties,MIN(sale_date) AS first_sale,
         MAX(sale_date) AS last_sale
  FROM public_property_sales
  WHERE state=ANY(:states) AND sale_date>=DATE '2020-01-01' AND sale_date<=CURRENT_DATE
  GROUP BY state,EXTRACT(YEAR FROM sale_date)::smallint
), snapshots AS (
  SELECT state,snapshot_year AS year,COUNT(*) AS snapshot_count,
         COUNT(DISTINCT county) AS snapshot_counties,
         ARRAY_AGG(DISTINCT county ORDER BY county) AS snapshot_county_names
  FROM public_property_snapshots
  WHERE state=ANY(:states) AND snapshot_year BETWEEN 2020 AND EXTRACT(YEAR FROM CURRENT_DATE)::int
  GROUP BY state,snapshot_year
)
INSERT INTO public_property_coverage_yearly
  (state,year,sale_count,sale_counties,snapshot_count,snapshot_counties,
   snapshot_county_names,first_sale,last_sale,refreshed_at)
SELECT COALESCE(s.state,p.state),COALESCE(s.year,p.year),COALESCE(s.sale_count,0),
       COALESCE(s.sale_counties,0),COALESCE(p.snapshot_count,0),COALESCE(p.snapshot_counties,0),
       COALESCE(p.snapshot_county_names,ARRAY[]::TEXT[]),s.first_sale,s.last_sale,NOW()
FROM sales s FULL JOIN snapshots p ON p.state=s.state AND p.year=s.year
ON CONFLICT(state,year) DO UPDATE SET sale_count=EXCLUDED.sale_count,
  sale_counties=EXCLUDED.sale_counties,snapshot_count=EXCLUDED.snapshot_count,
  snapshot_counties=EXCLUDED.snapshot_counties,
  snapshot_county_names=EXCLUDED.snapshot_county_names,
  first_sale=EXCLUDED.first_sale,last_sale=EXCLUDED.last_sale,refreshed_at=NOW()
""")
STATE_SQL = text("""
INSERT INTO public_property_coverage_state(state,future_dated_sales,refreshed_at)
SELECT state,COUNT(*),NOW() FROM public_property_sales
WHERE state=ANY(:states) AND sale_date>CURRENT_DATE GROUP BY state
ON CONFLICT(state) DO UPDATE SET future_dated_sales=EXCLUDED.future_dated_sales,
  refreshed_at=NOW()
""")


def main() -> None:
    with warehouse_engine.begin() as connection:
        connection.execute(YEARLY_SQL, {"states": list(STATES)})
        connection.execute(STATE_SQL, {"states": list(STATES)})
        rows = connection.execute(text("""SELECT state,SUM(sale_count),SUM(snapshot_count),
               MAX(refreshed_at) FROM public_property_coverage_yearly
               WHERE state=ANY(:states) GROUP BY state ORDER BY state"""),
                                  {"states": list(STATES)}).all()
    for state, sales, snapshots, refreshed_at in rows:
        print(f"{state}: sales={sales:,} snapshots={snapshots:,} refreshed={refreshed_at.isoformat()}")


if __name__ == "__main__":
    main()
