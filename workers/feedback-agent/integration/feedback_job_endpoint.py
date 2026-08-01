"""
Feedback Job Endpoint for openrecruiting-backend

Copy this file to: openrecruiting-backend/app/api/v1/admin/feedback_jobs.py
Add to router: from app.api.v1.admin import feedback_jobs
Include router: admin_router.include_router(feedback_jobs.router)

Add to config.py:
    AWS_REGION: str = "us-east-1"
    FEEDBACK_LAMBDA_NAME: str = "feedback-agent-worker"
"""
import json
from datetime import datetime

import boto3
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/feedback-jobs", tags=["feedback"])

AWS_REGION = "us-east-1"
FEEDBACK_LAMBDA_NAME = "feedback-agent-worker"

_lambda_client = None


def get_lambda_client():
    global _lambda_client
    if _lambda_client is None:
        _lambda_client = boto3.client("lambda", region_name=AWS_REGION)
    return _lambda_client


class FeedbackJobRequest(BaseModel):
    candidate_round_id: str


class FeedbackJobResponse(BaseModel):
    candidate_round_id: str
    status: str
    message: str


@router.post("", response_model=FeedbackJobResponse, status_code=202)
async def create_feedback_job(request: FeedbackJobRequest):
    """
    Submit a feedback processing job.
    Returns immediately. Processing happens async in Lambda.
    Poll GET /{candidate_round_id}/status to check progress.
    """
    try:
        lambda_client = get_lambda_client()
        lambda_client.invoke(
            FunctionName=FEEDBACK_LAMBDA_NAME,
            InvocationType="Event",
            Payload=json.dumps({"candidate_round_id": request.candidate_round_id}),
        )

        return FeedbackJobResponse(
            candidate_round_id=request.candidate_round_id,
            status="accepted",
            message="Feedback processing job submitted successfully",
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to submit job: {e}")


@router.get("/{candidate_round_id}/status")
async def get_feedback_status(candidate_round_id: str):
    """Get processing status for a candidate round."""
    return {
        "candidate_round_id": candidate_round_id,
        "message": "Implement Supabase fetch to get status",
    }


@router.post("/{candidate_round_id}/retry")
async def retry_feedback_processing(candidate_round_id: str):
    """Retry processing for a failed candidate round."""
    try:
        lambda_client = get_lambda_client()
        lambda_client.invoke(
            FunctionName=FEEDBACK_LAMBDA_NAME,
            InvocationType="Event",
            Payload=json.dumps({"candidate_round_id": candidate_round_id}),
        )

        return {"candidate_round_id": candidate_round_id, "status": "retrying"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retry job: {e}")
