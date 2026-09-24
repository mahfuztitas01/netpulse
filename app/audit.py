"""Audit log: record user activity for accountability.

Actions are recorded with the acting user, a human-readable action, the target
entity type/id and the actor's IP (when available from the request). Written
in-process via the shared DB session so it never requires a separate worker.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AuditLog, User, utcnow

log = logging.getLogger("netpulse.audit")


async def record(
    db: AsyncSession,
    *,
    action: str,
    username: str | None = None,
    user_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    detail: str | None = None,
    ip_address: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Append one audit row. Never raises (audit failure must not break a request)."""
    try:
        db.add(
            AuditLog(
                action=action,
                username=username,
                user_id=user_id,
                entity_type=entity_type,
                entity_id=entity_id,
                detail=detail,
                ip_address=ip_address,
                meta=meta,
                created_at=utcnow(),
            )
        )
    except Exception:  # noqa: BLE001
        log.exception("failed to write audit log")


async def resolve_user(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()
