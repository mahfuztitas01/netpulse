"""Create a few demo devices so the dashboard is not empty.

Usage:
    python -m scripts.seed_demo
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.database import SessionLocal, init_db
from app.models import Check, CheckType, Device

DEMO_DEVICES = [
    {
        "name": "Google DNS",
        "host": "8.8.8.8",
        "vendor": "Public",
        "interval_seconds": 30,
        "latency_threshold_ms": 100,
        "checks": [{"type": CheckType.ping, "params": {}, "name": "ping"}],
    },
    {
        "name": "Cloudflare DNS",
        "host": "1.1.1.1",
        "vendor": "Public",
        "interval_seconds": 30,
        "latency_threshold_ms": 100,
        "checks": [{"type": CheckType.ping, "params": {}, "name": "ping"}],
    },
    {
        "name": "Example HTTPS",
        "host": "example.com",
        "vendor": "Web",
        "interval_seconds": 60,
        "checks": [
            {"type": CheckType.http, "params": {"url": "https://example.com/", "expect_status": 200}, "name": "https"}
        ],
    },
    {
        "name": "Local Router (TCP 80)",
        "host": "192.168.1.1",
        "vendor": "MikroTik",
        "interval_seconds": 60,
        "checks": [{"type": CheckType.tcp, "params": {"port": 80}, "name": "tcp80"}],
    },
]


async def main() -> None:
    await init_db()
    async with SessionLocal() as db:
        for spec in DEMO_DEVICES:
            exists = await db.execute(select(Device).where(Device.host == spec["host"]))
            if exists.scalar_one_or_none():
                print(f"skip (exists): {spec['name']}")
                continue
            checks = spec.pop("checks")
            device = Device(**spec)
            for c in checks:
                device.checks.append(Check(**c))
            db.add(device)
            print(f"added: {spec['name']}")
        await db.commit()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
