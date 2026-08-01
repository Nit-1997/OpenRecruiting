import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from production.handler import process_intake_v2
from src.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["process"])

_in_flight: set[str] = set()


class ProcessRequest(BaseModel):
    session_id: str


class ProcessResponse(BaseModel):
    session_id: str
    status: str


@router.post("/process", response_model=ProcessResponse)
async def run_intake_pipeline(request: ProcessRequest):
    sid = request.session_id
    if sid in _in_flight:
        logger.warning("duplicate_request_rejected", session_id=sid)
        return ProcessResponse(session_id=sid, status="already_running")
    _in_flight.add(sid)
    asyncio.create_task(_run_pipeline(sid))
    return ProcessResponse(session_id=sid, status="accepted")


async def _run_pipeline(session_id: str):
    try:
        await process_intake_v2(session_id)
    except Exception as e:
        logger.error("pipeline_background_error", session_id=session_id, error=str(e))
    finally:
        _in_flight.discard(session_id)
