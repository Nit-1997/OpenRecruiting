from fastapi import APIRouter, Depends, HTTPException, status, Query
from uuid import UUID
from app.dependencies import require_staff, CurrentUser
from app.models.promotions import PromotionCreate, PromotionUpdate, PromotionResponse
from app.services.supabase import get_supabase_admin_client
import asyncio

router = APIRouter(prefix="/promotions", tags=["Admin - Promotions"])


@router.get("")
async def list_promotions(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current_user: CurrentUser = Depends(require_staff),
):
    supabase = get_supabase_admin_client()
    offset = (page - 1) * page_size
    result, total = await asyncio.gather(
        supabase.table("promotions").select("*").order("created_at", desc=True).limit(page_size).offset(offset).execute_async(),
        supabase.table("promotions").select("id").count_async(),
    )
    return {"items": [PromotionResponse(**p) for p in (result.data or [])], "total": total, "page": page, "page_size": page_size}


@router.post("", response_model=PromotionResponse, status_code=status.HTTP_201_CREATED)
async def create_promotion(
    promo: PromotionCreate,
    current_user: CurrentUser = Depends(require_staff),
):
    supabase = get_supabase_admin_client()

    if promo.is_active:
        await supabase.table("promotions") \
            .update({"is_active": False}) \
            .eq("is_active", True) \
            .execute_async()

    data = {
        "code": promo.code.upper(),
        "percent_off": promo.percent_off,
        "is_active": promo.is_active,
    }
    if promo.start_date:
        data["start_date"] = promo.start_date.isoformat()
    if promo.end_date:
        data["end_date"] = promo.end_date.isoformat()

    result = await supabase.table("promotions") \
        .insert(data) \
        .execute_async()
    row = result.data[0] if isinstance(result.data, list) else result.data
    return PromotionResponse(**row)


@router.put("/{promo_id}", response_model=PromotionResponse)
async def update_promotion(
    promo_id: UUID,
    promo: PromotionUpdate,
    current_user: CurrentUser = Depends(require_staff),
):
    supabase = get_supabase_admin_client()
    update_data = promo.model_dump(exclude_none=True)

    if update_data.get("code"):
        update_data["code"] = update_data["code"].upper()

    if update_data.get("is_active") is True:
        await supabase.table("promotions") \
            .update({"is_active": False}) \
            .eq("is_active", True) \
            .neq("id", str(promo_id)) \
            .execute_async()

    if "start_date" in update_data and update_data["start_date"]:
        update_data["start_date"] = update_data["start_date"].isoformat()
    if "end_date" in update_data and update_data["end_date"]:
        update_data["end_date"] = update_data["end_date"].isoformat()

    result = await supabase.table("promotions") \
        .update(update_data) \
        .eq("id", str(promo_id)) \
        .execute_async()

    data = result.data
    if not data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Promotion not found")
    row = data[0] if isinstance(data, list) else data
    return PromotionResponse(**row)


@router.delete("/{promo_id}")
async def delete_promotion(
    promo_id: UUID,
    current_user: CurrentUser = Depends(require_staff),
):
    supabase = get_supabase_admin_client()
    await supabase.table("promotions") \
        .delete() \
        .eq("id", str(promo_id)) \
        .execute_async()
    return {"message": "Promotion deleted", "id": str(promo_id)}
