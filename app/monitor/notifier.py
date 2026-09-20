"""Telegram notification delivery.

Configuration precedence: **database (set from the dashboard) overrides .env**.
The bot token is stored encrypted (see app.crypto). This lets the operator
configure Telegram entirely from the web UI without touching .env or sharing
secrets with anyone.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from sqlalchemy import select

from ..config import settings
from ..crypto import decrypt, encrypt

log = logging.getLogger("netpulse.notifier")

_API_BASE = "https://api.telegram.org"

KEY_ENABLED = "telegram_enabled"
KEY_TOKEN = "telegram_bot_token"
KEY_CHAT = "telegram_chat_id"
KEY_DIGEST = "telegram_digest_enabled"
KEY_DIGEST_MIN = "telegram_digest_minutes"


@dataclass(slots=True)
class TelegramConfig:
    enabled: bool = False
    token: str = ""
    chat_id: str = ""
    digest_enabled: bool = False
    digest_minutes: int = 60

    @property
    def ready(self) -> bool:
        return bool(self.enabled and self.token and self.chat_id)


# --------------------------------------------------------------------- config
async def load_telegram_config() -> TelegramConfig:
    """Read config from the DB, falling back to .env defaults."""
    cfg = TelegramConfig(
        enabled=settings.telegram_enabled,
        token=settings.telegram_bot_token or "",
        chat_id=settings.telegram_chat_id or "",
    )
    try:
        from ..database import SessionLocal
        from ..models import AppSetting

        async with SessionLocal() as db:
            rows = await db.execute(
                select(AppSetting).where(
                    AppSetting.key.in_([KEY_ENABLED, KEY_TOKEN, KEY_CHAT, KEY_DIGEST, KEY_DIGEST_MIN])
                )
            )
            kv = {r.key: (r.value or "") for r in rows.scalars().all()}

        if KEY_ENABLED in kv:
            cfg.enabled = kv[KEY_ENABLED].lower() == "true"
        if kv.get(KEY_TOKEN):
            cfg.token = decrypt(kv[KEY_TOKEN]) or ""
        if KEY_CHAT in kv:
            cfg.chat_id = kv[KEY_CHAT]
        if KEY_DIGEST in kv:
            cfg.digest_enabled = kv[KEY_DIGEST].lower() == "true"
        if kv.get(KEY_DIGEST_MIN):
            try:
                cfg.digest_minutes = max(5, int(kv[KEY_DIGEST_MIN]))
            except ValueError:
                pass
    except Exception as exc:  # noqa: BLE001 - never break notifications
        log.debug("could not load telegram config from db: %s", exc)
    return cfg


async def save_telegram_config(
    *,
    enabled: bool | None = None,
    token: str | None = None,
    chat_id: str | None = None,
    digest_enabled: bool | None = None,
    digest_minutes: int | None = None,
) -> None:
    """Persist telegram settings (token is encrypted at rest)."""
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
        if token is not None and token != "":
            await upsert(KEY_TOKEN, encrypt(token))
        if chat_id is not None:
            await upsert(KEY_CHAT, chat_id)
        if digest_enabled is not None:
            await upsert(KEY_DIGEST, "true" if digest_enabled else "false")
        if digest_minutes is not None:
            await upsert(KEY_DIGEST_MIN, str(max(5, digest_minutes)))
        await db.commit()


# --------------------------------------------------------------------- sender
class TelegramNotifier:
    """Async wrapper around the Telegram Bot API."""

    async def send(self, text: str, *, parse_mode: str = "HTML") -> bool:
        cfg = await load_telegram_config()
        if not cfg.ready:
            log.debug("Telegram not configured/enabled; skipping message")
            return False
        url = f"{_API_BASE}/bot{cfg.token}/sendMessage"
        payload = {
            "chat_id": cfg.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                log.warning("Telegram API error %s: %s", resp.status_code, resp.text[:300])
                return False
            return True
        except httpx.HTTPError as exc:
            log.warning("Telegram request failed: %s", exc)
            return False

    # ------------------------------------------------------------ templates
    async def _deliver(self, html: str) -> bool:
        """Send to every configured channel (Telegram + WhatsApp)."""
        ok = await self.send(html)
        try:
            from .whatsapp import whatsapp
            await whatsapp.send(html)
        except Exception as exc:  # noqa: BLE001
            log.debug("whatsapp delivery skipped: %s", exc)
        return ok

    async def device_down(self, device_name: str, host: str, reason: str) -> bool:
        return await self._deliver(
            "🔴 <b>DEVICE DOWN</b>\n"
            f"<b>Name:</b> {_esc(device_name)}\n"
            f"<b>Host:</b> <code>{_esc(host)}</code>\n"
            f"<b>Reason:</b> {_esc(reason)}"
        )

    async def device_up(self, device_name: str, host: str, downtime: str) -> bool:
        return await self._deliver(
            "🟢 <b>DEVICE UP</b>\n"
            f"<b>Name:</b> {_esc(device_name)}\n"
            f"<b>Host:</b> <code>{_esc(host)}</code>\n"
            f"<b>Downtime:</b> {_esc(downtime)}"
        )

    async def high_latency(
        self, device_name: str, host: str, latency_ms: float, threshold_ms: float
    ) -> bool:
        return await self._deliver(
            "🟠 <b>HIGH LATENCY</b>\n"
            f"<b>Name:</b> {_esc(device_name)}\n"
            f"<b>Host:</b> <code>{_esc(host)}</code>\n"
            f"<b>Latency:</b> {latency_ms:.1f} ms (threshold {threshold_ms:.0f} ms)"
        )

    async def metric_alert(
        self, title: str, device_name: str, host: str, value: str, threshold: str
    ) -> bool:
        return await self._deliver(
            f"🟠 <b>{_esc(title).upper()}</b>\n"
            f"<b>Name:</b> {_esc(device_name)}\n"
            f"<b>Host:</b> <code>{_esc(host)}</code>\n"
            f"<b>Value:</b> {_esc(value)} (threshold {_esc(threshold)})"
        )

    async def status_digest(
        self,
        *,
        total: int,
        up: int,
        down: int,
        unknown: int,
        avg_latency_ms: float | None,
        down_devices: list[str],
    ) -> bool:
        icon = "🟢" if down == 0 else "🔴"
        lines = [
            f"{icon} <b>NetPulse Status</b>",
            f"Total: <b>{total}</b>   Up: <b>{up}</b>   Down: <b>{down}</b>   Unknown: {unknown}",
        ]
        if avg_latency_ms is not None:
            lines.append(f"Avg latency: {avg_latency_ms:.1f} ms")
        if down_devices:
            lines.append("")
            lines.append("<b>DOWN now:</b>")
            for name in down_devices[:15]:
                lines.append(f"• {_esc(name)}")
            if len(down_devices) > 15:
                lines.append(f"… and {len(down_devices) - 15} more")
        return await self.send("\n".join(lines))

    async def test(self) -> tuple[bool, str]:
        cfg = await load_telegram_config()
        if not cfg.ready:
            return False, "Telegram is disabled or not configured"
        ok = await self.send("✅ <b>NetPulse</b> Telegram notifications are working.")
        return ok, ("Test message sent" if ok else "Failed to send (check token/chat id)")


def _esc(value: object) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


notifier = TelegramNotifier()
