"""Audit log read endpoint (super_admin only)."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import require_user_manage
from ..models import AuditLog, User

router = APIRouter(prefix="/api/audit", tags=["audit"])


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    action: str
    username: str | None = None
    entity_type: str | None = None
    entity_id: int | None = None
    detail: str | None = None
    ip_address: str | None = None
    created_at: datetime


@router.get("", response_model=list[AuditLogOut])
async def list_audit_logs(
    limit: int = Query(default=200, ge=1, le=1000),
    action: str | None = Query(default=None),
    _: User = Depends(require_user_manage),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if action:
        stmt = select(AuditLog).where(AuditLog.action == action).order_by(
            AuditLog.created_at.desc()
        ).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()
