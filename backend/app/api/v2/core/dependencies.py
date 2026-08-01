"""
FastAPI dependencies for v2 routers.

Eliminates the per-endpoint `if not current_user.organization_id: raise 403`
boilerplate. Routers inject `current = Depends(get_current_user_with_org)`
and trust that `current.organization_id` is always present and well-formed.
"""

import hmac
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException

from app.api.v2.core.exceptions import ForbiddenError
from app.config import get_settings
from app.dependencies import CurrentUser, get_current_user
from app.services.supabase import SupabaseAdminClient, get_supabase_admin_client


@dataclass(slots=True)
class CurrentUserWithOrg:
    """Authenticated user known to belong to exactly one organization."""

    user: CurrentUser
    organization_id: UUID

    @property
    def organization_id_str(self) -> str:
        return str(self.organization_id)


async def get_current_user_with_org(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUserWithOrg:
    if not current_user.organization_id:
        raise ForbiddenError("User is not associated with an organization")
    return CurrentUserWithOrg(
        user=current_user,
        organization_id=current_user.organization_id,
    )


def get_supabase() -> SupabaseAdminClient:
    """FastAPI dependency form of `get_supabase_admin_client`.

    Wrapping the admin-client factory in a `Depends`-able function lets tests
    override the data layer per-request with `app.dependency_overrides`
    without monkey-patching module globals.
    """
    return get_supabase_admin_client()


async def verify_internal_secret(
    x_internal_secret: str = Header(..., alias="X-Internal-Secret"),
) -> None:
    """Guard internal agent-to-backend endpoints behind the shared secret.

    Fails closed: an unset `INTERNAL_API_SECRET` rejects every request. Uses
    `hmac.compare_digest` for constant-time comparison. Routers adopt this in
    place of their copy-pasted inline checks.
    """
    expected = get_settings().INTERNAL_API_SECRET
    if not expected or not hmac.compare_digest(x_internal_secret, expected):
        raise HTTPException(status_code=401, detail="Invalid internal secret")


# Annotated aliases for the common v2 dependencies — lets routers write
# `current: CurrentUserOrg` / `db: Supabase` instead of repeating the
# Depends(...) wiring. The underlying callables are unchanged, so existing
# `Depends(get_current_user_with_org)` usage keeps working. (The alias is named
# CurrentUserOrg rather than CurrentUser to avoid shadowing the imported
# `CurrentUser` dataclass referenced in this module's signatures.)
CurrentUserOrg = Annotated[CurrentUserWithOrg, Depends(get_current_user_with_org)]
Supabase = Annotated[SupabaseAdminClient, Depends(get_supabase)]
InternalSecret = Annotated[None, Depends(verify_internal_secret)]
