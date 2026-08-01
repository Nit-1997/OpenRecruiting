"""Knit platform APIs: auth-session creation, org-integration listing,
integration deactivation. Account-level calls (no integration id), except
deactivation which targets one integration.

Verified contracts (developers.getknit.dev, 2026-06-11):
  POST /auth.createSession  → {success, msg: {token}}
  GET  /integration.details?originOrgId= → {data: {apps: [{id, category,
       integrationId, isActive, deactivatedAt, ...}]}}
  POST /integration.deactivate (X-Knit-Integration-Id) → {success, data: null}
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.integrations.ats.core.errors import AtsProviderError
from app.integrations.ats.unified_knit.transport import KnitTransport

_ATS_CATEGORY_FILTER = [{"category": "ATS"}]


class KnitIntegrationApp(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    app_id: str = Field(alias="id")
    category: str | None = None
    integration_id: str = Field(alias="integrationId")
    is_active: bool = Field(alias="isActive", default=False)
    deactivated_at: str | None = Field(alias="deactivatedAt", default=None)


class KnitPlatformApi:
    def __init__(self, transport: KnitTransport) -> None:
        self._transport = transport

    async def create_auth_session(
        self,
        *,
        origin_org_id: str,
        origin_org_name: str,
        origin_user_email: str,
        origin_user_name: str,
    ) -> str:
        body = await self._transport.request(
            "POST",
            "/auth.createSession",
            json={
                "originOrgId": origin_org_id,
                "originOrgName": origin_org_name,
                "originUserEmail": origin_user_email,
                "originUserName": origin_user_name,
                "filters": _ATS_CATEGORY_FILTER,
            },
        )
        token = (body.get("msg") or {}).get("token")
        if not token:
            raise AtsProviderError("auth.createSession returned no token")
        return token

    async def list_org_integrations(
        self, origin_org_id: str
    ) -> list[KnitIntegrationApp]:
        body = await self._transport.request(
            "GET", "/integration.details", params={"originOrgId": origin_org_id}
        )
        apps = (body.get("data") or {}).get("apps") or []
        return [KnitIntegrationApp.model_validate(app) for app in apps]

    async def deactivate_integration(self, integration_id: str) -> None:
        await self._transport.request(
            "POST",
            "/integration.deactivate",
            integration_id=integration_id,
            json={},
        )
