"""Fixture-driven tests for the Cypher validator.

Two arrays:
  VALID   — queries the validator must accept
  INVALID — queries the validator must reject, with a substring that the
            rejection message must contain (so we catch the right rule).

Add cases here as we discover edge cases; this file is the single source
of truth for what the validator promises.
"""
from __future__ import annotations

import pytest

from src.validator import ValidationError, validate_cypher


VALID = [
    # --- Tenant + inline scoping ---
    "MATCH (c:Candidate {group_id: $org_id}) RETURN c.name",
    "MATCH (req:Requisition {group_id: $org_id}) RETURN req.name, req.uuid",
    "MATCH (r:Round {group_id: $org_id}) RETURN count(r)",
    "MATCH (i:Interviewer {group_id: $org_id}) RETURN i.name",
    "MATCH (o:Organization {group_id: $org_id}) RETURN o.name",

    # --- Tenant + WHERE scoping ---
    "MATCH (c:Candidate) WHERE c.group_id = $org_id RETURN c",
    "MATCH (req:Requisition) WHERE req.group_id = $org_id RETURN req.name LIMIT 10",
    "MATCH (c:Candidate) WHERE c.group_id = $org_id AND c.status = 'active' RETURN c",

    # --- Joining tenant-scoped nodes (every label needs group_id) ---
    "MATCH (c:Candidate {group_id: $org_id})-[:RELATES_TO]->(s:Skill {group_id: $org_id}) RETURN c.name, s.name",
    """MATCH (c:Candidate)-[r:RELATES_TO]->(t:Trait)
       WHERE c.group_id = $org_id AND t.group_id = $org_id AND t.polarity = 'positive'
       RETURN c.name, t.name""",
    """MATCH (req:Requisition {group_id: $org_id})-[:RELATES_TO {name:'HAS_ROUND'}]->(rnd:Round)
       WHERE rnd.group_id = $org_id RETURN req.name, collect(rnd.name)""",

    # --- All concept labels now require tenant scope (V2-ontology dedup
    # not actually live yet; data is per-tenant). ---
    "MATCH (s:Skill {group_id: $org_id}) RETURN s.name LIMIT 50",
    "MATCH (t:Trait {group_id: $org_id}) WHERE t.polarity = 'negative' RETURN t.name, count(*) AS c",
    "MATCH (comp:Competency {group_id: $org_id}) RETURN comp.name",

    # --- OPTIONAL MATCH (Trait still needs tenant scope) ---
    """MATCH (c:Candidate {group_id: $org_id})
       OPTIONAL MATCH (c)-[:RELATES_TO]->(t:Trait {group_id: $org_id})
       RETURN c.name, collect(t.name)""",

    # --- Bounded variable-length (terminus still needs tenant scope) ---
    "MATCH (req:Requisition {group_id: $org_id})-[*1..3]-(s:Skill {group_id: $org_id}) RETURN req.name, s.name",
    "MATCH (c:Candidate {group_id: $org_id})-[r*..5]->(x:Skill {group_id: $org_id}) RETURN c.name, x.name",
    "MATCH p = (req:Requisition {group_id: $org_id})-[:RELATES_TO*2]->(s:Skill {group_id: $org_id}) RETURN p",

    # --- Aggregations + WITH (Trait still needs tenant scope) ---
    """MATCH (c:Candidate {group_id: $org_id})-[r:RELATES_TO {name:'EXHIBITS'}]->(t:Trait {group_id: $org_id})
       WITH c, t.polarity AS pol, count(t) AS n
       WHERE n > 0
       RETURN c.name, pol, n ORDER BY n DESC""",

    # --- UNWIND on input list ---
    """UNWIND ['active', 'hired'] AS s
       MATCH (c:Candidate) WHERE c.group_id = $org_id AND c.status = s
       RETURN s, count(c)""",

    # --- Anonymous nodes in paths ---
    "MATCH (c:Candidate {group_id: $org_id})-[]->()-[]->(s:Skill {group_id: $org_id}) RETURN c.name, s.name",

    # --- Trivial pings (no MATCH) ---
    "RETURN 1 AS ping",
    "RETURN datetime() AS now",

    # --- Literal containing what looks like a MATCH clause must not confuse scanner ---
    """MATCH (c:Candidate {group_id: $org_id})
       WHERE c.summary = 'MATCH (x:Candidate) RETURN x'
       RETURN c.uuid""",

    # --- Comments are ignored ---
    """// pull candidate names for active reqs
       MATCH (c:Candidate {group_id: $org_id})  /* inline comment */
       RETURN c.name""",

    # --- Multi-clause MATCH with different tenant labels ---
    """MATCH (req:Requisition {group_id: $org_id})
       MATCH (c:Candidate) WHERE c.group_id = $org_id
       RETURN req.name, c.name""",

    # --- Both endpoints must be tenant-scoped ---
    "MATCH (s:Skill)<-[]-(c:Candidate) WHERE s.group_id = $org_id AND c.group_id = $org_id RETURN s.name, c.name",

    # --- ORDER BY / LIMIT / SKIP ---
    "MATCH (c:Candidate {group_id: $org_id}) RETURN c.name ORDER BY c.created_at DESC SKIP 0 LIMIT 25",

    # --- UNION over two scoped queries ---
    """MATCH (c:Candidate {group_id: $org_id}) RETURN c.name AS name
       UNION
       MATCH (req:Requisition {group_id: $org_id}) RETURN req.name AS name""",

    # --- DISTINCT, COUNT ---
    "MATCH (c:Candidate {group_id: $org_id}) RETURN DISTINCT c.status, count(*) AS n",
]


# Each entry: (query, substring_that_must_appear_in_rejection_message)
INVALID: list[tuple[str, str]] = [
    # --- Unscoped tenant labels ---
    ("MATCH (c:Candidate) RETURN c", "group_id"),
    ("MATCH (req:Requisition) RETURN req.name", "group_id"),
    ("MATCH (r:Round) RETURN count(r)", "group_id"),

    # --- Hard-coded org_id literal (exfiltration attempt) ---
    (
        "MATCH (c:Candidate) WHERE c.group_id = '8f5311b7-7427-47c0-97d1-e1e6c4c23847' RETURN c",
        "Hard-coded org_id literal",
    ),

    # --- Write operations ---
    ("CREATE (c:Candidate {name: 'x'}) RETURN c", "Forbidden construct"),
    ("MATCH (c:Candidate {group_id: $org_id}) SET c.name = 'x' RETURN c", "Forbidden construct"),
    ("MATCH (c:Candidate {group_id: $org_id}) DELETE c", "Forbidden construct"),
    ("MATCH (c:Candidate {group_id: $org_id}) DETACH DELETE c", "Forbidden construct"),
    ("MERGE (c:Candidate {group_id: $org_id, name: 'x'}) RETURN c", "Forbidden construct"),
    ("MATCH (c:Candidate {group_id: $org_id}) REMOVE c.summary RETURN c", "Forbidden construct"),
    ("MATCH (c:Candidate {group_id: $org_id}) SET c:Flagged RETURN c", "Forbidden construct"),

    # --- Bulk / dangerous constructs ---
    (
        "LOAD CSV FROM 'http://evil/foo.csv' AS row CREATE (n {row})",
        "Forbidden construct",
    ),
    (
        "USING PERIODIC COMMIT MATCH (c:Candidate) RETURN c",
        "Forbidden construct",
    ),

    # --- APOC dynamic execution ---
    (
        "CALL apoc.cypher.run('MATCH (n) RETURN n', {}) YIELD value RETURN value",
        "Forbidden construct",
    ),
    (
        "CALL apoc.do.case([true, 'RETURN 1'], 'RETURN 2', {}) YIELD value RETURN value",
        "Forbidden construct",
    ),
    (
        "CALL apoc.periodic.iterate('MATCH (n) RETURN n', 'RETURN 1', {})",
        "Forbidden construct",
    ),
    ("CALL dbms.listConfig() YIELD name RETURN name", "Forbidden construct"),

    # --- Subqueries (v1 doesn't support) ---
    (
        "CALL { MATCH (c:Candidate {group_id: $org_id}) RETURN c } RETURN c",
        "subqueries are not supported",
    ),

    # --- Variable label without scope (would match everything) ---
    ("MATCH (n) RETURN n LIMIT 100", "missing a label"),
    ("MATCH (n) WHERE n.group_id = $org_id RETURN n", "missing a label"),

    # --- Unbounded variable-length paths ---
    ("MATCH (c:Candidate {group_id: $org_id})-[*]-(x:Skill) RETURN c, x", "bounded"),
    ("MATCH (c:Candidate {group_id: $org_id})-[*1..]-(x:Skill) RETURN c, x", "bounded"),
    ("MATCH (c:Candidate {group_id: $org_id})-[*..]-(x:Skill) RETURN c, x", "bounded"),

    # --- Unknown labels ---
    ("MATCH (n:User) WHERE n.group_id = $org_id RETURN n", "Unknown label"),
    ("MATCH (n:Profile {group_id: $org_id}) RETURN n", "Unknown label"),

    # --- Multi-label patterns ---
    ("MATCH (n:Candidate:VIP {group_id: $org_id}) RETURN n", "Multi-label"),

    # --- Unbound tenant binding without inline scope ---
    ("MATCH (:Candidate)-[]->(s:Skill) RETURN s", "Unbound"),

    # --- Empty query ---
    ("", "Empty query"),
    ("   ", "Empty query"),

    # --- Oversize query ---
    ("MATCH (c:Candidate {group_id: $org_id}) RETURN c // " + "x" * 16001, "16,000"),

    # --- Show admin metadata ---
    ("SHOW DATABASES YIELD name RETURN name", "Forbidden construct"),
    ("SHOW USERS", "Forbidden construct"),

    # --- FOREACH (write/iteration) ---
    (
        """MATCH (c:Candidate {group_id: $org_id})
           FOREACH (x IN [1] | SET c.flag = true) RETURN c""",
        "Forbidden construct",
    ),

    # --- Mixed: one binding scoped, the sibling tenant binding is not ---
    (
        """MATCH (c:Candidate {group_id: $org_id})-[:RELATES_TO]->(other:Candidate)
           RETURN c.name, other.name""",
        "group_id",
    ),

    # --- Concept labels (Skill/Trait/Competency/Market/Company/Location)
    # are NOT cross-tenant in the actual data — every node has a group_id.
    # Unscoped queries against them must reject. ---
    ("MATCH (s:Skill) RETURN s.name", "group_id"),
    ("MATCH (t:Trait) WHERE t.polarity = 'negative' RETURN t.name, count(*)", "group_id"),
    ("MATCH (c:Competency) RETURN c.name", "group_id"),
    ("MATCH (m:Market) RETURN m.name", "group_id"),
    ("MATCH (co:Company) RETURN co.name", "group_id"),
    ("MATCH (loc:Location) RETURN loc.name", "group_id"),
    # Mixed-path with scoped Candidate but unscoped Skill — must still reject
    (
        "MATCH (c:Candidate {group_id: $org_id})-[:RELATES_TO]->(s:Skill) RETURN s.name",
        "group_id",
    ),

    # --- Tautology bypass: scope predicate sits inside an OR branch.
    # The substring `c.group_id = $org_id` is present but the OR neuters it,
    # so the validator MUST reject. ---
    (
        "MATCH (c:Candidate) WHERE c.group_id = $org_id OR true RETURN c.name",
        "group_id",
    ),
    (
        "MATCH (c:Candidate) WHERE c.group_id = $org_id OR 1=1 RETURN c.name",
        "group_id",
    ),
    (
        "MATCH (c:Candidate) WHERE (c.group_id = $org_id OR true) RETURN c.name",
        "group_id",
    ),
    (
        "MATCH (c:Candidate) WHERE c.group_id = $org_id OR c.status = 'open' RETURN c.name",
        "group_id",
    ),

    # --- NOT-wrapped scope predicate: easy to misread as scoping, isn't. ---
    (
        "MATCH (c:Candidate) WHERE NOT (c.group_id <> $org_id) RETURN c.name",
        "group_id",
    ),
    (
        "MATCH (c:Candidate) WHERE NOT c.group_id = $org_id RETURN c.name",
        "group_id",
    ),

    # --- Multi-binding bypass: only one binding has a real top-level AND
    # conjunct; the sibling's predicate is OR'd. ---
    (
        """MATCH (c:Candidate)-[:RELATES_TO]->(s:Skill)
           WHERE c.group_id = $org_id AND (s.group_id = $org_id OR true)
           RETURN c.name, s.name""",
        "group_id",
    ),

    # --- Nested subquery bypass: the inner WHERE supplies the scope
    # predicate the validator looked for, while the OUTER WHERE is
    # `... OR true`. The v1 fix is to reject the subquery form entirely.
    # PoC from Codex adversarial review. ---
    (
        """MATCH (c:Candidate)
           WHERE EXISTS { MATCH (s:Skill {group_id: $org_id})
                           WHERE c.group_id = $org_id RETURN s }
              OR true
           RETURN c.name""",
        "EXISTS subqueries",
    ),
    (
        """MATCH (c:Candidate)
           WHERE COUNT { MATCH (s:Skill {group_id: $org_id})
                          WHERE c.group_id = $org_id RETURN s } > 0
              OR true
           RETURN c.name""",
        "COUNT subqueries",
    ),
    (
        """MATCH (c:Candidate)
           WHERE size(COLLECT { MATCH (s:Skill {group_id: $org_id})
                                 WHERE c.group_id = $org_id RETURN s }) > 0
              OR true
           RETURN c.name""",
        "COLLECT subqueries",
    ),
]


@pytest.mark.parametrize("query", VALID, ids=[f"valid#{i}" for i in range(len(VALID))])
def test_valid_queries_pass(query: str) -> None:
    validate_cypher(query)  # should not raise


@pytest.mark.parametrize(
    "query, expected_substr",
    INVALID,
    ids=[f"invalid#{i}" for i in range(len(INVALID))],
)
def test_invalid_queries_rejected(query: str, expected_substr: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        validate_cypher(query)
    assert expected_substr.lower() in str(excinfo.value).lower(), (
        f"Expected rejection message to contain {expected_substr!r}, "
        f"got: {excinfo.value!s}"
    )


def test_valid_count_meets_floor() -> None:
    assert len(VALID) >= 30, f"Need at least 30 valid fixtures, have {len(VALID)}"


def test_invalid_count_meets_floor() -> None:
    assert len(INVALID) >= 30, f"Need at least 30 invalid fixtures, have {len(INVALID)}"
