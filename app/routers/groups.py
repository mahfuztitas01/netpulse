"""Alert groups — one notification destination per client.

A group owns a Telegram chat id. Devices are assigned to a group, so a device
belonging to "client01" only ever notifies the client01 chat and never
client02's. Devices with no group fall back to the default chat configured in
the Alerts settings.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import get_current_user_ready
from ..models import AlertGroup, Device, User
from ..monitor.notifier import load_telegram_config, notifier
from ..schemas import AlertGroupIn, AlertGroupOut, AlertGroupUpdate, MessageOut

router = APIRouter(prefix="/api/groups", tags=["groups"])


async def _device_counts(db: AsyncSession) -> dict[int, int]:
    rows = await db.execute(
        select(Device.alert_group_id, func.count())
        .where(Device.alert_group_id.is_not(None))
        .group_by(Device.alert_group_id)
    )
    return {gid: count for gid, count in rows}


def _to_out(group: AlertGroup, counts: dict[int, int]) -> AlertGroupOut:
    return AlertGroupOut(
        id=group.id,
        name=group.name,
        description=group.description,
        telegram_chat_id=group.telegram_chat_id,
        whatsapp_enabled=group.whatsapp_enabled,
        enabled=group.enabled,
        device_count=counts.get(group.id, 0),
        created_at=group.created_at,
    )


async def _get_or_404(db: AsyncSession, group_id: int) -> AlertGroup:
    group = await db.get(AlertGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Alert group not found")
    return group


@router.get("", response_model=list[AlertGroupOut])
async def list_groups(
    _: User = Depends(get_current_user_ready), db: AsyncSession = Depends(get_db)
):
    rows = await db.execute(select(AlertGroup).order_by(AlertGroup.name))
    counts = await _device_counts(db)
    return [_to_out(g, counts) for g in rows.scalars().all()]


@router.post("", response_model=AlertGroupOut, status_code=status.HTTP_201_CREATED)
async def create_group(
    payload: AlertGroupIn,
    _: User = Depends(get_current_user_ready),
    db: AsyncSession = Depends(get_db),
):
    name = payload.name.strip()
    existing = await db.execute(select(AlertGroup).where(func.lower(AlertGroup.name) == name.lower()))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"A group named '{name}' already exists")
    group = AlertGroup(
        name=name,
        description=payload.description,
        telegram_chat_id=(payload.telegram_chat_id or "").strip() or None,
        whatsapp_enabled=payload.whatsapp_enabled,
        enabled=payload.enabled,
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return _to_out(group, {})


@router.patch("/{group_id}", response_model=AlertGroupOut)
async def update_group(
    group_id: int,
    payload: AlertGroupUpdate,
    _: User = Depends(get_current_user_ready),
    db: AsyncSession = Depends(get_db),
):
    group = await _get_or_404(db, group_id)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"]:
        name = data["name"].strip()
        clash = await db.execute(
            select(AlertGroup).where(
                func.lower(AlertGroup.name) == name.lower(), AlertGroup.id != group_id
            )
        )
        if clash.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail=f"A group named '{name}' already exists")
        data["name"] = name
    if "telegram_chat_id" in data:
        data["telegram_chat_id"] = (data["telegram_chat_id"] or "").strip() or None
    for key, value in data.items():
        setattr(group, key, value)
    await db.commit()
    await db.refresh(group)
    counts = await _device_counts(db)
    return _to_out(group, counts)


@router.delete("/{group_id}", response_model=MessageOut)
async def delete_group(
    group_id: int,
    _: User = Depends(get_current_user_ready),
    db: AsyncSession = Depends(get_db),
):
    group = await _get_or_404(db, group_id)
    # Devices keep existing; they just fall back to the default chat.
    await db.execute(
        Device.__table__.update().where(Device.alert_group_id == group_id).values(alert_group_id=None)
    )
    await db.delete(group)
    await db.commit()
    return MessageOut(detail="Alert group deleted (its devices now use the default chat)")


@router.post("/{group_id}/test", response_model=MessageOut)
async def test_group(
    group_id: int,
    _: User = Depends(get_current_user_ready),
    db: AsyncSession = Depends(get_db),
):
    group = await _get_or_404(db, group_id)
    if not group.telegram_chat_id:
        raise HTTPException(status_code=400, detail="This group has no Telegram chat id yet")
    cfg = await load_telegram_config()
    if not cfg.token:
        raise HTTPException(status_code=400, detail="No Telegram bot token saved (open Alerts first)")
    ok = await notifier.send(
        f"✅ <b>NetPulse</b> — test for group <b>{group.name}</b>\n"
        "Alerts for this group's devices will arrive here.",
        chat_id=group.telegram_chat_id,
    )
    if not ok:
        raise HTTPException(
            status_code=502,
            detail="Telegram rejected the message — check the chat id and that the bot is in that group",
        )
    return MessageOut(detail=f"Test message sent to '{group.name}'")
