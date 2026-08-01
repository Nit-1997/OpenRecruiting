from fastapi import APIRouter, Depends, HTTPException, status, Query
from uuid import UUID
import asyncio
from app.logging_config import get_logger
from app.dependencies import require_staff, CurrentUser, invalidate_profile_cache
from app.models.user import (
    UserCreate,
    UserListResponse,
    MagicLinkResponse,
    ResendMagicLinkRequest,
    DeleteUserResponse
)
from app.services.supabase import get_supabase_admin_client
from app.config import get_settings

logger = get_logger(__name__)

router = APIRouter(tags=["Users"])


@router.get("/users", response_model=UserListResponse)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current_user: CurrentUser = Depends(require_staff),
):
    supabase = get_supabase_admin_client()
    offset = (page - 1) * page_size
    result, total = await asyncio.gather(
        supabase.table("profiles").select("*").is_null("deleted_at").order("created_at", desc=True).limit(page_size).offset(offset).execute_async(),
        supabase.table("profiles").select("id").is_null("deleted_at").count_async(),
    )
    users = result.data if result.data else []
    return UserListResponse(users=users, total=total)


@router.get("/organizations/{org_id}/users", response_model=UserListResponse)
async def list_organization_users(
    org_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current_user: CurrentUser = Depends(require_staff),
):
    supabase = get_supabase_admin_client()
    offset = (page - 1) * page_size
    result, total = await asyncio.gather(
        supabase.table("profiles").select("*").eq("organization_id", str(org_id)).is_null("deleted_at").order("created_at", desc=True).limit(page_size).offset(offset).execute_async(),
        supabase.table("profiles").select("id").eq("organization_id", str(org_id)).is_null("deleted_at").count_async(),
    )
    profiles = result.data if result.data else []

    if not profiles:
        return UserListResponse(users=[], total=total)

    user_ids = [p["id"] for p in profiles]
    auth_users = await supabase.get_auth_users_batch(user_ids)

    users = []
    for profile in profiles:
        auth_user = auth_users.get(profile["id"], {})
        email_confirmed = auth_user.get("email_confirmed_at")
        last_sign_in = auth_user.get("last_sign_in_at")

        if not email_confirmed:
            status = "invited"
        elif not last_sign_in or last_sign_in == email_confirmed:
            status = "link_clicked"
        else:
            status = "signed_up"

        users.append({
            **profile,
            "invitation_status": status,
            "invitation_sent_at": profile.get("created_at")
        })

    return UserListResponse(users=users, total=total)


@router.post(
    "/organizations/{org_id}/users",
    response_model=MagicLinkResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_user_with_magic_link(
    org_id: UUID,
    user: UserCreate,
    current_user: CurrentUser = Depends(require_staff)
):
    settings = get_settings()
    supabase = get_supabase_admin_client()

    existing = await supabase.table("profiles").select("id").eq("email", user.email).execute_async()
    if existing.data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists"
        )

    redirect_url = f"{settings.RECRUITER_PORTAL_URL}/set-password"

    try:
        auth_result = await supabase.invite_user_by_email(
            user.email,
            redirect_to=redirect_url,
            data={"full_name": user.full_name}
        )
    except Exception as e:
        logger.exception("admin_create_user_invite_failed", extra={"email": user.email})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send invitation"
        )

    auth_user_id = auth_result.get("id")
    if not auth_user_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user"
        )

    profile_data = {
        "id": auth_user_id,
        "organization_id": str(org_id),
        "email": user.email,
        "full_name": user.full_name,
        "is_staff": False,
        "invitation_status": "invited",
        "onboarding_completed": False
    }

    try:
        profile_result = await supabase.table("profiles").insert(profile_data).execute_async()

        if not profile_result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create user profile"
            )
    except Exception as e:
        logger.exception("admin_create_user_profile_failed", extra={"email": user.email})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user profile"
        )

    return MagicLinkResponse(
        message="Invitation sent successfully",
        user_id=UUID(auth_user_id),
        email=user.email
    )


@router.post("/users/resend-magic-link", response_model=MagicLinkResponse)
async def resend_magic_link(
    request: ResendMagicLinkRequest,
    current_user: CurrentUser = Depends(require_staff)
):
    settings = get_settings()
    supabase = get_supabase_admin_client()

    profile_result = await supabase.table("profiles").select("id, email").eq("email", request.email).single().execute_async()

    if not profile_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    redirect_url = f"{settings.RECRUITER_PORTAL_URL}/set-password"

    try:
        await supabase.invite_user_by_email(
            request.email,
            redirect_to=redirect_url
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send invitation"
        )

    return MagicLinkResponse(
        message="Invitation resent successfully",
        user_id=UUID(profile_result.data["id"]),
        email=request.email
    )


@router.post("/users/{user_id}/reset-invite", response_model=MagicLinkResponse)
async def reset_invite(
    user_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    settings = get_settings()
    supabase = get_supabase_admin_client()

    profile_result = await supabase.table("profiles").select("*").eq("id", str(user_id)).single().execute_async()

    if not profile_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    saved_profile = dict(profile_result.data)
    email = saved_profile["email"]
    full_name = saved_profile.get("full_name", "")

    redirect_url = f"{settings.RECRUITER_PORTAL_URL}/set-password"

    # Safe ordering: this flow spans the Supabase Auth API (delete + invite) and
    # a profiles DB write, so a pure DB transaction cannot cover it. We therefore
    # do the REVERSIBLE work first (invite new auth user, insert its profile) and
    # only perform the IRREVERSIBLE delete of the old auth user LAST, after the
    # replacement is fully in place. The old account (and its profile, via the
    # ON DELETE CASCADE FK) survives until then, so an invite/insert failure
    # never destroys the only record of the user.

    # 1. Invite the new auth user (reversible — can be deleted to compensate).
    try:
        auth_result = await supabase.invite_user_by_email(
            email,
            redirect_to=redirect_url,
            data={"full_name": full_name}
        )
    except Exception as e:
        logger.exception("admin_reset_invite_send_failed", extra={"user_id": str(user_id)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send invitation"
        )

    new_auth_user_id = auth_result.get("id")
    if not new_auth_user_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user"
        )

    # 2. Insert the new profile row. On failure, compensate by deleting the NEW
    #    auth user only — the old account is still intact and recoverable.
    saved_profile["id"] = new_auth_user_id
    saved_profile.pop("created_at", None)
    saved_profile.pop("updated_at", None)
    saved_profile.pop("deleted_at", None)
    saved_profile.pop("invitation_status", None)
    saved_profile.pop("invitation_sent_at", None)

    try:
        await supabase.table("profiles").insert(saved_profile).execute_async()
    except Exception as e:
        try:
            await supabase.delete_user(new_auth_user_id)
        except Exception as comp_err:
            logger.error(
                "reset_invite_compensation_failed",
                extra={
                    "event": "reset_invite_compensation_failed",
                    "old_user_id": str(user_id),
                    "new_user_id": new_auth_user_id,
                    "error": str(comp_err),
                },
            )
        logger.exception("admin_reset_invite_profile_failed", extra={"user_id": str(user_id)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to recreate profile"
        )

    # 3. Delete the OLD auth user LAST (irreversible; old profile cascades). A
    #    failure here leaves a harmless orphaned old account — the new user is
    #    fully functional — so we log it and still return success.
    try:
        await supabase.delete_user(str(user_id))
    except Exception as del_err:
        logger.warning(
            "reset_invite_old_user_delete_failed",
            extra={
                "event": "reset_invite_old_user_delete_failed",
                "old_user_id": str(user_id),
                "new_user_id": new_auth_user_id,
                "error": str(del_err),
            },
        )

    invalidate_profile_cache(str(user_id))

    return MagicLinkResponse(
        message="Invitation reset successfully",
        user_id=UUID(new_auth_user_id),
        email=email
    )


@router.delete("/users/{user_id}", response_model=DeleteUserResponse)
async def delete_user(
    user_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()

    profile_result = await supabase.table("profiles").select("id, email, is_staff, deleted_at").eq("id", str(user_id)).single().execute_async()

    if not profile_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    if profile_result.data.get("deleted_at"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already deleted"
        )

    if profile_result.data.get("is_staff"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete admin users"
        )

    try:
        from datetime import datetime, timezone

        await supabase.ban_user(str(user_id), ban=True)

        await supabase.table("profiles").update({
            "deleted_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", str(user_id)).execute_async()

        invalidate_profile_cache(str(user_id))
    except Exception as e:
        logger.exception("admin_delete_user_failed", extra={"user_id": str(user_id)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete user"
        )

    return DeleteUserResponse(
        message="User deleted successfully",
        user_id=user_id
    )


@router.post("/users/{user_id}/restore", response_model=DeleteUserResponse)
async def restore_user(
    user_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()

    profile_result = await supabase.table("profiles").select("id, email, deleted_at").eq("id", str(user_id)).single().execute_async()

    if not profile_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    if not profile_result.data.get("deleted_at"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not deleted"
        )

    try:
        await supabase.ban_user(str(user_id), ban=False)

        await supabase.table("profiles").update({
            "deleted_at": None
        }).eq("id", str(user_id)).execute_async()

        invalidate_profile_cache(str(user_id))
    except Exception as e:
        logger.exception("admin_restore_user_failed", extra={"user_id": str(user_id)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to restore user"
        )

    return DeleteUserResponse(
        message="User restored successfully",
        user_id=user_id
    )


@router.get("/organizations/{org_id}/users/deleted", response_model=UserListResponse)
async def list_deleted_organization_users(
    org_id: UUID,
    current_user: CurrentUser = Depends(require_staff)
):
    supabase = get_supabase_admin_client()
    result = await supabase.table("profiles").select("*").eq("organization_id", str(org_id)).not_null("deleted_at").execute_async()
    users = result.data if result.data else []
    return UserListResponse(users=users, total=len(users))
