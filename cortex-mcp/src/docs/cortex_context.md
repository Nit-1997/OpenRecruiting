# Cortex Graph — Schema Reference

You query a Neo4j graph of the user's recruitment data with the
`execute_query` tool. This document is a reference card: the labels,
the relationships, and worked examples. Keep it open while you compose
queries.

## One rule for every query

Every node binding must include `group_id = $org_id`. The server binds
`$org_id` to the user's organization automatically — reference it as a
parameter, never substitute a literal.

```cypher
// Inline (preferred — most concise)
MATCH (c:Candidate {group_id: $org_id}) RETURN c.name

// WHERE clause (use when combining with other filters)
MATCH (c:Candidate)
WHERE c.group_id = $org_id AND c.status = 'active'
RETURN c.name
```

If you forget, the response comes back with `status="rejected"` and an
`error` telling you exactly what to add. Read it, fix the query, retry —
don't reword the same idea hoping the rejection reason changes.

---

## Labels

| Label | What it represents | Key properties |
|---|---|---|
| `Organization` | The customer (their company) | `name` |
| `Requisition` | A role being hired for | `name`, `role_title`, `role_location`, `status`, `experience_min_years`, `experience_max_years`, `requisition_ref` |
| `Round` | An interview round within a requisition | `name`, `category`, `duration_minutes` |
| `Candidate` | A person in the pipeline | `name`, `status`, `candidate_ref`, `summary` |
| `Interviewer` | A person who conducted interviews | `name`, `interviewer_ref` |
| `Skill` | A technical / functional capability | `name`, `aliases`, `summary` |
| `Competency` | A rubric dimension assessed in interviews | `name`, `heading`, `summary` |
| `Trait` | A behavioral observation | `name`, `polarity` (`positive`/`negative`/`neutral`), `category` |
| `Market` | An industry or domain | `name`, `category`, `aliases` |
| `Location` | A geographic location | `name`, `location_type`, `aliases` |
| `Company` | An external company (e.g. past employer) | `name`, `domain_summary`, `size_signal`, `aliases` |

---

## Relationships

The graph uses **one relationship type** — `RELATES_TO` — with a `name`
property holding the semantic edge type. Always filter on `r.name` to
scope to a specific edge:

```cypher
MATCH (c:Candidate {group_id: $org_id})-[:RELATES_TO {name: 'EXHIBITS'}]->(t:Trait {group_id: $org_id})
WHERE t.polarity = 'positive'
RETURN c.name, t.name
```

| `r.name` | From → To | Meaning |
|---|---|---|
| `HOSTS` | Organization → Requisition | Org owns this req |
| `HAS_ROUND` | Requisition → Round | Round belongs to a req |
| `REQUIRES` | Requisition → Skill | Required skill |
| `VALUES` | Requisition → Trait | Trait the role values |
| `TARGETS` | Requisition → Market | Target market |
| `LOCATED_IN` | Requisition → Location | Role location |
| `ASSESSES` | Round → Skill / Competency | What this round evaluates |
| `INTERVIEWED_IN` | Candidate → Round | Candidate participated in this round |
| `DEMONSTRATED` | Candidate → Skill | Skill the candidate showed |
| `ASSESSED_ON` | Candidate → Competency | Competency that was evaluated |
| `STRONG_IN` / `WEAK_IN` | Candidate → Competency | Rubric outcome |
| `EXHIBITS` | Candidate → Trait | Behavioral observation |
| `EXPERIENCED_IN` | Candidate → Market | Markets in candidate's past work |
| `WORKED_AT` | Candidate → Company | Past employer |
| `OPERATES_IN` | Company → Market | Company industry |
| `BASED_IN` | Candidate → Location | Candidate's location |
| `CONDUCTED` | Interviewer → Round | Interviewer ran this round |
| `DEMONSTRATES` | Interviewer → Trait | Interviewer's observed traits |
| `HIRED_BY` / `REJECTED_BY` | Candidate → Requisition | Pipeline outcome |

`RELATES_TO` edges also carry a `fact` property (a natural-language
sentence describing the relationship) — use it when you want to quote
specifics back to the user.

---

## Example queries

### List requisitions

```cypher
MATCH (req:Requisition {group_id: $org_id})
RETURN req.name, req.role_title, req.role_location, req.status
ORDER BY req.role_title
```

### Candidates in a specific requisition's pipeline

```cypher
MATCH (c:Candidate)-[:RELATES_TO {name: 'INTERVIEWED_IN'}]->(rnd:Round)
      <-[:RELATES_TO {name: 'HAS_ROUND'}]-(req:Requisition)
WHERE c.group_id = $org_id
  AND req.group_id = $org_id
  AND rnd.group_id = $org_id
  AND req.name = $req_name
RETURN DISTINCT c.name, c.status, collect(DISTINCT rnd.name) AS rounds
```

### Compare what a requisition requires to what its rounds actually assess

```cypher
MATCH (req:Requisition {group_id: $org_id})
WHERE req.name = $req_name
OPTIONAL MATCH (req)-[:RELATES_TO {name: 'REQUIRES'}]->(needed:Skill {group_id: $org_id})
OPTIONAL MATCH (req)-[:RELATES_TO {name: 'HAS_ROUND'}]->(rnd:Round {group_id: $org_id})
              -[:RELATES_TO {name: 'ASSESSES'}]->(assessed)
WHERE assessed.group_id = $org_id
RETURN req.name,
       collect(DISTINCT needed.name) AS required_skills,
       collect(DISTINCT assessed.name) AS what_rounds_actually_assess
```

### Top weaknesses across the candidate pool

```cypher
MATCH (c:Candidate)-[r:RELATES_TO {name: 'WEAK_IN'}]->(comp:Competency)
WHERE c.group_id = $org_id AND comp.group_id = $org_id
RETURN comp.name AS competency,
       count(DISTINCT c) AS candidates,
       count(r) AS evidence_count
ORDER BY candidates DESC, evidence_count DESC
LIMIT 10
```

### Positive vs negative trait counts per candidate

```cypher
MATCH (c:Candidate {group_id: $org_id})-[:RELATES_TO {name: 'EXHIBITS'}]->(t:Trait {group_id: $org_id})
RETURN c.name,
       sum(CASE WHEN t.polarity = 'positive' THEN 1 ELSE 0 END) AS positives,
       sum(CASE WHEN t.polarity = 'negative' THEN 1 ELSE 0 END) AS negatives
ORDER BY negatives DESC
```

### What skills did this specific candidate demonstrate?

```cypher
MATCH (c:Candidate {group_id: $org_id})-[r:RELATES_TO {name: 'DEMONSTRATED'}]->(s:Skill {group_id: $org_id})
WHERE c.name = $candidate_name
RETURN s.name, r.fact
```

### Trait frequency

```cypher
MATCH (t:Trait {group_id: $org_id})
WHERE t.polarity = 'negative'
RETURN t.name, count(*) AS mentions
ORDER BY mentions DESC
LIMIT 20
```

### Bounded path traversal

```cypher
MATCH (req:Requisition {group_id: $org_id})-[*1..3]-(s:Skill {group_id: $org_id})
WHERE req.name = $req_name
RETURN DISTINCT s.name
```

---

## Practical tips

- Project specific properties (`RETURN c.name`) rather than whole nodes
  (`RETURN c`) — smaller payloads, easier to format.
- Use `DISTINCT` when joining through multiple paths to avoid dup rows.
- Result sets cap at 1,000 rows per query; query timeout is 10s. If you
  hit either, narrow the `WHERE` or add a `LIMIT`.
- For "most recent" listings, order by `created_at DESC`.
- For org metadata (org name etc.) call `who_am_i` rather than querying
  the `Organization` node.
