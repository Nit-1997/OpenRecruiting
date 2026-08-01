from fastapi import APIRouter, Depends, HTTPException

from app.api.v2.core.dependencies import verify_internal_secret
from app.services.slack_service import (
    SlackReauthRequiredError,
    get_slack_service,
)

router = APIRouter(prefix="/internal", dependencies=[Depends(verify_internal_secret)])


@router.get("/slack-integrations/health")
async def slack_integrations_health():
    service = get_slack_service()
    return await service.get_installation_health_summary()


@router.post("/slack-integrations/refresh/{team_id}")
async def force_refresh_slack_team(team_id: str):
    service = get_slack_service()
    try:
        return await service.force_refresh_team_token(team_id)
    except SlackReauthRequiredError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/slack-integrations/backfill-auth-state")
async def backfill_slack_auth_state():
    service = get_slack_service()
    return await service.backfill_auth_state()
