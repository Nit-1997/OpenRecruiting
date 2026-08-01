# OpenRecruiting Cortex MCP

A read-only, multi-tenant **Model Context Protocol** server that exposes the OpenRecruiting Cortex
recruitment-intelligence graph to MCP-compatible clients (Claude.ai web, Claude Code,
agentic tools).

> Customers authenticate with their Scout account, get a scoped JWT, and run
> parameterized Cypher against their own organization's slice of the graph.
> Cross-tenant reads are structurally impossible.

## Architecture

```
Claude.ai / Claude Code
        │  bearer JWT (issued by backend OAuth)
        ▼
cortex-mcp.localhost:3000/mcp   (streamable-HTTP MCP)
        │
        ▼
┌──────────────────────────────┐
│  Cortex MCP (this service)   │
│  ┌────────────────────────┐  │
│  │ AuthMiddleware         │  │  validates JWT, extracts org_id
│  │ Tools:                 │  │
│  │  • who_am_i            │  │  display-safe identity (no UUIDs)
│  │  • get_cortex_context  │  │  schema + tenancy rule + examples
│  │  • execute_query       │  │  validate → force-bind $org_id → execute
│  └────────────────────────┘  │
└──────────────────────────────┘
        │
        ▼
   Neo4j (Cortex graph)
```

## Why three tools, not ten?

The graph is the product, but the *queries* are the surface. Three composable tools
beat a curated catalog because:

1. The customer's LLM already has reasoning ability — we don't need to think for it.
2. Cypher is more expressive than any fixed REST schema we could ship.
3. The deterministic validator makes tenancy a structural property, not a documentation one.

## Tools

| Tool | Returns | When to call |
|---|---|---|
| `who_am_i()` | `{org_name, user_name, role, scopes}` (no UUIDs) | At session start, for narration |
| `get_cortex_context()` | Markdown: schema + tenancy rule + 8 example queries | Once per session, before writing Cypher |
| `execute_query(query, params)` | `{status: "ok"\|"rejected"\|"error", data, error}` | Every time a query needs to be run |

## Validator — what's blocked

The validator is the security boundary. It rejects:

- **Writes & mutations**: `CREATE`, `MERGE`, `DELETE`, `DETACH`, `SET`, `REMOVE`, `DROP`, `FOREACH`
- **Bulk/dynamic execution**: `LOAD CSV`, `USING PERIODIC`, `apoc.cypher.run`, `apoc.do.*`, `apoc.periodic.*`
- **Admin procs**: `CALL dbms.*`, `CALL db.index.*`, `SHOW DATABASES/USERS/ROLES`
- **Unscoped tenant queries**: any `MATCH (c:Candidate)` without `group_id = $org_id`
- **Hard-coded org_id literals**: `WHERE c.group_id = '<uuid>'` (must use `$org_id` param)
- **Multi-label patterns**: `MATCH (n:Candidate:VIP)` — too risky to reason about per-label scoping
- **Unbounded variable-length paths**: `[*]`, `[*1..]`, `[*..]`
- **Unknown labels**: anything outside the documented tenant + cross-org sets
- **CALL subqueries** (v1 — the tokenizer doesn't recurse yet)

The `$org_id` parameter value is *always* injected from the JWT, overriding any
caller-supplied value. The customer's LLM never sees nor needs the org UUID.

## Setup

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env  # fill in NEO4J_* and OIDC_* values

# Run the test suite (66 validator tests, all offline)
.venv/bin/python -m pytest tests/test_validator.py

# Run E2E tests against a live Neo4j (requires real creds)
RUN_E2E=1 .venv/bin/python -m pytest tests/test_e2e_live.py

# Run the server
.venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8020
```

Or as part of the full stack (recommended — runs alongside `backend`,
which is required for OAuth):

```bash
cd ../deploy-config/backend-deploy
sudo bash ec2-deploy.sh
```

`ec2-deploy.sh` auto-generates the JWT signing keypair on first run and
appends it to `.env` — no manual openssl steps needed.

For testing the MCP without the full OAuth flow, mint a dev token:

```bash
python3 scripts/mint_dev_token.py --org acme
# Token prints to stdout; paste into Claude Code .mcp.json Authorization header
```

This works as long as `.env` in `deploy-config/backend-deploy/` has the
auto-generated `MCP_JWT_PRIVATE_KEY_PEM`. The dev token is identical in
shape to one issued by the OAuth flow — Cortex MCP can't tell them apart.

## OAuth (depends on backend work)

This service expects bearer JWTs issued by Scout's OAuth authorization server
(implemented in `backend`). The token must contain:

| Claim | Type | Required | Notes |
|---|---|---|---|
| `sub` | string | yes | User UUID |
| `org_id` | string | yes | Organization UUID — becomes `$org_id` in every query |
| `org_name` | string | no | Display name for `who_am_i` |
| `name` | string | no | User display name |
| `role` | string | no | User role for `who_am_i` |
| `scope` | string | yes | Must include `cortex:read` |
| `aud` | string | yes | Must equal `OIDC_AUDIENCE` env var |
| `iss` | string | yes | Must equal `OIDC_ISSUER` env var |
| `exp` | int | yes | Standard expiry |

Public keys are fetched from `OIDC_JWKS_URL` and cached for 10 minutes.

## Roadmap

- [x] v1: 3 tools, deterministic validator, streamable HTTP transport
- [ ] OAuth 2.1 authorization server in `backend` (DCR + /authorize + /token)
- [ ] Caddy route for `cortex-mcp.localhost:3000` (TLS termination)
- [ ] Per-tool telemetry (query latency, rejection rate, top queries)
- [ ] v2: optional LLM anomaly review (soft warn, doesn't block)
- [ ] v2: `CALL { ... }` subquery support (requires real Cypher AST parser)
- [ ] v2: `explain_query(query)` for cost preview
- [ ] Enterprise tier: per-org Aura instance option for full DB-level isolation
