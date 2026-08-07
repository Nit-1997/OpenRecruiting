"""The internal routers adopt the shared `verify_internal_secret` dependency.

A bad/missing secret returns 401 (was the legacy inline 403) and never reaches
the handler. Also asserts the copy-pasted inline check is deleted from each
router source.
"""

import inspect

import pytest


@pytest.mark.parametrize(
    "path",
    [
        "/api/v2/internal/feedback/voice-complete",
    ],
)
def test_wrong_secret_rejected_401(unauthed_client, path):
    resp = unauthed_client.post(path, headers={"X-Internal-Secret": "wrong"}, json={})
    assert resp.status_code == 401


@pytest.mark.parametrize(
    "module_name",
    [
        "app.api.v2.routers.internal_feedback",
        "app.api.v2.routers.internal_cortex_token",
    ],
)
def test_inline_internal_secret_check_removed(module_name):
    module = __import__(module_name, fromlist=["x"])
    src = inspect.getsource(module)
    # No router defines its own secret-check coroutine anymore.
    assert "def verify_internal_secret" not in src, module_name
    # No router does an inline hmac.compare_digest on the header anymore.
    assert "hmac.compare_digest" not in src, module_name
