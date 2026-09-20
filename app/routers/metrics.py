"""Metrics & interface history endpoints (for dashboard charts)."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import get_current_user_ready
from ..models import Device, Interface, InterfaceSample, MetricSample, User, utcnow
from ..schemas import InterfaceOut, MetricPoint, MetricSeries

router = APIRouter(prefix="/api", tags=["metrics"])

_UNITS = {"cpu": "%", "ram": "%", "uptime": "s"}


async def _require_device(db: AsyncSession, device_id: int) -> Device:
    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


@router.get("/devices/{device_id}/metrics", response_model=MetricSeries)
async def device_metric_series(
    device_id: int,
    metric: str = Query(default="cpu", pattern="^(cpu|ram|uptime)$"),
    hours: int = Query(default=24, ge=1, le=24 * 30),
    _: User = Depends(get_current_user_ready),
    db: AsyncSession = Depends(get_db),
):
    await _require_device(db, device_id)
    since = utcnow() - timedelta(hours=hours)
    result = await db.execute(
        select(MetricSample.timestamp, MetricSample.value)
        .where(
            MetricSample.device_id == device_id,
            MetricSample.metric == metric,
            MetricSample.timestamp >= since,
        )
        .order_by(MetricSample.timestamp.asc())
        .limit(2000)
    )
    points = [MetricPoint(t=ts, v=val) for ts, val in result.all()]
    return MetricSeries(metric=metric, unit=_UNITS.get(metric), points=points)


@router.get("/devices/{device_id}/interfaces", response_model=list[InterfaceOut])
async def device_interfaces(
    device_id: int,
    only_monitored: bool = Query(default=False),
    _: User = Depends(get_current_user_ready),
    db: AsyncSession = Depends(get_db),
):
    await _require_device(db, device_id)
    stmt = select(Interface).where(Interface.device_id == device_id)
    if only_monitored:
        stmt = stmt.where(Interface.monitor.is_(True))
    stmt = stmt.order_by(Interface.if_index)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.patch("/interfaces/{interface_id}", response_model=InterfaceOut)
async def toggle_interface(
    interface_id: int,
    monitor: bool,
    _: User = Depends(get_current_user_ready),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Interface).where(Interface.id == interface_id))
    iface = result.scalar_one_or_none()
    if iface is None:
        raise HTTPException(status_code=404, detail="Interface not found")
    iface.monitor = monitor
    await db.commit()
    await db.refresh(iface)
    return iface


@router.get("/interfaces/{interface_id}/traffic", response_model=list[MetricPoint])
async def interface_traffic(
    interface_id: int,
    direction: str = Query(default="in", pattern="^(in|out)$"),
    hours: int = Query(default=6, ge=1, le=24 * 30),
    _: User = Depends(get_current_user_ready),
    db: AsyncSession = Depends(get_db),
):
    since = utcnow() - timedelta(hours=hours)
    column = InterfaceSample.in_bps if direction == "in" else InterfaceSample.out_bps
    result = await db.execute(
        select(InterfaceSample.timestamp, column)
        .where(InterfaceSample.interface_id == interface_id, InterfaceSample.timestamp >= since)
        .order_by(InterfaceSample.timestamp.asc())
        .limit(2000)
    )
    return [MetricPoint(t=ts, v=val or 0.0) for ts, val in result.all()]
