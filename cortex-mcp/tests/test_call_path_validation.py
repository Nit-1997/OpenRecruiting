"""Regression tests for the two guards on the execute_query CALL path.

Discovery (tools/list) does not validate anything, so it is easy for the checks
to live only there in spirit. These assert they run where it matters: on an
actual tool call.

Guard 1 -- the Cypher validator rejects anything that is not a read.
Guard 2 -- $org_id is taken from the JWT, never from the caller, so a client
           cannot read another tenant's graph by passing its own org_id.
"""

import importlib
import os

import pytest

# Settings are required at import time; give them local values.
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USERNAME", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "openrecruiting")

# `src.tools` re-exports the function under the same name as its module, so the
# dotted string form of monkeypatch would resolve to the function. Import the
# module object explicitly.
_eq = importlib.import_module("src.tools.execute_query")
execute_query = _eq.execute_query
from src.validator import ValidationError, validate_cypher


class _Auth:
    org_id = "11111111-1111-1111-1111-111111111111"
    org_name = "Acme"
    sub = "user-1"
    scope = "cortex:read"


@pytest.mark.parametrize(
    "query",
    [
        "CREATE (n:Person {name:'x'}) RETURN n",
        "MATCH (n) DETACH DELETE n",
        "MERGE (n:Person {id:1}) RETURN n",
        "MATCH (n) SET n.name = 'x' RETURN n",
        "DROP INDEX idx_person",
        "CALL apoc.export.csv.all('out.csv', {})",
    ],
)
def test_validator_rejects_writes_and_side_effects(query):
    with pytest.raises(ValidationError):
        validate_cypher(query)


async def test_execute_query_returns_rejected_not_raised_for_a_write():
    """The call path must surface a structured rejection the client can read,
    rather than executing or blowing up."""
    result = await execute_query(
        query="CREATE (n:Person {name:'mallory'}) RETURN n",
        auth=_Auth(),
    )
    assert result["status"] == "rejected"
    assert result["data"] is None
    assert result["error"]


async def test_caller_supplied_org_id_cannot_override_the_token(monkeypatch):
    """Cross-tenant read attempt: the caller passes another org's id, and the
    parameters actually sent to Neo4j must still carry the JWT's org_id."""
    seen = {}

    async def _fake_run_read_query(*, query, params, **kw):
        seen.update(params)
        return []

    monkeypatch.setattr(_eq, "run_read_query", _fake_run_read_query)

    await execute_query(
        query="MATCH (c:Candidate {group_id: $org_id}) RETURN c LIMIT 1",
        auth=_Auth(),
        params={"org_id": "22222222-2222-2222-2222-222222222222"},
    )

    assert seen["org_id"] == _Auth.org_id
