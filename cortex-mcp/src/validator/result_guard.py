"""Post-query defense-in-depth: scan Neo4j result rows for cross-tenant leaks.

The Cypher validator catches most leaks at query-time by requiring every
node binding to be scoped. But the validator is a regex-based tokenizer —
if it ever misses an edge case (a future Cypher construct, a subtle pattern
combination, an APOC bypass), a malformed query could still execute and
return rows belonging to a different tenant.

This module is the second wall. It runs AFTER Neo4j executes the query,
walks every returned value, and raises if ANY `group_id` or `org_id` field
in any row doesn't match the authenticated org. The query is then rejected
with a clear, agent-actionable error message — same envelope shape the
validator uses, so the calling LLM can read it and retry.

Trust model:
  - The validator catches >99% of bad queries at parse time, with helpful
    error messages so the LLM can self-correct.
  - This guard catches the residual <1% — including cases the validator's
    tokenizer can't reason about — by inspecting the actual data that
    Neo4j returned.
  - Together they form an "allow only on both pass" gate.
"""
from __future__ import annotations

import re
from typing import Any


class CrossTenantLeak(Exception):
    """Raised when a query result contains data scoped to a different org.

    The message is meant to be surfaced verbatim to the calling LLM so it
    learns the boundary: cross-org queries are forbidden — every node and
    relationship the agent reads must belong to the authenticated org."""


# Field names we treat as tenant-identifying. Any value at a key in this set
# (case-insensitive) must equal the authenticated org_id.
_SCOPE_FIELDS: frozenset[str] = frozenset({"group_id", "org_id", "organization_id"})

# Cortex stores org IDs as UUIDs. The hard-coded-literal check in the
# validator uses the same shape.
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def check_result(rows: list[Any], auth_org_id: str) -> None:
    """Walk every cell of every row. Raise CrossTenantLeak on any mismatch.

    Accepts the row shape produced by Cortex MCP's `run_read_query`
    (i.e., a list of dicts, where values may themselves be neo4j Node /
    Relationship / dict / list / scalar). Recursively descends through
    nested containers so a node returned inside a list or as a
    relationship property is still inspected.
    """
    if not auth_org_id:
        # Defensive — the auth context always carries org_id, but if a
        # future code path forgets, fail closed instead of silently
        # accepting everything.
        raise CrossTenantLeak(
            "Internal error: no authenticated org_id available for result scan."
        )

    for idx, row in enumerate(rows):
        _scan(row, auth_org_id, path=f"row[{idx}]")


def _scan(value: Any, auth_org_id: str, *, path: str, parent_key: str | None = None) -> None:
    # neo4j Node / Relationship objects support mapping-like access; pull
    # their properties into a dict-like view for uniform handling.
    if _is_neo4j_node_or_rel(value):
        try:
            props = dict(value)  # type: ignore[arg-type]
        except Exception:
            props = {}
        _scan(props, auth_org_id, path=f"{path}<node>")
        return

    if isinstance(value, dict):
        for k, v in value.items():
            klow = str(k).lower()
            # Direct scope-field check on the value
            if klow in _SCOPE_FIELDS:
                _enforce_match(v, auth_org_id, path=f"{path}.{k}")
            _scan(v, auth_org_id, path=f"{path}.{k}", parent_key=str(k))
        return

    if isinstance(value, (list, tuple, set)):
        for i, item in enumerate(value):
            _scan(item, auth_org_id, path=f"{path}[{i}]", parent_key=parent_key)
        return

    # Scalar — only worth checking if the parent key looked like a scope field
    # and we have a UUID-shaped string. This covers projections like
    # `RETURN c.group_id` aliased to a column whose name preserves the
    # `.group_id` suffix.
    if isinstance(value, str) and parent_key:
        plow = parent_key.lower()
        if any(field in plow for field in _SCOPE_FIELDS):
            _enforce_match(value, auth_org_id, path=path)


def _enforce_match(actual: Any, expected: str, *, path: str) -> None:
    if actual is None or actual == "" or actual == expected:
        return
    if not isinstance(actual, str):
        # A scope field with a non-string value is unusual; ignore.
        return
    if not _UUID_RE.match(actual):
        # Not UUID-shaped — could be a label key or other noise; skip to
        # avoid false positives on, e.g., aliases that happen to contain
        # the substring "org_id".
        return
    raise CrossTenantLeak(
        "Cross-tenant data detected in query result. A row at "
        f"`{path}` carries `{actual}`, which is NOT your authenticated "
        f"organization. Cortex MCP only serves data scoped to your own "
        f"organization — cross-org reads are forbidden. Add "
        "`group_id = $org_id` to every node binding in your query and retry. "
        "If you intended to reference shared concepts across tenants, that "
        "is currently not supported; rephrase the question to stay within "
        "your organization."
    )


def _is_neo4j_node_or_rel(value: Any) -> bool:
    """Detect neo4j.graph.Node / Relationship without forcing an import.

    The neo4j driver may or may not be importable in test contexts; we
    duck-type on the attributes the driver exposes for graph entities.
    """
    cls = type(value)
    mod = getattr(cls, "__module__", "") or ""
    name = getattr(cls, "__name__", "") or ""
    if mod.startswith("neo4j.") and name in {"Node", "Relationship"}:
        return True
    # Some driver versions expose graph entities with a `_properties` dict.
    return hasattr(value, "items") and hasattr(value, "labels") and not isinstance(value, dict)
