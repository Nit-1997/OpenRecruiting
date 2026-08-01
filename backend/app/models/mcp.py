"""Pydantic models for the MCP OAuth 2.1 endpoints."""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class ClientRegistrationRequest(BaseModel):
    """RFC 7591 client metadata. We only honor the subset we actually use."""
    model_config = ConfigDict(extra="ignore")

    redirect_uris: list[str] = Field(min_length=1)
    client_name: str | None = None
    client_uri: str | None = None
    logo_uri: str | None = None
    grant_types: list[str] | None = None
    response_types: list[str] | None = None
    token_endpoint_auth_method: str = "none"
    scope: str | None = None
    software_id: str | None = None
    software_version: str | None = None


class ClientRegistrationResponse(BaseModel):
    client_id: str
    client_name: str | None
    redirect_uris: list[str]
    grant_types: list[str]
    response_types: list[str]
    token_endpoint_auth_method: str
    scope: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    refresh_token: str | None = None
    scope: str | None = None


class OAuthError(BaseModel):
    """RFC 6749 §5.2 error envelope."""
    error: str
    error_description: str | None = None
    error_uri: str | None = None


class AuthServerMetadata(BaseModel):
    """RFC 8414 authorization-server metadata."""
    model_config = ConfigDict(extra="allow")

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str
    jwks_uri: str
    response_types_supported: list[str] = ["code"]
    grant_types_supported: list[str] = ["authorization_code", "refresh_token"]
    token_endpoint_auth_methods_supported: list[str] = ["none"]
    code_challenge_methods_supported: list[str] = ["S256"]
    scopes_supported: list[str] = ["cortex:read"]
    revocation_endpoint: str | None = None
    service_documentation: str | None = None


class ProtectedResourceMetadata(BaseModel):
    """RFC 9728 protected-resource metadata. Hosted by the resource server, not
    the auth server — but the resource server can statically advertise this
    document and we define the schema here for any future OpenRecruiting MCPs."""
    model_config = ConfigDict(extra="allow")

    resource: str
    authorization_servers: list[str]
    bearer_methods_supported: list[str] = ["header"]
    scopes_supported: list[str] = ["cortex:read"]
