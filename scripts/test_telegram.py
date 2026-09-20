"""Isolated test for Telegram settings (throwaway DB, no real network needed)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

TEST_DB = Path(__file__).resolve().parent.parent / "test_tg.db"
for _s in ("", "-wal", "-shm"):
    try:
        (TEST_DB.parent / (TEST_DB.name + _s)).unlink()
    except OSError:
        pass

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB.as_posix()}"
os.environ["FIRST_ADMIN_PASSWORD"] = "Admin@12345"
os.environ["FIRST_ADMIN_EMAIL"] = "admin@example.com"
os.environ["TELEGRAM_ENABLED"] = "false"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

FAILS: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        FAILS.append(label)


with TestClient(app) as c:
    c.post("/api/auth/login", json={"username": "admin", "password": "Admin@12345"})
    c.post("/api/auth/change-password",
           json={"current_password": "Admin@12345", "new_password": "AdminNew@2026"})

    print("== initial state ==")
    s = c.get("/api/system/telegram").json()
    check("enabled False", s["enabled"] is False, str(s))
    check("has_token False", s["has_token"] is False, str(s))
    check("ready False", s["ready"] is False, str(s))

    print("== save token + chat id ==")
    r = c.put("/api/system/telegram", json={
        "enabled": True, "bot_token": "123456:FAKE-TOKEN-for-test", "chat_id": "987654321",
    })
    check("PUT 200", r.status_code == 200, r.text[:120])
    s = r.json()
    check("enabled True", s["enabled"] is True, str(s))
    check("has_token True", s["has_token"] is True, str(s))
    check("ready True", s["ready"] is True, str(s))
    check("chat id saved", s["chat_id"] == "987654321", str(s))

    print("== token is never echoed back ==")
    raw = c.get("/api/system/telegram").text
    check("token not in response", "FAKE-TOKEN" not in raw, raw[:120])

    print("== token encrypted at rest ==")
    import sqlite3
    con = sqlite3.connect(TEST_DB)
    row = con.execute("SELECT value FROM app_settings WHERE key='telegram_bot_token'").fetchone()
    con.close()
    check("stored encrypted (enc:)", bool(row and row[0].startswith("enc:")), str(row)[:60])

    print("== partial update keeps token ==")
    r = c.put("/api/system/telegram", json={"chat_id": "111222333"})
    s = r.json()
    check("chat id updated", s["chat_id"] == "111222333", str(s))
    check("token still present", s["has_token"] is True, str(s))

    print("== disable ==")
    s = c.put("/api/system/telegram", json={"enabled": False}).json()
    check("enabled False again", s["enabled"] is False, str(s))
    check("ready False (disabled)", s["ready"] is False, str(s))

    print("== test endpoint responds gracefully (fake token) ==")
    r = c.post("/api/system/telegram/test")
    check("test 200", r.status_code == 200, str(r.status_code))
    check("returns a message", bool(r.json().get("detail")), r.text[:120])

    print("== WhatsApp settings ==")
    w = c.get("/api/system/whatsapp").json()
    check("wa initial disabled", w["enabled"] is False, str(w))
    r = c.put("/api/system/whatsapp", json={
        "enabled": True, "phone": "+8801700000000", "apikey": "FAKEKEY123",
    })
    check("wa PUT 200", r.status_code == 200, r.text[:120])
    w = r.json()
    check("wa ready True", w["ready"] is True, str(w))
    check("wa phone saved", w["phone"] == "+8801700000000", str(w))
    check("wa apikey not echoed", "FAKEKEY123" not in c.get("/api/system/whatsapp").text)
    con = sqlite3.connect(TEST_DB)
    row = con.execute("SELECT value FROM app_settings WHERE key='whatsapp_apikey'").fetchone()
    con.close()
    check("wa apikey encrypted", bool(row and row[0].startswith("enc:")), str(row)[:50])
    r = c.post("/api/system/whatsapp/test")
    check("wa test 200", r.status_code == 200, str(r.status_code))

print("\n" + "=" * 50)
if FAILS:
    print(f"TELEGRAM TEST FAILED ({len(FAILS)}): {FAILS}")
else:
    print("TELEGRAM TEST PASSED - all checks OK")

for _s in ("", "-wal", "-shm"):
    try:
        (TEST_DB.parent / (TEST_DB.name + _s)).unlink()
    except OSError:
        pass
