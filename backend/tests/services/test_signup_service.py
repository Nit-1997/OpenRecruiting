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


# --- Seat-limit branch (BE-P0-1) ----------------------------------------------

_FUTURE = "2999-01-01T00:00:00+00:00"
_TARGET_ORG = "org-target-1"
_SEAT_LIMIT = 5


class _SeatLimitTable:
    """Routes per-table behaviour for the invite seat-limit path.

    The signup flow issues, in order:
      profiles(single)         -> no existing profile
      organization_invites     -> one valid pending invite
      profiles.count_async()   -> current member count
      subscriptions            -> active sub capping seats at max_users
    """

    def __init__(self, name, member_count):
        self._name = name
        self._member_count = member_count
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

    def single(self):
        self._single = True
        return self

    async def count_async(self):
        # count_async returns an int directly (no .count attribute).
        return self._member_count

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
                "organizations": {"id": _TARGET_ORG, "name": "Enterprise Co", "org_type": "enterprise"},
            }])
        if self._name == "subscriptions":
            return _Resp([{
                "custom_max_users": _SEAT_LIMIT,
                "plan_id": "plan-1",
                "plans": {"max_users": _SEAT_LIMIT},
                "status": "active",
            }])
        return _Resp([])


class _SeatLimitSupa:
    def __init__(self, member_count):
        self._member_count = member_count

    def table(self, name):
        return _SeatLimitTable(name, self._member_count)

    async def get_auth_user(self, user_id):
        return {
            "email": "newcomer@enterprise.com",
            "user_metadata": {"full_name": "New Comer"},
        }


@pytest.mark.asyncio
async def test_complete_signup_seat_limit_reached_blocks_without_typeerror(monkeypatch):
    """When member count == max_users the seat gate must fire and the user is
    blocked. This used to raise TypeError because the code called
    .select("id", count="exact") then read .count; the fix uses count_async().

    SIGNUP_INVITE_ONLY is forced on: with the gate off, a user whose invite is
    refused by the seat cap falls through to getting their own organization
    instead of being blocked."""
    from types import SimpleNamespace

    monkeypatch.setattr(
        signup_service,
        "get_supabase_admin_client",
        lambda: _SeatLimitSupa(member_count=_SEAT_LIMIT),
    )
    monkeypatch.setattr(
        signup_service, "get_settings",
        lambda: SimpleNamespace(SIGNUP_INVITE_ONLY=True),
    )

    with pytest.raises(signup_service.SignupBlockedError):
        await signup_service.complete_user_signup("new-user-1")
