"""Score conservatively matched sheriff-sale properties with the local AVM."""
from __future__ import annotations
import argparse,json,uuid
from datetime import date,datetime,timezone,timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree
from sqlalchemy import text

from app.database.session import engine
from pipeline.train_avm import CATEGORICAL_FEATURES,MODEL_DIR,NUMERIC_FEATURES

PROVIDER="monmouth_xgboost_avm_v2"
MODEL=MODEL_DIR/"monmouth_avm_xgboost.joblib"
METRICS=MODEL_DIR/"monmouth_avm_metrics.json"

def subjects(pending_only=False):
    query=text("""
    SELECT p.id property_id,p.square_feet,f.*,h.living_space,h.latitude,h.longitude
    FROM property_avm_features f JOIN properties p ON p.id=f.property_id
    LEFT JOIN LATERAL (SELECT living_space,latitude,longitude FROM nj_avm_training_sales s
      WHERE s.municipality_code=f.municipality_code AND s.block=f.block AND s.lot=f.lot
      ORDER BY deed_date DESC LIMIT 1) h ON TRUE
    WHERE f.match_confidence>=90 AND trim(f.property_class)='2'
      AND EXISTS (SELECT 1 FROM sheriff_sales ss WHERE ss.property_id=p.id
        AND ss.current_sale_date>=CURRENT_DATE)
      AND (:pending_only=FALSE OR NOT EXISTS (SELECT 1 FROM property_valuations pv
        WHERE pv.property_id=p.id AND pv.is_current=TRUE))
    """)
    with engine.connect() as c:
        return [dict(r) for r in c.execute(query,{"pending_only":pending_only}).mappings()]

def history():
    with engine.connect() as c:
        return pd.read_sql(text("""SELECT deed_date,sale_price,living_space,latitude,longitude
          FROM nj_avm_training_sales WHERE latitude IS NOT NULL AND longitude IS NOT NULL
          AND deed_date < date_trunc('quarter',CURRENT_DATE)
          AND deed_date >= date_trunc('quarter',CURRENT_DATE)-interval '2 years'"""),c)

def local_features(subject_rows, sales):
    sales["ppsf"]=sales.sale_price/sales.living_space; earth=3958.7613
    tree=BallTree(np.radians(sales[["latitude","longitude"]].to_numpy()),metric="haversine")
    for row in subject_rows:
        row.update(local_comp_median_price=np.nan,local_comp_median_ppsf=np.nan,
                   local_comp_median_miles=np.nan,local_comp_count=0.0)
        if row["latitude"] is None or row["longitude"] is None: continue
        k=min(20,len(sales)); distances,indices=tree.query(
            np.radians([[row["latitude"],row["longitude"]]]),k=k)
        miles=distances[0]*earth; valid=miles<=5
        if not valid.any(): continue
        comps=sales.iloc[indices[0][valid]]
        row.update(local_comp_median_price=float(comps.sale_price.median()),
            local_comp_median_ppsf=float(comps.ppsf.median()),
            local_comp_median_miles=float(np.median(miles[valid])),local_comp_count=float(len(comps)))

def feature_frame(rows):
    today=date.today(); prepared=[]
    for row in rows:
        sqft=row["square_feet"] or row["living_space"] or np.nan
        row["living_area_imputed"]=bool(np.isnan(sqft))
        prepared.append({**row,"living_space":sqft,"sale_month":today.month,
            "property_age":today.year-row["year_built"] if row["year_built"] else np.nan,
            "living_area_imputed":row["living_area_imputed"]})
    return pd.DataFrame(prepared)

def save(rows,predictions,interval):
    statement=text("""INSERT INTO property_valuations
      (id,property_id,provider,estimated_value,low_value,high_value,confidence_score,
       provider_response,effective_date,retrieved_at,expires_at,is_current)
      VALUES (:id,:property_id,:provider,:estimate,:low,:high,:confidence,
       CAST(:response AS JSONB),CURRENT_DATE,NOW(),:expires,:is_current)""")
    saved=0
    with engine.begin() as c:
        for row,pred in zip(rows,predictions):
            imputed=bool(row.get("living_area_imputed")); adjusted_interval=interval*(1.75 if imputed else 1)
            confidence=.40 if imputed else (.62 if row["local_comp_count"]>=5 else .50)
            payload={"model_version":"v2-distance-comps","identity_match_method":row["match_method"],
                "identity_confidence":float(row["match_confidence"]),"local_comp_count":int(row["local_comp_count"]),
                "living_area_imputed":imputed,
                "coordinate_source":"NJGIN" if row["latitude"] is not None else None,
                "warning":"Statistical estimate; not an appraisal."}
            stronger=c.execute(text("""SELECT EXISTS(SELECT 1 FROM property_valuations
                WHERE property_id=:p AND is_current AND provider<>:provider)"""),
                {"p":row["property_id"],"provider":PROVIDER}).scalar()
            c.execute(text("UPDATE property_valuations SET is_current=FALSE WHERE property_id=:p AND provider=:provider AND is_current"),
                      {"p":row["property_id"],"provider":PROVIDER})
            c.execute(statement,{"id":str(uuid.uuid4()),"property_id":row["property_id"],"provider":PROVIDER,
                "estimate":round(max(float(pred),25000),2),"low":round(max(float(pred)-adjusted_interval,25000),2),
                "high":round(float(pred)+adjusted_interval,2),"confidence":confidence,"response":json.dumps(payload),
                "expires":datetime.now(timezone.utc)+timedelta(days=90),"is_current":not stronger}); saved+=1
    return saved

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--save",action="store_true")
    parser.add_argument("--pending-only",action="store_true"); args=parser.parse_args()
    rows=subjects(args.pending_only)
    if not rows:
        print("Scoreable properties: 0")
        return
    local_features(rows,history()); frame=feature_frame(rows)
    model=joblib.load(MODEL); predictions=model.predict(frame[NUMERIC_FEATURES+CATEGORICAL_FEATURES])
    interval=json.loads(METRICS.read_text())["metrics"]["test"]["xgboost"]["mae"]
    print(f"Scoreable properties: {len(rows)}; median estimate: ${np.median(predictions):,.0f}")
    if args.save: print(f"Valuations saved: {save(rows,predictions,interval)}")

if __name__=="__main__": main()
