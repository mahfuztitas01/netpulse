"""Event log, statistics and notification test endpoints."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import get_current_user_ready
from ..models import Device, DeviceStatus, Event, User, utcnow
from ..monitor.notifier import notifier
from ..schemas import EventOut, MessageOut, StatsOut

router = APIRouter(prefix="/api", tags=["events"])


@router.get("/events", response_model=list[EventOut])
async def list_events(
    device_id: int | None = None,
    type: str | None = Query(default=None, alias="type"),
    severity: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    _: User = Depends(get_current_user_ready),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Event)
    if device_id is not None:
        stmt = stmt.where(Event.device_id == device_id)
    if type:
        stmt = stmt.where(Event.type == type)
    if severity:
        stmt = stmt.where(Event.severity == severity)
    stmt = stmt.order_by(Event.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/stats", response_model=StatsOut)
async def stats(
    _: User = Depends(get_current_user_ready), db: AsyncSession = Depends(get_db)
):
    total = await db.scalar(select(func.count()).select_from(Device)) or 0
    up = (
        await db.scalar(
            select(func.count()).select_from(Device).where(Device.status == DeviceStatus.up)
        )
        or 0
    )
    down = (
        await db.scalar(
            select(func.count()).select_from(Device).where(Device.status == DeviceStatus.down)
        )
        or 0
    )
    unknown = total - up - down

    avg_latency = await db.scalar(
        select(func.avg(Device.last_latency_ms)).where(Device.last_latency_ms.isnot(None))
    )
    avg_cpu = await db.scalar(
        select(func.avg(Device.last_cpu)).where(Device.last_cpu.isnot(None))
    )
    avg_ram = await db.scalar(
        select(func.avg(Device.last_ram)).where(Device.last_ram.isnot(None))
    )

    since = utcnow() - timedelta(hours=24)
    events_24h = (
        await db.scalar(select(func.count()).select_from(Event).where(Event.created_at >= since))
        or 0
    )

    return StatsOut(
        total=total,
        up=up,
        down=down,
        unknown=unknown,
        avg_latency_ms=round(avg_latency, 2) if avg_latency else None,
        avg_cpu=round(avg_cpu, 1) if avg_cpu else None,
        avg_ram=round(avg_ram, 1) if avg_ram else None,
        events_last_24h=events_24h,
    )


@router.post("/notifications/test", response_model=MessageOut)
async def test_notification(_: User = Depends(get_current_user_ready)):
    ok, msg = await notifier.test()
    return MessageOut(detail=msg)
