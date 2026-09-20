"""WireGuard helpers: status, key generation and config rendering.

The web app usually runs as a non-root user, so read-only status commands may
require the service account to have passwordless sudo for ``wg``/``wg-quick``.
Everything degrades gracefully when WireGuard is not present or not permitted.
"""
from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass, field

from ..config import settings


@dataclass(slots=True)
class Peer:
    public_key: str | None = None
    endpoint: str | None = None
    allowed_ips: str | None = None
    latest_handshake: str | None = None
    transfer_rx: str | None = None
    transfer_tx: str | None = None


@dataclass(slots=True)
class Status:
    enabled: bool
    interface: str
    installed: bool
    up: bool = False
    listen_port: int | None = None
    peers: list[Peer] = field(default_factory=list)
    message: str | None = None


def wg_installed() -> bool:
    return shutil.which("wg") is not None


async def _run(*args: str, timeout: float = 5.0) -> tuple[int, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, out.decode(errors="ignore"), err.decode(errors="ignore")
    except (FileNotFoundError, asyncio.TimeoutError, OSError) as exc:
        return 1, "", str(exc)


async def generate_private_key() -> str | None:
    if not wg_installed():
        return None
    code, out, _ = await _run("wg", "genkey")
    return out.strip() if code == 0 and out.strip() else None


async def derive_public_key(private_key: str) -> str | None:
    if not wg_installed():
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            "wg", "pubkey",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(private_key.encode()), timeout=5)
        return out.decode().strip() or None
    except (FileNotFoundError, asyncio.TimeoutError, OSError):
        return None


async def get_status() -> Status:
    iface = settings.wg_interface
    status = Status(enabled=settings.wg_enabled, interface=iface, installed=wg_installed())
    if not status.installed:
        status.message = "WireGuard (wg) is not installed on this host"
        return status

    code, out, err = await _run("wg", "show", iface, "dump")
    if code != 0:
        # try with sudo (passwordless) as a fallback
        code, out, err = await _run("sudo", "-n", "wg", "show", iface, "dump")
    if code != 0 or not out.strip():
        status.message = (err or "interface down or insufficient permission").strip()
        return status

    lines = [line for line in out.strip().splitlines() if line.strip()]
    if not lines:
        status.message = "no data"
        return status

    # first line: private_key  public_key  listen_port  fwmark
    first = lines[0].split("\t")
    status.up = True
    if len(first) >= 3 and first[2].isdigit():
        status.listen_port = int(first[2])

    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) < 8:
            continue
        status.peers.append(
            Peer(
                public_key=parts[0],
                endpoint=parts[2] or None,
                allowed_ips=parts[3] or None,
                latest_handshake=parts[4] if parts[4] != "0" else None,
                transfer_rx=parts[5],
                transfer_tx=parts[6],
            )
        )
    return status


def render_server_config(
    *,
    address: str,
    listen_port: int,
    private_key: str,
    peer_public_key: str,
    peer_allowed_ips: str,
    peer_endpoint: str | None = None,
    keepalive: int = 25,
) -> str:
    """Render a wg0.conf for the cloud side (office is the initiator)."""
    lines = [
        "[Interface]",
        f"Address = {address}",
        f"ListenPort = {listen_port}",
        f"PrivateKey = {private_key}",
        "",
        "# Office MikroTik peer",
        "[Peer]",
        f"PublicKey = {peer_public_key}",
        f"AllowedIPs = {peer_allowed_ips}",
    ]
    if peer_endpoint:
        lines.append(f"Endpoint = {peer_endpoint}")
    lines.append(f"PersistentKeepalive = {keepalive}")
    lines.append("")
    return "\n".join(lines)


def render_client_config(
    *,
    address: str,
    private_key: str,
    peer_public_key: str,
    peer_endpoint: str,
    peer_allowed_ips: str,
    keepalive: int = 25,
) -> str:
    """Render a client config for an agent / remote admin."""
    return "\n".join(
        [
            "[Interface]",
            f"Address = {address}",
            f"PrivateKey = {private_key}",
            "",
            "[Peer]",
            f"PublicKey = {peer_public_key}",
            f"Endpoint = {peer_endpoint}",
            f"AllowedIPs = {peer_allowed_ips}",
            f"PersistentKeepalive = {keepalive}",
            "",
        ]
    )
