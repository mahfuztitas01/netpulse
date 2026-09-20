"""SNMP metrics collection: CPU, RAM, uptime and interface traffic.

Uses the device's vendor profile (see ``app/vendors``) and stores results in
``metric_samples`` / ``interface_samples``. All failures are non-fatal.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..crypto import decrypt
from ..models import Device, Interface, InterfaceSample, MetricSample, utcnow
from ..vendors import get_profile
from .snmp import SnmpAuth, SnmpError, snmp_available, snmp_get, snmp_walk

log = logging.getLogger("netpulse.metrics")

# HOST-RESOURCES-MIB
_HR_STORAGE_DESCR = "1.3.6.1.2.1.25.2.3.1.3"
_HR_STORAGE_ALLOC = "1.3.6.1.2.1.25.2.3.1.4"
_HR_STORAGE_SIZE = "1.3.6.1.2.1.25.2.3.1.5"
_HR_STORAGE_USED = "1.3.6.1.2.1.25.2.3.1.6"
_HR_STORAGE_TYPE = "1.3.6.1.2.1.25.2.1.2"  # hrStorageRam


@dataclass(slots=True)
class InterfaceReading:
    if_index: int
    if_name: str | None = None
    if_alias: str | None = None
    if_type: int | None = None
    oper_status: int | None = None
    speed_bps: float | None = None
    in_octets: float | None = None
    out_octets: float | None = None


@dataclass(slots=True)
class MetricsResult:
    cpu: float | None = None
    ram: float | None = None
    uptime_s: float | None = None
    interfaces: list[InterfaceReading] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# --------------------------------------------------------------------- helpers
def _index(oid: str, base: str) -> int | None:
    oid = oid.lstrip(".")
    base = base.lstrip(".")
    if oid.startswith(base + "."):
        suffix = oid[len(base) + 1:]
        try:
            return int(suffix.split(".")[0])
        except ValueError:
            return None
    return None


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def auth_for_device(device: Device) -> SnmpAuth:
    return SnmpAuth(
        version=(device.snmp_version.value if device.snmp_version else "2c"),
        community=decrypt(device.snmp_community_enc) or "public",
        port=device.snmp_port or settings.snmp_default_port,
        timeout=device.timeout_seconds or settings.snmp_timeout,
        retries=settings.snmp_retries,
        v3_user=device.snmp_v3_user,
        v3_auth_proto=device.snmp_v3_auth_proto,
        v3_auth_pass=decrypt(device.snmp_v3_auth_pass_enc),
        v3_priv_proto=device.snmp_v3_priv_proto,
        v3_priv_pass=decrypt(device.snmp_v3_priv_pass_enc),
    )


# --------------------------------------------------------------------- CPU
async def _read_cpu(host: str, auth: SnmpAuth, profile: dict) -> float | None:
    cfg = (profile or {}).get("cpu") or {}
    for candidate in (cfg, cfg.get("fallback")):
        if not candidate:
            continue
        mode = candidate.get("mode")
        try:
            if mode == "percent":
                value = _to_float((await snmp_get(host, [candidate["oid"]], auth)).get(
                    candidate["oid"].lstrip(".")))
                if value is None:
                    # dict key may carry the leading dot variant; try by value
                    data = await snmp_get(host, [candidate["oid"]], auth)
                    value = _to_float(next(iter(data.values()), None))
                if value is not None:
                    return max(0.0, min(100.0, value))
            elif mode == "walk_avg":
                data = await snmp_walk(host, candidate["oid"], auth, max_rows=64)
                nums = [v for v in (_to_float(x) for x in data.values()) if v is not None]
                if nums:
                    return max(0.0, min(100.0, sum(nums) / len(nums)))
        except SnmpError:
            continue
    return None


# --------------------------------------------------------------------- RAM
async def _ram_host_resources(host: str, auth: SnmpAuth) -> float | None:
    descr = await snmp_walk(host, _HR_STORAGE_DESCR, auth, max_rows=64)
    alloc = await snmp_walk(host, _HR_STORAGE_ALLOC, auth, max_rows=64)
    size = await snmp_walk(host, _HR_STORAGE_SIZE, auth, max_rows=64)
    used = await snmp_walk(host, _HR_STORAGE_USED, auth, max_rows=64)
    types = await snmp_walk(host, _HR_STORAGE_TYPE, auth, max_rows=64)

    best: float | None = None
    best_size = -1.0
    for oid, desc in descr.items():
        idx = _index(oid, _HR_STORAGE_DESCR)
        if idx is None:
            continue
        is_ram = "ram" in str(desc).lower() or "physical" in str(desc).lower()
        if not is_ram:
            for toid, tval in types.items():
                if _index(toid, _HR_STORAGE_TYPE) == idx and "25.2.1.2" in str(tval):
                    is_ram = True
                    break
        if not is_ram:
            continue

        def pick(base: str, table: dict):
            for oid2, val in table.items():
                if _index(oid2, base) == idx:
                    return _to_float(val)
            return None

        units = pick(_HR_STORAGE_ALLOC, alloc) or 1.0
        total = pick(_HR_STORAGE_SIZE, size)
        usedv = pick(_HR_STORAGE_USED, used)
        if total and usedv is not None and total > 0:
            total_bytes = total * units
            if total_bytes > best_size:
                best_size = total_bytes
                best = max(0.0, min(100.0, usedv / total * 100.0))
    return best


async def _read_ram(host: str, auth: SnmpAuth, profile: dict) -> float | None:
    cfg = (profile or {}).get("ram") or {}
    for candidate in (cfg, cfg.get("fallback")):
        if not candidate:
            continue
        mode = candidate.get("mode")
        try:
            if mode == "percent":
                data = await snmp_get(host, [candidate["oid"]], auth)
                value = _to_float(next(iter(data.values()), None))
                if value is not None:
                    return max(0.0, min(100.0, value))
            elif mode == "free_total":
                data = await snmp_get(host, [candidate["total_oid"], candidate["free_oid"]], auth)
                vals = list(data.values())
                if len(vals) == 2:
                    total, free = _to_float(vals[0]), _to_float(vals[1])
                    if total and free is not None and total > 0:
                        return max(0.0, min(100.0, (total - free) / total * 100.0))
            elif mode == "used_free":
                data = await snmp_get(host, [candidate["used_oid"], candidate["free_oid"]], auth)
                vals = list(data.values())
                if len(vals) == 2:
                    usedv, free = _to_float(vals[0]), _to_float(vals[1])
                    if usedv is not None and free is not None and (usedv + free) > 0:
                        return max(0.0, min(100.0, usedv / (usedv + free) * 100.0))
            elif mode == "used_free_walk":
                used_tbl = await snmp_walk(host, candidate["used_oid"], auth, max_rows=32)
                free_tbl = await snmp_walk(host, candidate["free_oid"], auth, max_rows=32)
                best_pct, best_total = None, -1.0
                for oid, usedv in used_tbl.items():
                    idx = _index(oid, candidate["used_oid"])
                    if idx is None:
                        continue
                    free = None
                    for oid2, fv in free_tbl.items():
                        if _index(oid2, candidate["free_oid"]) == idx:
                            free = _to_float(fv)
                            break
                    u = _to_float(usedv)
                    if u is None or free is None:
                        continue
                    total = u + free
                    if total > best_total:
                        best_total = total
                        best_pct = max(0.0, min(100.0, u / total * 100.0))
                if best_pct is not None:
                    return best_pct
            elif mode == "host_resources":
                value = await _ram_host_resources(host, auth)
                if value is not None:
                    return value
        except SnmpError:
            continue
    return None


# --------------------------------------------------------------------- uptime
async def _read_uptime(host: str, auth: SnmpAuth, profile: dict) -> float | None:
    oid = ((profile or {}).get("uptime") or {}).get("oid", "1.3.6.1.2.1.1.3.0")
    try:
        data = await snmp_get(host, [oid], auth)
        value = _to_float(next(iter(data.values()), None))
        if value is not None:
            return value / 100.0  # TimeTicks (1/100 s) -> seconds
    except SnmpError:
        pass
    return None


# --------------------------------------------------------------------- interfaces
async def _read_interfaces(host: str, auth: SnmpAuth, profile: dict) -> list[InterfaceReading]:
    iface = (profile or {}).get("interfaces") or {}
    name_oid = iface.get("name_oid", "1.3.6.1.2.1.31.1.1.1.1")
    alias_oid = iface.get("alias_oid", "1.3.6.1.2.1.31.1.1.1.18")
    type_oid = iface.get("type_oid", "1.3.6.1.2.1.2.2.1.3")
    oper_oid = iface.get("oper_oid", "1.3.6.1.2.1.2.2.1.8")
    speed_oid = iface.get("speed_oid", "1.3.6.1.2.1.31.1.1.1.15")
    in_oid = iface.get("in_oid", "1.3.6.1.2.1.31.1.1.1.6")
    out_oid = iface.get("out_oid", "1.3.6.1.2.1.31.1.1.1.10")
    in_oid32 = iface.get("in_oid32", "1.3.6.1.2.1.2.2.1.10")
    out_oid32 = iface.get("out_oid32", "1.3.6.1.2.1.2.2.1.16")

    max_rows = settings.snmp_max_interfaces
    readings: dict[int, InterfaceReading] = {}

    def ensure(idx: int) -> InterfaceReading:
        if idx not in readings:
            readings[idx] = InterfaceReading(if_index=idx)
        return readings[idx]

    try:
        names = await snmp_walk(host, name_oid, auth, max_rows=max_rows)
    except SnmpError:
        names = {}
    for oid, value in names.items():
        idx = _index(oid, name_oid)
        if idx is not None:
            ensure(idx).if_name = str(value) if value is not None else None

    for base, attr in ((alias_oid, "if_alias"), (oper_oid, "oper_status"),
                       (speed_oid, "speed_bps"), (type_oid, "if_type")):
        try:
            table = await snmp_walk(host, base, auth, max_rows=max_rows)
        except SnmpError:
            continue
        for oid, value in table.items():
            idx = _index(oid, base)
            if idx is None:
                continue
            item = ensure(idx)
            if attr == "if_alias":
                item.if_alias = str(value) if value is not None else None
            elif attr == "speed_bps":
                mbps = _to_float(value)
                item.speed_bps = mbps * 1_000_000 if mbps else None
            else:
                num = _to_float(value)
                setattr(item, attr, int(num) if num is not None else None)

    # 64-bit counters, fall back to 32-bit
    try:
        in_tbl = await snmp_walk(host, in_oid, auth, max_rows=max_rows)
        out_tbl = await snmp_walk(host, out_oid, auth, max_rows=max_rows)
    except SnmpError:
        in_tbl = out_tbl = {}
    if not in_tbl:
        try:
            in_tbl = await snmp_walk(host, in_oid32, auth, max_rows=max_rows)
            out_tbl = await snmp_walk(host, out_oid32, auth, max_rows=max_rows)
        except SnmpError:
            in_tbl = out_tbl = {}

    for oid, value in in_tbl.items():
        idx = _index(oid, in_oid) or _index(oid, in_oid32)
        if idx is not None:
            ensure(idx).in_octets = _to_float(value)
    for oid, value in out_tbl.items():
        idx = _index(oid, out_oid) or _index(oid, out_oid32)
        if idx is not None:
            ensure(idx).out_octets = _to_float(value)

    return list(readings.values())


# --------------------------------------------------------------------- orchestration
async def collect_device_metrics(db: AsyncSession, device: Device) -> MetricsResult:
    """Collect CPU/RAM/uptime/interfaces for one device and persist the samples."""
    result = MetricsResult()
    if not device.snmp_enabled or not snmp_available():
        return result

    profile = get_profile(device.vendor) or get_profile("generic")
    auth = auth_for_device(device)
    host = device.host
    now = utcnow()

    try:
        result.cpu = await _read_cpu(host, auth, profile)
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"cpu: {exc}")
    try:
        result.ram = await _read_ram(host, auth, profile)
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"ram: {exc}")
    try:
        result.uptime_s = await _read_uptime(host, auth, profile)
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"uptime: {exc}")
    try:
        result.interfaces = await _read_interfaces(host, auth, profile)
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"interfaces: {exc}")

    if result.cpu is not None:
        db.add(MetricSample(device_id=device.id, metric="cpu", value=result.cpu, timestamp=now))
        device.last_cpu = result.cpu
    if result.ram is not None:
        db.add(MetricSample(device_id=device.id, metric="ram", value=result.ram, timestamp=now))
        device.last_ram = result.ram
    if result.uptime_s is not None:
        db.add(MetricSample(device_id=device.id, metric="uptime", value=result.uptime_s, timestamp=now))

    await _persist_interfaces(db, device, result.interfaces, now)
    device.last_metrics_at = now
    return result


async def _persist_interfaces(
    db: AsyncSession, device: Device, readings: list[InterfaceReading], now: datetime
) -> None:
    if not readings:
        return
    existing = await db.execute(select(Interface).where(Interface.device_id == device.id))
    by_index = {i.if_index: i for i in existing.scalars().all()}
    pending_samples: list[tuple[Interface, float | None, float | None]] = []

    for reading in readings:
        iface = by_index.get(reading.if_index)
        if iface is None:
            iface = Interface(device_id=device.id, if_index=reading.if_index)
            db.add(iface)
            by_index[reading.if_index] = iface

        iface.if_name = reading.if_name or iface.if_name
        iface.if_alias = reading.if_alias or iface.if_alias
        iface.if_type = reading.if_type if reading.if_type is not None else iface.if_type
        iface.oper_status = reading.oper_status if reading.oper_status is not None else iface.oper_status
        iface.speed_bps = reading.speed_bps or iface.speed_bps

        # compute rate from previous counters
        prev_ts = iface.last_polled_at
        prev_in, prev_out = iface.last_in_octets, iface.last_out_octets
        elapsed = (now - prev_ts).total_seconds() if prev_ts else None

        in_bps = out_bps = None
        if elapsed and elapsed > 0:
            if reading.in_octets is not None and prev_in is not None and reading.in_octets >= prev_in:
                in_bps = (reading.in_octets - prev_in) * 8 / elapsed
            if reading.out_octets is not None and prev_out is not None and reading.out_octets >= prev_out:
                out_bps = (reading.out_octets - prev_out) * 8 / elapsed

        if reading.in_octets is not None:
            iface.last_in_octets = reading.in_octets
        if reading.out_octets is not None:
            iface.last_out_octets = reading.out_octets
        iface.last_in_bps = in_bps if in_bps is not None else iface.last_in_bps
        iface.last_out_bps = out_bps if out_bps is not None else iface.last_out_bps
        iface.last_polled_at = now

        if in_bps is not None or out_bps is not None:
            pending_samples.append((iface, in_bps, out_bps))

    if pending_samples:
        await db.flush()  # assign ids to any newly created interfaces
        for iface, in_bps, out_bps in pending_samples:
            db.add(
                InterfaceSample(
                    device_id=device.id,
                    interface_id=iface.id,
                    timestamp=now,
                    in_bps=in_bps,
                    out_bps=out_bps,
                )
            )
