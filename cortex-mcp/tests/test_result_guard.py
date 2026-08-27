"""Tests for the post-query cross-tenant leak guard.

The guard is the second line of defense after the Cypher validator. These
tests verify that no matter what shape Neo4j returns, any cell containing a
group_id / org_id field tied to a different organization causes the query
to be rejected with an agent-actionable message.
"""
from __future__ import annotations

import pytest

from src.validator.result_guard import CrossTenantLeak, check_result


ACME = "8f5311b7-7427-47c0-97d1-e1e6c4c23847"
NORTHWIND = "e6a942c5-5345-4790-9b83-c0b18d880825"


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------

def test_empty_result_ok():
    check_result([], ACME)


def test_scalar_columns_ok():
    rows = [
        {"name": "Carter Ellis", "status": "active"},
        {"name": "Akanksha Singh", "status": None},
    ]
    check_result(rows, ACME)


def test_correct_group_id_ok():
    rows = [
        {"name": "SDE 4 - Backend", "group_id": ACME},
        {"name": "Solutions Architect", "group_id": ACME},
    ]
    check_result(rows, ACME)


def test_node_dict_with_correct_group_id_ok():
    rows = [{"c": {"name": "Nguyen", "group_id": ACME, "status": "active"}}]
    check_result(rows, ACME)


def test_nested_list_of_nodes_ok():
    rows = [
        {
            "name": "Nguyen",
            "traits": [
                {"name": "structured thinking", "group_id": ACME},
                {"name": "outcome-focused", "group_id": ACME},
            ],
        }
    ]
    check_result(rows, ACME)


def test_relationship_properties_ok():
    rows = [
        {
            "r": {"name": "EXHIBITS", "group_id": ACME, "fact": "...", "valid_at": "x"},
        }
    ]
    check_result(rows, ACME)


def test_org_id_field_also_checked_when_correct():
    """IngestionRecord uses `org_id` instead of `group_id`; treat the same."""
    rows = [{"ingestion": {"event_type": "plan_created", "org_id": ACME}}]
    check_result(rows, ACME)


def test_scalar_value_in_unrelated_column_ok():
    """A UUID value in a column whose name doesn't suggest scope shouldn't
    falsely trip the guard. Candidates / requisitions also have UUIDs."""
    rows = [{"candidate_uuid": "11111111-2222-3333-4444-555555555555"}]
    check_result(rows, ACME)


# ---------------------------------------------------------------------------
# Leak detection
# ---------------------------------------------------------------------------

def test_top_level_wrong_group_id_blocked():
    rows = [{"name": "Other Org Req", "group_id": NORTHWIND}]
    with pytest.raises(CrossTenantLeak, match="Cross-tenant data detected"):
        check_result(rows, ACME)


def test_node_property_wrong_group_id_blocked():
    rows = [{"c": {"name": "Imposter Candidate", "group_id": NORTHWIND}}]
    with pytest.raises(CrossTenantLeak):
        check_result(rows, ACME)


def test_relationship_property_wrong_group_id_blocked():
    rows = [{"r": {"name": "EXHIBITS", "group_id": NORTHWIND}}]
    with pytest.raises(CrossTenantLeak):
        check_result(rows, ACME)


def test_nested_list_with_wrong_group_id_blocked():
    rows = [
        {
            "name": "Nguyen",
            "traits": [
                {"name": "ok-trait", "group_id": ACME},
                {"name": "leaked-trait", "group_id": NORTHWIND},
            ],
        }
    ]
    with pytest.raises(CrossTenantLeak):
        check_result(rows, ACME)


def test_deeply_nested_wrong_group_id_blocked():
    rows = [
        {
            "outer": {
                "middle": {
                    "inner": [
                        {"node": {"group_id": NORTHWIND, "name": "leaked"}},
                    ]
                }
            }
        }
    ]
    with pytest.raises(CrossTenantLeak):
        check_result(rows, ACME)


def test_scalar_group_id_projection_blocked():
    """`RETURN c.group_id AS scope` — column alias preserves the suffix."""
    rows = [{"scope_group_id": NORTHWIND}]
    with pytest.raises(CrossTenantLeak):
        check_result(rows, ACME)


def test_org_id_mismatch_also_blocked():
    rows = [{"event_org_id": NORTHWIND}]
    with pytest.raises(CrossTenantLeak):
        check_result(rows, ACME)


def test_mixed_row_set_blocks_on_first_mismatch():
    rows = [
        {"c": {"name": "ours", "group_id": ACME}},
        {"c": {"name": "leaked", "group_id": NORTHWIND}},
        {"c": {"name": "also-ours", "group_id": ACME}},
    ]
    with pytest.raises(CrossTenantLeak):
        check_result(rows, ACME)


def test_error_message_is_agent_actionable():
    """The LLM should learn from the error: name the violation and the fix."""
    rows = [{"node": {"group_id": NORTHWIND}}]
    with pytest.raises(CrossTenantLeak) as exc:
        check_result(rows, ACME)
    msg = str(exc.value).lower()
    assert "cross-tenant" in msg
    assert "group_id = $org_id" in msg.lower() or "group_id = $org_id".lower() in msg
    assert "forbidden" in msg


# ---------------------------------------------------------------------------
# Defensive
# ---------------------------------------------------------------------------

def test_missing_auth_org_id_fails_closed():
    """If something forgot to pass org_id, do NOT silently accept the result."""
    with pytest.raises(CrossTenantLeak, match="no authenticated org_id"):
        check_result([{"c": {"group_id": ACME}}], auth_org_id="")


def test_unrelated_uuid_in_value_does_not_trip():
    """Falsely flagging arbitrary UUID-shaped strings would break candidate /
    requisition lookups. The guard only checks values when the parent key
    is itself scope-related."""
    rows = [
        {"candidate_id": "11111111-2222-3333-4444-555555555555",
         "name": "Nguyen",
         "group_id": ACME},
    ]
    check_result(rows, ACME)
