"""Trigger evaluation and alert lifecycle management.

Separated from the polling engine so the alert rules stay testable and the
engine stays focused on gathering data. ``AlertManager`` owns the
open/ack/resolve state machine (PROBLEM -> ACKNOWLEDGED -> RESOLVED).
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    Alert,
    AlertSeverity,
    AlertStatus,
    Device,
    Trigger,
    TriggerMetric,
    TriggerOperator,
    utcnow,
)

log = logging.getLogger("netpulse.alerts")

# metric name -> latest value source on a Device
_METRIC_ACCESSORS = {
    TriggerMetric.device_down: lambda d: 1.0 if d.status.value == "down" else 0.0,
    TriggerMetric.cpu: lambda d: d.last_cpu,
    TriggerMetric.ram: lambda d: d.last_ram,
    TriggerMetric.latency_ms: lambda d: d.last_latency_ms,
}


def _compare(operator: TriggerOperator, value: float, threshold: float) -> bool:
    if operator == TriggerOperator.gt:
        return value > threshold
    if operator == TriggerOperator.gte:
        return value >= threshold
    if operator == TriggerOperator.lt:
        return value < threshold
    if operator == TriggerOperator.lte:
        return value <= threshold
    if operator == TriggerOperator.eq:
        return value == threshold
    if operator == TriggerOperator.neq:
        return value != threshold
    return False


class AlertManager:
    """Create, acknowledge and resolve alerts."""

    async def open_alert(
        self,
        db: AsyncSession,
        *,
        device_id: int | None,
        name: str,
        severity: AlertSeverity,
        message: str,
        value: float | None = None,
        threshold: float | None = None,
        trigger_id: int | None = None,
    ) -> Alert | None:
        """Open a problem alert. Deduplicates: if an open alert of the same
        (device, name) already exists it is returned instead of duplicated."""
        existing = await db.execute(
            select(Alert).where(
                Alert.device_id == device_id,
                Alert.name == name,
                Alert.status.in_([AlertStatus.problem, AlertStatus.acknowledged]),
            )
        )
        alert = existing.scalar_one_or_none()
        if alert is not None:
            # refresh current value so the UI sees the latest reading
            alert.value = value
            alert.threshold = threshold
            return alert

        alert = Alert(
            device_id=device_id,
            trigger_id=trigger_id,
            name=name,
            severity=severity,
            status=AlertStatus.problem,
            message=message,
            value=value,
            threshold=threshold,
        )
        db.add(alert)
        await db.flush()
        return alert

    async def resolve(
        self,
        db: AsyncSession,
        *,
        device_id: int | None,
        name: str,
        by: str | None = None,
    ) -> None:
        """Resolve all open alerts matching (device, name)."""
        rows = (
            await db.execute(
                select(Alert).where(
                    Alert.device_id == device_id,
                    Alert.name == name,
                    Alert.status.in_([AlertStatus.problem, AlertStatus.acknowledged]),
                )
            )
        ).scalars().all()
        now = utcnow()
        for alert in rows:
            alert.status = AlertStatus.resolved
            alert.resolved_at = now
            alert.resolved_by = by

    async def acknowledge(
        self,
        db: AsyncSession,
        alert_id: int,
        *,
        by: str,
    ) -> Alert | None:
        alert = (
            await db.execute(
                select(Alert).where(
                    Alert.id == alert_id,
                    Alert.status.in_([AlertStatus.problem, AlertStatus.acknowledged]),
                )
            )
        ).scalar_one_or_none()
        if alert is None:
            return None
        alert.status = AlertStatus.acknowledged
        alert.acknowledged_at = utcnow()
        alert.acknowledged_by = by
        return alert

    async def evaluate_device_triggers(
        self,
        db: AsyncSession,
        device: Device,
        *,
        now: datetime | None = None,
    ) -> list[Alert]:
        """Evaluate all enabled triggers for a device and open alerts."""
        triggers = (
            await db.execute(
                select(Trigger).where(
                    Trigger.enabled.is_(True),
                    Trigger.device_id.in_([device.id, None]),
                )
            )
        ).scalars().all()

        opened: list[Alert] = []
        for trig in triggers:
            accessor = _METRIC_ACCESSORS.get(trig.metric)
            if accessor is None:
                continue  # interface/packet-loss metrics handled elsewhere
            value = accessor(device)
            if value is None:
                continue
            if _compare(trig.operator, float(value), trig.threshold):
                alert = await self.open_alert(
                    db,
                    device_id=device.id,
                    trigger_id=trig.id,
                    name=trig.name,
                    severity=trig.severity,
                    message=f"{trig.name} {trig.operator.value} {trig.threshold} "
                    f"(current {value:g})",
                    value=float(value),
                    threshold=trig.threshold,
                )
                if alert is not None:
                    opened.append(alert)
        return opened


alert_manager = AlertManager()
