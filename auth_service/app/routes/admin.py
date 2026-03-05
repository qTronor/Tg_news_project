from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..dependencies import get_client_ip, require_admin
from ..models import AdminAuditLog, ChannelVisibility, User
from ..schemas import (
    AuditLogEntry,
    ChannelInfo,
    ChannelVisibilityUpdate,
    MessageEdit,
)

router = APIRouter(prefix="/admin", tags=["admin"])


async def _log_action(
    db: AsyncSession,
    admin: User,
    request: Request,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    old_value: dict | None = None,
    new_value: dict | None = None,
):
    entry = AdminAuditLog(
        admin_id=admin.id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        old_value=old_value,
        new_value=new_value,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
    )
    db.add(entry)


@router.patch("/messages/{event_id}")
async def edit_message(
    event_id: str,
    body: MessageEdit,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No changes provided")

    await _log_action(
        db, admin, request,
        action="edit_message",
        target_type="message",
        target_id=event_id,
        new_value=changes,
    )

    return {"status": "ok", "event_id": event_id, "changes": changes}


@router.get("/channels", response_model=list[ChannelInfo])
async def list_channels(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ChannelVisibility).order_by(ChannelVisibility.channel_name))
    return result.scalars().all()


@router.put("/channels/{channel_name}")
async def upsert_channel_visibility(
    channel_name: str,
    body: ChannelVisibilityUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ChannelVisibility).where(ChannelVisibility.channel_name == channel_name)
    )
    channel = result.scalar_one_or_none()
    old_visible = channel.is_visible if channel else None

    if channel:
        channel.is_visible = body.is_visible
        channel.updated_by = admin.id
    else:
        channel = ChannelVisibility(
            channel_name=channel_name,
            is_visible=body.is_visible,
            updated_by=admin.id,
        )
        db.add(channel)

    await _log_action(
        db, admin, request,
        action="toggle_channel",
        target_type="channel",
        target_id=channel_name,
        old_value={"is_visible": old_visible},
        new_value={"is_visible": body.is_visible},
    )

    return {"status": "ok", "channel_name": channel_name, "is_visible": body.is_visible}


@router.get("/audit-log", response_model=list[AuditLogEntry])
async def get_audit_log(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: str | None = None,
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(AdminAuditLog, User.username.label("admin_username"))
        .outerjoin(User, AdminAuditLog.admin_id == User.id)
        .order_by(AdminAuditLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if action:
        query = query.where(AdminAuditLog.action == action)

    result = await db.execute(query)
    rows = result.all()

    return [
        AuditLogEntry(
            id=row.AdminAuditLog.id,
            admin_id=row.AdminAuditLog.admin_id,
            admin_username=row.admin_username,
            action=row.AdminAuditLog.action,
            target_type=row.AdminAuditLog.target_type,
            target_id=row.AdminAuditLog.target_id,
            old_value=row.AdminAuditLog.old_value,
            new_value=row.AdminAuditLog.new_value,
            ip_address=str(row.AdminAuditLog.ip_address) if row.AdminAuditLog.ip_address else None,
            created_at=row.AdminAuditLog.created_at,
        )
        for row in rows
    ]
