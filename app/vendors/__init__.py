"""Vendor SNMP profile loader.

Profiles are YAML files under ``app/vendors/profiles`` describing how to read
CPU, RAM, uptime and interfaces for a device family. They are plain data so
they can be edited without touching code.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from ..config import settings


@lru_cache(maxsize=1)
def load_profiles() -> dict[str, dict]:
    directory = Path(settings.vendor_profiles_dir)
    profiles: dict[str, dict] = {}
    if not directory.exists():
        return profiles
    for path in sorted(directory.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        key = data.get("key")
        if key:
            data["_source"] = path.name
            profiles[key] = data
    return profiles


def get_profile(key: str | None) -> dict | None:
    if not key:
        return None
    return load_profiles().get(key.lower())


def list_profiles() -> list[dict]:
    return list(load_profiles().values())


def reload_profiles() -> None:
    load_profiles.cache_clear()
