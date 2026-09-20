"""Low-level, dependency-isolated network checks.

Every check returns a :class:`CheckOutcome` and never raises, so one bad
device can never take down the monitoring loop.
"""
from __future__ import annotations

import asyncio
import platform
import re
import time
from dataclasses import dataclass

import httpx

from ..config import settings
from ..models import CheckType

# ---------------------------------------------------------------------------
# Optional imports (kept isolated so a missing lib degrades gracefully)
# ---------------------------------------------------------------------------
try:  # ICMP via icmplib (raw sockets, needs privileges)
    from icmplib import async_ping as _icmp_async_ping
except Exception:  # pragma: no cover
    _icmp_async_ping = None

try:  # SNMP via pysnmp 6.x  (pysnmp.hlapi.asyncio)
    from pysnmp.hlapi.asyncio import (  # type: ignore
        CommunityData,
        ContextData,
        ObjectIdentity,
        ObjectType,
        SnmpEngine,
        UdpTransportTarget,
        getCmd as _snmp_get_cmd,
    )
    _SNMP_AVAILABLE = True
except Exception:  # pragma: no cover
    try:  # older/newer layout
        from pysnmp.hlapi.v3arch.asyncio import (  # type: ignore
            CommunityData,
            ContextData,
            ObjectIdentity,
            ObjectType,
            SnmpEngine,
            UdpTransportTarget,
            get_cmd as _snmp_get_cmd,
        )
        _SNMP_AVAILABLE = True
    except Exception:
        _SNMP_AVAILABLE = False

_SNMP_ENGINE = SnmpEngine() if _SNMP_AVAILABLE else None

_IS_WINDOWS = platform.system().lower().startswith("win")


@dataclass(slots=True)
class CheckOutcome:
    success: bool
    latency_ms: float | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# ICMP ping
# ---------------------------------------------------------------------------
async def _ping_subprocess(host: str, timeout: float) -> CheckOutcome:
    """Fallback ping using the OS `ping` binary (works without raw sockets)."""
    if _IS_WINDOWS:
        args = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), host]
    else:
        args = ["ping", "-c", "1", "-W", str(max(1, int(round(timeout)))), host]

    started = time.perf_counter()
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout + 2)
    except (asyncio.TimeoutError, FileNotFoundError, OSError) as exc:
        return CheckOutcome(False, error=f"ping failed: {exc}")

    elapsed_ms = (time.perf_counter() - started) * 1000
    text = (stdout or b"").decode(errors="ignore")
    if proc.returncode == 0:
        # try to read the real RTT from the output
        m = re.search(r"time[=<]\s*([\d.]+)\s*ms", text, re.IGNORECASE)
        latency = float(m.group(1)) if m else round(elapsed_ms, 2)
        return CheckOutcome(True, latency_ms=latency)
    return CheckOutcome(False, error="no reply")


async def check_ping(host: str, params: dict, timeout: float) -> CheckOutcome:
    count = int(params.get("count", 1))
    if _icmp_async_ping is not None:
        try:
            result = await _icmp_async_ping(
                host,
                count=count,
                timeout=timeout,
                privileged=settings.ping_privileged,
            )
            if result.is_alive:
                return CheckOutcome(True, latency_ms=round(result.avg_rtt, 2))
            return CheckOutcome(False, error="no ICMP reply")
        except PermissionError:
            # not allowed to open raw sockets -> fall back
            return await _ping_subprocess(host, timeout)
        except Exception:
            return await _ping_subprocess(host, timeout)
    return await _ping_subprocess(host, timeout)


# ---------------------------------------------------------------------------
# TCP connect
# ---------------------------------------------------------------------------
async def check_tcp(host: str, params: dict, timeout: float) -> CheckOutcome:
    port = params.get("port")
    if not port:
        return CheckOutcome(False, error="tcp check requires 'port'")
    started = time.perf_counter()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, int(port)), timeout=timeout
        )
        latency = (time.perf_counter() - started) * 1000
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return CheckOutcome(True, latency_ms=round(latency, 2))
    except asyncio.TimeoutError:
        return CheckOutcome(False, error=f"tcp {port} timeout")
    except (ConnectionRefusedError, OSError) as exc:
        return CheckOutcome(False, error=f"tcp {port}: {exc}")


# ---------------------------------------------------------------------------
# HTTP(S)
# ---------------------------------------------------------------------------
async def check_http(host: str, params: dict, timeout: float) -> CheckOutcome:
    url = params.get("url") or f"http://{host}/"
    expect_status = int(params.get("expect_status", 200))
    verify = bool(params.get("verify_tls", False))
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            timeout=timeout, verify=verify, follow_redirects=True
        ) as client:
            resp = await client.get(url)
        latency = (time.perf_counter() - started) * 1000
        ok = resp.status_code == expect_status
        return CheckOutcome(
            ok,
            latency_ms=round(latency, 2),
            error=None if ok else f"status {resp.status_code} != {expect_status}",
        )
    except httpx.HTTPError as exc:
        return CheckOutcome(False, error=f"http: {exc}")


# ---------------------------------------------------------------------------
# SNMP GET (v1 / v2c)
# ---------------------------------------------------------------------------
async def check_snmp(host: str, params: dict, timeout: float) -> CheckOutcome:
    if not _SNMP_AVAILABLE:
        return CheckOutcome(False, error="pysnmp not installed")

    community = params.get("community", "public")
    port = int(params.get("port", 161))
    oid = params.get("oid", "1.3.6.1.2.1.1.3.0")  # sysUpTime
    retries = int(params.get("retries", 0))

    started = time.perf_counter()
    try:
        if hasattr(UdpTransportTarget, "create"):  # newer asyncio API
            transport = await UdpTransportTarget.create(
                (host, port), timeout=timeout, retries=retries
            )
        else:  # pysnmp 6.2.x direct constructor
            transport = UdpTransportTarget((host, port), timeout=timeout, retries=retries)
        error_indication, error_status, _idx, var_binds = await _snmp_get_cmd(
            _SNMP_ENGINE,
            CommunityData(community, mpModel=1),  # v2c
            transport,
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
        )
        if error_indication:
            return CheckOutcome(False, error=str(error_indication))
        if error_status:
            return CheckOutcome(False, error=error_status.prettyPrint())
        latency = (time.perf_counter() - started) * 1000
        return CheckOutcome(True, latency_ms=round(latency, 2))
    except Exception as exc:  # pragma: no cover
        return CheckOutcome(False, error=f"snmp: {exc}")


# ---------------------------------------------------------------------------
# dispatcher
# ---------------------------------------------------------------------------
async def run_check(
    check_type: CheckType | str,
    host: str,
    params: dict | None,
    timeout: float,
) -> CheckOutcome:
    params = params or {}
    ctype = check_type.value if isinstance(check_type, CheckType) else str(check_type)
    try:
        if ctype == CheckType.ping.value:
            return await check_ping(host, params, timeout)
        if ctype == CheckType.tcp.value:
            return await check_tcp(host, params, timeout)
        if ctype == CheckType.http.value:
            return await check_http(host, params, timeout)
        if ctype == CheckType.snmp.value:
            return await check_snmp(host, params, timeout)
        return CheckOutcome(False, error=f"unknown check type: {ctype}")
    except Exception as exc:  # safety net
        return CheckOutcome(False, error=f"{ctype} error: {exc}")
