"""Device + check management endpoints."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..audit import record
from ..crypto import encrypt
from ..database import get_db
from ..deps import get_current_user_ready, require_device_write
from ..models import Check, CheckResult, Device, Event, User, utcnow
from ..monitor.engine import engine
from ..schemas import (
    CheckCreate,
    CheckOut,
    CheckResultOut,
    DeviceCreate,
    DeviceOut,
    DeviceSummary,
    DeviceUpdate,
    EventOut,
    MessageOut,
)

router = APIRouter(prefix="/api/devices", tags=["devices"])


def _client_ip(request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None

_SECRET_FIELDS = ("snmp_community", "snmp_v3_auth_pass", "snmp_v3_priv_pass")
_SECRET_TARGETS = {
    "snmp_community": "snmp_community_enc",
    "snmp_v3_auth_pass": "snmp_v3_auth_pass_enc",
    "snmp_v3_priv_pass": "snmp_v3_priv_pass_enc",
}


def _split_snmp(data: dict) -> tuple[dict, dict]:
    """Separate plain device fields from SNMP secrets."""
    secrets = {key: data.pop(key, None) for key in _SECRET_FIELDS}
    return data, secrets


def _apply_snmp_secrets(device: Device, secrets: dict) -> None:
    for plain, column in _SECRET_TARGETS.items():
        value = secrets.get(plain)
        if value is not None and value != "":
            setattr(device, column, encrypt(value))


# ---------------------------------------------------------------- helpers
async def _get_device_or_404(db: AsyncSession, device_id: int) -> Device:
    result = await db.execute(
        select(Device).where(Device.id == device_id).options(selectinload(Device.checks))
    )
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


async def _uptime_map(db: AsyncSession, device_ids: list[int], hours: int = 24) -> dict[int, float]:
    if not device_ids:
        return {}
    since = utcnow() - timedelta(hours=hours)
    rows = await db.execute(
        select(
            CheckResult.device_id,
            func.count().label("total"),
            func.sum(cast(CheckResult.success, Integer)).label("ok"),
        )
        .where(CheckResult.device_id.in_(device_ids), CheckResult.timestamp >= since)
        .group_by(CheckResult.device_id)
    )
    out: dict[int, float] = {}
    for device_id, total, ok in rows:
        out[device_id] = round((ok or 0) / total * 100, 2) if total else 0.0
    return out


# ---------------------------------------------------------------- CRUD
@router.get("", response_model=list[DeviceSummary])
async def list_devices(
    q: str | None = Query(default=None, description="search name/host"),
    status_filter: str | None = Query(default=None, alias="status"),
    vendor: str | None = Query(default=None),
    enabled_only: bool = Query(default=False),
    _: User = Depends(get_current_user_ready),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Device)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Device.name.ilike(like) | Device.host.ilike(like))
    if status_filter:
        stmt = stmt.where(Device.status == status_filter)
    if vendor:
        stmt = stmt.where(Device.vendor == vendor)
    if enabled_only:
        stmt = stmt.where(Device.enabled.is_(True))
    stmt = stmt.order_by(Device.name)
    result = await db.execute(stmt.options(selectinload(Device.alert_group)))
    devices = result.scalars().all()

    up = await _uptime_map(db, [d.id for d in devices])
    return [
        DeviceSummary(
            id=d.id,
            name=d.name,
            host=d.host,
            vendor=d.vendor,
            status=d.status,
            alert_group_id=d.alert_group_id,
            alert_group_name=d.alert_group_name,
            last_latency_ms=d.last_latency_ms,
            last_cpu=d.last_cpu,
            last_ram=d.last_ram,
            last_checked_at=d.last_checked_at,
            uptime_percent=up.get(d.id),
        )
        for d in devices
    ]


@router.post("", response_model=DeviceOut, status_code=status.HTTP_201_CREATED)
async def create_device(
    payload: DeviceCreate,
    request: Request,
    user: User = Depends(require_device_write),
    db: AsyncSession = Depends(get_db),
):
    data = payload.model_dump(exclude={"checks"})
    data, secrets = _split_snmp(data)
    device = Device(**data)
    _apply_snmp_secrets(device, secrets)
    for check in payload.checks:
        device.checks.append(Check(**check.model_dump()))
    db.add(device)
    await db.commit()
    await db.refresh(device)
    await record(db, action="device_created", username=user.username, user_id=user.id,
                 entity_type="device", entity_id=device.id,
                 detail=f"added device {device.name} ({device.host})",
                 ip_address=_client_ip(request))
    await db.commit()
    return device


@router.get("/{device_id}", response_model=DeviceOut)
async def get_device(
    device_id: int, _: User = Depends(get_current_user_ready), db: AsyncSession = Depends(get_db)
):
    return await _get_device_or_404(db, device_id)


@router.patch("/{device_id}", response_model=DeviceOut)
async def update_device(
    device_id: int,
    payload: DeviceUpdate,
    request: Request,
    user: User = Depends(require_device_write),
    db: AsyncSession = Depends(get_db),
):
    device = await _get_device_or_404(db, device_id)
    data = payload.model_dump(exclude_unset=True)
    data, secrets = _split_snmp(data)
    for key, value in data.items():
        setattr(device, key, value)
    _apply_snmp_secrets(device, secrets)
    await db.commit()
    await db.refresh(device)
    await record(db, action="device_updated", username=user.username, user_id=user.id,
                 entity_type="device", entity_id=device.id,
                 detail=f"edited device {device.name}",
                 ip_address=_client_ip(request))
    await db.commit()
    return device


@router.delete("/{device_id}", response_model=MessageOut)
async def delete_device(
    device_id: int,
    request: Request,
    user: User = Depends(require_device_write),
    db: AsyncSession = Depends(get_db),
):
    device = await _get_device_or_404(db, device_id)
    await db.delete(device)
    await db.commit()
    await record(db, action="device_deleted", username=user.username, user_id=user.id,
                 entity_type="device", entity_id=device_id,
                 detail=f"deleted device {device.name} ({device.host})",
                 ip_address=_client_ip(request))
    await db.commit()
    return MessageOut(detail="Device deleted")


# ---------------------------------------------------------------- checks
@router.post("/{device_id}/checks", response_model=CheckOut, status_code=201)
async def add_check(
    device_id: int,
    payload: CheckCreate,
    _: User = Depends(get_current_user_ready),
    db: AsyncSession = Depends(get_db),
):
    device = await _get_device_or_404(db, device_id)
    check = Check(device_id=device.id, **payload.model_dump())
    db.add(check)
    await db.commit()
    await db.refresh(check)
    return check


@router.delete("/{device_id}/checks/{check_id}", response_model=MessageOut)
async def delete_check(
    device_id: int,
    check_id: int,
    _: User = Depends(get_current_user_ready),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Check).where(Check.id == check_id, Check.device_id == device_id)
    )
    check = result.scalar_one_or_none()
    if check is None:
        raise HTTPException(status_code=404, detail="Check not found")
    await db.delete(check)
    await db.commit()
    return MessageOut(detail="Check deleted")


# ---------------------------------------------------------------- data
@router.get("/{device_id}/history", response_model=list[CheckResultOut])
async def device_history(
    device_id: int,
    hours: int = Query(default=24, ge=1, le=24 * 30),
    limit: int = Query(default=500, ge=1, le=5000),
    _: User = Depends(get_current_user_ready),
    db: AsyncSession = Depends(get_db),
):
    await _get_device_or_404(db, device_id)
    since = utcnow() - timedelta(hours=hours)
    result = await db.execute(
        select(CheckResult)
        .where(CheckResult.device_id == device_id, CheckResult.timestamp >= since)
        .order_by(CheckResult.timestamp.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/{device_id}/events", response_model=list[EventOut])
async def device_events(
    device_id: int,
    limit: int = Query(default=100, ge=1, le=1000),
    _: User = Depends(get_current_user_ready),
    db: AsyncSession = Depends(get_db),
):
    await _get_device_or_404(db, device_id)
    result = await db.execute(
        select(Event).where(Event.device_id == device_id)
        .order_by(Event.created_at.desc()).limit(limit)
    )
    return result.scalars().all()


@router.post("/{device_id}/check-now", response_model=MessageOut)
async def check_now(
    device_id: int, _: User = Depends(get_current_user_ready), db: AsyncSession = Depends(get_db)
):
    await _get_device_or_404(db, device_id)
    await engine.check_now(device_id)
    return MessageOut(detail="Check queued")
