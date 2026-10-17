from app.api.properties import _property_filters
from app.auth import Access


def test_map_points_and_list_share_the_plan_scope():
    access = Access(user_id="u", email="u@example.com", plan="starter", plan_status="active", coverage_state="OH")
    conditions, parameters = _property_filters(access, state=[], county=[], status_contains="scheduled")

    assert parameters["scope_state"] == access.scope_state
    assert "p.state = :scope_state" in conditions
    assert parameters["status_contains"] == "scheduled"


def test_sale_ids_limit_the_list_to_those_sales():
    access = Access(user_id="u", email="u@example.com", role="developer")
    conditions, parameters = _property_filters(access, state=["fl"], county=[], sale_id=["abc"])

    assert parameters == {"states": ["FL"], "sale_ids": ["abc"]}
    assert "ss.id::text = ANY(:sale_ids)" in conditions


def test_spotlight_is_the_top_ten_within_the_plan_scope():
    access = Access(user_id="u", email="u@example.com", plan="starter", plan_status="active", coverage_state="OH")
    conditions, parameters = _property_filters(access, state=[], county=[], investor_spotlight=True)

    # One condition: the ranking subquery, which applies the plan scope before picking the top ten.
    assert len(conditions) == 1
    assert "p.state = :scope_state" in conditions[0]
    assert "probability_rank >= 0.5" in conditions[0]
    assert conditions[0].rstrip().endswith("LIMIT 10)")
    assert parameters["scope_state"] == "OH"


def test_search_filters_build_range_and_property_conditions():
    from datetime import date

    from app.api.properties import SearchFilters

    filters = SearchFilters(min_price=50000, max_price=150000, min_beds=3, home_type=["single_family", "castle"],
                            sale_from=date(2026, 10, 15), min_probability=0.5)
    conditions, parameters = filters.conditions()
    joined = " AND ".join(conditions)
    assert ":filter_min_price" in joined and ":filter_max_price" in joined
    assert "azr.raw_payload->>'bedrooms'" in joined and parameters["filter_min_beds"] == 3
    assert parameters["filter_home_types"] == ["SINGLE_FAMILY"]  # unknown types are ignored
    assert parameters["filter_min_sale_date"] == date(2026, 10, 15)
    assert "sp.probability >= :filter_min_probability" in joined
    assert "sp.probability" not in " ".join(filters.conditions(include_probability=False)[0])
    assert SearchFilters(sale_kind="all").conditions() == ([], {})


def test_tax_sales_are_shown_only_when_asked_for():
    from app.api.properties import TAX_SALE_SQL, SearchFilters

    assert SearchFilters().conditions()[0] == [f"NOT {TAX_SALE_SQL}"]
    assert SearchFilters(sale_kind="tax").conditions()[0] == [TAX_SALE_SQL]
    access = Access(user_id="u", email="u@example.com", role="developer")
    opened, _ = _property_filters(access, state=[], county=[], sale_id=["s1"], filters=SearchFilters())
    assert not any(TAX_SALE_SQL in condition for condition in opened)  # a sale opened by id always shows


def test_property_filters_include_search_filters():
    from app.api.properties import SearchFilters

    access = Access(user_id="u", email="u@example.com", role="developer")
    conditions, parameters = _property_filters(access, state=[], county=[], filters=SearchFilters(min_sqft=1500))
    assert any(":filter_min_sqft" in condition for condition in conditions) and parameters["filter_min_sqft"] == 1500


def test_scheduled_listings_only_include_upcoming_dates():
    access = Access(user_id="u", email="u@example.com", role="developer")
    conditions, _ = _property_filters(access, state=[], county=[], status_contains="scheduled")
    assert "ss.current_sale_date >= CURRENT_DATE" in conditions
    conditions, _ = _property_filters(access, state=[], county=[], status_contains="sold")
    assert "ss.current_sale_date >= CURRENT_DATE" not in conditions


def test_judgment_execution_dockets():
    import re

    from app.api.properties import JUDGMENT_SALE_SQL

    pattern = re.compile(re.search(r"~\* '(.+)'\)", JUDGMENT_SALE_SQL).group(1), re.I)
    judgments = ["L-002105-20", "ESX-L-003587-23", "L301921", "L", "ATL-DC-005885-23", "HUD-DC-012313-25",
                 "DJ04885525", "DJ00099625", "DC724725DJ04193726"]
    foreclosures = ["F-012345-25", "F00331823", "SWC-F-000573-25", "SWCF01046725", "00063626", "SWC", "F"]
    assert all(pattern.search(docket) for docket in judgments)
    assert not any(pattern.search(docket) for docket in foreclosures)
