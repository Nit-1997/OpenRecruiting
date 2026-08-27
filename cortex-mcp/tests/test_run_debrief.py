"""Tests for the run_debrief MCP tool (spec §11).

run_debrief proxies to cortex-backend's POST /api/v1/debrief with the shared
X-Internal-Secret, then renders a COMPACT, non-technical text summary for a
talent-leader. We verify:

  * org_id is taken from auth.org_id — NEVER from a tool param.
  * The proxy payload + headers + URL are correct.
  * An httpx.AsyncClient is built per-call and closed (no loop-bound global).
  * The text summary leads with the recommendation and includes the ranking,
    confidence, and top risks.
  * The summary NEVER leaks internals (org_id, Cypher, tool names, HTTP/infra
    words) per the MCP "zero tolerance" instructions.
  * Every error path returns a friendly string and NEVER raises.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.auth.context import AuthContext
from src.tools.run_debrief import run_debrief

ORG_ID = "8f5311b7-7427-47c0-97d1-e1e6c4c23847"
REQ_ID = "11111111-1111-1111-1111-111111111111"
CAND_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CAND_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

# Words that must NEVER surface to the non-technical user (MCP instructions
# §"NEVER say or show these"). Lowercased substring match against the summary.
FORBIDDEN = [
    ORG_ID,
    "org_id",
    "group_id",
    "cypher",
    "match (",
    "relates_to",
    "neo4j",
    "x-internal-secret",
    "internal_secret",
    "http",
    "endpoint",
    "/api/v1/debrief",
    "execute_query",
    "run_debrief",
    "mcp",
    "json",
    "token",
    "jwt",
    "traceback",
]


def _auth(org_id: str = ORG_ID) -> AuthContext:
    return AuthContext(
        user_id="user-1",
        org_id=org_id,
        org_name="Acme Talent",
        user_name="Dana",
        role="admin",
        scopes=("cortex:read",),
    )


def _packet(**overrides: Any) -> dict:
    """A minimal-but-valid DebriefPacket dict (spec §4)."""
    packet = {
        "id": "pkt-1",
        "requisition_id": REQ_ID,
        "role_title": "Senior Product Manager",
        "title": "PM Finalists Debrief",
        "subtitle": "2 candidates",
        "generated_at": "2026-06-07T00:00:00Z",
        "generated_by": "Scout debrief agent",
        "status": "fresh",
        "confidence": "high",
        "verdict": "hire",
        "headline_recommendation": (
            "Sloane Nair is the strongest fit and is ready for an offer."
        ),
        "panel_members": [],
        "candidates": [
            {
                "candidate_id": CAND_A,
                "name": "Sloane Nair",
                "initials": "PN",
                "color": "#123456",
                "rank": 1,
                "verdict": "hire",
                "headline": "Clear product instincts.",
                "aggregate_score": 3.6,
                "score_scale": 4,
                "rounds_completed": 3,
                "rounds_total": 3,
                "top_strengths": ["Stakeholder alignment"],
                "top_concerns": [],
                "recommendation": "Move to offer.",
                "panel_votes": [],
            },
            {
                "candidate_id": CAND_B,
                "name": "Marcus Webb",
                "initials": "MW",
                "color": "#654321",
                "rank": 2,
                "verdict": "mixed",
                "headline": "Strong execution, thin on strategy.",
                "aggregate_score": 2.9,
                "score_scale": 4,
                "rounds_completed": 2,
                "rounds_total": 3,
                "top_strengths": ["Execution"],
                "top_concerns": ["Strategic depth"],
                "recommendation": "Hold pending a strategy round.",
                "panel_votes": [],
            },
        ],
        "source_stats": {"scorecards": 5, "transcripts": 5},
        "themes": [],
        "decision_matrix": [],
        "risks": [
            "Marcus has not completed the strategy round.",
            "Limited evidence on Sloane's data fluency.",
        ],
        "next_steps": [],
    }
    packet.update(overrides)
    return packet


def _mock_client_returning(response: httpx.Response) -> tuple[AsyncMock, AsyncMock]:
    """Build an AsyncClient stub usable as an `async with` ctx manager.

    Returns (client, post_mock) so tests can assert on the POST call and on
    `aclose`. The real tool may use either `async with` or explicit aclose;
    we support both by making the context manager return the same client.
    """
    client = AsyncMock(spec=httpx.AsyncClient)
    client.post = AsyncMock(return_value=response)
    client.aclose = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client, client.post


def _patch_client(client: AsyncMock):
    """Patch httpx.AsyncClient *inside the run_debrief module* to return our stub."""
    return patch("src.tools.run_debrief.httpx.AsyncClient", return_value=client)


# ---------------------------------------------------------------------------
# Happy path — proxy contract
# ---------------------------------------------------------------------------

@patch("src.tools.run_debrief.get_settings")
async def test_org_id_comes_from_auth_not_params(mock_settings):
    """The proxied body's org_id MUST be auth.org_id; a caller cannot inject it."""
    mock_settings.return_value = MagicMock(
        cortex_backend_internal_url="http://cortex:8010",
        internal_secret="s3cr3t",
        debrief_timeout_seconds=30.0,
    )
    client, post = _mock_client_returning(httpx.Response(200, json=_packet()))

    with _patch_client(client):
        await run_debrief(
            auth=_auth("the-real-org"),
            requisition_id=REQ_ID,
            candidate_ids=[CAND_A, CAND_B],
        )

    _, kwargs = post.call_args
    assert kwargs["json"]["org_id"] == "the-real-org"
    # The tool signature has no org param, but defensively confirm the request
    # carries exactly the three contract fields.
    assert set(kwargs["json"].keys()) == {"org_id", "requisition_id", "candidate_ids"}


@patch("src.tools.run_debrief.get_settings")
async def test_proxy_payload_url_and_headers(mock_settings):
    mock_settings.return_value = MagicMock(
        cortex_backend_internal_url="http://cortex:8010/",  # trailing slash tolerated
        internal_secret="s3cr3t",
        debrief_timeout_seconds=30.0,
    )
    client, post = _mock_client_returning(httpx.Response(200, json=_packet()))

    with _patch_client(client):
        await run_debrief(
            auth=_auth(),
            requisition_id=REQ_ID,
            candidate_ids=[CAND_A, CAND_B],
        )

    args, kwargs = post.call_args
    url = args[0] if args else kwargs.get("url")
    assert url == "http://cortex:8010/api/v1/debrief"
    assert kwargs["json"] == {
        "org_id": ORG_ID,
        "requisition_id": REQ_ID,
        "candidate_ids": [CAND_A, CAND_B],
    }
    assert kwargs["headers"]["X-Internal-Secret"] == "s3cr3t"


@patch("src.tools.run_debrief.get_settings")
async def test_client_is_closed_after_call(mock_settings):
    mock_settings.return_value = MagicMock(
        cortex_backend_internal_url="http://cortex:8010",
        internal_secret="s3cr3t",
        debrief_timeout_seconds=30.0,
    )
    client, _ = _mock_client_returning(httpx.Response(200, json=_packet()))

    with _patch_client(client):
        await run_debrief(auth=_auth(), requisition_id=REQ_ID, candidate_ids=[CAND_A, CAND_B])

    # Closed via aclose() or via __aexit__ of an async-with — accept either.
    assert client.aclose.await_count >= 1 or client.__aexit__.await_count >= 1


# ---------------------------------------------------------------------------
# Summary content + non-leakage
# ---------------------------------------------------------------------------

@patch("src.tools.run_debrief.get_settings")
async def test_summary_leads_with_recommendation_and_includes_signal(mock_settings):
    mock_settings.return_value = MagicMock(
        cortex_backend_internal_url="http://cortex:8010",
        internal_secret="s3cr3t",
        debrief_timeout_seconds=30.0,
    )
    client, _ = _mock_client_returning(httpx.Response(200, json=_packet()))

    with _patch_client(client):
        summary = await run_debrief(
            auth=_auth(), requisition_id=REQ_ID, candidate_ids=[CAND_A, CAND_B]
        )

    assert isinstance(summary, str) and summary.strip()
    # Recommended winner named, ranking shows the runner-up, confidence stated,
    # at least one risk surfaced.
    assert "Sloane Nair" in summary
    assert "Marcus Webb" in summary
    assert "high" in summary.lower()  # confidence
    assert "strategy round" in summary  # a risk
    # Leads with the answer: the recommended candidate appears before the
    # runner-up in the text.
    assert summary.index("Sloane Nair") < summary.index("Marcus Webb")


@patch("src.tools.run_debrief.get_settings")
async def test_summary_never_leaks_internals(mock_settings):
    mock_settings.return_value = MagicMock(
        cortex_backend_internal_url="http://cortex:8010",
        internal_secret="s3cr3t",
        debrief_timeout_seconds=30.0,
    )
    client, _ = _mock_client_returning(httpx.Response(200, json=_packet()))

    with _patch_client(client):
        summary = await run_debrief(
            auth=_auth(), requisition_id=REQ_ID, candidate_ids=[CAND_A, CAND_B]
        )

    lower = summary.lower()
    for banned in FORBIDDEN:
        assert banned.lower() not in lower, f"summary leaked forbidden token: {banned!r}"
    # Candidate UUIDs must not appear (only display names).
    assert CAND_A not in summary
    assert CAND_B not in summary


# ---------------------------------------------------------------------------
# Error paths — friendly, never raises, never leaks
# ---------------------------------------------------------------------------

@patch("src.tools.run_debrief.get_settings")
async def test_http_error_status_returns_friendly_message(mock_settings):
    mock_settings.return_value = MagicMock(
        cortex_backend_internal_url="http://cortex:8010",
        internal_secret="s3cr3t",
        debrief_timeout_seconds=30.0,
    )
    client, _ = _mock_client_returning(
        httpx.Response(500, text="Traceback: KeyError at line 42 in debrief_service")
    )

    with _patch_client(client):
        summary = await run_debrief(
            auth=_auth(), requisition_id=REQ_ID, candidate_ids=[CAND_A, CAND_B]
        )

    assert isinstance(summary, str) and summary.strip()
    lower = summary.lower()
    for banned in FORBIDDEN:
        assert banned.lower() not in lower
    assert "traceback" not in lower
    assert "keyerror" not in lower


@patch("src.tools.run_debrief.get_settings")
async def test_network_error_returns_friendly_message(mock_settings):
    mock_settings.return_value = MagicMock(
        cortex_backend_internal_url="http://cortex:8010",
        internal_secret="s3cr3t",
        debrief_timeout_seconds=30.0,
    )
    client, _ = _mock_client_returning(httpx.Response(200, json=_packet()))
    client.post = AsyncMock(side_effect=httpx.ConnectError("network is down"))

    with _patch_client(client):
        summary = await run_debrief(
            auth=_auth(), requisition_id=REQ_ID, candidate_ids=[CAND_A, CAND_B]
        )

    assert isinstance(summary, str) and summary.strip()
    assert "network is down" not in summary.lower()
    assert "http" not in summary.lower()


@patch("src.tools.run_debrief.get_settings")
async def test_malformed_packet_returns_friendly_message(mock_settings):
    """A 200 with a non-packet body must not raise — degrade gracefully."""
    mock_settings.return_value = MagicMock(
        cortex_backend_internal_url="http://cortex:8010",
        internal_secret="s3cr3t",
        debrief_timeout_seconds=30.0,
    )
    client, _ = _mock_client_returning(httpx.Response(200, json={"unexpected": "shape"}))

    with _patch_client(client):
        summary = await run_debrief(
            auth=_auth(), requisition_id=REQ_ID, candidate_ids=[CAND_A, CAND_B]
        )

    assert isinstance(summary, str) and summary.strip()


@patch("src.tools.run_debrief.get_settings")
async def test_empty_candidates_returns_friendly_message_without_calling_backend(mock_settings):
    """Guard the obvious bad input before spending a backend round-trip."""
    mock_settings.return_value = MagicMock(
        cortex_backend_internal_url="http://cortex:8010",
        internal_secret="s3cr3t",
        debrief_timeout_seconds=30.0,
    )
    client, post = _mock_client_returning(httpx.Response(200, json=_packet()))

    with _patch_client(client):
        summary = await run_debrief(auth=_auth(), requisition_id=REQ_ID, candidate_ids=[])

    assert isinstance(summary, str) and summary.strip()
    post.assert_not_called()


# ---------------------------------------------------------------------------
# Registration — the tool is actually exposed on the FastMCP server
# ---------------------------------------------------------------------------

def _server_env(monkeypatch) -> None:
    """Set the minimal env `src.main` needs to import + build the server."""
    for k, v in {
        "NEO4J_URI": "neo4j+s://placeholder",
        "NEO4J_USERNAME": "placeholder",
        "NEO4J_PASSWORD": "placeholder",
        "NEO4J_DATABASE": "placeholder",
        "OIDC_ISSUER": "http://testserver-auth",
        "OIDC_JWKS_URL": "http://testserver-auth/.well-known/jwks.json",
        "OIDC_AUDIENCE": "cortex-mcp",
        "CORTEX_PUBLIC_URL": "https://cortex.example.test",
    }.items():
        monkeypatch.setenv(k, v)


async def test_run_debrief_is_registered_on_the_server(monkeypatch):
    """The @mcp.tool wrapper must be discoverable under the name 'run_debrief'."""
    _server_env(monkeypatch)

    from src.config.settings import get_settings

    get_settings.cache_clear()
    try:
        import src.main as main_mod

        tools = await main_mod.mcp.list_tools(run_middleware=False)
        names = {t.name for t in tools}
        assert "run_debrief" in names
    finally:
        get_settings.cache_clear()


async def test_run_debrief_tool_schema_accepts_only_contract_params(monkeypatch):
    """The LLM-facing INPUT SCHEMA must accept exactly {requisition_id, candidate_ids}.

    `test_org_id_comes_from_auth_not_params` exercises the inner `run_debrief`
    coroutine, but the LLM never calls that — it calls the `@mcp.tool` wrapper
    `run_debrief_tool`, and all it can see/supply is that tool's published input
    schema. The "org is bound server-side, the LLM never supplies it" invariant
    therefore lives at THIS boundary. If someone added an `org_id`/`group_id`/
    `organization_id` parameter to the wrapper, the inner-function tests above
    would still pass while the tenant wall is breached at the schema the LLM sees.

    We assert against the serialized MCP wire schema (`to_mcp_tool().inputSchema`)
    — exactly what FastMCP advertises to clients. The `ctx: Context` param is
    injected server-side and is correctly absent from that schema.
    """
    _server_env(monkeypatch)

    from src.config.settings import get_settings

    get_settings.cache_clear()
    try:
        import src.main as main_mod

        tools = await main_mod.mcp.list_tools(run_middleware=False)
        by_name = {t.name: t for t in tools}
        assert "run_debrief" in by_name, "run_debrief tool not registered"

        # The schema as serialized over the wire to the MCP client (the LLM).
        input_schema = by_name["run_debrief"].to_mcp_tool().inputSchema
        accepted = set(input_schema.get("properties", {}).keys())

        assert accepted == {"requisition_id", "candidate_ids"}, (
            "run_debrief exposes unexpected input parameters to the LLM: "
            f"{accepted}"
        )
        # Explicit, named guards so a regression names the leaked org param.
        for tenant_param in ("org_id", "group_id", "organization_id"):
            assert tenant_param not in accepted, (
                f"run_debrief must NOT accept a tenant param ({tenant_param!r}) "
                "from the LLM — org_id is bound server-side from auth."
            )
    finally:
        get_settings.cache_clear()
