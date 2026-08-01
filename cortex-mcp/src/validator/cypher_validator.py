"""Read-only, single-tenant Cypher validator.

Two jobs:
  1) Reject anything that could write, mutate, or escape the read scope.
  2) Ensure every tenant-scoped node binding is filtered by `group_id = $org_id`.

The validator never rewrites the query. On failure it returns a structured
ValidationError with a precise reason the caller's LLM can read and use to
fix its next attempt.

The `$org_id` parameter is force-bound from the JWT in execute_query, so
all the validator needs to verify is that the *reference* to `$org_id`
(or an inline `{group_id: $org_id}`) exists on every tenant binding.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from src.validator.tokenizer import (
    extract_node_bindings,
    find_unbounded_variable_paths,
    strip_literals_and_comments,
)


class ValidationError(Exception):
    """Raised when a query violates a safety rule. Message is meant to be
    surfaced to the calling LLM so it can correct the query."""


# EVERY node label in the Cortex graph carries org-specific data — the V2
# ontology design intended cross-tenant concept merging via embeddings, but
# the actual ingestion stamps every node with `group_id`. We treat every
# label as tenant-scoped until ingestion truly merges concepts.
#
# This is the single source of truth for the validator. If you add a new
# label that is genuinely cross-tenant (e.g., a curated canonical taxonomy
# table), add it to CROSS_ORG_LABELS — but verify in the graph first that
# the data is actually shared, not per-tenant.
TENANT_LABELS: frozenset[str] = frozenset({
    "Candidate",
    "Requisition",
    "Round",
    "Interviewer",
    "Organization",
    "Skill",
    "Competency",
    "Market",
    "Trait",
    "Location",
    "Company",
    "Community",
    "Entity",
    "Episodic",
})

# Labels that are scoped via a DIFFERENT property name than `group_id`.
# IngestionRecord uses `org_id` instead.
_ALT_SCOPE_PROPERTY: dict[str, str] = {
    "IngestionRecord": "org_id",
}

# Labels that are NOT tenant-scoped at all. Currently empty — kept as a
# placeholder for future curated cross-org taxonomies.
CROSS_ORG_LABELS: frozenset[str] = frozenset()


# Things that are immediately disqualifying. Matched case-insensitively
# against the stripped query (no string literals or comments).
_FORBIDDEN_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bCREATE\b", "write operation"),
    (r"\bMERGE\b", "write operation"),
    (r"\bDELETE\b", "write operation"),
    (r"\bDETACH\b", "write operation"),
    (r"\bSET\b", "write operation"),
    (r"\bREMOVE\b", "write operation"),
    (r"\bDROP\b", "schema mutation"),
    (r"\bLOAD\s+CSV\b", "bulk import"),
    (r"\bUSING\s+PERIODIC\b", "bulk import"),
    (r"\bFOREACH\b", "write/iteration construct"),
    (r"\bapoc\.cypher\.run\b", "dynamic Cypher execution"),
    (r"\bapoc\.cypher\.doIt\b", "dynamic Cypher execution"),
    (r"\bapoc\.do\.", "dynamic Cypher execution"),
    (r"\bapoc\.periodic\.", "background job procedure"),
    # Export reads the WHOLE graph, ignoring the per-tenant scoping this
    # validator exists to enforce, and writes it somewhere the caller chooses.
    (r"\bapoc\.export\.", "bulk export bypasses tenant scoping"),
    # Load fetches an arbitrary URL from the database server (SSRF) and can
    # pull data in from outside the tenant.
    (r"\bapoc\.load\.", "external data load"),
    (r"\bapoc\.trigger\.", "trigger management"),
    (r"\bapoc\.util\.sleep\b", "resource exhaustion"),
    (r"\bapoc\.systemdb\.", "system database access"),
    (r"\bCALL\s+dbms\.", "administrative procedure"),
    (r"\bCALL\s+db\.index\.", "index management"),
    (r"\bCALL\s+db\.constraint", "constraint management"),
    (r"\bSHOW\s+(USERS|ROLES|PRIVILEGES|DATABASES)\b", "admin metadata"),
    # Subqueries — defer to v2 (validator can't recurse yet).
    # The `\s*\{` discriminates the Cypher-5 subquery form from the
    # legacy `EXISTS(prop)` / `COUNT(prop)` / `COLLECT(expr)` function
    # calls (which use parens). The subquery form has its own MATCH
    # and WHERE inside the braces — and our tenant validator cannot
    # reason about those inner scopes, so an attacker can use them as
    # a side channel (the inner WHERE supplies the scope predicate
    # the validator looks for, while the outer WHERE is an `OR true`
    # tautology that exfiltrates other tenants).
    (r"\bCALL\s*\{", "CALL subqueries are not supported in v1"),
    (r"\bEXISTS\s*\{", "EXISTS subqueries are not supported in v1"),
    (r"\bCOUNT\s*\{", "COUNT subqueries are not supported in v1"),
    (r"\bCOLLECT\s*\{", "COLLECT subqueries are not supported in v1"),
)

_FORBIDDEN_COMPILED: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p, re.IGNORECASE), reason) for p, reason in _FORBIDDEN_PATTERNS
)


# WHERE-clause extraction + conjunct verification.
#
# Earlier this function merely regex-searched the stripped query for
# `var.group_id = $org_id`. That let a tautology slip past:
#     MATCH (c:Candidate) WHERE c.group_id = $org_id OR true RETURN c.name
# the substring is present, but the OR neuters the scope and returns every
# tenant's rows. The result guard cannot catch this when the projection
# omits `group_id`. We now require the scope predicate to appear as a
# *top-level AND-conjunct* of a WHERE clause — not buried inside an OR/NOT
# branch.
_WHERE_RE = re.compile(r"\bWHERE\b", re.IGNORECASE)

_WHERE_TERMINATORS_RE = re.compile(
    r"\b(MATCH|OPTIONAL\s+MATCH|RETURN|WITH|UNWIND|UNION|ORDER|SKIP|LIMIT|CALL)\b",
    re.IGNORECASE,
)

_AND_RE = re.compile(r"\bAND\b", re.IGNORECASE)
_OR_OR_NOT_RE = re.compile(r"\b(OR|NOT)\b", re.IGNORECASE)


def _extract_where_clauses(stripped_query: str) -> list[str]:
    """Return each *top-level* WHERE clause body.

    Only WHERE keywords at paren/bracket/brace depth 0 in the outer query
    count. A WHERE that sits inside `{ ... }` (e.g. an EXISTS / COUNT /
    COLLECT subquery body) belongs to a nested scope the tenant validator
    cannot reason about — counting that body would let an attacker supply
    the scope predicate from inside the subquery while the OUTER WHERE is
    a tautology (`... OR true`). The forbidden-pattern check already
    rejects today's known subquery forms, but this is the structural
    guarantee.
    """
    bodies: list[str] = []
    n = len(stripped_query)
    depth = 0
    i = 0
    while i < n:
        ch = stripped_query[i]
        if ch in "([{":
            depth += 1
            i += 1
            continue
        if ch in ")]}":
            depth = max(0, depth - 1)
            i += 1
            continue
        if depth == 0:
            m = _WHERE_RE.match(stripped_query, i)
            if m:
                start = m.end()
                body_depth = 0
                j = start
                end = n
                while j < n:
                    c = stripped_query[j]
                    if c in "([{":
                        body_depth += 1
                        j += 1
                        continue
                    if c in ")]}":
                        body_depth = max(0, body_depth - 1)
                        j += 1
                        continue
                    if body_depth == 0:
                        tm = _WHERE_TERMINATORS_RE.match(stripped_query, j)
                        if tm:
                            end = j
                            break
                    j += 1
                bodies.append(stripped_query[start:end])
                i = end
                continue
        i += 1
    return bodies


def _split_top_level_and(where_body: str) -> list[str]:
    """Split a WHERE-clause body at top-level (depth-0) `AND` keywords.
    Conjuncts inside parens / brackets / braces stay grouped so an inner
    `AND` cannot fool us into thinking we have an extra top-level conjunct.
    """
    parts: list[str] = []
    depth = 0
    cursor = 0
    i = 0
    n = len(where_body)
    while i < n:
        ch = where_body[i]
        if ch in "([{":
            depth += 1
            i += 1
            continue
        if ch in ")]}":
            depth = max(0, depth - 1)
            i += 1
            continue
        if depth == 0:
            am = _AND_RE.match(where_body, i)
            if am:
                parts.append(where_body[cursor:i])
                cursor = am.end()
                i = am.end()
                continue
        i += 1
    parts.append(where_body[cursor:])
    return [p.strip() for p in parts if p.strip()]


def _strip_balanced_outer_parens(s: str) -> str:
    """Strip balanced outer `( ... )` wrapping the whole expression. Only
    strips when the opening paren closes at the very end — `(a) AND (b)` is
    left untouched."""
    s = s.strip()
    while len(s) >= 2 and s[0] == "(" and s[-1] == ")":
        depth = 0
        balanced = True
        for idx, ch in enumerate(s):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and idx != len(s) - 1:
                    balanced = False
                    break
        if not balanced:
            break
        s = s[1:-1].strip()
    return s


def _where_predicate_exists(stripped_query: str, var: str) -> bool:
    """True iff some WHERE clause has a top-level AND-conjunct that is
    literally `var.group_id = $org_id` (or the flipped form). Conjuncts
    that contain `OR` / `NOT` are rejected — even if the scope predicate
    appears inside them — because boolean short-circuiting can neuter the
    filter."""
    exact = re.compile(
        rf"^\s*{re.escape(var)}\s*\.\s*group_id\s*=\s*\$org_id\s*$",
        re.IGNORECASE,
    )
    flipped = re.compile(
        rf"^\s*\$org_id\s*=\s*{re.escape(var)}\s*\.\s*group_id\s*$",
        re.IGNORECASE,
    )
    for body in _extract_where_clauses(stripped_query):
        for conjunct in _split_top_level_and(body):
            inner = _strip_balanced_outer_parens(conjunct)
            if not inner:
                continue
            if _OR_OR_NOT_RE.search(inner):
                continue
            if exact.match(inner) or flipped.match(inner):
                return True
    return False


# Regex that detects inline `{group_id: $org_id}` inside the binding's
# property bag. The tokenizer hands us the binding's "rest" (everything
# between (var:Label and the closing ).
def _inline_property_filter(rest: str) -> bool:
    # `{...group_id: $org_id...}`
    return bool(re.search(r"group_id\s*:\s*\$org_id\b", rest))


@dataclass
class ValidationResult:
    ok: bool
    reason: str | None = None


def validate_cypher(query: str) -> None:
    """Validate a Cypher query. Raises ValidationError on any violation.

    Does not modify the query. The caller is responsible for force-binding
    `$org_id` in the params dict before execution.
    """
    if not query or not query.strip():
        raise ValidationError("Empty query.")

    if len(query) > 16_000:
        raise ValidationError("Query exceeds 16,000 character limit.")

    # 0. Reject hard-coded UUID-looking literals near `group_id` BEFORE any
    # other binding-level check, so the user gets the most actionable error.
    # We check the ORIGINAL query (with literals intact).
    if re.search(
        r"group_id\s*=\s*['\"][0-9a-f]{8}-[0-9a-f]{4}",
        query,
        re.IGNORECASE,
    ):
        raise ValidationError(
            "Hard-coded org_id literal detected. Use the `$org_id` parameter instead."
        )

    stripped = strip_literals_and_comments(query)

    # 1. Reject forbidden constructs.
    for pat, reason in _FORBIDDEN_COMPILED:
        m = pat.search(stripped)
        if m:
            raise ValidationError(
                f"Forbidden construct `{m.group(0)}` ({reason}). "
                f"Only MATCH/OPTIONAL MATCH/WITH/RETURN/UNWIND/UNION are allowed."
            )

    # 2. Reject unbounded variable-length paths.
    unbounded = find_unbounded_variable_paths(stripped)
    if unbounded:
        raise ValidationError(
            f"Variable-length relationship patterns must be bounded with an "
            f"explicit upper bound (e.g. `[*1..3]`). Offending: {unbounded[0]!r}"
        )

    # 3. Find every node binding and verify tenant scoping.
    bindings = extract_node_bindings(stripped)

    # First pass: build a map of variable -> primary label for every binding
    # that explicitly declares one. Subsequent unlabeled references to the
    # same variable (e.g. in OPTIONAL MATCH clauses) inherit this label.
    var_to_label: dict[str, str] = {}
    for b in bindings:
        if b.var and b.label and b.var not in var_to_label:
            var_to_label[b.var] = b.label

    seen_tenant_bindings = 0

    for b in bindings:
        # Multi-label patterns: too risky to reason about per-label scoping.
        if b.extra_labels:
            raise ValidationError(
                f"Multi-label node patterns are not supported (saw "
                f"`{b.label}:{':'.join(b.extra_labels)}`). Use a single label per binding."
            )

        # A binding with no label and no variable, e.g. `()`, is fine — it's a
        # bare path step. A binding with a variable but no label is allowed
        # ONLY if the same variable was previously declared with a label
        # (idiomatic re-use across MATCH / OPTIONAL MATCH clauses).
        label = b.label
        if label is None:
            if b.var is None:
                # Anonymous node, e.g. `()-[r]->(c:Candidate)` — fine.
                continue
            inherited = var_to_label.get(b.var)
            if inherited is None:
                raise ValidationError(
                    f"Node binding `({b.var})` is missing a label. Every variable "
                    f"binding must specify an explicit label "
                    f"(e.g. `({b.var}:Candidate)`)."
                )
            # The earlier labeled binding already enforced tenant scoping;
            # an unlabeled re-use does not need to re-prove it.
            label = inherited
            if label in TENANT_LABELS:
                seen_tenant_bindings += 1
            continue

        if label in CROSS_ORG_LABELS:
            continue

        if label not in TENANT_LABELS:
            raise ValidationError(
                f"Unknown label `{label}`. Allowed labels: {sorted(TENANT_LABELS)}."
            )

        # Tenant label: require either an inline filter on this binding's
        # property bag OR a `var.group_id = $org_id` predicate elsewhere.
        if b.var is None:
            # An unbound tenant binding can't be referenced in a WHERE, so
            # it MUST have inline filtering.
            if not _inline_property_filter(b.rest):
                raise ValidationError(
                    f"Unbound `(:{b.label})` pattern must include "
                    f"`{{group_id: $org_id}}` inline."
                )
            seen_tenant_bindings += 1
            continue

        if _inline_property_filter(b.rest):
            seen_tenant_bindings += 1
            continue

        if _where_predicate_exists(stripped, b.var):
            seen_tenant_bindings += 1
            continue

        raise ValidationError(
            f"Node `{b.var}:{b.label}` is missing a `group_id` filter. "
            f"Add `{b.var}.group_id = $org_id` to the WHERE clause or "
            f"`{{group_id: $org_id}}` inline."
        )

    # 4. Trivial RETURN-only queries (no MATCH at all) are permitted — they
    # don't touch the graph at all.
    if "MATCH" not in stripped.upper():
        return
