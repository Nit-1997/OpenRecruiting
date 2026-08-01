"""Tests for GET /api/v2/public/blog/posts search-filter injection hardening.

The `search` query param is interpolated into PostgREST's `or=` grammar. Raw
user input containing `,` `(` `)` `.` `"` could break out of the intended
ilike filter and inject arbitrary conditions. The router must escape it so the
constructed `or` filter stays a safe two-condition ilike on title/excerpt.
"""

import httpx
import pytest

from tests.helpers.supabase_mocks import rest_url

ENDPOINT = "/api/v2/public/blog/posts"


def _mock_blog(respx_mock):
    """Mock both the count (Range header) and the list GET on blog_posts.

    Returns the respx route so the test can inspect the captured request's
    `or` query param.
    """
    return respx_mock.get(rest_url("blog_posts")).mock(
        return_value=httpx.Response(
            200,
            json=[],
            headers={"Content-Range": "0-0/0"},
        )
    )


@pytest.mark.parametrize(
    "malicious",
    [
        "foo,status.eq.draft",          # comma breaks out into a new condition
        "foo)",                          # close-paren breaks the or() group
        "title.eq.secret",               # dots form a PostgREST operator path
        'foo"bar',                       # double-quote could break quoting
        "a,b(c).d",                      # everything at once
    ],
)
def test_malicious_search_is_escaped_not_injected(unauthed_client, respx_mock, malicious):
    route = _mock_blog(respx_mock)

    resp = unauthed_client.get(ENDPOINT, params={"search": malicious})

    # Endpoint behaves normally (no 500, no PostgREST error) and returns empty.
    assert resp.status_code == 200, resp.text
    assert resp.json()["posts"] == []

    # Inspect the `or` filter actually sent to PostgREST.
    assert route.called
    or_param = None
    for call in route.calls:
        val = call.request.url.params.get("or")
        if val is not None:
            or_param = val
            break
    assert or_param is not None, "expected an or= filter to be sent"

    # The filter must contain exactly the two intended ilike conditions — no
    # more. Any injected condition (an extra ilike/eq/etc. introduced by the
    # payload) would push the ilike-condition count past two or land the payload
    # outside the quoted value.
    assert or_param.startswith("(title.ilike.") and or_param.endswith(")")
    assert "excerpt.ilike." in or_param
    assert or_param.count(".ilike.") == 2
    # Exactly two quoted ilike values — the payload lives INSIDE quotes, never
    # as bare grammar that could open a third condition.
    assert or_param.count('.ilike."') == 2
    # The two quoted-value openers/closers balance: 2 conditions => the only
    # top-level comma is the title/excerpt separator. Reconstruct the expected
    # safe filter and compare to prove no injection slipped through.
    esc = malicious.replace("\\", "\\\\").replace('"', '\\"')
    expected = f'(title.ilike."*{esc}*",excerpt.ilike."*{esc}*")'
    assert or_param == expected


def test_plain_search_still_filters(unauthed_client, respx_mock):
    route = _mock_blog(respx_mock)
    resp = unauthed_client.get(ENDPOINT, params={"search": "python"})
    assert resp.status_code == 200
    or_param = None
    for call in route.calls:
        val = call.request.url.params.get("or")
        if val is not None:
            or_param = val
            break
    assert or_param is not None
    assert "python" in or_param
    assert "title.ilike." in or_param
    assert "excerpt.ilike." in or_param


def test_no_search_sends_no_or_filter(unauthed_client, respx_mock):
    route = _mock_blog(respx_mock)
    resp = unauthed_client.get(ENDPOINT)
    assert resp.status_code == 200
    for call in route.calls:
        assert call.request.url.params.get("or") is None
