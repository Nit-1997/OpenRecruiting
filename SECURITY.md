# Security Policy

OpenRecruiting is self-hostable: **you** own the security of your deployment.

**[`docs/security.md`](docs/security.md)** is the real document. It covers the
trust boundaries, the row-level-security multi-tenancy model, the
`SECURITY DEFINER` lockdown, the Cortex MCP query guards, what you are expected
to configure, and the known considerations that are left to you.

Before putting real candidate data in an instance, read at least these:

- Keep `SUPABASE_SECRET_KEY` server-side — it bypasses row-level security.
- Change `INTERNAL_API_SECRET` from its placeholder.
- Terminate TLS in front of the backend.
- Don't run `ENV=test` in production.

## Reporting a vulnerability

This is an archived reference release and is not actively maintained, so there is
no response SLA. Open a GitHub issue. Please don't include real candidate data.
