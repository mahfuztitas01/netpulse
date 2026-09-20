"""Symmetric encryption for sensitive values stored in the database
(e.g. SNMP community strings / v3 credentials).

The key is derived from ``SECRET_KEY`` so no extra secret has to be managed.
Values are stored as ``enc:<fernet-token>``; anything without the prefix is
treated as legacy plaintext and returned as-is.
"""
from __future__ import annotations

import base64
import hashlib

from .config import settings

_PREFIX = "enc:"

try:
    from cryptography.fernet import Fernet, InvalidToken

    _FERNET_AVAILABLE = True
except Exception:  # pragma: no cover
    _FERNET_AVAILABLE = False
    InvalidToken = Exception  # type: ignore


def _fernet():
    digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt(value: str | None) -> str | None:
    if value is None or value == "":
        return value
    if not _FERNET_AVAILABLE:  # graceful degradation
        return value
    token = _fernet().encrypt(value.encode("utf-8")).decode("ascii")
    return _PREFIX + token


def decrypt(value: str | None) -> str | None:
    if value is None or value == "":
        return value
    if not value.startswith(_PREFIX) or not _FERNET_AVAILABLE:
        return value  # plaintext / legacy
    try:
        return _fernet().decrypt(value[len(_PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken:
        return None


def is_encrypted(value: str | None) -> bool:
    return bool(value and value.startswith(_PREFIX))
