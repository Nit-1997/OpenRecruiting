from fastapi import APIRouter, Depends, HTTPException, status, Query
from uuid import UUID
from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime
from app.dependencies import require_staff, CurrentUser
from app.services.supabase import get_supabase_admin_client


class AssessmentTemplateCreate(BaseModel):
    title: str
    description: Optional[str] = None
    role_seniority: Optional[str] = None
    tools_enabled: List[str] = Field(default=["whiteboard"])
    time_limit_minutes: int = Field(default=45, ge=15, le=180)
    task_definition: dict
    evaluation_rubric: dict
    status: str = Field(default="draft")


class AssessmentTemplateUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    role_seniority: Optional[str] = None
    tools_enabled: Optional[List[str]] = None
    time_limit_minutes: Optional[int] = Field(default=None, ge=15, le=180)
    task_definition: Optional[dict] = None
    evaluation_rubric: Optional[dict] = None
    status: Optional[str] = None


class AssessmentTemplateResponse(BaseModel):
    id: UUID
    title: str
    description: Optional[str]
    role_seniority: Optional[str]
    tools_enabled: List[str]
    time_limit_minutes: int
    task_definition: Any
    evaluation_rubric: Any
    version: str
    status: str
    created_at: datetime
    updated_at: datetime


class AssessmentTemplateListResponse(BaseModel):
    templates: List[AssessmentTemplateResponse]
    total: int


router = APIRouter(prefix="/assessment-templates", tags=["Assessment Templates"])


@router.get("", response_model=AssessmentTemplateListResponse)
async def list_assessment_templates(
    status: Optional[str] = Query(None, description="Filter by status: draft, published, archived"),
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()

    query = supabase.table("assessment_templates").select("*")

    if status:
        query = query.eq("status", status)

    query = query.order("created_at", desc=True)

    result = await query.execute_async()

    templates = result.data if isinstance(result.data, list) else [result.data] if result.data else []

    return AssessmentTemplateListResponse(
        templates=templates,
        total=len(templates)
    )


@router.post(
    "",
    response_model=AssessmentTemplateResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_assessment_template(
    template: AssessmentTemplateCreate,
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()

    data = {
        "title": template.title,
        "description": template.description,
        "role_seniority": template.role_seniority,
        "tools_enabled": template.tools_enabled,
        "time_limit_minutes": template.time_limit_minutes,
        "task_definition": template.task_definition,
        "evaluation_rubric": template.evaluation_rubric,
        "status": template.status,
        "version": "1.0",
        "created_by": str(current_user.id)
    }

    result = await supabase.table("assessment_templates").insert(data).execute_async()

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create assessment template"
        )

    return result.data[0] if isinstance(result.data, list) else result.data


@router.get("/{template_id}", response_model=AssessmentTemplateResponse)
async def get_assessment_template(
    template_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()

    result = await supabase.table("assessment_templates").select("*").eq("id", str(template_id)).single().execute_async()

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assessment template not found"
        )

    return result.data


@router.put("/{template_id}", response_model=AssessmentTemplateResponse)
async def update_assessment_template(
    template_id: UUID,
    template: AssessmentTemplateUpdate,
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()

    existing = await supabase.table("assessment_templates").select("id").eq("id", str(template_id)).single().execute_async()

    if not existing.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assessment template not found"
        )

    update_data = {k: v for k, v in template.model_dump().items() if v is not None}

    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update"
        )

    result = await supabase.table("assessment_templates").update(update_data).eq("id", str(template_id)).execute_async()

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update assessment template"
        )

    return result.data[0] if isinstance(result.data, list) else result.data


@router.delete("/{template_id}")
async def delete_assessment_template(
    template_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()

    existing = await supabase.table("assessment_templates").select("id").eq("id", str(template_id)).single().execute_async()

    if not existing.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assessment template not found"
        )

    await supabase.table("assessment_templates").delete().eq("id", str(template_id)).execute_async()

    return {"message": "Assessment template deleted successfully", "id": str(template_id)}
