"""BE-T6: behavioural coverage of FeedbackNotificationService.

This service composes the recruiter/interviewer notification emails for the
happy path, the not-admitted / interview-complete path, the optional
enhancement path, and the fallback path. It reaches the DB via
get_supabase_admin_client() directly (not an injected client), so that symbol
is monkeypatched in the module namespace; the email/otp boundaries are stub
objects injected onto the service's lazy backing fields.

Key behaviours under test:
  - happy path stamps scorecard_status/processing_status = complete (the CAS
    write) then notifies scheduler + interviewer.
  - openrecruiting vs non-platform interviewer chooses the auth-link vs OTP-link branch.
  - feedback-token creation vs reuse (email change resets OTP fields).
  - fallback skips entirely when scorecard already complete.
"""

from dataclasses import dataclass

import pytest

import app.services.feedback_notification_service as fns
from app.services.feedback_notification_service import FeedbackNotificationService


# --- fakes -----------------------------------------------------------------
@dataclass
class _EmailResult:
    success: bool = True
    message_id: str | None = "msg-1"


class _Resp:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, fake, table):
        self._fake = fake
        self._table = table
        self._op = "select"
        self._payload = None

    def select(self, *a, **k):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def eq(self, *a, **k):
        return self

    def single(self, *a, **k):
        return self

    async def execute_async(self):
        if self._op in ("insert", "update"):
            self._fake.writes.append((self._table, self._op, self._payload))
            return _Resp([dict(self._payload) if isinstance(self._payload, dict) else self._payload])
        queue = self._fake.selects.get(self._table, [])
        data = queue.pop(0) if queue else None
        return _Resp(data)


class _FakeSb:
    def __init__(self):
        self.selects: dict[str, list] = {}
        self.writes: list[tuple] = []

    def table(self, name):
        return _Q(self, name)

    def writes_to(self, table, op):
        return [w for w in self.writes if w[0] == table and w[1] == op]


class _FakeEmail:
    def __init__(self, scheduler=None, interviewer=None):
        self._scheduler = scheduler
        self._interviewer = interviewer
        self.sent: list[dict] = []

    async def get_scheduler_email(self, cr_id):
        return self._scheduler

    async def get_interviewer_email(self, cr_id):
        return self._interviewer

    async def send_templated_email(self, to_email, to_name, subject, template_name, context):
        self.sent.append({
            "to_email": to_email, "subject": subject,
            "template": template_name, "context": context,
        })
        return _EmailResult()


class _FakeOtp:
    OTP_VALIDITY_MINUTES = 720

    def __init__(self, is_registered=False):
        self._is_registered = is_registered

    def generate_otp(self, length=6):
        return "123456"

    def generate_feedback_token(self, length=32):
        return "tok-generated"

    async def is_interviewer_registered(self, email):
        return self._is_registered


@dataclass
class _FakeSettings:
    APP_URL: str = "https://app.test"


def _make_service(fake_sb, monkeypatch, *, scheduler=None, interviewer=None, is_registered=False):
    monkeypatch.setattr(fns, "get_supabase_admin_client", lambda: fake_sb)
    svc = FeedbackNotificationService()
    svc._email_service = _FakeEmail(scheduler=scheduler, interviewer=interviewer)
    svc._otp_service = _FakeOtp(is_registered=is_registered)
    svc._settings = _FakeSettings()
    return svc


def _cr_context_selects(*, interviewer_email="iv@test.com", role_title="Backend Eng"):
    """Queue rows for _get_candidate_round_context: candidate_rounds single,
    then requisitions single. Also pre-seed feedback_access_tokens lookup as
    empty so a fresh token is created (insert)."""
    return {
        "candidate_rounds": [
            {"id": "cr-1", "round_id": "round-1", "interviewer_email": interviewer_email,
             "candidates": {"id": "cand-1", "name": "Jane Doe", "requisition_id": "req-1"}},
        ],
        "requisitions": [
            {"id": "req-1", "role_title": role_title},
        ],
        "feedback_access_tokens": [
            [],  # _ensure_feedback_token: no existing -> insert new
        ],
    }


# --- _get_candidate_round_context -----------------------------------------
@pytest.mark.asyncio
async def test_context_returns_none_when_round_missing(monkeypatch):
    fake = _FakeSb()
    fake.selects = {"candidate_rounds": [None]}
    svc = _make_service(fake, monkeypatch)
    assert await svc._get_candidate_round_context("missing") is None


@pytest.mark.asyncio
async def test_context_returns_none_when_no_candidate(monkeypatch):
    fake = _FakeSb()
    fake.selects = {"candidate_rounds": [{"id": "cr-1", "round_id": "r", "candidates": None}]}
    svc = _make_service(fake, monkeypatch)
    assert await svc._get_candidate_round_context("cr-1") is None


@pytest.mark.asyncio
async def test_context_builds_round_name_from_role_title(monkeypatch):
    fake = _FakeSb()
    fake.selects = _cr_context_selects(role_title="Staff SWE")
    svc = _make_service(fake, monkeypatch)
    ctx = await svc._get_candidate_round_context("cr-1")
    assert ctx["candidate_name"] == "Jane Doe"
    assert ctx["round_name"] == "Staff SWE"


# --- send_happy_path_emails ------------------------------------------------
@pytest.mark.asyncio
async def test_happy_path_404_when_context_missing(monkeypatch):
    fake = _FakeSb()
    fake.selects = {"candidate_rounds": [None]}
    svc = _make_service(fake, monkeypatch)
    out = await svc.send_happy_path_emails("missing")
    assert out == {"error": "candidate_round_not_found"}


@pytest.mark.asyncio
async def test_happy_path_stamps_status_and_notifies_both(monkeypatch):
    fake = _FakeSb()
    fake.selects = _cr_context_selects()
    svc = _make_service(
        fake, monkeypatch,
        scheduler=("sched@test.com", "Sched"),
        interviewer=("iv@test.com", "Ivy"),
        is_registered=False,
    )
    out = await svc.send_happy_path_emails("cr-1")
    # the CAS-style stamp write
    cr_upd = fake.writes_to("candidate_rounds", "update")
    assert cr_upd and cr_upd[0][2]["scorecard_status"] == "complete"
    assert cr_upd[0][2]["processing_status"] == "completed"
    # both notified
    assert out["scheduler"]["sent"] is True
    assert out["interviewer"]["sent"] is True
    # non-platform interviewer -> OTP link + otp stored
    iv_email = next(s for s in svc._email_service.sent if "iv@test.com" == s["to_email"])
    assert "otp=" in iv_email["context"]["feedback_link"]
    assert iv_email["context"]["is_registered_user"] is False


@pytest.mark.asyncio
async def test_happy_path_registered_interviewer_uses_auth_link(monkeypatch):
    fake = _FakeSb()
    fake.selects = _cr_context_selects()
    svc = _make_service(
        fake, monkeypatch,
        scheduler=None,
        interviewer=("iv@test.com", "Ivy"),
        is_registered=True,
    )
    out = await svc.send_happy_path_emails("cr-1")
    assert out["scheduler"] is None
    iv_email = svc._email_service.sent[0]
    assert "platform_auth=pending" in iv_email["context"]["feedback_link"]
    assert iv_email["context"]["is_registered_user"] is True
    assert out["interviewer"]["is_registered_user"] is True


@pytest.mark.asyncio
async def test_happy_path_scheduler_link_includes_candidate(monkeypatch):
    fake = _FakeSb()
    fake.selects = _cr_context_selects()
    svc = _make_service(
        fake, monkeypatch,
        scheduler=("sched@test.com", "Sched"),
        interviewer=None,
    )
    await svc.send_happy_path_emails("cr-1")
    sched_email = svc._email_service.sent[0]
    link = sched_email["context"]["candidate_link"]
    assert "/view/roles/req-1?candidate=cand-1" in link
    assert sched_email["context"]["has_interviewer_email"] is False


# --- _ensure_feedback_token ------------------------------------------------
@pytest.mark.asyncio
async def test_ensure_token_creates_when_absent(monkeypatch):
    fake = _FakeSb()
    fake.selects = {"feedback_access_tokens": [[]]}
    svc = _make_service(fake, monkeypatch)
    token = await svc._ensure_feedback_token("cr-1", "iv@test.com", is_registered_user=False)
    assert token == "tok-generated"
    ins = fake.writes_to("feedback_access_tokens", "insert")
    assert ins and ins[0][2]["interviewer_email"] == "iv@test.com"


@pytest.mark.asyncio
async def test_ensure_token_reuses_and_updates_on_email_change(monkeypatch):
    fake = _FakeSb()
    fake.selects = {"feedback_access_tokens": [[
        {"token": "existing-tok", "interviewer_email": "old@test.com", "is_registered_user": False},
    ]]}
    svc = _make_service(fake, monkeypatch)
    token = await svc._ensure_feedback_token("cr-1", "new@test.com", is_registered_user=True)
    assert token == "existing-tok"
    upd = fake.writes_to("feedback_access_tokens", "update")
    assert upd and upd[0][2]["interviewer_email"] == "new@test.com"
    # email change resets OTP fields
    assert upd[0][2]["otp_code"] is None
    assert upd[0][2]["is_registered_user"] is True


@pytest.mark.asyncio
async def test_ensure_token_updates_only_registered_flag(monkeypatch):
    fake = _FakeSb()
    fake.selects = {"feedback_access_tokens": [[
        {"token": "existing-tok", "interviewer_email": "iv@test.com", "is_registered_user": False},
    ]]}
    svc = _make_service(fake, monkeypatch)
    token = await svc._ensure_feedback_token("cr-1", "iv@test.com", is_registered_user=True)
    assert token == "existing-tok"
    upd = fake.writes_to("feedback_access_tokens", "update")
    assert upd and upd[0][2]["is_registered_user"] is True
    # no email-reset fields since email unchanged
    assert "otp_code" not in upd[0][2]


@pytest.mark.asyncio
async def test_ensure_token_no_update_when_unchanged(monkeypatch):
    fake = _FakeSb()
    fake.selects = {"feedback_access_tokens": [[
        {"token": "existing-tok", "interviewer_email": "iv@test.com", "is_registered_user": False},
    ]]}
    svc = _make_service(fake, monkeypatch)
    token = await svc._ensure_feedback_token("cr-1", "iv@test.com", is_registered_user=False)
    assert token == "existing-tok"
    assert fake.writes_to("feedback_access_tokens", "update") == []


@pytest.mark.asyncio
async def test_store_otp_for_token_sets_expiry(monkeypatch):
    fake = _FakeSb()
    svc = _make_service(fake, monkeypatch)
    await svc._store_otp_for_token("cr-1", "654321")
    upd = fake.writes_to("feedback_access_tokens", "update")
    assert upd and upd[0][2]["otp_code"] == "654321"
    assert upd[0][2]["otp_expires_at"]


# --- send_optional_feedback_enhancement_email ------------------------------
@pytest.mark.asyncio
async def test_optional_enhancement_404_when_context_missing(monkeypatch):
    fake = _FakeSb()
    fake.selects = {"candidate_rounds": [None]}
    svc = _make_service(fake, monkeypatch)
    out = await svc.send_optional_feedback_enhancement_email("missing")
    assert out == {"error": "candidate_round_not_found"}


@pytest.mark.asyncio
async def test_optional_enhancement_skips_without_interviewer(monkeypatch):
    fake = _FakeSb()
    fake.selects = _cr_context_selects()
    svc = _make_service(fake, monkeypatch, interviewer=None)
    out = await svc.send_optional_feedback_enhancement_email("cr-1")
    assert out == {"skipped": "no_interviewer_email"}


@pytest.mark.asyncio
async def test_optional_enhancement_sends_with_is_optional_flag(monkeypatch):
    fake = _FakeSb()
    fake.selects = _cr_context_selects()
    svc = _make_service(fake, monkeypatch, interviewer=("iv@test.com", "Ivy"), is_registered=False)
    out = await svc.send_optional_feedback_enhancement_email("cr-1")
    assert out["interviewer"]["sent"] is True
    sent = svc._email_service.sent[0]
    assert sent["context"]["is_optional"] is True
    assert "otp=" in sent["context"]["feedback_link"]  # non-platform OTP branch
    assert sent["template"] == "feedback_enhancement_optional.html"


@pytest.mark.asyncio
async def test_optional_enhancement_platform_auth_link(monkeypatch):
    fake = _FakeSb()
    fake.selects = _cr_context_selects()
    svc = _make_service(fake, monkeypatch, interviewer=("iv@test.com", "Ivy"), is_registered=True)
    await svc.send_optional_feedback_enhancement_email("cr-1")
    sent = svc._email_service.sent[0]
    assert "platform_auth=pending" in sent["context"]["feedback_link"]
    assert sent["context"]["is_registered_user"] is True


# --- send_interview_complete_emails ----------------------------------------
@pytest.mark.asyncio
async def test_interview_complete_404_when_context_missing(monkeypatch):
    fake = _FakeSb()
    fake.selects = {"candidate_rounds": [None]}
    svc = _make_service(fake, monkeypatch)
    out = await svc.send_interview_complete_emails("missing")
    assert out == {"error": "candidate_round_not_found"}


@pytest.mark.asyncio
async def test_interview_complete_notifies_both(monkeypatch):
    fake = _FakeSb()
    fake.selects = _cr_context_selects()
    svc = _make_service(
        fake, monkeypatch,
        scheduler=("sched@test.com", "Sched"),
        interviewer=("iv@test.com", "Ivy"),
        is_registered=True,
    )
    out = await svc.send_interview_complete_emails("cr-1")
    assert out["interviewer"]["sent"] is True
    assert out["scheduler"]["sent"] is True
    # scheduler email knows an interviewer exists
    sched = next(s for s in svc._email_service.sent if s["to_email"] == "sched@test.com")
    assert sched["context"]["has_interviewer"] is True
    assert sched["template"] == "feedback_not_there_recruiter.html"


@pytest.mark.asyncio
async def test_interview_complete_non_platform_interviewer_otp(monkeypatch):
    fake = _FakeSb()
    fake.selects = _cr_context_selects()
    svc = _make_service(
        fake, monkeypatch,
        scheduler=None,
        interviewer=("iv@test.com", "Ivy"),
        is_registered=False,
    )
    out = await svc.send_interview_complete_emails("cr-1")
    assert out["interviewer"]["sent"] is True
    iv = svc._email_service.sent[0]
    assert "otp=" in iv["context"]["feedback_link"]
    assert iv["context"]["is_registered_user"] is False


@pytest.mark.asyncio
async def test_interview_complete_scheduler_only(monkeypatch):
    fake = _FakeSb()
    fake.selects = _cr_context_selects()
    svc = _make_service(
        fake, monkeypatch,
        scheduler=("sched@test.com", "Sched"),
        interviewer=None,
    )
    out = await svc.send_interview_complete_emails("cr-1")
    assert out["interviewer"] is None
    assert out["scheduler"]["sent"] is True
    sched = svc._email_service.sent[0]
    assert sched["context"]["has_interviewer"] is False


# --- send_fallback_emails --------------------------------------------------
@pytest.mark.asyncio
async def test_fallback_skips_when_already_complete(monkeypatch):
    fake = _FakeSb()
    fake.selects = {"candidate_rounds": [{"scorecard_status": "complete"}]}
    svc = _make_service(fake, monkeypatch)
    out = await svc.send_fallback_emails("cr-1")
    assert out == {"skipped": "feedback_already_complete"}
    # no emails sent
    assert svc._email_service.sent == []


@pytest.mark.asyncio
async def test_fallback_404_when_context_missing(monkeypatch):
    fake = _FakeSb()
    # first read: scorecard_status not complete; then context read -> None
    fake.selects = {"candidate_rounds": [{"scorecard_status": "pending"}, None]}
    svc = _make_service(fake, monkeypatch)
    out = await svc.send_fallback_emails("cr-1")
    assert out == {"error": "candidate_round_not_found"}


@pytest.mark.asyncio
async def test_fallback_notifies_scheduler_and_interviewer_non_platform(monkeypatch):
    fake = _FakeSb()
    fake.selects = {
        # fallback prechecks scorecard_status (not complete), then context reads
        "candidate_rounds": [
            {"scorecard_status": "pending"},
            {"id": "cr-1", "round_id": "round-1", "interviewer_email": "iv@test.com",
             "candidates": {"id": "cand-1", "name": "Jane Doe", "requisition_id": "req-1"}},
        ],
        "requisitions": [{"id": "req-1", "role_title": "Backend Eng"}],
        "feedback_access_tokens": [[]],  # ensure token -> insert
    }
    svc = _make_service(
        fake, monkeypatch,
        scheduler=("sched@test.com", "Sched"),
        interviewer=("iv@test.com", "Ivy"),
        is_registered=False,
    )
    out = await svc.send_fallback_emails("cr-1")
    assert out["scheduler"]["sent"] is True
    assert out["interviewer"]["sent"] is True
    # non-platform reminder: OTP appended to the shareable link + otp stored
    iv = next(s for s in svc._email_service.sent if s["to_email"] == "iv@test.com")
    assert "otp=123456" in iv["context"]["feedback_link"]
    assert iv["context"]["is_registered_user"] is False
    # the shareable link was given to the scheduler
    sched = next(s for s in svc._email_service.sent if s["to_email"] == "sched@test.com")
    assert "shareable_link" in sched["context"]


@pytest.mark.asyncio
async def test_fallback_registered_interviewer_auth_link(monkeypatch):
    fake = _FakeSb()
    fake.selects = {
        "candidate_rounds": [
            {"scorecard_status": "pending"},
            {"id": "cr-1", "round_id": "round-1", "interviewer_email": "iv@test.com",
             "candidates": {"id": "cand-1", "name": "Jane Doe", "requisition_id": "req-1"}},
        ],
        "requisitions": [{"id": "req-1", "role_title": "Backend Eng"}],
        "feedback_access_tokens": [[]],
    }
    svc = _make_service(
        fake, monkeypatch,
        scheduler=None,
        interviewer=("iv@test.com", "Ivy"),
        is_registered=True,
    )
    out = await svc.send_fallback_emails("cr-1")
    assert out["scheduler"] is None
    iv = svc._email_service.sent[0]
    assert "platform_auth=pending" in iv["context"]["feedback_link"]
    assert iv["context"]["is_registered_user"] is True


# --- send_capture_request_to_interviewer -----------------------------------
@pytest.mark.asyncio
async def test_capture_request_non_platform(monkeypatch):
    fake = _FakeSb()
    fake.selects = {"feedback_access_tokens": [[]]}
    svc = _make_service(fake, monkeypatch, is_registered=False)
    ctx = {"candidate_name": "Jane", "round_name": "Interview"}
    out = await svc.send_capture_request_to_interviewer(("iv@test.com", "Ivy"), ctx, "cr-1")
    assert out["sent"] is True
    sent = svc._email_service.sent[0]
    assert "otp=" in sent["context"]["feedback_link"]
    assert sent["template"] == "feedback_reminder_interviewer.html"


@pytest.mark.asyncio
async def test_capture_request_openrecruiting(monkeypatch):
    fake = _FakeSb()
    fake.selects = {"feedback_access_tokens": [[]]}
    svc = _make_service(fake, monkeypatch, is_registered=True)
    ctx = {"candidate_name": "Jane", "round_name": "Interview"}
    out = await svc.send_capture_request_to_interviewer(("iv@test.com", "Ivy"), ctx, "cr-1")
    assert out["is_registered_user"] is True
    sent = svc._email_service.sent[0]
    assert "platform_auth=pending" in sent["context"]["feedback_link"]


# --- lazy property wiring + cache ------------------------------------------
def test_lazy_properties_resolve(monkeypatch):
    monkeypatch.setattr(fns, "get_email_service", lambda: "EMAIL")
    monkeypatch.setattr(fns, "get_otp_service", lambda: "OTP")
    monkeypatch.setattr(fns, "get_settings", lambda: "SETTINGS")
    svc = FeedbackNotificationService()
    assert svc.email_service == "EMAIL"
    assert svc.otp_service == "OTP"
    assert svc.settings == "SETTINGS"


def test_get_feedback_notification_service_cached():
    fns.get_feedback_notification_service.cache_clear()
    a = fns.get_feedback_notification_service()
    b = fns.get_feedback_notification_service()
    assert a is b
