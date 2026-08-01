"""End-to-end smoke test against the live Neo4j instance.

Skipped automatically unless RUN_E2E=1 is set in the environment. This is
intentional — CI should not depend on production data.
"""
from __future__ import annotations

import os
import pytest
import pytest_asyncio

from src.auth.context import AuthContext
from src.clients.neo4j_client import close_driver, init_driver
from src.tools.execute_query import execute_query

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_E2E") != "1",
    reason="Live Neo4j test — set RUN_E2E=1 to enable",
)


ACME_ORG_ID = "8f5311b7-7427-47c0-97d1-e1e6c4c23847"
NORTHWIND_ORG_ID = "e6a942c5-5345-4790-9b83-c0b18d880825"


def _auth(org_id: str) -> AuthContext:
    return AuthContext(
        user_id="test-user",
        org_id=org_id,
        org_name="Test",
        user_name="Test User",
        role="admin",
        scopes=("cortex:read",),
    )


@pytest_asyncio.fixture(autouse=True)
async def driver_lifecycle():
    await init_driver()
    yield
    await close_driver()


async def test_acme_lists_only_acme_requisitions():
    result = await execute_query(
        "MATCH (req:Requisition {group_id: $org_id}) RETURN req.name AS name",
        auth=_auth(ACME_ORG_ID),
    )
    assert result["status"] == "ok", result
    names = sorted(r["name"] for r in result["data"])
    assert "SDE 4 - Backend" in names
    assert "Solutions Architect" in names


async def test_northwind_does_not_see_acme_reqs():
    """Even if a malicious org_id literal were attempted, the query is rejected
    BEFORE execution. This proves the validator catches exfiltration attempts."""
    result = await execute_query(
        f"MATCH (req:Requisition) WHERE req.group_id = '{ACME_ORG_ID}' RETURN req.name",
        auth=_auth(NORTHWIND_ORG_ID),
    )
    assert result["status"] == "rejected", result
    assert "Hard-coded org_id literal" in result["error"]


async def test_unscoped_query_rejected():
    result = await execute_query(
        "MATCH (c:Candidate) RETURN c.name",
        auth=_auth(ACME_ORG_ID),
    )
    assert result["status"] == "rejected"
    assert "group_id" in result["error"]


async def test_unscoped_skill_query_now_rejected():
    """Until V2 ontology dedup actually merges concepts across tenants,
    Skill/Trait/Competency/etc. are per-tenant. An unscoped query against
    Skill must reject — otherwise org A can enumerate org B's skill nodes."""
    result = await execute_query(
        "MATCH (s:Skill) RETURN s.name LIMIT 5",
        auth=_auth(ACME_ORG_ID),
    )
    assert result["status"] == "rejected"
    assert "group_id" in result["error"]


async def test_scoped_skill_query_works():
    """The same query, properly scoped, returns rows for the auth'd org."""
    result = await execute_query(
        "MATCH (s:Skill {group_id: $org_id}) RETURN s.name LIMIT 5",
        auth=_auth(ACME_ORG_ID),
    )
    assert result["status"] == "ok"
    assert result["row_count"] <= 5


async def test_cross_tenant_concept_isolation():
    """Concept nodes must NOT leak across tenants. Auth'd as Acme, all
    returned Skill nodes must have Acme's group_id."""
    result = await execute_query(
        "MATCH (s:Skill {group_id: $org_id}) RETURN DISTINCT s.group_id AS scope",
        auth=_auth(ACME_ORG_ID),
    )
    assert result["status"] == "ok"
    scopes = {row["scope"] for row in result["data"]}
    assert scopes <= {ACME_ORG_ID}, (
        f"Cross-tenant leak: Acme session saw {scopes - {ACME_ORG_ID}}"
    )


async def test_write_attempt_rejected():
    result = await execute_query(
        "MATCH (c:Candidate {group_id: $org_id}) SET c.flagged = true RETURN c",
        auth=_auth(ACME_ORG_ID),
    )
    assert result["status"] == "rejected"
    assert "Forbidden" in result["error"]
