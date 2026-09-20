"""System endpoints: WireGuard status, vendor profiles, health/version."""
from __future__ import annotations

import platform
import sys

from fastapi import APIRouter, Depends, HTTPException

from .. import __version__
from ..config import settings
from ..deps import get_current_user_ready
from ..models import User
from ..schemas import (
    MessageOut,
    TelegramSettingsIn,
    TelegramSettingsOut,
    VendorProfileOut,
    WhatsAppSettingsIn,
    WhatsAppSettingsOut,
    WireGuardPeer,
    WireGuardStatus,
)
from ..monitor.notifier import load_telegram_config, notifier, save_telegram_config
from ..monitor.whatsapp import (
    load_whatsapp_config,
    save_whatsapp_config,
    whatsapp,
)
from ..vendors import list_profiles, reload_profiles
from ..wireguard import manager as wg

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/info")
async def system_info(_: User = Depends(get_current_user_ready)):
    return {
        "app": settings.app_name,
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "database": "sqlite" if settings.is_sqlite else "postgres",
        "monitor_tick_seconds": settings.monitor_tick_seconds,
        "metrics_interval_seconds": settings.metrics_interval_seconds,
        "telegram_enabled": bool(settings.telegram_enabled),
        "wireguard_enabled": settings.wg_enabled,
    }


@router.get("/vendors", response_model=list[VendorProfileOut])
async def vendor_profiles(_: User = Depends(get_current_user_ready)):
    out: list[VendorProfileOut] = []
    for profile in list_profiles():
        out.append(
            VendorProfileOut(
                key=profile.get("key", ""),
                label=profile.get("label", profile.get("key", "")),
                cpu=(profile.get("cpu") or {}).get("oid"),
                ram=(profile.get("ram") or {}).get("oid"),
                description=(profile.get("description") or "").strip() or None,
            )
        )
    return sorted(out, key=lambda p: p.key)


@router.post("/vendors/reload", response_model=MessageOut)
async def reload_vendor_profiles(_: User = Depends(get_current_user_ready)):
    reload_profiles()
    return MessageOut(detail="Vendor profiles reloaded")


@router.get("/wireguard", response_model=WireGuardStatus)
async def wireguard_status(_: User = Depends(get_current_user_ready)):
    status = await wg.get_status()
    return WireGuardStatus(
        enabled=status.enabled,
        interface=status.interface,
        installed=status.installed,
        up=status.up,
        listen_port=status.listen_port,
        message=status.message,
        peers=[
            WireGuardPeer(
                public_key=p.public_key,
                endpoint=p.endpoint,
                allowed_ips=p.allowed_ips,
                latest_handshake=p.latest_handshake,
                transfer_rx=p.transfer_rx,
                transfer_tx=p.transfer_tx,
            )
            for p in status.peers
        ],
    )


@router.get("/telegram", response_model=TelegramSettingsOut)
async def telegram_settings(_: User = Depends(get_current_user_ready)):
    cfg = await load_telegram_config()
    return TelegramSettingsOut(
        enabled=cfg.enabled,
        chat_id=cfg.chat_id or None,
        has_token=bool(cfg.token),
        ready=cfg.ready,
        digest_enabled=cfg.digest_enabled,
        digest_minutes=cfg.digest_minutes,
    )


@router.put("/telegram", response_model=TelegramSettingsOut)
async def update_telegram_settings(
    payload: TelegramSettingsIn,
    _: User = Depends(get_current_user_ready),
):
    await save_telegram_config(
        enabled=payload.enabled,
        token=payload.bot_token,
        chat_id=payload.chat_id,
        digest_enabled=payload.digest_enabled,
        digest_minutes=payload.digest_minutes,
    )
    cfg = await load_telegram_config()
    return TelegramSettingsOut(
        enabled=cfg.enabled,
        chat_id=cfg.chat_id or None,
        has_token=bool(cfg.token),
        ready=cfg.ready,
        digest_enabled=cfg.digest_enabled,
        digest_minutes=cfg.digest_minutes,
    )


@router.post("/telegram/test", response_model=MessageOut)
async def test_telegram(_: User = Depends(get_current_user_ready)):
    ok, msg = await notifier.test()
    return MessageOut(detail=msg)


@router.get("/telegram/chats")
async def telegram_chats(_: User = Depends(get_current_user_ready)):
    """List chats the bot has recently seen (so you can copy a GROUP chat id)."""
    cfg = await load_telegram_config()
    if not cfg.token:
        raise HTTPException(status_code=400, detail="Save the bot token first")
    import httpx

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"https://api.telegram.org/bot{cfg.token}/getUpdates")
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Telegram request failed: {exc}")

    if not data.get("ok"):
        raise HTTPException(status_code=400, detail=data.get("description", "Telegram error"))

    chats: dict[int, dict] = {}
    for upd in data.get("result", []):
        msg = (
            upd.get("message")
            or upd.get("edited_message")
            or upd.get("channel_post")
            or upd.get("my_chat_member")
            or upd.get("chat_member")
            or {}
        )
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid is None:
            continue
        chats[cid] = {
            "id": cid,
            "type": chat.get("type"),
            "title": chat.get("title") or chat.get("username") or chat.get("first_name") or "",
        }
    return {
        "chats": list(chats.values()),
        "hint": (
            "Group id starts with -100 (e.g. -1001234567890). "
            "Add the bot to your group, send a message there, then refresh this list."
        ),
    }


@router.get("/whatsapp", response_model=WhatsAppSettingsOut)
async def whatsapp_settings(_: User = Depends(get_current_user_ready)):
    cfg = await load_whatsapp_config()
    return WhatsAppSettingsOut(
        enabled=cfg.enabled,
        phone=cfg.phone or None,
        has_apikey=bool(cfg.apikey),
        ready=cfg.ready,
    )


@router.put("/whatsapp", response_model=WhatsAppSettingsOut)
async def update_whatsapp_settings(
    payload: WhatsAppSettingsIn,
    _: User = Depends(get_current_user_ready),
):
    await save_whatsapp_config(
        enabled=payload.enabled,
        phone=payload.phone,
        apikey=payload.apikey,
    )
    cfg = await load_whatsapp_config()
    return WhatsAppSettingsOut(
        enabled=cfg.enabled,
        phone=cfg.phone or None,
        has_apikey=bool(cfg.apikey),
        ready=cfg.ready,
    )


@router.post("/whatsapp/test", response_model=MessageOut)
async def test_whatsapp(_: User = Depends(get_current_user_ready)):
    ok, msg = await whatsapp.test()
    return MessageOut(detail=msg)
