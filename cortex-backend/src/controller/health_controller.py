from fastapi import APIRouter

from src.service.health_service import HealthService
from src.model.health import HealthResponse

router = APIRouter(tags=["health"])
health_service = HealthService()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return await health_service.get_health_status()
