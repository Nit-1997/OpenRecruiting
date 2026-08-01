import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = structlog.get_logger(__name__)


class CortexException(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


class NotFoundError(CortexException):
    def __init__(self, detail: str = "Resource not found"):
        super().__init__(status_code=404, detail=detail)


class ValidationError(CortexException):
    def __init__(self, detail: str = "Validation failed"):
        super().__init__(status_code=422, detail=detail)


class DatabaseError(CortexException):
    def __init__(self, detail: str = "Database operation failed"):
        super().__init__(status_code=503, detail=detail)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(CortexException)
    async def cortex_exception_handler(request: Request, exc: CortexException):
        logger.error(
            "cortex_exception",
            status_code=exc.status_code,
            detail=exc.detail,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("unhandled_exception", path=request.url.path, error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )
