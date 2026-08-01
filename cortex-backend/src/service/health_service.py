import structlog

from src.config.database import neo4j_driver
from src.config.settings import get_settings
from src.model.health import HealthResponse, DependencyStatus

logger = structlog.get_logger(__name__)


class HealthService:
    async def get_health_status(self) -> HealthResponse:
        settings = get_settings()
        neo4j_status = await self._check_neo4j()

        overall_status = "healthy" if neo4j_status.status == "up" else "degraded"

        return HealthResponse(
            status=overall_status,
            version=settings.app.version,
            dependencies={"neo4j": neo4j_status},
        )

    async def _check_neo4j(self) -> DependencyStatus:
        try:
            result = await neo4j_driver.execute_read("RETURN 1 AS ping")
            if result and result[0].get("ping") == 1:
                return DependencyStatus(status="up")
        except Exception as e:
            logger.warning("neo4j_health_check_failed", error=str(e))
        return DependencyStatus(status="down")
