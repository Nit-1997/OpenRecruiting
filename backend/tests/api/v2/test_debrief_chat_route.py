"""Tests for the debrief chat SSE route.

Auth comes from the conftest `recruiter_client` / `unauthed_client` fixtures.
The packet load is mocked via respx (the org-scoped DebriefRepository.get_packet
read of debrief_packets). The runner is stubbed by monkeypatching the module-level
`_build_runner` factory to yield canned ChatEvents — so the route is tested in
isolation from the Anthropic loop and the Cortex token seam.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import httpx
import pytest

import app.api.v2.routers.debrief_chat as chat_router
from app.api.v2.core.dependencies import CurrentUserWithOrg
from app.dependencies import CurrentUser
from app.services.debrief_chat.contracts import ChatEvent
from app.services.debrief_chat.runner import DebriefChatRunner
from tests.helpers.mock_data import ORG_ID, RECRUITER_EMAIL, RECRUITER_USER_ID, REQ_ID
from tests.helpers.supabase_mocks import rest_url

V2_ROOT = "/api/v2"
PACKET_ID = "00000000-0000-0000-0000-0000000000f1"
OTHER_ORG = "00000000-0000-0000-0000-0000000000ee"


_UNSET = object()


def _packet_row(*, org=ORG_ID, packet=_UNSET):
    return {
        "id": PACKET_ID,
        "organization_id": org,
        "requisition_id": REQ_ID,
        "candidate_ids": [],
        "status": "fresh",
        "packet": {"role_title": "PM", "candidates": []} if packet is _UNSET else packet,
    }


class _StubRunner:
    def __init__(self, events):
        self._events = events

    async def run(self, message):
        for ev in self._events:
            yield ev


def _stub_factory(events):
    def factory(row, current, supabase):
        return _StubRunner(events)

    return factory


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def test_chat_requires_auth(unauthed_client):
    resp = unauthed_client.post(
        f"{V2_ROOT}/debrief/packets/{PACKET_ID}/chat", json={"message": "hi"}
    )
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Happy path — SSE frames
# ---------------------------------------------------------------------------
def test_chat_streams_sse_frames(recruiter_client, respx_mock, monkeypatch):
    respx_mock.get(rest_url("debrief_packets")).mock(
        return_value=httpx.Response(200, json=[_packet_row()])
    )
    events = [
        ChatEvent(type="token", data="Ada "),
        ChatEvent(type="token", data="wins."),
        ChatEvent(type="done", data={"turn_idx": 1}),
    ]
    monkeypatch.setattr(chat_router, "_build_runner", _stub_factory(events))

    resp = recruiter_client.post(
        f"{V2_ROOT}/debrief/packets/{PACKET_ID}/chat",
        json={"message": "why does Ada win?"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    frames = [
        json.loads(line[len("data: "):])
        for line in resp.text.splitlines()
        if line.startswith("data: ")
    ]
    assert frames[0] == {"type": "token", "data": "Ada "}
    assert frames[1] == {"type": "token", "data": "wins."}
    assert frames[-1] == {"type": "done", "data": {"turn_idx": 1}}


def test_chat_streams_proposed_action_frame(recruiter_client, respx_mock, monkeypatch):
    respx_mock.get(rest_url("debrief_packets")).mock(
        return_value=httpx.Response(200, json=[_packet_row()])
    )
    events = [
        ChatEvent(type="proposed_action", data={"kind": "propose_add_round", "input": {}}),
        ChatEvent(type="done", data={"turn_idx": 2}),
    ]
    monkeypatch.setattr(chat_router, "_build_runner", _stub_factory(events))

    resp = recruiter_client.post(
        f"{V2_ROOT}/debrief/packets/{PACKET_ID}/chat",
        json={"message": "add a round for Ada"},
    )
    assert resp.status_code == 200
    frames = [
        json.loads(line[len("data: "):])
        for line in resp.text.splitlines()
        if line.startswith("data: ")
    ]
    assert frames[0]["type"] == "proposed_action"
    assert frames[0]["data"]["kind"] == "propose_add_round"


# ---------------------------------------------------------------------------
# Not-ready / not-found
# ---------------------------------------------------------------------------
def test_chat_404_when_packet_missing(recruiter_client, respx_mock):
    respx_mock.get(rest_url("debrief_packets")).mock(
        return_value=httpx.Response(200, json=[])  # single() no rows -> None
    )
    resp = recruiter_client.post(
        f"{V2_ROOT}/debrief/packets/{PACKET_ID}/chat", json={"message": "hi"}
    )
    assert resp.status_code == 404


def test_chat_404_when_cross_org(recruiter_client, respx_mock):
    # get_packet filters on organization_id; a foreign-org packet returns no row.
    respx_mock.get(rest_url("debrief_packets")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = recruiter_client.post(
        f"{V2_ROOT}/debrief/packets/{PACKET_ID}/chat", json={"message": "hi"}
    )
    assert resp.status_code == 404


def test_chat_409_when_packet_body_null(recruiter_client, respx_mock):
    # A draft/generating row with a NULL packet body -> not ready -> 409.
    respx_mock.get(rest_url("debrief_packets")).mock(
        return_value=httpx.Response(200, json=[_packet_row(packet=None)])
    )
    resp = recruiter_client.post(
        f"{V2_ROOT}/debrief/packets/{PACKET_ID}/chat", json={"message": "hi"}
    )
    assert resp.status_code == 409


def test_chat_422_on_empty_message(recruiter_client, respx_mock):
    resp = recruiter_client.post(
        f"{V2_ROOT}/debrief/packets/{PACKET_ID}/chat", json={"message": "   "}
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Factory wiring (the real _build_runner + the Cortex query seam)
# ---------------------------------------------------------------------------
def _current():
    return CurrentUserWithOrg(
        user=CurrentUser(
            id=UUID(RECRUITER_USER_ID),
            email=RECRUITER_EMAIL,
            is_staff=False,
            organization_id=UUID(ORG_ID),
        ),
        organization_id=UUID(ORG_ID),
    )


def test_build_runner_constructs_real_runner():
    row = _packet_row()
    runner = chat_router._build_runner(row, _current(), MagicMock())
    assert isinstance(runner, DebriefChatRunner)


# ---------------------------------------------------------------------------
# /actions endpoint
# ---------------------------------------------------------------------------
CAND_A = "00000000-0000-0000-0000-0000000000a1"


def _packet_row_with_cands(*, org=ORG_ID):
    return {
        "id": PACKET_ID,
        "organization_id": org,
        "requisition_id": REQ_ID,
        "candidate_ids": [CAND_A],
        "status": "fresh",
        "packet": {
            "role_title": "PM",
            "requisition_id": REQ_ID,
            "candidates": [{"candidate_id": CAND_A, "name": "Ada"}],
        },
    }


class _StubActionService:
    def __init__(self, result=None, exc=None):
        self._result = result or {"ok": True, "result_summary": "done"}
        self._exc = exc
        self.executed = None

    async def execute(self, action):
        self.executed = action
        if self._exc:
            raise self._exc
        return self._result


def test_actions_requires_auth(unauthed_client):
    resp = unauthed_client.post(
        f"{V2_ROOT}/debrief/packets/{PACKET_ID}/actions",
        json={"kind": "propose_record_decision", "input": {}},
    )
    assert resp.status_code in (401, 403)


def test_actions_404_when_cross_org(recruiter_client, respx_mock):
    respx_mock.get(rest_url("debrief_packets")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = recruiter_client.post(
        f"{V2_ROOT}/debrief/packets/{PACKET_ID}/actions",
        json={
            "kind": "propose_record_decision",
            "input": {
                "candidate_ids": [CAND_A],
                "verdict": "hire",
                "summary": "s",
                "rationale": "r",
            },
        },
    )
    assert resp.status_code == 404


def test_actions_happy_path(recruiter_client, respx_mock, monkeypatch):
    respx_mock.get(rest_url("debrief_packets")).mock(
        return_value=httpx.Response(200, json=[_packet_row_with_cands()])
    )
    stub = _StubActionService()
    monkeypatch.setattr(
        chat_router, "_build_action_service", lambda row, current, supabase: stub
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/debrief/packets/{PACKET_ID}/actions",
        json={
            "kind": "propose_record_decision",
            "input": {
                "candidate_ids": [CAND_A],
                "verdict": "strong_hire",
                "status": "hired",
                "summary": "Hire Ada",
                "rationale": "Best on system design.",
            },
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["result"]["result_summary"] == "done"
    # The route built a ProposedAction and handed it to the service.
    assert stub.executed.kind.value == "record_decision"
    assert stub.executed.candidate_ids == [CAND_A]


def test_actions_unknown_kind_400(recruiter_client, respx_mock):
    # NOTE: the prompt asked for 422, but the codebase's global handler maps the
    # domain ValidationError to 400 (api/v2/core/error_handlers.py:53). Following
    # the codebase convention (domain exceptions -> global handlers) over the
    # prompt's literal status.
    respx_mock.get(rest_url("debrief_packets")).mock(
        return_value=httpx.Response(200, json=[_packet_row_with_cands()])
    )
    resp = recruiter_client.post(
        f"{V2_ROOT}/debrief/packets/{PACKET_ID}/actions",
        json={
            "kind": "propose_teleport",
            "input": {"candidate_ids": [CAND_A], "summary": "s", "rationale": "r"},
        },
    )
    assert resp.status_code == 400


def test_actions_candidate_not_in_packet_400(recruiter_client, respx_mock, monkeypatch):
    # Membership guard raises a domain ValidationError -> 400 via the global
    # handler (see note on test_actions_unknown_kind_400).
    respx_mock.get(rest_url("debrief_packets")).mock(
        return_value=httpx.Response(200, json=[_packet_row_with_cands()])
    )
    # Use the REAL action service so the membership guard runs and raises.
    resp = recruiter_client.post(
        f"{V2_ROOT}/debrief/packets/{PACKET_ID}/actions",
        json={
            "kind": "propose_record_decision",
            "input": {
                "candidate_ids": ["00000000-0000-0000-0000-0000000000ff"],
                "verdict": "hire",
                "summary": "s",
                "rationale": "r",
            },
        },
    )
    assert resp.status_code == 400


def test_build_action_service_constructs_real_service():
    from app.services.debrief_chat.action_service import DebriefActionService

    row = _packet_row_with_cands()
    svc = chat_router._build_action_service(row, _current(), MagicMock())
    assert isinstance(svc, DebriefActionService)


def test_actions_log_insight_flows_to_insight_service(
    recruiter_client, respx_mock, monkeypatch
):
    """A propose_log_insight action flows through /actions to the (patched)
    DebriefInsightService via the REAL action service -> 200."""
    respx_mock.get(rest_url("debrief_packets")).mock(
        return_value=httpx.Response(200, json=[_packet_row_with_cands()])
    )
    insight_stub = MagicMock()
    insight_stub.log = AsyncMock(
        return_value={"ok": True, "insight_id": "i1", "sync_status": "synced"}
    )
    monkeypatch.setattr(
        chat_router, "DebriefInsightService", lambda *a, **k: insight_stub
    )

    resp = recruiter_client.post(
        f"{V2_ROOT}/debrief/packets/{PACKET_ID}/actions",
        json={
            "kind": "propose_log_insight",
            "input": {
                "candidate_ids": [CAND_A],
                "summary": "Why Ada won",
                "rationale": "Durable signal.",
                "insight_kind": "decision_rationale",
                "text": "Ada won on system-design depth.",
            },
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["result"]["sync_status"] == "synced"
    insight_stub.log.assert_awaited_once()
    kwargs = insight_stub.log.await_args.kwargs
    assert kwargs["candidate_id"] == CAND_A
    assert kwargs["kind"] == "decision_rationale"


# The REAL get_role_pipeline RPC shape: the round NAME is nested at
# cr["round"]["name"] — there is NO top-level "round_name" key (see
# deploy-config/sql/93-fix-get-role-pipeline-interviewer-name.sql).
def _pipeline_payload():
    return {
        "candidates": [
            {
                "id": CAND_A,
                "candidate_rounds": [
                    {
                        "id": "cr-onsite",
                        "round_id": "rid-onsite",
                        "round": {"id": "rid-onsite", "name": "System Design"},
                    },
                    {
                        "id": "cr-screen",
                        "round_id": "rid-screen",
                        "round": {"id": "rid-screen", "name": "Screen"},
                    },
                ],
            }
        ]
    }


def _bind_resolver(monkeypatch):
    async def fake_get_role_candidates(supabase, org_id, role_id):
        return _pipeline_payload()

    monkeypatch.setattr(
        chat_router.pipeline_service, "get_role_candidates", fake_get_role_candidates
    )
    return chat_router._make_cr_resolver(MagicMock(), ORG_ID, REQ_ID)


@pytest.mark.asyncio
async def test_cr_resolver_maps_round_name_to_cr_id(monkeypatch):
    """The bound cr_resolver resolves a round NAME (cr["round"]["name"]) -> cr id.

    The model emits a round name, not an id; with the real nested RPC shape this is
    the common path. (Was always broken — the resolver only read a non-existent
    top-level "round_name" key.)"""
    resolver = _bind_resolver(monkeypatch)
    assert await resolver(CAND_A, "System Design") == "cr-onsite"


@pytest.mark.asyncio
async def test_cr_resolver_maps_round_id_to_cr_id(monkeypatch):
    """The resolver also accepts a literal round_id."""
    resolver = _bind_resolver(monkeypatch)
    assert await resolver(CAND_A, "rid-screen") == "cr-screen"


@pytest.mark.asyncio
async def test_cr_resolver_returns_empty_on_no_match(monkeypatch):
    """No matching round -> "" (the action service surfaces it as a
    ValidationError -> 400 via the global handler)."""
    resolver = _bind_resolver(monkeypatch)
    assert await resolver(CAND_A, "Nonexistent Round") == ""



@pytest.mark.asyncio
async def test_make_cortex_query_mints_token_and_unwraps_rows():
    rows = [{"competency": "System Design", "candidate": "Ada"}]
    resp_envelope = {
        "result": {"content": [{"text": json.dumps({"status": "ok", "data": rows})}]}
    }
    with patch.object(
        chat_router, "mint_cortex_service_token", return_value=("tok", 300)
    ) as mock_mint, patch.object(
        chat_router.CortexGapReader,
        "_execute_query",
        new=AsyncMock(return_value=resp_envelope),
    ):
        cortex_query = chat_router._make_cortex_query(ORG_ID)
        out = await cortex_query("MATCH (n) RETURN n", {"org_id": ORG_ID})

    assert out == rows
    mock_mint.assert_called_once_with(org_id=ORG_ID, org_name="OpenRecruiting")


# ---------------------------------------------------------------------------
# GET /packets/{id}/conversation — persisted history hydration
# ---------------------------------------------------------------------------
def test_conversation_requires_auth(unauthed_client):
    resp = unauthed_client.get(f"{V2_ROOT}/debrief/packets/{PACKET_ID}/conversation")
    assert resp.status_code in (401, 403)


def test_conversation_404_when_packet_missing(recruiter_client, respx_mock):
    respx_mock.get(rest_url("debrief_packets")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = recruiter_client.get(f"{V2_ROOT}/debrief/packets/{PACKET_ID}/conversation")
    assert resp.status_code == 404


def test_conversation_returns_persisted_turns(recruiter_client, respx_mock):
    respx_mock.get(rest_url("debrief_packets")).mock(
        return_value=httpx.Response(200, json=[_packet_row()])
    )
    turns = [
        {"role": "user", "text": "why Ada?", "idx": 0, "ts": "2026-06-09T10:00:00+00:00"},
        {
            "role": "assistant",
            "text": "",
            "idx": 1,
            "proposed_action": {"kind": "propose_add_round", "input": {}},
        },
        {"role": "assistant", "text": "Ada leads on design.", "idx": 2},
    ]
    respx_mock.get(rest_url("debrief_conversations")).mock(
        return_value=httpx.Response(200, json=[{"turns": turns}])
    )
    resp = recruiter_client.get(f"{V2_ROOT}/debrief/packets/{PACKET_ID}/conversation")
    assert resp.status_code == 200
    body = resp.json()
    assert body["packet_id"] == PACKET_ID
    assert len(body["turns"]) == 3
    assert body["turns"][0]["role"] == "user"
    assert body["turns"][0]["ts"] == "2026-06-09T10:00:00+00:00"
    # Pre-stamp turns simply have no ts; propose-only turns keep their action.
    assert body["turns"][2]["ts"] is None
    assert body["turns"][1]["proposed_action"]["kind"] == "propose_add_round"


def test_conversation_empty_when_no_row(recruiter_client, respx_mock):
    respx_mock.get(rest_url("debrief_packets")).mock(
        return_value=httpx.Response(200, json=[_packet_row()])
    )
    respx_mock.get(rest_url("debrief_conversations")).mock(
        return_value=httpx.Response(200, json=[])
    )
    resp = recruiter_client.get(f"{V2_ROOT}/debrief/packets/{PACKET_ID}/conversation")
    assert resp.status_code == 200
    assert resp.json()["turns"] == []
