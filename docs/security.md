# Security model

OpenRecruiting is self-hosted. You run it, you own its security. This page
describes what the code does defend, what it assumes you will do, and what is
knowingly left to you — so you can decide whether it clears your bar before you
put real candidate data in it.

This is an archived reference release, not a maintained product. Read this page
as an honest description of the state of the code, not a guarantee.

## Trust boundaries

| Boundary | Enforced by |
|---|---|
| Browser → backend | Supabase JWT, verified per request against `SUPABASE_JWT_SECRET` |
| Browser → database | Row-level security, scoped to the caller's organization |
| Backend → database | `service_role` key, which **bypasses RLS by design** |
| Service → service | `INTERNAL_API_SECRET` in an `X-Internal-Secret` header |
| Recall.ai → backend | HMAC webhook signature (`RECALL_WEBHOOK_SECRET`) |
| MCP client → graph | RS256 JWT, plus a deterministic Cypher validator |

## Multi-tenancy

Tenant isolation is row-level security in Postgres, not application code. Every
tenant-scoped table has RLS enabled with policies keyed on the caller's
organization, so a query that forgets a `WHERE organization_id = …` returns
nothing rather than another tenant's rows.

The `service_role` key deliberately bypasses all of it. That is why the backend
holds it and the browser never does: **anything with that key is fully
privileged**. If you leak it, RLS provides you no protection at all.

### `SECURITY DEFINER` functions

Multi-statement mutations run inside `SECURITY DEFINER` plpgsql functions so they
are atomic. Those functions execute as their owner and bypass RLS — that is the
point of them, and the reason they are dangerous if callable by the wrong role.

A stock Supabase project grants `EXECUTE` on new functions in `public` to `anon`
and `authenticated`. Left alone, that would let anyone holding the publishable
key call, for example, `admin_archive_organization()` against any organization.
`schema.sql` therefore ends with an explicit lockdown: every definer function is
revoked from `PUBLIC`, `anon` and `authenticated`, and granted only to
`service_role`. Every RPC in this codebase is called by the backend with the
service-role key, so nothing legitimate needs the broader grant.

**If you add a `SECURITY DEFINER` function, add its `REVOKE`/`GRANT` pair too.**
You can check the current state with:

```sql
select p.proname
from pg_proc p join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'public' and p.prosecdef
  and (has_function_privilege('authenticated', p.oid, 'EXECUTE')
       or has_function_privilege('anon', p.oid, 'EXECUTE'));
-- expected: zero rows
```

## The Cortex MCP query path

`execute_query` lets an MCP client run Cypher against the recruiting graph. Two
guards run on the **call** path, not merely at discovery:

1. A deterministic validator rejects anything that is not a read — writes, schema
   changes, `LOAD CSV`, subqueries the validator cannot reason about, and APOC
   procedures that would escape tenant scoping (`apoc.export`, `apoc.load`,
   `apoc.cypher.run`, `apoc.periodic`, and friends). No LLM is involved in the
   decision.
2. `$org_id` is force-bound from the caller's token. A client that passes its own
   `org_id` has that value overwritten and the attempt logged.

Both are covered by regression tests in `cortex-mcp/tests/`.

## The staff admin portal

`admin-app` (:3001) is part of this release and runs as a compose service. It is
gated entirely on `profiles.is_staff`, which is effectively superuser across
every organization in the instance — see [setup/supabase.md](setup/supabase.md).

**Known issue: the staff-gate pre-check can be bypassed with a forged cookie.**
`admin-app/middleware.ts` skips the `is_staff` lookup whenever the request
carries `openrecruiting-staff-verified=true`. That cookie is a 5-minute cache,
unsigned and not bound to the session; `httpOnly` stops browser JavaScript from
writing it, not an attacker's HTTP client from sending it.

It is defense-in-depth only, and the layer beneath it holds: `admin-app` talks to
Supabase with the publishable key and the caller's own session — it never holds
the service-role key — and every admin table is row-level-security gated on
`public.is_admin()`, a `SECURITY DEFINER` server-side read of `profiles.is_staff`.
`AuthGuard` also re-checks per page. Forging the cookie therefore yields the UI
shell with its data denied, not the data. Fix it before exposing the portal
beyond localhost: bind the cache to the session, or drop it and take the lookup
on every request.

## What is not shipped here

The Slack agent is **not part of this release** — its backend was removed, and
the agent service it called was never in this repo. An IDOR in that agent's
entity lookup, from the original security review, is therefore unreachable here.
If you port it in from elsewhere, review that path first.

## Your responsibilities

- **Keep `SUPABASE_SECRET_KEY` server-side.** Never put it in a `NEXT_PUBLIC_*`
  variable — those are compiled into the browser bundle.
- **Change `INTERNAL_API_SECRET`** from the placeholder before exposing anything.
- **Terminate TLS in front of the backend.** Nothing here does it for you, and
  the auth cookie and internal secret both travel in headers.
- **Do not expose the workers or Neo4j publicly.** The compose file only
  publishes what needs to be reachable; the workers use `expose`, not `ports`.
- **Set the Supabase auth redirect allow-list** to your own origins.
- **Consider `SIGNUP_INVITE_ONLY=true`** on anything shared. It is off by default
  because on a personal instance your Supabase auth settings already decide who
  can sign in at all.

## Known considerations

- **The `ENV=test` webhook bypass.** To keep test fixtures from minting HMACs,
  unsigned webhooks are accepted when `ENV=test`. This is gated: unless
  `WEBHOOK_BASE_URL` is a recognised local or tunnel host, the deployment is
  treated as production and signature verification runs anyway. The check is
  fail-closed — an unset or unfamiliar host counts as production. Do not run
  `ENV=test` in production regardless.
- **Feedback portal tokens travel in URLs.** Interviewers reach the no-login
  feedback portal through a tokenised link, so the token appears in browser
  history and any referrer. Tokens are single-purpose and expiring, but treat
  those links as secrets.
- **Bring-your-own LLM keys leave your instance.** Interview transcripts are sent
  to whichever provider you configure. If that matters for your candidates, say
  so in your privacy notice.
- **No rate limiting.** There is none in front of the public endpoints. Put a
  reverse proxy or WAF in front of anything internet-facing.

## Reporting

This release is unmaintained, so there is no response SLA. If you find something,
open a GitHub issue. Please do not include real candidate data in a report.
