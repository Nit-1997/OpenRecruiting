"""OAuth 2.1 endpoints — register, authorize, token, revoke.

Mounted under `/api/v2/mcp/oauth/`. The companion `/.well-known/*` endpoints
live in `well_known.py` and are mounted at the FastAPI root.

This module deliberately keeps zero state in module globals — every storage
operation goes through the services in `app.services.mcp`. That makes the
endpoints trivially testable: stub the service-layer functions, drive the
endpoints via TestClient, observe the response.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.config import get_settings
from app.dependencies import get_current_user, CurrentUser
from app.models.mcp import (
    ClientRegistrationRequest,
    ClientRegistrationResponse,
    TokenResponse,
)
from app.services.mcp import client_store, code_store, pkce, refresh_store
from app.services.mcp.jwt_signer import sign_access_token


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp/oauth", tags=["MCP - OAuth"])


def _oauth_error(error: str, description: str, status_code: int = 400) -> JSONResponse:
    """RFC 6749 §5.2 standard error envelope."""
    return JSONResponse(
        status_code=status_code,
        content={"error": error, "error_description": description},
    )


# Scopes the authorization server is willing to issue. Adding a new scope
# means deciding what it grants — leave this conservative.
_ALLOWED_SCOPES: frozenset[str] = frozenset({"cortex:read"})


def _validate_scope(scope: str) -> str | None:
    """Return an error description if any space-delimited scope token is not
    in the allowlist; otherwise None."""
    if not scope or not scope.strip():
        return None  # Empty scope = caller takes the default elsewhere.
    for tok in scope.split():
        if tok and tok not in _ALLOWED_SCOPES:
            return f"Scope {tok!r} is not enabled."
    return None


async def _validate_authorize_params(
    *,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str,
    scope: str,
    audience: str,
) -> JSONResponse | None:
    """Single-source-of-truth validation for /authorize and
    /authorize/decision. Returns the error response on failure, else None.

    The decision endpoint MUST re-run this check on POST — otherwise an
    attacker can craft their own POST (or tamper with the hidden form
    fields) to bypass the GET-side audience/PKCE/scope guards and have the
    backend sign tokens for an unvalidated audience or unknown scope.
    """
    if code_challenge_method != "S256":
        return _oauth_error("invalid_request", "Only S256 PKCE is supported.")
    if not code_challenge:
        return _oauth_error("invalid_request", "code_challenge is required.")

    client = await client_store.get_client(client_id)
    if client is None:
        return _oauth_error("invalid_client", f"Unknown client_id {client_id!r}", 401)
    if not client_store.validate_redirect_uri(client, redirect_uri):
        return _oauth_error("invalid_request", "redirect_uri does not match a registered URI.")

    if audience not in _allowed_audiences():
        return _oauth_error("invalid_target", f"Audience {audience!r} is not enabled.")

    scope_err = _validate_scope(scope)
    if scope_err is not None:
        return _oauth_error("invalid_scope", scope_err)

    return None


def _allowed_audiences() -> set[str]:
    """Normalize the comma-separated env value into a set of acceptable
    audience identifiers.

    Each entry is right-stripped of trailing slashes so the URL form
    (`https://host/`) and the canonical form (`https://host`) compare
    equal. The MCP OAuth spec uses RFC 8707 Resource Indicators, where
    clients send their MCP server URL as the `resource` parameter — that
    URL becomes the JWT's `aud` claim.
    """
    return {
        a.strip().rstrip("/")
        for a in get_settings().MCP_ALLOWED_AUDIENCES.split(",")
        if a.strip()
    }


def _normalize_audience(raw: str | None) -> str:
    if not raw:
        # Default to the first allowed audience (the short form).
        return next(iter(_allowed_audiences()), "cortex-mcp")
    return raw.rstrip("/")


# ---------------------------------------------------------------------------
# Dynamic Client Registration (RFC 7591)
# ---------------------------------------------------------------------------

@router.get("/clients/{client_id}")
async def get_client_metadata(client_id: str):
    """Public lookup of display-safe client metadata.

    Used by the consent page in `landing` to show "Claude.ai wants to
    access OpenRecruiting Cortex" rather than a raw `client_id`. Returns ONLY fields
    safe to render to any unauthenticated visitor — client_name, the list of
    registered redirect URIs (already public knowledge of the URL bar), and
    the scope. Does NOT return software_id / software_version or any other
    fingerprint-y metadata.
    """
    client = await client_store.get_client(client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return {
        "client_id": client.client_id,
        "client_name": client.client_name,
        "redirect_uris": client.redirect_uris,
        "scope": client.scope,
    }


@router.post(
    "/register",
    response_model=ClientRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(payload: ClientRegistrationRequest) -> ClientRegistrationResponse:
    """RFC 7591 Dynamic Client Registration.

    MCP clients (Claude.ai, Claude Code, etc.) call this once per user-server
    pair to obtain a client_id. We do not require a registration token — any
    party may register because the only thing a fresh client_id grants is
    *the ability to start an OAuth flow*, and the user still has to approve
    consent at /authorize.
    """
    try:
        client = await client_store.register_client(
            client_name=payload.client_name,
            redirect_uris=payload.redirect_uris,
            grant_types=payload.grant_types,
            response_types=payload.response_types,
            token_endpoint_auth_method=payload.token_endpoint_auth_method,
            scope=payload.scope or "cortex:read",
            software_id=payload.software_id,
            software_version=payload.software_version,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return ClientRegistrationResponse(
        client_id=client.client_id,
        client_name=client.client_name,
        redirect_uris=client.redirect_uris,
        grant_types=client.grant_types,
        response_types=client.response_types,
        token_endpoint_auth_method=client.token_endpoint_auth_method,
        scope=client.scope,
    )


# ---------------------------------------------------------------------------
# Authorization endpoint (RFC 6749 §4.1)
# ---------------------------------------------------------------------------

_INLINE_CONSENT_FALLBACK = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><title>Authorize — OpenRecruiting Cortex</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 480px; margin: 80px auto; padding: 0 24px; color: #1a1a1a; }}
  h1 {{ font-size: 20px; margin-bottom: 8px; }}
  .org {{ background: #f5f5f7; border-radius: 8px; padding: 12px 16px; margin: 16px 0; }}
  .scope-list {{ list-style: none; padding: 0; margin: 16px 0; }}
  .scope-list li {{ padding: 8px 0; border-bottom: 1px solid #eee; }}
  .row {{ display: flex; gap: 12px; margin-top: 24px; }}
  button {{ flex: 1; padding: 12px; font-size: 15px; border-radius: 8px; cursor: pointer; border: 0; }}
  .allow {{ background: #0a84ff; color: white; }}
  .deny {{ background: #f5f5f7; color: #1a1a1a; }}
</style></head><body>
<h1>{client_name} wants to access OpenRecruiting Cortex</h1>
<div class="org">Signed in as <strong>{user_email}</strong> ({org_name})</div>
<p>This will allow {client_name} to:</p>
<ul class="scope-list">{scope_html}</ul>
<form method="post" action="{action_url}" class="row">
  {hidden_fields}
  <button class="deny" type="submit" name="decision" value="deny">Deny</button>
  <button class="allow" type="submit" name="decision" value="allow">Allow</button>
</form>
</body></html>"""


def _build_consent_redirect_url(
    *,
    response_type: str,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str,
    scope: str,
    state: str | None,
    audience: str,
) -> str:
    """Build the landing /oauth/consent URL with OAuth params preserved.

    The frontend handles the session check + UI render. It POSTs the user's
    decision through its own /oauth/consent/submit route, which in turn calls
    POST /api/v2/mcp/oauth/authorize/decision on this backend with the
    Authorization header attached.
    """
    from urllib.parse import urlencode

    consent_base = (get_settings().MCP_CONSENT_URL or "").rstrip("/")
    params = {
        "response_type": response_type,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "scope": scope,
        "audience": audience,
    }
    if state:
        params["state"] = state
    return f"{consent_base}?{urlencode(params)}"


@router.get("/authorize")
async def authorize_get(
    request: Request,
    response_type: Annotated[str, Query()],
    client_id: Annotated[str, Query()],
    redirect_uri: Annotated[str, Query()],
    code_challenge: Annotated[str, Query()],
    code_challenge_method: Annotated[str, Query()] = "S256",
    scope: Annotated[str, Query()] = "cortex:read",
    state: Annotated[str | None, Query()] = None,
    resource: Annotated[str | None, Query()] = None,
):
    """Step 1: validate request, then hand off to the consent UI.

    Behavior depends on MCP_CONSENT_URL:
      - If set (production): 302 redirect to the marketing site's consent
        page, with all OAuth params preserved in the query string. The
        marketing site handles session check + UI + form submission.
      - If unset (dev / unit tests): render the inline HTML form as before.

    Validation rules (response_type, PKCE method, client_id, redirect_uri,
    audience) are enforced here BEFORE we redirect — so a malformed link from
    a misconfigured MCP client never reaches the consent page.
    """
    # --- Validate request shape ---
    if response_type != "code":
        return _oauth_error("unsupported_response_type", f"Got {response_type!r}; only 'code' is supported.")

    audience = _normalize_audience(resource)
    err = await _validate_authorize_params(
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        scope=scope,
        audience=audience,
    )
    if err is not None:
        return err

    # Re-load the client now that validation passed (used by the dev fallback's UI).
    client = await client_store.get_client(client_id)

    settings = get_settings()

    # --- Production path: hand off to marketing site ---
    if settings.MCP_CONSENT_URL:
        return RedirectResponse(
            _build_consent_redirect_url(
                response_type=response_type,
                client_id=client_id,
                redirect_uri=redirect_uri,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
                scope=scope,
                state=state,
                audience=audience,
            ),
            status_code=302,
        )

    # --- Dev fallback: inline HTML form (used when MCP_CONSENT_URL is unset) ---
    try:
        current_user = await _resolve_session_user(request)
    except _NotAuthenticated:
        return_to = str(request.url)
        login_url = f"{settings.APP_URL.rstrip('/')}/login?next={return_to}"
        return RedirectResponse(login_url, status_code=302)

    org_id, org_name, email = await _load_user_org_context(current_user)

    scope_items = [s for s in scope.split() if s] or ["cortex:read"]
    scope_html = "".join(
        f"<li>{_describe_scope(s)}</li>" for s in scope_items
    )
    hidden = (
        f'<input type="hidden" name="client_id" value="{client_id}">'
        f'<input type="hidden" name="redirect_uri" value="{redirect_uri}">'
        f'<input type="hidden" name="code_challenge" value="{code_challenge}">'
        f'<input type="hidden" name="code_challenge_method" value="{code_challenge_method}">'
        f'<input type="hidden" name="scope" value="{scope}">'
        f'<input type="hidden" name="state" value="{state or ""}">'
        f'<input type="hidden" name="audience" value="{audience}">'
    )
    body = _INLINE_CONSENT_FALLBACK.format(
        client_name=client.client_name or "An MCP application",
        user_email=email,
        org_name=org_name,
        scope_html=scope_html,
        action_url=f"{settings.MCP_JWT_ISSUER.rstrip('/')}/api/v2/mcp/oauth/authorize/decision",
        hidden_fields=hidden,
    )
    return HTMLResponse(body)


@router.post("/authorize/decision")
async def authorize_decision(
    request: Request,
    decision: Annotated[str, Form()],
    client_id: Annotated[str, Form()],
    redirect_uri: Annotated[str, Form()],
    code_challenge: Annotated[str, Form()],
    code_challenge_method: Annotated[str, Form()],
    scope: Annotated[str, Form()],
    audience: Annotated[str, Form()],
    state: Annotated[str, Form()] = "",
):
    """Step 2: process the user's allow/deny choice and redirect back to the client.

    SECURITY: every OAuth parameter on this POST is attacker-controllable —
    a malicious client can craft a direct POST or tamper with the consent
    form's hidden fields. We MUST re-run the full /authorize validation
    here so PKCE method, audience allowlist, scope allowlist, client
    registration, and redirect-uri match are all re-enforced before we
    persist an authorization code.
    """
    # Normalize the audience the same way GET does (strip trailing slash).
    audience = _normalize_audience(audience)
    # 1. Validate redirect_uri BEFORE deny — otherwise we'd redirect to a
    #    URI we never validated, leaking the OAuth error to an attacker.
    err = await _validate_authorize_params(
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        scope=scope,
        audience=audience,
    )
    if err is not None:
        return err

    if decision != "allow":
        # RFC 6749 §4.1.2.1: redirect with error
        return _redirect_with_error(redirect_uri, "access_denied", "User denied access.", state)

    try:
        current_user = await _resolve_session_user(request)
    except _NotAuthenticated as e:
        logger.warning(
            "mcp_oauth_decision_session_missing",
            extra={"event": "mcp_oauth_decision_session_missing", "client_id": client_id, "reason": repr(e)},
        )
        return _oauth_error("invalid_request", "Session expired during consent.", 401)
    except Exception as e:
        logger.exception(
            "mcp_oauth_decision_session_unexpected",
            extra={"event": "mcp_oauth_decision_session_unexpected", "client_id": client_id, "reason": repr(e)},
        )
        return _oauth_error(
            "server_error",
            "Could not complete authorization. Please retry.",
            500,
        )

    org_id, _org_name, _email = await _load_user_org_context(current_user)
    logger.info(
        "mcp_oauth_decision_user_resolved",
        extra={
            "event": "mcp_oauth_decision_user_resolved",
            "client_id": client_id,
            "user_id": str(current_user.id),
            "has_org_id": bool(org_id),
            "decision": decision,
        },
    )

    code = await code_store.issue_code(
        client_id=client_id,
        user_id=str(current_user.id),
        organization_id=org_id,
        redirect_uri=redirect_uri,
        scope=scope or "cortex:read",
        audience=audience,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
    )

    qs = f"code={code.code}"
    if state:
        qs += f"&state={state}"
    sep = "&" if "?" in redirect_uri else "?"
    final_url = f"{redirect_uri}{sep}{qs}"
    logger.info(
        "mcp_oauth_code_issued",
        extra={
            "event": "mcp_oauth_code_issued",
            "client_id": client_id,
            "user_id": str(current_user.id),
            "org_id": org_id,
            "audience": audience,
            "redirect_uri": redirect_uri,
            "has_state": bool(state),
            "redirect_to": final_url[:120],
        },
    )
    return RedirectResponse(final_url, status_code=302)


def _redirect_with_error(redirect_uri: str, error: str, description: str, state: str) -> RedirectResponse:
    qs = f"error={error}&error_description={description}"
    if state:
        qs += f"&state={state}"
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{sep}{qs}", status_code=302)


# ---------------------------------------------------------------------------
# Token endpoint (RFC 6749 §4.1.3, §6)
# ---------------------------------------------------------------------------

@router.post("/token")
async def token(
    grant_type: Annotated[str, Form()],
    client_id: Annotated[str, Form()],
    code: Annotated[str | None, Form()] = None,
    redirect_uri: Annotated[str | None, Form()] = None,
    code_verifier: Annotated[str | None, Form()] = None,
    refresh_token: Annotated[str | None, Form()] = None,
):
    """Issue or refresh access tokens.

    Supported grants:
      authorization_code  — exchange a /authorize code + PKCE verifier
      refresh_token       — rotate a long-lived refresh token
    """
    logger.info(
        "mcp_oauth_token_request",
        extra={
            "event": "mcp_oauth_token_request",
            "grant_type": grant_type,
            "client_id": client_id,
            "has_code": bool(code),
            "has_verifier": bool(code_verifier),
            "has_refresh_token": bool(refresh_token),
            "redirect_uri": redirect_uri,
        },
    )
    client = await client_store.get_client(client_id)
    if client is None:
        return _oauth_error("invalid_client", "Unknown client_id.", 401)

    if grant_type == "authorization_code":
        return await _grant_authorization_code(
            client_id=client_id,
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
        )
    if grant_type == "refresh_token":
        return await _grant_refresh_token(
            client_id=client_id,
            refresh_token=refresh_token,
        )
    return _oauth_error("unsupported_grant_type", f"Got {grant_type!r}.")


async def _grant_authorization_code(
    *,
    client_id: str,
    code: str | None,
    redirect_uri: str | None,
    code_verifier: str | None,
):
    if not code or not redirect_uri or not code_verifier:
        logger.warning("mcp_token_missing_param", extra={"event": "mcp_token_missing_param",
            "has_code": bool(code), "has_uri": bool(redirect_uri), "has_verifier": bool(code_verifier)})
        return _oauth_error("invalid_request", "Missing code, redirect_uri, or code_verifier.")

    auth_code = await code_store.consume_code(code)
    if auth_code is None:
        logger.warning("mcp_token_code_invalid", extra={"event": "mcp_token_code_invalid", "code_prefix": code[:8]})
        return _oauth_error("invalid_grant", "Authorization code is invalid, expired, or already used.")
    if auth_code.client_id != client_id:
        logger.warning("mcp_token_code_client_mismatch", extra={"event": "mcp_token_code_client_mismatch",
            "expected": auth_code.client_id, "got": client_id})
        return _oauth_error("invalid_grant", "Code was issued to a different client.")
    if auth_code.redirect_uri != redirect_uri:
        logger.warning("mcp_token_code_redirect_mismatch", extra={"event": "mcp_token_code_redirect_mismatch",
            "stored": auth_code.redirect_uri, "got": redirect_uri})
        return _oauth_error("invalid_grant", "redirect_uri does not match the code.")

    try:
        pkce.verify(code_verifier, auth_code.code_challenge, auth_code.code_challenge_method)
    except pkce.PKCEError as e:
        logger.warning("mcp_token_pkce_failed", extra={"event": "mcp_token_pkce_failed", "reason": str(e)})
        return _oauth_error("invalid_grant", str(e))

    return await _issue_tokens(
        client_id=client_id,
        user_id=auth_code.user_id,
        org_id=auth_code.organization_id,
        scope=auth_code.scope,
        audience=auth_code.audience,
    )


async def _grant_refresh_token(*, client_id: str, refresh_token: str | None):
    if not refresh_token:
        return _oauth_error("invalid_request", "Missing refresh_token.")

    rt = await refresh_store.use_refresh_token(refresh_token, client_id=client_id)
    if rt is None:
        return _oauth_error("invalid_grant", "Refresh token is invalid, expired, revoked, or for a different client.")

    # Re-check current membership before minting fresh tokens. The refresh
    # token row stores the org the user belonged to at consent time; without
    # this check, a removed/deleted/org-switched user could keep getting
    # 1-hour access tokens for the OLD org's Cortex data for the full
    # 30-day refresh-token TTL. The old refresh token was already revoked
    # atomically by use_refresh_token, so on mismatch we just refuse to
    # mint a fresh pair — the user has to re-consent through /authorize.
    membership = await _load_current_membership(rt.user_id)
    stored_org = rt.organization_id or None
    if membership is None or (membership.org_id or None) != stored_org:
        logger.warning(
            "mcp_refresh_membership_changed",
            extra={
                "event": "mcp_refresh_membership_changed",
                "user_id": rt.user_id,
                "client_id": client_id,
                "stored_org_id": stored_org,
                "current_org_id": membership.org_id if membership else None,
                "profile_deleted": membership is None,
            },
        )
        return _oauth_error(
            "invalid_grant",
            "User membership has changed since consent; reauthorization required.",
        )

    return await _issue_tokens(
        client_id=client_id,
        user_id=rt.user_id,
        org_id=rt.organization_id,
        scope=rt.scope,
        audience=rt.audience,
    )


async def _issue_tokens(
    *,
    client_id: str,
    user_id: str,
    org_id: str | None,
    scope: str,
    audience: str,
):
    # Pull the user's display info so it lands in the access token's claims.
    org_name, user_name, role = await _load_token_claim_context(user_id, org_id)

    access = sign_access_token(
        subject=user_id,
        audience=audience,
        org_id=org_id or "",
        org_name=org_name,
        user_name=user_name,
        role=role,
        scope=scope,
        ttl_seconds=3600,
    )
    refresh = await refresh_store.issue_refresh_token(
        client_id=client_id,
        user_id=user_id,
        organization_id=org_id,
        scope=scope,
        audience=audience,
    )
    logger.info(
        "mcp_oauth_token_issued",
        extra={
            "event": "mcp_oauth_token_issued",
            "client_id": client_id,
            "user_id": user_id,
            "org_id": org_id,
            "audience": audience,
            "scope": scope,
            "access_ttl": access.expires_in,
            "kid": access.kid,
        },
    )
    return TokenResponse(
        access_token=access.token,
        token_type="Bearer",
        expires_in=access.expires_in,
        refresh_token=refresh.token,
        scope=scope,
    )


# ---------------------------------------------------------------------------
# Revoke (RFC 7009)
# ---------------------------------------------------------------------------

@router.post("/revoke", status_code=200)
async def revoke(
    token: Annotated[str, Form()],
    token_type_hint: Annotated[str | None, Form()] = None,
):
    """Revoke a refresh token. Per RFC 7009 §2.2 we always return 200 — the
    client should not learn whether the token existed."""
    await refresh_store.revoke_refresh_token(token)
    return {}


# ---------------------------------------------------------------------------
# Session resolution helpers
# ---------------------------------------------------------------------------

class _NotAuthenticated(Exception):
    """Raised when /authorize can't find a OpenRecruiting session for the caller."""


async def _resolve_session_user(request: Request) -> CurrentUser:
    """Resolve the current OpenRecruiting user from the request.

    Strategy: look for an `Authorization: Bearer <supabase-jwt>` header. The
    consent page is loaded inside the user's browser, where OpenRecruiting's recruiter-app
    can attach the Supabase JWT (e.g. via the same cookie -> header bridge
    used elsewhere). If no header is present we raise _NotAuthenticated, and
    the caller redirects to the login page.

    NOTE for next iteration: today this depends on the frontend to inject the
    Supabase access token. A cleaner production setup is a session-cookie
    bridge in landing that turns the cookie into an Authorization
    header before this endpoint runs.
    """
    auth = request.headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        # Also accept the Supabase access token as a `sb-access-token` cookie,
        # which is how landing stores it. This lets the consent page
        # work end-to-end on first load without any custom JS.
        cookie_token = request.cookies.get("sb-access-token")
        if not cookie_token:
            raise _NotAuthenticated
        # Synthesize a header for the existing dependency to consume.
        auth = f"Bearer {cookie_token}"

    # Re-use the existing FastAPI dependency by constructing the credentials.
    from fastapi.security import HTTPAuthorizationCredentials

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth.split(None, 1)[1])
    try:
        return await get_current_user(creds)
    except HTTPException as e:
        if e.status_code in (401, 403):
            raise _NotAuthenticated from e
        raise


async def _load_user_org_context(user: CurrentUser) -> tuple[str | None, str, str]:
    """Return (org_id, org_name, email) for display on the consent screen."""
    org_id = str(user.organization_id) if user.organization_id else None
    org_name = "OpenRecruiting"
    if org_id:
        from app.services.supabase import get_supabase_admin_client

        supabase = get_supabase_admin_client()
        result = (
            await supabase.table("organizations")
            .select("name")
            .eq("id", org_id)
            .single()
            .execute_async()
        )
        if result.data and result.data.get("name"):
            org_name = result.data["name"]
    return org_id, org_name, user.email


@dataclass(frozen=True)
class _CurrentMembership:
    """Snapshot of a user's profile at refresh time. `org_id` is None if the
    profile exists but has no organization (e.g. mid-onboarding or org
    deleted via ON DELETE SET NULL)."""
    org_id: str | None


async def _load_current_membership(user_id: str) -> _CurrentMembership | None:
    """Return the user's *current* org membership, or None if the profile is
    missing or soft-deleted (`deleted_at IS NOT NULL`). The refresh path
    uses this to refuse minting fresh tokens after the user was offboarded.

    A nullable `organization_id` (e.g. org deleted under the user) is
    preserved as `org_id=None` rather than treated as "deleted user" — the
    caller decides whether None matches the stored value.
    """
    from app.services.supabase import get_supabase_admin_client

    supabase = get_supabase_admin_client()
    res = (
        await supabase.table("profiles")
        .select("organization_id, deleted_at")
        .eq("id", user_id)
        .single()
        .execute_async()
    )
    if not res.data:
        return None
    if res.data.get("deleted_at") is not None:
        return None
    return _CurrentMembership(org_id=res.data.get("organization_id"))


async def _load_token_claim_context(
    user_id: str,
    org_id: str | None,
) -> tuple[str, str | None, str | None]:
    """Return (org_name, user_name, role) for inclusion in the access token."""
    from app.services.supabase import get_supabase_admin_client

    supabase = get_supabase_admin_client()
    profile_res = (
        await supabase.table("profiles")
        .select("full_name")
        .eq("id", user_id)
        .single()
        .execute_async()
    )
    user_name = (profile_res.data or {}).get("full_name") if profile_res.data else None
    # `profiles` has no `role` column; the JWT `role` claim is optional
    # (jwt_signer omits it when None), so leave it unset rather than query a
    # column that does not exist (was a 42703 → 500 on token exchange).
    role = None

    org_name = ""
    if org_id:
        org_res = (
            await supabase.table("organizations")
            .select("name")
            .eq("id", org_id)
            .single()
            .execute_async()
        )
        if org_res.data:
            org_name = org_res.data.get("name") or ""
    return org_name, user_name, role


def _describe_scope(scope: str) -> str:
    descriptions = {
        "cortex:read": "Read your organization's recruitment-intelligence graph (candidates, requisitions, feedback, traits)",
    }
    return descriptions.get(scope, scope)
