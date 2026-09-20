"""End-to-end smoke test using FastAPI TestClient (no real server needed).

IMPORTANT: this runs against a THROWAWAY database (test_smoke.db) so it can
never touch your live data.

Covers: forced password change, auth, vendors, SNMP secret encryption,
device CRUD, metrics endpoints, stats, system info and dashboard pages.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

TEST_DB = Path(__file__).resolve().parent.parent / "test_smoke.db"
for _suffix in ("", "-wal", "-shm"):
    try:
        (TEST_DB.parent / (TEST_DB.name + _suffix)).unlink()
    except FileNotFoundError:
        pass

# isolate BEFORE importing the app
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB.as_posix()}"
os.environ["FIRST_ADMIN_USERNAME"] = "admin"
os.environ["FIRST_ADMIN_PASSWORD"] = "Admin@12345"
os.environ["FIRST_ADMIN_EMAIL"] = "admin@example.com"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

INITIAL_PW = "Admin@12345"
NEW_PW = "NewAdmin@2026!"

with TestClient(app) as client:
    # ---- 1. login with the initial (generated/default) password ----
    r = client.post("/api/auth/login", json={"username": "admin", "password": INITIAL_PW})
    assert r.status_code == 200, r.text
    print("1. login with initial password:", r.status_code)

    # ---- 2. data endpoints must be BLOCKED until password is changed ----
    r = client.get("/api/devices")
    assert r.status_code == 403, f"expected 403, got {r.status_code}"
    assert r.headers.get("X-Password-Change-Required") == "1"
    print("2. /api/devices blocked before change:", r.status_code, "(header set)")

    r = client.get("/api/auth/me")
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    print("3. /api/auth/me -> must_change_password:", r.json()["must_change_password"])

    # ---- 3. change the password ----
    r = client.post("/api/auth/change-password",
                    json={"current_password": INITIAL_PW, "new_password": NEW_PW})
    assert r.status_code == 200, r.text
    print("4. change-password:", r.status_code, r.json()["detail"])

    r = client.get("/api/auth/me")
    assert r.json()["must_change_password"] is False
    print("5. must_change_password cleared:", r.json()["must_change_password"] is False)

    # ---- 4. data endpoints now work ----
    r = client.get("/api/devices")
    assert r.status_code == 200
    print("6. /api/devices unlocked:", r.status_code)

    # ---- 5. old password no longer works, new one does ----
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"username": "admin", "password": INITIAL_PW}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": NEW_PW}).status_code == 200
    print("7. old password rejected, new password accepted")

    # ---- 6. vendor profiles ----
    vendors = client.get("/api/system/vendors").json()
    assert {"mikrotik", "cisco", "unifi", "olt_generic", "generic"} <= {v["key"] for v in vendors}
    print("8. vendors:", [v["key"] for v in vendors])

    # ---- 7. create device with SNMP; secret must be encrypted & never echoed ----
    payload = {
        "name": "Core MikroTik", "host": "192.168.1.1", "vendor": "mikrotik",
        "interval_seconds": 30, "timeout_seconds": 4, "latency_threshold_ms": 100,
        "cpu_threshold": 85, "ram_threshold": 90,
        "snmp_enabled": True, "snmp_version": "2c", "snmp_port": 161,
        "snmp_community": "s3cr3t-community",
        "checks": [{"name": "ping", "type": "ping", "params": {}, "critical": True}],
    }
    r = client.post("/api/devices", json=payload)
    assert r.status_code == 201, r.text
    device = r.json()
    device_id = device["id"]
    assert device["has_snmp_community"] is True
    assert "snmp_community" not in device and "snmp_community_enc" not in device, "secret leaked!"
    print("9. device created id=", device_id, "secret not leaked")

    import asyncio

    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Device

    async def stored_secret():
        async with SessionLocal() as db:
            res = await db.execute(select(Device).where(Device.id == device_id))
            return res.scalar_one().snmp_community_enc

    stored = asyncio.run(stored_secret())
    assert stored and stored.startswith("enc:"), "community not encrypted at rest"
    print("10. secret encrypted at rest:", stored[:20] + "...")

    # ---- 8. metrics / interfaces / history / events ----
    for path in (f"/api/devices/{device_id}/metrics?metric=cpu",
                 f"/api/devices/{device_id}/metrics?metric=ram",
                 f"/api/devices/{device_id}/interfaces",
                 f"/api/devices/{device_id}/history",
                 f"/api/devices/{device_id}/events"):
        assert client.get(path).status_code == 200, path
    print("11. metrics/interfaces/history/events: OK")

    # ---- 9. check + stats ----
    assert client.post(f"/api/devices/{device_id}/check-now").status_code == 200
    time.sleep(2)
    dev = client.get("/api/devices").json()[0]
    print("12. device status:", dev["status"], "latency:", dev["last_latency_ms"], "uptime:", dev["uptime_percent"])
    print("13. stats:", client.get("/api/stats").json())

    # ---- 10. system + dashboard ----
    print("14. system info:", client.get("/api/system/info").json()["app"],
          client.get("/api/system/info").json()["version"])
    assert client.get("/").status_code == 200
    assert client.get("/health").status_code == 200
    print("15. dashboard + health: OK")

print("\nE2E OK - all checks passed")

for _suffix in ("", "-wal", "-shm"):
    try:
        (TEST_DB.parent / (TEST_DB.name + _suffix)).unlink()
    except OSError:
        pass
