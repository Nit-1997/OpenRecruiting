import pytest
from app.services import signup_service


class _Resp:
    def __init__(self, data): self.data = data


class _Table:
    def __init__(self, profile): self._profile = profile
    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def single(self): return self
    async def execute_async(self): return _Resp(self._profile)


class _Supa:
    def __init__(self, profile): self._profile = profile
    def table(self, name): return _Table(self._profile)


@pytest.mark.asyncio
async def test_complete_signup_returns_existing_profile(monkeypatch):
    profile = {"id": "u1", "email": "a@b.com", "organization_id": "o1"}
    monkeypatch.setattr(
        signup_service, "get_supabase_admin_client", lambda: _Supa(profile)
    )
    result = await signup_service.complete_user_signup("u1")
    assert result == {"is_new": False, "profile": profile}


# --- Invite branch -----------------------------------------------------------

_FUTURE = "2999-01-01T00:00:00+00:00"
_TARGET_ORG = "org-target-1"


class _InviteTable:
    """Routes per-table behaviour for the invite-accept path.

    The signup flow issues, in order:
      profiles(single)      -> no existing profile
      organization_invites  -> one valid pending invite
      organization_invites  -> mark accepted
      profiles              -> insert the new profile
    """

    def __init__(self, name):
        self._name = name
        self._single = False

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def update(self, *a, **k):
        return self

    def insert(self, *a, **k):
        return self

    def single(self):
        self._single = True
        return self

    async def execute_async(self):
        if self._name == "profiles" and self._single:
            return _Resp(None)
        if self._name == "organization_invites":
            return _Resp([{
                "id": "inv-1",
                "organization_id": _TARGET_ORG,
                "email": "newcomer@enterprise.com",
                "status": "pending",
                "expires_at": _FUTURE,
                "organizations": {"id": _TARGET_ORG, "name": "Enterprise Co", "org_type": "team"},
            }])
        if self._name == "profiles":
            return _Resp([{"id": "new-user-1", "organization_id": _TARGET_ORG}])
        return _Resp([])


class _InviteSupa:
    def table(self, name):
        return _InviteTable(name)

    async def get_auth_user(self, user_id):
        return {
            "email": "newcomer@enterprise.com",
            "user_metadata": {"full_name": "New Comer"},
        }


@pytest.mark.asyncio
async def test_valid_invite_admits_user_regardless_of_member_count(monkeypatch):
    """Seats are unlimited: an org is bounded by its credit budget, not a head
    count, so a valid invite always lands the user in the inviting org. This
    replaces the old seat-cap gate, which read the now-dropped subscriptions
    and plans tables."""
    from types import SimpleNamespace

    monkeypatch.setattr(
        signup_service, "get_supabase_admin_client", lambda: _InviteSupa()
    )
    monkeypatch.setattr(
        signup_service, "get_settings",
        lambda: SimpleNamespace(SIGNUP_INVITE_ONLY=True),
    )

    result = await signup_service.complete_user_signup("new-user-1")

    assert result["is_new"] is True
    assert result["organization_id"] == _TARGET_ORG
