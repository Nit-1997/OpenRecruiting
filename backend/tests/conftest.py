import os

os.environ.update({
    "SUPABASE_URL": "http://test-supabase.local",
    "SUPABASE_SECRET_KEY": "test-secret-key-placeholder",
    "SUPABASE_JWT_SECRET": "test-jwt-secret-must-be-at-least-32-chars-long",
    "CORS_ORIGINS": "http://localhost:3000",
    "RECALL_API_KEY": "test-recall-key",
    "RECALL_WEBHOOK_SECRET": "test-webhook-secret",
    "WEBHOOK_BASE_URL": "http://localhost:8004",
    "ASSESSMENT_UI_URL": "http://localhost:3002",
    # No provider API keys: this backend reaches every model through the gateway,
    # so LLM_GATEWAY_URL + LITELLM_MASTER_KEY below are the only LLM credentials
    # a test environment needs.
    "EMAIL_PROVIDER": "zoho",
    "ZEPTOMAIL_API_TOKEN": "test-zepto-token",
    "AWS_ACCESS_KEY_ID": "test-aws-key",
    "AWS_SECRET_ACCESS_KEY": "test-aws-secret",
    "LAMBDA_CALLBACK_SECRET": "test-lambda-secret",
    "ENV": "test",
    "KNIT_API_KEY": "test-knit-key",
    "ATS_INTEGRATIONS_ENABLED": "true",
    "LLM_GATEWAY_URL": "http://litellm.invalid:4000",
    "LITELLM_MASTER_KEY": "test-litellm-key",
})

import pytest
import respx
from uuid import UUID
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_current_user, require_staff, CurrentUser
from app.config import get_settings
from app.services.supabase import get_supabase_admin_client
import app.services.supabase as supabase_module
import app.integrations.ats.unified_knit.transport as knit_transport_module

from tests.helpers.mock_data import (
    STAFF_USER_ID, STAFF_EMAIL,
    RECRUITER_USER_ID, RECRUITER_EMAIL, ORG_ID,
)

SUPABASE_URL = "http://test-supabase.local"

STAFF_USER = CurrentUser(
    id=UUID(STAFF_USER_ID),
    email=STAFF_EMAIL,
    is_staff=True,
    organization_id=None,
)

RECRUITER_USER = CurrentUser(
    id=UUID(RECRUITER_USER_ID),
    email=RECRUITER_EMAIL,
    is_staff=False,
    organization_id=UUID(ORG_ID),
)


@pytest.fixture(autouse=True)
def clear_caches():
    get_settings.cache_clear()
    get_supabase_admin_client.cache_clear()
    supabase_module._async_client = None
    supabase_module._sync_client = None
    knit_transport_module._transport = None
    yield
    get_settings.cache_clear()
    get_supabase_admin_client.cache_clear()
    knit_transport_module._transport = None
    app.dependency_overrides.clear()


@pytest.fixture
def respx_mock():
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as mock:
        mock.route(host="testserver").pass_through()
        yield mock


@pytest.fixture
def staff_client(respx_mock):
    app.dependency_overrides[require_staff] = lambda: STAFF_USER
    app.dependency_overrides[get_current_user] = lambda: STAFF_USER
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def recruiter_client(respx_mock):
    app.dependency_overrides[get_current_user] = lambda: RECRUITER_USER
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def unauthed_client(respx_mock):
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
