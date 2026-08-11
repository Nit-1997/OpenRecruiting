"""Tell the user, precisely, whether their database is ready.

DELIBERATE DEVIATION FROM THE SPEC, with the reason measured rather than
assumed. The design said this service would apply `schema.sql` for the user.
It cannot, and the constraint is not a missing library:

  * the service key CAN detect whether the schema exists — a REST read of a
    known table returns 200 when it is there and 404 when it is not (verified
    against a live project);
  * the service key CANNOT run DDL. PostgREST exposes tables and functions, not
    arbitrary SQL, and there is no `exec` RPC to borrow (verified: 404
    PGRST202). Applying schema.sql needs a direct Postgres connection to
    db.<ref>.supabase.co with the DATABASE password — a different credential
    from the service key, which this UI deliberately does not collect.

Asking for a database superuser password so a setup page can run 53 CREATE
TABLEs is a worse trade than asking someone to paste a file into the SQL editor
once. So this module does the half that is genuinely useful and honest: it says
whether the schema is applied, and if not it hands over the exact steps.

`schema.sql` is also NOT idempotent (53 CREATE TABLE against 6 IF NOT EXISTS,
plus bare CREATE TYPE), so "just run it again" is not safe advice either — the
check below is what stops someone re-running it into a pile of errors.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

# A table that exists only once the schema has been applied. `organizations` is
# the root of the tenancy model, so it can never legitimately be absent from a
# provisioned project.
_SENTINEL_TABLE = "organizations"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


@dataclass(frozen=True)
class SchemaStatus:
    state: str  # "ready" | "not_applied" | "unreachable" | "unconfigured"
    detail: str

    @property
    def ready(self) -> bool:
        return self.state == "ready"


async def check_schema(url: str, service_key: str) -> SchemaStatus:
    """Is this Supabase project provisioned?

    Distinguishes "reachable but empty" from "cannot reach at all", because the
    two need completely different things from the user and conflating them is
    how a wrong URL gets diagnosed as a missing schema.
    """
    if not url or not service_key:
        return SchemaStatus("unconfigured", "Set the project URL and service key first.")

    endpoint = f"{url.rstrip('/')}/rest/v1/{_SENTINEL_TABLE}"
    headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(endpoint, params={"select": "id", "limit": 1}, headers=headers)
    except httpx.HTTPError as exc:
        return SchemaStatus("unreachable", f"Could not reach the project: {exc}")

    if resp.status_code == 200:
        return SchemaStatus("ready", "Schema is applied.")
    if resp.status_code == 404:
        return SchemaStatus(
            "not_applied",
            f"Reached the project, but the '{_SENTINEL_TABLE}' table does not exist yet.",
        )
    if resp.status_code in (401, 403):
        return SchemaStatus("unreachable", "The project rejected the service key.")
    return SchemaStatus("unreachable", f"Unexpected response {resp.status_code}: {resp.text[:200]}")


def manual_instructions(url: str) -> list[str]:
    """What to do when the schema is missing. Concrete enough to follow without
    leaving the page and looking for a doc."""
    project = url.rstrip("/").replace("https://", "").split(".")[0] if url else "<project>"
    return [
        f"Open the SQL editor: https://supabase.com/dashboard/project/{project}/sql/new",
        "Paste the contents of schema.sql from the repository root, and run it.",
        "Then do the same with seed.sql to create the demo organisation.",
        "Come back here and press Re-check.",
        "schema.sql is not re-runnable — if it has already been applied, running "
        "it again will error on objects that already exist. Re-check first.",
    ]
