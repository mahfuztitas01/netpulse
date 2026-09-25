"""The heart of NetPulse: an async scheduler that runs checks, collects SNMP
metrics, updates device state, records history and fires notifications."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from ..config import settings
from ..database import SessionLocal
from ..models import (
    Alert,
    AlertGroup,
    AlertSeverity,
    Check,
    CheckResult,
    Device,
    DeviceStatus,
    Event,
    EventSeverity,
    EventType,
    InterfaceSample,
    MetricSample,
    utcnow,
)
from .alerts import alert_manager
from .checks import run_check
from .metrics import collect_device_metrics
from .notifier import load_telegram_config, notifier

log = logging.getLogger("netpulse.engine")


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _humanize(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def _routing(device: Device) -> tuple[str | None, bool]:
    """Return (telegram_chat_id, whatsapp_enabled) for a device's alerts.

    A device assigned to an enabled alert group notifies that group's chat
    only. Everything else falls back to the default chat.
    """
    group = device.alert_group
    if group is not None and group.enabled:
        return (group.telegram_chat_id or None), bool(group.whatsapp_enabled)
    return None, True


class MonitorEngine:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._sem = asyncio.Semaphore(settings.max_concurrency)
        self._last_cleanup: datetime | None = None
        self._last_digest: datetime | None = None

    # ------------------------------------------------------------------ life
    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="netpulse-monitor")
        log.info("Monitor engine started (tick=%ss)", settings.monitor_tick_seconds)

    async def stop(self) -> None:
        self._stopping.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        log.info("Monitor engine stopped")

    async def check_now(self, device_id: int) -> None:
        await self._process_device(device_id, force_metrics=True)

    # ------------------------------------------------------------------ loop
    async def _run(self) -> None:
        while not self._stopping.is_set():
            started = asyncio.get_event_loop().time()
            try:
                await self._tick()
            except Exception:  # never let the loop die
                log.exception("Monitor tick failed")
            elapsed = asyncio.get_event_loop().time() - started
            delay = max(0.0, settings.monitor_tick_seconds - elapsed)
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    async def _tick(self) -> None:
        now = utcnow()
        async with SessionLocal() as db:
            result = await db.execute(
                select(Device).where(Device.enabled.is_(True)).options(selectinload(Device.checks))
            )
            devices = result.scalars().all()

        due_ids: list[int] = []
        for device in devices:
            last = _as_utc(device.last_checked_at)
            if last is None or (now - last).total_seconds() >= device.interval_seconds:
                due_ids.append(device.id)

        if due_ids:
            await asyncio.gather(*(self._process_device(did) for did in due_ids))

        await self._maybe_digest(now)
        await self._maybe_cleanup(now)

    # ------------------------------------------------------------ per-device
    async def _process_device(self, device_id: int, *, force_metrics: bool = False) -> None:
        async with self._sem:
            async with SessionLocal() as db:
                result = await db.execute(
                    select(Device)
                    .where(Device.id == device_id)
                    .options(selectinload(Device.checks), selectinload(Device.alert_group))
                )
                device = result.scalar_one_or_none()
                if device is None or not device.enabled:
                    return

                now = utcnow()
                await self._run_checks(db, device, now)
                await self._maybe_collect_metrics(db, device, now, force=force_metrics)
                await db.commit()

    async def _run_checks(self, db, device: Device, now: datetime) -> None:
        enabled_checks = [c for c in device.checks if c.enabled]
        if not enabled_checks:
            return

        outcomes = await asyncio.gather(
            *(run_check(c.type, device.host, c.params, device.timeout_seconds) for c in enabled_checks)
        )

        best_latency: float | None = None
        for check, outcome in zip(enabled_checks, outcomes):
            check.last_success = outcome.success
            check.last_latency_ms = outcome.latency_ms
            check.last_error = outcome.error
            db.add(
                CheckResult(
                    device_id=device.id,
                    check_id=check.id,
                    timestamp=now,
                    success=outcome.success,
                    latency_ms=outcome.latency_ms,
                    error=outcome.error,
                )
            )
            if outcome.success and outcome.latency_ms is not None:
                if best_latency is None or outcome.latency_ms < best_latency:
                    best_latency = outcome.latency_ms

        critical = [c for c in enabled_checks if c.critical] or enabled_checks
        flags = [c.last_success for c in critical]
        any_up = any(flags)
        all_down = all(not f for f in flags)

        if any_up:
            device.consecutive_successes += 1
            device.consecutive_failures = 0
        else:
            device.consecutive_failures += 1
            device.consecutive_successes = 0

        previous = device.status
        new_status = previous
        if all_down and device.consecutive_failures >= settings.down_failure_threshold:
            new_status = DeviceStatus.down
        elif any_up and device.consecutive_successes >= settings.up_success_threshold:
            new_status = DeviceStatus.up

        device.status = new_status
        device.last_latency_ms = best_latency
        device.last_checked_at = now

        await self._handle_status_alerts(db, device, previous, new_status, now, enabled_checks)

    async def _maybe_collect_metrics(self, db, device: Device, now: datetime, *, force: bool) -> None:
        if not device.snmp_enabled:
            return
        interval = device.metrics_interval_seconds or settings.metrics_interval_seconds
        last = _as_utc(device.last_metrics_at)
        if not force and last is not None and (now - last).total_seconds() < interval:
            return
        metrics = await collect_device_metrics(db, device)
        if metrics.errors:
            log.debug("metrics %s: %s", device.host, "; ".join(metrics.errors))
        await self._handle_metric_alerts(db, device, now)
        # evaluate custom threshold triggers (CPU/RAM/latency) after metrics
        await alert_manager.evaluate_device_triggers(db, device, now=now)

    # -------------------------------------------------------------- alerts
    async def _handle_status_alerts(
        self, db, device: Device, previous: DeviceStatus, current: DeviceStatus,
        now: datetime, checks: list[Check],
    ) -> None:
        first_state = previous in (DeviceStatus.unknown, None)
        errors = "; ".join(f"{c.name}: {c.last_error}" for c in checks if c.last_error) or "no response"
        chat_id, wa = _routing(device)

        if current == DeviceStatus.down and previous != DeviceStatus.down:
            device.last_down_at = now
            device.last_change_at = now
            event = Event(device_id=device.id, type=EventType.down, severity=EventSeverity.critical,
                          message=f"Device DOWN - {errors}", notified=False)
            db.add(event)
            # alert lifecycle: open a critical problem
            await alert_manager.open_alert(
                db, device_id=device.id, name=f"Device DOWN - {device.name}",
                severity=AlertSeverity.critical,
                message=f"{device.name} ({device.host}) is DOWN: {errors}",
            )
            if device.notify and not first_state:
                ok = await notifier.device_down(device.name, device.host, errors,
                                                chat_id=chat_id, whatsapp=wa)
                event.notified = bool(ok)
            log.warning("Device %s (%s) DOWN: %s", device.name, device.host, errors)

        elif current == DeviceStatus.up and previous == DeviceStatus.down:
            device.last_change_at = now
            down_at = _as_utc(device.last_down_at)
            downtime = _humanize(now - down_at) if down_at else "unknown"
            event = Event(device_id=device.id, type=EventType.up, severity=EventSeverity.info,
                          message=f"Device UP (downtime {downtime})", notified=False)
            db.add(event)
            # resolve the open down alert
            await alert_manager.resolve(db, device_id=device.id,
                                        name=f"Device DOWN - {device.name}", by="system")
            if device.notify:
                ok = await notifier.device_up(device.name, device.host, downtime,
                                              chat_id=chat_id, whatsapp=wa)
                event.notified = bool(ok)
            await self._resolve_open_events(db, device.id, now)
            log.info("Device %s (%s) UP (downtime %s)", device.name, device.host, downtime)

        elif current == DeviceStatus.down and previous == DeviceStatus.down and device.notify:
            if await self._cooldown_elapsed(db, device.id, EventType.down, settings.alert_renotify_minutes, now):
                await notifier.device_down(device.name, device.host, f"still down - {errors}",
                                           chat_id=chat_id, whatsapp=wa)
                db.add(Event(device_id=device.id, type=EventType.down, severity=EventSeverity.critical,
                             message=f"Device still DOWN - {errors}", notified=True))

        if current == DeviceStatus.up:
            threshold = device.latency_threshold_ms
            if threshold is None:
                thresholds = [c.latency_threshold_ms for c in checks if c.latency_threshold_ms]
                threshold = min(thresholds) if thresholds else None
            if (threshold is not None and device.last_latency_ms is not None
                    and device.last_latency_ms > threshold):
                if await self._cooldown_elapsed(db, device.id, EventType.high_latency,
                                                settings.latency_alert_cooldown_minutes, now):
                    db.add(Event(device_id=device.id, type=EventType.high_latency,
                                 severity=EventSeverity.warning,
                                 message=f"High latency {device.last_latency_ms:.1f} ms (threshold {threshold:.0f} ms)",
                                 notified=True))
                    if device.notify:
                        await notifier.high_latency(device.name, device.host, device.last_latency_ms,
                                                    threshold, chat_id=chat_id, whatsapp=wa)

    async def _handle_metric_alerts(self, db, device: Device, now: datetime) -> None:
        chat_id, wa = _routing(device)
        # CPU
        cpu_threshold = device.cpu_threshold or settings.cpu_threshold_percent
        if device.last_cpu is not None and cpu_threshold and device.last_cpu >= cpu_threshold:
            if await self._cooldown_elapsed(db, device.id, EventType.high_cpu,
                                            settings.latency_alert_cooldown_minutes, now):
                db.add(Event(device_id=device.id, type=EventType.high_cpu, severity=EventSeverity.warning,
                             message=f"High CPU {device.last_cpu:.0f}% (threshold {cpu_threshold:.0f}%)",
                             notified=True))
                if device.notify:
                    await notifier.metric_alert("High CPU", device.name, device.host,
                                                f"{device.last_cpu:.0f}%", f"{cpu_threshold:.0f}%",
                                                chat_id=chat_id, whatsapp=wa)

        # RAM
        ram_threshold = device.ram_threshold or settings.ram_threshold_percent
        if device.last_ram is not None and ram_threshold and device.last_ram >= ram_threshold:
            if await self._cooldown_elapsed(db, device.id, EventType.high_ram,
                                            settings.latency_alert_cooldown_minutes, now):
                db.add(Event(device_id=device.id, type=EventType.high_ram, severity=EventSeverity.warning,
                             message=f"High RAM {device.last_ram:.0f}% (threshold {ram_threshold:.0f}%)",
                             notified=True))
                if device.notify:
                    await notifier.metric_alert("High RAM", device.name, device.host,
                                                f"{device.last_ram:.0f}%", f"{ram_threshold:.0f}%",
                                                chat_id=chat_id, whatsapp=wa)

    # ------------------------------------------------------- alert helpers
    @staticmethod
    async def _resolve_open_events(db, device_id: int, now: datetime) -> None:
        result = await db.execute(
            select(Event).where(Event.device_id == device_id, Event.type == EventType.down,
                                Event.resolved_at.is_(None))
        )
        for event in result.scalars().all():
            event.resolved_at = now

    @staticmethod
    async def _cooldown_elapsed(db, device_id: int, etype: EventType, minutes: int, now: datetime) -> bool:
        result = await db.execute(
            select(Event).where(Event.device_id == device_id, Event.type == etype)
            .order_by(Event.created_at.desc()).limit(1)
        )
        event = result.scalar_one_or_none()
        if event is None:
            return True
        created = _as_utc(event.created_at)
        return created is None or (now - created) >= timedelta(minutes=minutes)

    # ------------------------------------------------------------- digest
    async def _maybe_digest(self, now: datetime) -> None:
        """Periodically post a per-group status summary to Telegram/WhatsApp.

        Each alert group gets a digest scoped to *its own* devices, so client01
        never sees client02's status.
        """
        try:
            cfg = await load_telegram_config()
        except Exception:
            return
        if not (cfg.enabled and cfg.token and cfg.digest_enabled):
            return
        last = self._last_digest
        if last is not None and (now - last) < timedelta(minutes=cfg.digest_minutes):
            return
        self._last_digest = now

        async with SessionLocal() as db:
            devices = (await db.execute(
                select(Device).options(selectinload(Device.alert_group))
            )).scalars().all()
            groups = (await db.execute(select(AlertGroup))).scalars().all()
        group_by_id = {g.id: g for g in groups}

        buckets: dict[int | None, list[Device]] = {}
        for d in devices:
            gid = d.alert_group_id if (d.alert_group and d.alert_group.enabled) else None
            buckets.setdefault(gid, []).append(d)

        for gid, devs in buckets.items():
            group = group_by_id.get(gid) if gid is not None else None
            chat_id = (group.telegram_chat_id or None) if group else None
            wa = bool(group.whatsapp_enabled) if group else True
            title = f"NetPulse — {group.name}" if group else "NetPulse Status"

            total = len(devs)
            up = sum(1 for d in devs if d.status == DeviceStatus.up)
            down = sum(1 for d in devs if d.status == DeviceStatus.down)
            unknown = total - up - down
            lats = [d.last_latency_ms for d in devs if d.last_latency_ms is not None]
            avg = (sum(lats) / len(lats)) if lats else None
            down_names = [d.name for d in devs if d.status == DeviceStatus.down]

            ok = await notifier.status_digest(
                total=total, up=up, down=down, unknown=unknown,
                avg_latency_ms=avg, down_devices=down_names,
                title=title, chat_id=chat_id, whatsapp=wa,
            )
            log.info("status digest sent=%s group=%s (up=%s down=%s)",
                     ok, group.name if group else "default", up, down)

    # ----------------------------------------------------------- retention
    async def _maybe_cleanup(self, now: datetime) -> None:
        last = self._last_cleanup
        if last is not None and (now - last) < timedelta(hours=6):
            return
        self._last_cleanup = now
        async with SessionLocal() as db:
            if settings.history_retention_days > 0:
                cutoff = now - timedelta(days=settings.history_retention_days)
                await db.execute(delete(CheckResult).where(CheckResult.timestamp < cutoff))
            if settings.metrics_retention_days > 0:
                mcutoff = now - timedelta(days=settings.metrics_retention_days)
                await db.execute(delete(MetricSample).where(MetricSample.timestamp < mcutoff))
                await db.execute(delete(InterfaceSample).where(InterfaceSample.timestamp < mcutoff))
            await db.commit()
        log.info("Pruned history (checks=%sd, metrics=%sd)",
                 settings.history_retention_days, settings.metrics_retention_days)


engine = MonitorEngine()
