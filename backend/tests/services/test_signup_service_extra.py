"""Extra coverage for signup_service.complete_user_signup — the invite happy
path, the no-invite block, the auth-user-missing error, and the
invite-lookup transient-failure re-raise (which must NOT delete the orphan auth
row).
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import signup_service

_FUTURE = "2999-01-01T00:00:00+00:00"
_PAST = "2000-01-01T00:00:00+00:00"
_ORG = "org-target"


def _resp(data):
    return MagicMock(data=data)


class _RoutedTable:
    """Routes execute_async / count_async per table name. `profiles(single)` is
    the existing-profile check; the second `profiles` insert returns the new row.
    """

    def __init__(self, name, plan):
        self._name = name
        self._plan = plan
        self._single = False
        self._insert = False

    def select(self, *a, **k):
        return self

    def insert(self, *a, **k):
        self._insert = True
        return self

    def update(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def single(self):
        self._single = True
        return self

    async def count_async(self):
        return self._plan.get("member_count", 0)

    async def execute_async(self):
        if self._name == "profiles":
            if self._insert:
                return _resp({"id": "new-user", "email": self._plan["email"]})
            return _resp(None)  # no existing profile
        if self._name == "organization_invites":
            return _resp(self._plan.get("invite"))
        if self._name == "organizations" and self._insert:
            # Self-serve path: the org the user gets when signup is not gated.
            return _resp([{"id": "org-self-serve", "name": self._plan.get("org_name")}])
        return _resp([])


class _RoutedSupa:
    def __init__(self, plan):
        self._plan = plan

    def table(self, name):
        return _RoutedTable(name, self._plan)

    async def get_auth_user(self, user_id):
        return self._plan.get("auth_user")


def _patch(plan, invite_only=False):
    """Patch the Supabase client and the SIGNUP_INVITE_ONLY setting together.

    invite_only defaults to False to match the shipped default (self-hosted
    instances are not invite-gated); tests that exercise the gate opt in.
    """
    return patch.multiple(
        signup_service,
        get_supabase_admin_client=lambda: _RoutedSupa(plan),
        get_settings=lambda: SimpleNamespace(SIGNUP_INVITE_ONLY=invite_only),
    )


async def test_signup_via_valid_invite_no_subscription_cap():
    plan = {
        "email": "newcomer@enterprise.com",
        "auth_user": {"email": "newcomer@enterprise.com", "user_metadata": {"full_name": "New Comer"}},
        "invite": [{
            "id": "inv-1",
            "organization_id": _ORG,
            "email": "newcomer@enterprise.com",
            "status": "pending",
            "expires_at": _FUTURE,
            "organizations": {"id": _ORG, "name": "Enterprise Co"},
        }],
        "member_count": 0,
    }
    with _patch(plan):
        result = await signup_service.complete_user_signup("new-user")
    assert result["is_new"] is True
    assert result["organization_id"] == _ORG


async def test_signup_auth_user_not_found_raises():
    plan = {"email": "x@y.com", "auth_user": None}
    with _patch(plan):
        with pytest.raises(ValueError, match="Auth user not found"):
            await signup_service.complete_user_signup("ghost")


async def test_signup_no_invite_blocks_when_invite_only():
    plan = {
        "email": "nobody@nowhere.com",
        "auth_user": {"email": "nobody@nowhere.com", "user_metadata": {}},
        "invite": [],  # no pending invite
    }
    with _patch(plan, invite_only=True):
        with pytest.raises(signup_service.SignupBlockedError):
            await signup_service.complete_user_signup("nobody")


async def test_signup_expired_invite_blocks_when_invite_only():
    plan = {
        "email": "late@enterprise.com",
        "auth_user": {"email": "late@enterprise.com", "user_metadata": {}},
        "invite": [{
            "id": "inv-2",
            "organization_id": _ORG,
            "email": "late@enterprise.com",
            "status": "pending",
            "expires_at": _PAST,  # expired -> invite ignored
            "organizations": {"id": _ORG, "name": "Enterprise Co"},
        }],
    }
    with _patch(plan, invite_only=True):
        with pytest.raises(signup_service.SignupBlockedError):
            await signup_service.complete_user_signup("late")


# --- Permissive path (SIGNUP_INVITE_ONLY=false, the self-hosted default) ------


async def test_signup_without_invite_creates_own_org_when_not_gated():
    """A self-hoster with no invite must get their own organization rather than
    being turned away on their own instance."""
    plan = {
        "email": "solo@example.com",
        "auth_user": {
            "email": "solo@example.com",
            "user_metadata": {"full_name": "Solo Recruiter"},
        },
        "invite": [],
        "org_name": "Solo Recruiter's Workspace",
    }
    with _patch(plan, invite_only=False):
        result = await signup_service.complete_user_signup("solo")

    assert result["is_new"] is True
    assert result["organization_id"] == "org-self-serve"


async def test_signup_expired_invite_falls_through_to_own_org_when_not_gated():
    plan = {
        "email": "late@example.com",
        "auth_user": {"email": "late@example.com", "user_metadata": {}},
        "invite": [{
            "id": "inv-3",
            "organization_id": _ORG,
            "email": "late@example.com",
            "status": "pending",
            "expires_at": _PAST,
            "organizations": {"id": _ORG, "name": "Enterprise Co"},
        }],
    }
    with _patch(plan, invite_only=False):
        result = await signup_service.complete_user_signup("late")

    # The expired invite is ignored, so they land in their own org, not _ORG.
    assert result["organization_id"] == "org-self-serve"


async def test_signup_invite_lookup_failure_reraises():
    """A transient DB read failure during invite lookup must propagate (so the
    API returns 500) and NOT fall through to the invite-only block."""

    class _FailingInviteTable(_RoutedTable):
        async def execute_async(self):
            if self._name == "organization_invites":
                raise RuntimeError("db timeout")
            return await super().execute_async()

    class _Supa(_RoutedSupa):
        def table(self, name):
            return _FailingInviteTable(name, self._plan)

    plan = {
        "email": "x@y.com",
        "auth_user": {"email": "x@y.com", "user_metadata": {}},
    }
    with patch.object(signup_service, "get_supabase_admin_client", lambda: _Supa(plan)):
        with pytest.raises(RuntimeError, match="db timeout"):
            await signup_service.complete_user_signup("u-transient")
