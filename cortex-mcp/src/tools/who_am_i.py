"""who_am_i — return the caller's identity, scoped to display-safe fields only.

Deliberately does NOT include `org_id` or `user_id` (UUIDs). The customer's
LLM should never see those values — the `$org_id` parameter in Cypher queries
is bound server-side from the JWT.

We also OMIT any field whose value is null/empty. Returning `user_name: null`
trains the LLM to literally narrate "user_name: null" back to the end user
and to speculate about why provisioning is incomplete. The LLM should only
see fields that have real values; missing fields simply don't exist from
its perspective.
"""
from __future__ import annotations

from src.auth.context import AuthContext


async def who_am_i(auth: AuthContext) -> dict:
    payload: dict = {"org_name": auth.org_name}
    if auth.user_name:
        payload["user_name"] = auth.user_name
    if auth.role:
        payload["role"] = auth.role
    if auth.scopes:
        payload["scopes"] = list(auth.scopes)
    return payload
