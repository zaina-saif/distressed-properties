from pandas import DataFrame, Timestamp

from pipeline.train_avm import add_comparable_features, add_distance_comparable_features


def test_comparable_features_only_use_earlier_quarters_and_sales():
    frame = DataFrame([
        {"municipality_code":"1301","block":"1","lot":"1","census_tract":"10",
         "deed_date":Timestamp("2024-01-10"),"sale_price":100_000,"living_space":1_000},
        {"municipality_code":"1301","block":"2","lot":"1","census_tract":"10",
         "deed_date":Timestamp("2024-02-10"),"sale_price":300_000,"living_space":1_000},
        {"municipality_code":"1301","block":"1","lot":"1","census_tract":"10",
         "deed_date":Timestamp("2024-04-10"),"sale_price":900_000,"living_space":1_000},
    ])
    result = add_comparable_features(frame).sort_values("deed_date")
    assert result.iloc[0]["municipality_prior_quarter_median_price"] != result.iloc[0]["municipality_prior_quarter_median_price"]
    assert result.iloc[2]["municipality_prior_quarter_median_price"] == 200_000
    assert result.iloc[2]["prior_parcel_sale_price"] == 100_000

def test_distance_comps_exclude_current_quarter_sales():
    frame=DataFrame([
        {"deed_date":Timestamp("2024-01-10"),"sale_price":100_000,"living_space":1_000,"latitude":40.2,"longitude":-74.1},
        {"deed_date":Timestamp("2024-04-01"),"sale_price":900_000,"living_space":1_000,"latitude":40.2,"longitude":-74.1},
        {"deed_date":Timestamp("2024-04-20"),"sale_price":800_000,"living_space":1_000,"latitude":40.2,"longitude":-74.1},
    ])
    result=add_distance_comparable_features(frame)
    q2=result[result.deed_date.dt.quarter==2]
    assert set(q2.local_comp_median_price)=={100_000}
    assert set(q2.local_comp_count)=={1.0}
