"""
FastAPI exception handlers for v2 domain exceptions.

Routes raise v2 domain exceptions from `core.exceptions`; these handlers
translate them into JSONResponse + HTTP status code. Centralising the
mapping here keeps the routers and services free of HTTP-specific
concerns.

Register once from `app/main.py`:
    register_v2_error_handlers(app)
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.logging_config import get_logger, request_id_var
from app.api.v2.core.rpc import map_rpc_error
from app.integrations.ats.core.errors import (
    AtsAuthError,
    AtsIntegrationError,
    AtsNotConnectedError,
    AtsNotSupportedError,
    AtsRateLimitedError,
    AtsResourceNotFoundError,
)
from app.services.supabase import PostgrestError, RpcError
from app.api.v2.core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    NotImplementedFeatureError,
    PreconditionFailedError,
    PreconditionRequiredError,
    UpstreamServiceError,
    V2DomainError,
    ValidationError,
)

logger = get_logger(__name__)


# SQLSTATE -> HTTP status. Derived from the documented intent in
# `app/services/supabase.py` (PostgrestError docstring): unique/FK violations
# are state conflicts (409), check violations are bad input (400). Anything
# unmodelled (e.g. 42P01 undefined_table, missing code) is a server fault (500).
SQLSTATE_TO_HTTP: dict[str, int] = {
    "23505": 409,  # unique_violation
    "23503": 409,  # foreign_key_violation
    "23514": 400,  # check_violation
}
_DEFAULT_DB_STATUS = 500


# Domain-exception -> HTTP status, mirroring the per-type handlers below. Used
# by the RpcError safety net so it can turn a mapped domain exception into the
# same response the dedicated handlers would, without re-dispatching.
_DOMAIN_STATUS: dict[type, int] = {
    NotFoundError: 404,
    ConflictError: 409,
    ForbiddenError: 403,
    ValidationError: 400,
    PreconditionFailedError: 412,
    PreconditionRequiredError: 428,
    NotImplementedFeatureError: 501,
}


def _request_id(request: Request) -> str | None:
    """Resolve the request id for an error response/log.

    Prefer `request.state.request_id` (set by CorrelationIDMiddleware): the
    `request_id` ContextVar is reset in that middleware's finally block, which
    runs BEFORE the outermost catch-all Exception handler, so the ContextVar is
    `None` there. The state attribute survives. Fall back to the ContextVar for
    paths that never reached the middleware (defensive)."""
    rid = getattr(request.state, "request_id", None)
    return rid if rid else request_id_var.get()


def _domain_exc_to_response(exc: V2DomainError) -> JSONResponse:
    """Render a v2 domain exception as the response its dedicated handler
    would. Centralised so the RpcError safety net stays in sync with the
    per-type handlers registered below."""
    if isinstance(exc, ConflictError):
        return JSONResponse(
            {"detail": exc.detail},
            status_code=409,
            headers={"X-Error-Code": exc.code},
        )
    if isinstance(exc, UpstreamServiceError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)
    status = _DOMAIN_STATUS.get(type(exc), 502)
    return JSONResponse({"detail": str(exc)}, status_code=status)


def register_v2_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFoundError)
    async def _not_found_handler(request: Request, exc: NotFoundError):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(ConflictError)
    async def _conflict_handler(request: Request, exc: ConflictError):
        # Match the legacy contract — detail is the human message; the
        # machine-readable code travels as a separate header so it does not
        # alter the response body shape.
        return JSONResponse(
            {"detail": exc.detail},
            status_code=409,
            headers={"X-Error-Code": exc.code},
        )

    @app.exception_handler(ForbiddenError)
    async def _forbidden_handler(request: Request, exc: ForbiddenError):
        return JSONResponse({"detail": str(exc)}, status_code=403)

    @app.exception_handler(ValidationError)
    async def _validation_handler(request: Request, exc: ValidationError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(PreconditionFailedError)
    async def _precondition_failed_handler(
        request: Request, exc: PreconditionFailedError
    ):
        return JSONResponse({"detail": str(exc)}, status_code=412)

    @app.exception_handler(PreconditionRequiredError)
    async def _precondition_required_handler(
        request: Request, exc: PreconditionRequiredError
    ):
        return JSONResponse({"detail": str(exc)}, status_code=428)

    @app.exception_handler(UpstreamServiceError)
    async def _upstream_handler(request: Request, exc: UpstreamServiceError):
        return JSONResponse(
            {"detail": str(exc)},
            status_code=exc.status_code,
        )

    @app.exception_handler(NotImplementedFeatureError)
    async def _not_implemented_handler(
        request: Request, exc: NotImplementedFeatureError
    ):
        return JSONResponse({"detail": str(exc)}, status_code=501)

    # ATS-integration taxonomy → HTTP. Static client messages — the real
    # provider error stays in server logs only.
    _ATS_STATUS: dict[type, tuple[int, str]] = {
        AtsAuthError: (502, "ATS provider authentication failed"),
        AtsNotSupportedError: (400, "Operation not supported by the connected ATS"),
        AtsRateLimitedError: (429, "ATS provider rate limit exceeded — try again shortly"),
        AtsResourceNotFoundError: (404, "ATS resource not found"),
        AtsNotConnectedError: (404, "No ATS connected"),
    }

    @app.exception_handler(AtsIntegrationError)
    async def _ats_error_handler(request: Request, exc: AtsIntegrationError):
        status, message = _ATS_STATUS.get(type(exc), (502, "ATS provider error"))
        logger.error(
            "ats_integration_error",
            extra={
                "event": "ats_integration_error",
                "error": str(exc),
                "error_type": type(exc).__name__,
                "status_code": status,
                "path": request.url.path,
                "request_id": _request_id(request),
            },
        )
        return JSONResponse({"detail": message}, status_code=status)

    @app.exception_handler(PostgrestError)
    async def _postgrest_handler(request: Request, exc: PostgrestError):
        # A table read/write failed below the router (e.g. BE-F1 reads now
        # raise instead of returning None). Map the SQLSTATE to a status, log
        # the full error server-side with the request id, and return a static
        # envelope that leaks neither the raw DB message nor a traceback.
        status_code = SQLSTATE_TO_HTTP.get(exc.code or "", _DEFAULT_DB_STATUS)
        rid = _request_id(request)
        logger.error(
            "db_error",
            extra={
                "event": "db_error",
                "error": exc.message,
                "error_type": type(exc).__name__,
                "code": exc.code,
                "details": exc.details,
                "status_code": status_code,
                "path": request.url.path,
                "request_id": rid,
            },
        )
        return JSONResponse(
            {"detail": {"error": "db_error", "code": exc.code}},
            status_code=status_code,
        )

    @app.exception_handler(RpcError)
    async def _rpc_handler(request: Request, exc: RpcError):
        # Safety net for call sites that raise RpcError raw (i.e. bypass
        # `core.rpc.call_rpc`, which normally maps these to domain exceptions
        # upstream). Reuse the same SQLSTATE->domain mapping so behaviour is
        # identical whether the mapping happened at the call site or here.
        # NB: PostgrestError subclasses RpcError but has its own handler above,
        # so only genuine RpcError instances reach this.
        rid = _request_id(request)
        logger.error(
            "rpc_error",
            extra={
                "event": "rpc_error",
                "error": exc.message,
                "error_type": type(exc).__name__,
                "code": exc.code,
                "details": exc.details,
                "path": request.url.path,
                "request_id": rid,
            },
        )
        return _domain_exc_to_response(map_rpc_error(exc))

    @app.exception_handler(Exception)
    async def _catch_all_handler(request: Request, exc: Exception):
        # Last-resort handler for anything not modelled above. FastAPI's
        # HTTPException and RequestValidationError have their own built-in
        # handlers that take precedence over this catch-all, so their normal
        # behaviour is preserved. Log the full exception (with traceback) and
        # the request id server-side; return a static, non-leaky 500.
        rid = _request_id(request)
        logger.error(
            "unhandled_exception",
            extra={
                "event": "unhandled_exception",
                "error": str(exc),
                "error_type": type(exc).__name__,
                "path": request.url.path,
                "request_id": rid,
            },
            exc_info=True,
        )
        return JSONResponse(
            {"detail": {"error": "internal_error", "request_id": rid}},
            status_code=500,
        )
