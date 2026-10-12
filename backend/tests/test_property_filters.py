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
    assert SearchFilters().conditions() == ([], {})


def test_property_filters_include_search_filters():
    from app.api.properties import SearchFilters

    access = Access(user_id="u", email="u@example.com", role="developer")
    conditions, parameters = _property_filters(access, state=[], county=[], filters=SearchFilters(min_sqft=1500))
    assert any(":filter_min_sqft" in condition for condition in conditions) and parameters["filter_min_sqft"] == 1500
