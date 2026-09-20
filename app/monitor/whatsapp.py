"""WhatsApp notifications via CallMeBot (free, personal use).

Setup (one time, done by the operator in WhatsApp):
  1. Save the bot number  +34 623 91 22 04  in your contacts
  2. Send it the message:  "I allow callmebot to send me messages"
  3. You receive an API key -> paste phone + apikey into the dashboard

API: https://api.callmebot.com/whatsapp.php?phone=..&text=..&apikey=..
Config precedence: database (dashboard) overrides .env.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx
from sqlalchemy import select

from ..config import settings
from ..crypto import decrypt, encrypt

log = logging.getLogger("netpulse.whatsapp")

_API = "https://api.callmebot.com/whatsapp.php"

KEY_ENABLED = "whatsapp_enabled"
KEY_PHONE = "whatsapp_phone"
KEY_APIKEY = "whatsapp_apikey"

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    """Convert simple HTML (used by Telegram) into WhatsApp-friendly text."""
    text = text.replace("<b>", "*").replace("</b>", "*")
    text = text.replace("<code>", "`").replace("</code>", "`")
    text = text.replace("<br>", "\n").replace("<br/>", "\n")
    text = _TAG_RE.sub("", text)
    return text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


@dataclass(slots=True)
class WhatsAppConfig:
    enabled: bool = False
    phone: str = ""
    apikey: str = ""

    @property
    def ready(self) -> bool:
        return bool(self.enabled and self.phone and self.apikey)


async def load_whatsapp_config() -> WhatsAppConfig:
    cfg = WhatsAppConfig(
        enabled=bool(getattr(settings, "whatsapp_enabled", False)),
        phone=getattr(settings, "whatsapp_phone", "") or "",
        apikey=getattr(settings, "whatsapp_apikey", "") or "",
    )
    try:
        from ..database import SessionLocal
        from ..models import AppSetting

        async with SessionLocal() as db:
            rows = await db.execute(
                select(AppSetting).where(AppSetting.key.in_([KEY_ENABLED, KEY_PHONE, KEY_APIKEY]))
            )
            kv = {r.key: (r.value or "") for r in rows.scalars().all()}

        if KEY_ENABLED in kv:
            cfg.enabled = kv[KEY_ENABLED].lower() == "true"
        if KEY_PHONE in kv:
            cfg.phone = kv[KEY_PHONE]
        if kv.get(KEY_APIKEY):
            cfg.apikey = decrypt(kv[KEY_APIKEY]) or ""
    except Exception as exc:  # noqa: BLE001
        log.debug("could not load whatsapp config: %s", exc)
    return cfg


async def save_whatsapp_config(
    *, enabled: bool | None = None, phone: str | None = None, apikey: str | None = None
) -> None:
    from ..database import SessionLocal
    from ..models import AppSetting

    async with SessionLocal() as db:
        async def upsert(key: str, value: str | None) -> None:
            res = await db.execute(select(AppSetting).where(AppSetting.key == key))
            row = res.scalar_one_or_none()
            if row is None:
                db.add(AppSetting(key=key, value=value))
            else:
                row.value = value

        if enabled is not None:
            await upsert(KEY_ENABLED, "true" if enabled else "false")
        if phone is not None:
            await upsert(KEY_PHONE, phone)
        if apikey is not None and apikey != "":
            await upsert(KEY_APIKEY, encrypt(apikey))
        await db.commit()


class WhatsAppNotifier:
    async def send(self, text: str) -> bool:
        cfg = await load_whatsapp_config()
        if not cfg.ready:
            return False
        params = {"phone": cfg.phone, "text": strip_html(text), "apikey": cfg.apikey}
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(_API, params=params)
            if resp.status_code != 200:
                log.warning("CallMeBot error %s: %s", resp.status_code, resp.text[:200])
                return False
            return True
        except httpx.HTTPError as exc:
            log.warning("WhatsApp request failed: %s", exc)
            return False

    async def test(self) -> tuple[bool, str]:
        cfg = await load_whatsapp_config()
        if not cfg.ready:
            return False, "WhatsApp is disabled or not configured"
        ok = await self.send("✅ *NetPulse* WhatsApp notifications are working.")
        return ok, ("Test message sent" if ok else "Failed to send (check phone/apikey)")


whatsapp = WhatsAppNotifier()
