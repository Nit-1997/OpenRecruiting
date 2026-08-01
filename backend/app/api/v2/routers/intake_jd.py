"""POST /intake/jd/extract — recruiter JD (url | file | text) -> formatted JD.

Multipart form with exactly one of: file, url, text. The pipeline lives in
jd_extract_service (acquire -> sanitize -> guardrail -> parse). Fetch/parse
failures map to HTTP codes; a successful call with no usable text or a tripped
injection guardrail returns 200 with status 'empty'/'rejected' so the modal can
explain it without hard-failing the recruiter.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api.v2.core.dependencies import CurrentUserWithOrg, get_current_user_with_org
from app.api.v2.schemas.intake_jd import JdExtractResponse
from app.config import get_settings
from app.dependencies import get_anthropic_async_client
from app.services.intake.jd_extract_service import extract_jd
from app.services.intake.jd_fetch import (
    FileTooLargeError,
    JdFetchError,
    SsrfBlockedError,
    UnsupportedFileError,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/intake", tags=["v2/intake"])


@router.post("/jd/extract", response_model=JdExtractResponse)
async def post_jd_extract(
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
    current: CurrentUserWithOrg = Depends(get_current_user_with_org),
    client=Depends(get_anthropic_async_client),
) -> JdExtractResponse:
    """One box: `text` (URL auto-detected + fetched) and/or an uploaded `file`."""
    has_text = bool(text and text.strip())
    if file is None and not has_text:
        raise HTTPException(status_code=400, detail="Paste some context, a URL, or upload a file.")

    model = get_settings().INTAKE_JD_MODEL
    try:
        file_arg = None
        if file is not None:
            file_arg = (file.filename, file.content_type, await file.read())
        result = await extract_jd(
            client=client,
            model=model,
            text=text if has_text else None,
            file=file_arg,
        )
    except SsrfBlockedError as exc:
        raise HTTPException(status_code=400, detail=f"That URL can't be fetched: {exc}") from exc
    except UnsupportedFileError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except FileTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except JdFetchError as exc:
        raise HTTPException(status_code=502, detail=f"Could not read the job description: {exc}") from exc

    return JdExtractResponse(**result)
