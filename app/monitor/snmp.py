"""Async SNMP client (v1 / v2c / v3) built on pysnmp.

Everything is defensive: a failure returns an :class:`SnmpError` and never
crashes the monitoring loop.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("netpulse.snmp")

try:
    from pysnmp.hlapi.asyncio import (  # type: ignore
        CommunityData,
        ContextData,
        ObjectIdentity,
        ObjectType,
        SnmpEngine,
        UdpTransportTarget,
        UsmUserData,
        getCmd as _get_cmd,
        walkCmd as _walk_cmd,
        usmAesCfb128Protocol,
        usmDESPrivProtocol,
        usmHMACMD5AuthProtocol,
        usmHMACSHAAuthProtocol,
        usmNoAuthProtocol,
        usmNoPrivProtocol,
    )
    _SNMP_OK = True
except Exception:  # pragma: no cover - fallback for older/newer layouts
    try:
        from pysnmp.hlapi.v3arch.asyncio import (  # type: ignore
            CommunityData,
            ContextData,
            ObjectIdentity,
            ObjectType,
            SnmpEngine,
            UdpTransportTarget,
            UsmUserData,
            get_cmd as _get_cmd,
            walk_cmd as _walk_cmd,
            usmAesCfb128Protocol,
            usmDESPrivProtocol,
            usmHMACMD5AuthProtocol,
            usmHMACSHAAuthProtocol,
            usmNoAuthProtocol,
            usmNoPrivProtocol,
        )
        _SNMP_OK = True
    except Exception:
        _SNMP_OK = False

_ENGINE = SnmpEngine() if _SNMP_OK else None

_AUTH_PROTOCOLS = {
    "MD5": usmHMACMD5AuthProtocol if _SNMP_OK else None,
    "SHA": usmHMACSHAAuthProtocol if _SNMP_OK else None,
    "SHA1": usmHMACSHAAuthProtocol if _SNMP_OK else None,
    "NONE": usmNoAuthProtocol if _SNMP_OK else None,
}
_PRIV_PROTOCOLS = {
    "DES": usmDESPrivProtocol if _SNMP_OK else None,
    "AES": usmAesCfb128Protocol if _SNMP_OK else None,
    "AES128": usmAesCfb128Protocol if _SNMP_OK else None,
    "NONE": usmNoPrivProtocol if _SNMP_OK else None,
}


class SnmpError(Exception):
    """Raised when an SNMP operation cannot be completed."""


@dataclass(slots=True)
class SnmpAuth:
    version: str = "2c"  # "1" | "2c" | "3"
    community: str | None = "public"
    port: int = 161
    timeout: float = 3.0
    retries: int = 1
    # v3
    v3_user: str | None = None
    v3_auth_proto: str | None = "SHA"
    v3_auth_pass: str | None = None
    v3_priv_proto: str | None = "AES"
    v3_priv_pass: str | None = None

    def _auth_data(self):
        if self.version == "3":
            auth_proto = _AUTH_PROTOCOLS.get((self.v3_auth_proto or "SHA").upper(), usmNoAuthProtocol)
            priv_proto = _PRIV_PROTOCOLS.get((self.v3_priv_proto or "AES").upper(), usmNoPrivProtocol)
            return UsmUserData(
                self.v3_user,
                self.v3_auth_pass or None,
                self.v3_priv_pass or None,
                authProtocol=auth_proto,
                privProtocol=priv_proto,
            )
        mp_model = 0 if self.version == "1" else 1
        return CommunityData(self.community or "public", mpModel=mp_model)

    def _transport(self, host: str):
        return (host, int(self.port)), dict(timeout=self.timeout, retries=int(self.retries))


# --------------------------------------------------------------------- helpers
def _to_python(value: Any) -> Any:
    """Convert an SNMP value object to a native Python type."""
    if value is None:
        return None
    cls = type(value).__name__
    try:
        if cls in {"Integer", "Integer32", "Counter32", "Counter64", "Gauge32", "Unsigned32", "TimeTicks"}:
            return int(value)
        if cls in {"OctetString", "Bits"}:
            raw = bytes(value)
            try:
                return raw.decode("utf-8", errors="replace").strip()
            except Exception:
                return raw.hex()
        if cls == "ObjectIdentifier":
            return str(value.prettyPrint())
        if cls == "IpAddress":
            return str(value.prettyPrint())
        if cls in {"Null", "NoSuchObject", "NoSuchInstance", "EndOfMibView"}:
            return None
    except Exception:  # noqa: BLE001
        pass
    try:
        return value.prettyPrint()
    except Exception:  # noqa: BLE001
        return str(value)


async def _make_transport(host: str, auth: SnmpAuth):
    addr, kwargs = auth._transport(host)
    if hasattr(UdpTransportTarget, "create"):
        return await UdpTransportTarget.create(addr, **kwargs)
    return UdpTransportTarget(addr, **kwargs)


def _norm_oid(oid: str) -> str:
    return oid.lstrip(".")


# --------------------------------------------------------------------- public API
async def snmp_get(host: str, oids: list[str], auth: SnmpAuth) -> dict[str, Any]:
    """GET one or more OIDs. Returns {oid: value} (missing/failed OIDs are omitted)."""
    if not _SNMP_OK:
        raise SnmpError("pysnmp not available")
    if not oids:
        return {}
    try:
        transport = await _make_transport(host, auth)
        var_binds = [ObjectType(ObjectIdentity(_norm_oid(o))) for o in oids]
        error_indication, error_status, error_index, result = await _get_cmd(
            _ENGINE, auth._auth_data(), transport, ContextData(), *var_binds
        )
        if error_indication:
            raise SnmpError(str(error_indication))
        if error_status:
            raise SnmpError(error_status.prettyPrint())
        out: dict[str, Any] = {}
        for oid, value in result:
            out[str(oid)] = _to_python(value)
        return out
    except SnmpError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise SnmpError(f"snmp get failed: {exc}") from exc


async def snmp_get_one(host: str, oid: str, auth: SnmpAuth) -> Any:
    """Convenience GET for a single OID, returning just the value."""
    data = await snmp_get(host, [oid], auth)
    for value in data.values():
        return value
    return None


async def snmp_walk(
    host: str, base_oid: str, auth: SnmpAuth, *, max_rows: int = 256
) -> dict[str, Any]:
    """WALK a subtree. Returns {oid: value}."""
    if not _SNMP_OK:
        raise SnmpError("pysnmp not available")
    out: dict[str, Any] = {}
    try:
        transport = await _make_transport(host, auth)
        generator = _walk_cmd(
            _ENGINE,
            auth._auth_data(),
            transport,
            ContextData(),
            ObjectType(ObjectIdentity(_norm_oid(base_oid))),
            lexicographicMode=False,
        )
        async for error_indication, error_status, error_index, var_binds in generator:
            if error_indication:
                raise SnmpError(str(error_indication))
            if error_status:
                raise SnmpError(error_status.prettyPrint())
            for oid, value in var_binds:
                out[str(oid)] = _to_python(value)
                if len(out) >= max_rows:
                    return out
        return out
    except SnmpError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise SnmpError(f"snmp walk failed: {exc}") from exc


def snmp_available() -> bool:
    return _SNMP_OK
