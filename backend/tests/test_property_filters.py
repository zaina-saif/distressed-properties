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
