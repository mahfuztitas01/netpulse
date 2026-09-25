"""Alert + trigger endpoints.

Alerts follow the PROBLEM -> ACKNOWLEDGED -> RESOLVED lifecycle. Triggers are
custom threshold rules that automatically open alerts when crossed.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..audit import record
from ..database import get_db
from ..deps import get_current_user_ready, require_role
from ..models import (
    Alert,
    AlertSeverity,
    AlertStatus,
    Device,
    Trigger,
    TriggerMetric,
    TriggerOperator,
    User,
)
from ..monitor.alerts import alert_manager

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


def _client_ip(request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


# ---------------------------------------------------------------- schemas
class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    device_id: int | None = None
    device_name: str | None = None
    trigger_id: int | None = None
    name: str
    severity: AlertSeverity
    status: AlertStatus
    message: str
    value: float | None = None
    threshold: float | None = None
    created_at: datetime
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None


class AlertStats(BaseModel):
    total_open: int
    critical: int
    high: int
    average: int
    warning: int
    info: int
    acknowledged: int


class TriggerIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    device_id: int | None = None
    metric: TriggerMetric
    operator: TriggerOperator = TriggerOperator.gt
    threshold: float
    severity: AlertSeverity = AlertSeverity.warning
    enabled: bool = True


class TriggerUpdate(BaseModel):
    name: str | None = None
    device_id: int | None = None
    metric: TriggerMetric | None = None
    operator: TriggerOperator | None = None
    threshold: float | None = None
    severity: AlertSeverity | None = None
    enabled: bool | None = None


class TriggerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    device_id: int | None = None
    metric: TriggerMetric
    operator: TriggerOperator
    threshold: float
    severity: AlertSeverity
    enabled: bool
    created_at: datetime


# ---------------------------------------------------------------- alert endpoints
@router.get("", response_model=list[AlertOut])
async def list_alerts(
    status_filter: AlertStatus | None = Query(default=None, alias="status"),
    severity: AlertSeverity | None = Query(default=None),
    device_id: int | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    _: User = Depends(get_current_user_ready),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Alert).options(selectinload(Alert.device)).order_by(Alert.created_at.desc()).limit(limit)
    if status_filter:
        stmt = select(Alert).options(selectinload(Alert.device)).where(Alert.status == status_filter).order_by(Alert.created_at.desc()).limit(limit)
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    if device_id:
        stmt = stmt.where(Alert.device_id == device_id)
    rows = (await db.execute(stmt)).scalars().all()
    out = []
    for a in rows:
        d = AlertOut.model_validate(a)
        d.device_name = a.device.name if a.device else None
        out.append(d)
    return out


@router.get("/stats", response_model=AlertStats)
async def alert_stats(
    _: User = Depends(get_current_user_ready),
    db: AsyncSession = Depends(get_db),
):
    open_statuses = [AlertStatus.problem, AlertStatus.acknowledged]
    total_open = await db.scalar(
        select(func.count()).select_from(Alert).where(Alert.status.in_(open_statuses))
    ) or 0

    async def _count(sev):
        return await db.scalar(
            select(func.count()).select_from(Alert).where(
                Alert.status.in_(open_statuses), Alert.severity == sev
            )
        ) or 0

    acknowledged = await db.scalar(
        select(func.count()).select_from(Alert).where(Alert.status == AlertStatus.acknowledged)
    ) or 0
    return AlertStats(
        total_open=total_open,
        critical=await _count(AlertSeverity.critical),
        high=await _count(AlertSeverity.high),
        average=await _count(AlertSeverity.average),
        warning=await _count(AlertSeverity.warning),
        info=await _count(AlertSeverity.info),
        acknowledged=acknowledged,
    )


@router.post("/{alert_id}/ack", response_model=AlertOut)
async def acknowledge_alert(
    alert_id: int,
    request: Request,
    user: User = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    alert = await alert_manager.acknowledge(db, alert_id, by=user.username)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found or already resolved")
    await db.commit()
    await record(db, action="alert_acknowledged", username=user.username, user_id=user.id,
                 entity_type="alert", entity_id=alert_id,
                 detail=f"acknowledged alert {alert.name}", ip_address=_client_ip(request))
    await db.commit()
    await db.refresh(alert)
    return alert


@router.post("/{alert_id}/resolve", response_model=AlertOut)
async def resolve_alert(
    alert_id: int,
    request: Request,
    user: User = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    alert = (await db.execute(select(Alert).where(Alert.id == alert_id))).scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = AlertStatus.resolved
    alert.resolved_at = datetime.now().astimezone()
    alert.resolved_by = user.username
    await db.commit()
    await record(db, action="alert_resolved", username=user.username, user_id=user.id,
                 entity_type="alert", entity_id=alert_id,
                 detail=f"resolved alert {alert.name}", ip_address=_client_ip(request))
    await db.commit()
    await db.refresh(alert)
    return alert


# ---------------------------------------------------------------- trigger endpoints
@router.get("/triggers", response_model=list[TriggerOut])
async def list_triggers(
    _: User = Depends(get_current_user_ready),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(select(Trigger).order_by(Trigger.id))).scalars().all()
    return rows


@router.post("/triggers", response_model=TriggerOut, status_code=status.HTTP_201_CREATED)
async def create_trigger(
    payload: TriggerIn,
    request: Request,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    trigger = Trigger(**payload.model_dump())
    db.add(trigger)
    await db.commit()
    await db.refresh(trigger)
    await record(db, action="trigger_created", username=user.username, user_id=user.id,
                 entity_type="trigger", entity_id=trigger.id,
                 detail=f"created trigger {trigger.name}", ip_address=_client_ip(request))
    await db.commit()
    return trigger


@router.patch("/triggers/{trigger_id}", response_model=TriggerOut)
async def update_trigger(
    trigger_id: int,
    payload: TriggerUpdate,
    request: Request,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    trigger = (await db.execute(select(Trigger).where(Trigger.id == trigger_id))).scalar_one_or_none()
    if trigger is None:
        raise HTTPException(status_code=404, detail="Trigger not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(trigger, key, value)
    await db.commit()
    await db.refresh(trigger)
    await record(db, action="trigger_updated", username=user.username, user_id=user.id,
                 entity_type="trigger", entity_id=trigger_id,
                 detail=f"updated trigger {trigger.name}", ip_address=_client_ip(request))
    await db.commit()
    return trigger


@router.delete("/triggers/{trigger_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trigger(
    trigger_id: int,
    request: Request,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    trigger = (await db.execute(select(Trigger).where(Trigger.id == trigger_id))).scalar_one_or_none()
    if trigger is None:
        raise HTTPException(status_code=404, detail="Trigger not found")
    await db.delete(trigger)
    await db.commit()
    await record(db, action="trigger_deleted", username=user.username, user_id=user.id,
                 entity_type="trigger", entity_id=trigger_id,
                 detail=f"deleted trigger {trigger.name}", ip_address=_client_ip(request))
    await db.commit()
