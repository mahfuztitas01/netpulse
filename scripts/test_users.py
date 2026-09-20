"""Isolated test for the user-management feature (uses a throwaway DB)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

TEST_DB = Path(__file__).resolve().parent.parent / "test_users.db"
for suffix in ("", "-wal", "-shm"):
    try:
        (TEST_DB.parent / (TEST_DB.name + suffix)).unlink()
    except OSError:
        pass

# point the app at a throwaway database BEFORE importing it
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB.as_posix()}"
os.environ["FIRST_ADMIN_USERNAME"] = "admin"
os.environ["FIRST_ADMIN_PASSWORD"] = "Admin@12345"
os.environ["FIRST_ADMIN_EMAIL"] = "admin@example.com"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

FAILS: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        FAILS.append(label)


with TestClient(app) as c:
    print("== login (fresh admin, must change password) ==")
    r = c.post("/api/auth/login", json={"username": "admin", "password": "Admin@12345"})
    check("login 200", r.status_code == 200, str(r.status_code))
    check("must_change_password True", r.status_code == 200 and c.get("/api/auth/me").json()["must_change_password"] is True)

    print("== /api/auth/users blocked until password changed ==")
    check("users list blocked (403)", c.get("/api/auth/users").status_code == 403)

    r = c.post("/api/auth/change-password",
               json={"current_password": "Admin@12345", "new_password": "AdminNew@2026"})
    check("change own password 200", r.status_code == 200, r.text[:80])

    print("== create user ==")
    r = c.post("/api/auth/users", json={
        "username": "nocoperator", "email": "noc@example.com",
        "password": "NocUser@2026", "is_superuser": False,
    })
    check("create user 201", r.status_code == 201, r.text[:120])
    uid = r.json()["id"] if r.status_code == 201 else None
    check("password not exposed in response", "hashed_password" not in (r.json() if r.status_code == 201 else {}))

    print("== duplicate rejected ==")
    r = c.post("/api/auth/users", json={
        "username": "nocoperator", "email": "other@example.com",
        "password": "Whatever@2026",
    })
    check("duplicate username -> 409", r.status_code == 409, str(r.status_code))

    print("== new user can log in ==")
    r = c.post("/api/auth/login", json={"username": "nocoperator", "password": "NocUser@2026"})
    check("new user login 200", r.status_code == 200, str(r.status_code))
    # restore the admin session (the login above replaced the cookie)
    c.post("/api/auth/login", json={"username": "admin", "password": "AdminNew@2026"})

    print("== patch: reset password + disable ==")
    r = c.patch(f"/api/auth/users/{uid}", json={"password": "ResetPw@2026", "is_active": False})
    check("patch 200", r.status_code == 200, r.text[:120])
    check("user now inactive", r.status_code == 200 and r.json()["is_active"] is False)

    r = c.post("/api/auth/login", json={"username": "nocoperator", "password": "ResetPw@2026"})
    check("disabled user cannot log in (403)", r.status_code == 403, str(r.status_code))
    c.post("/api/auth/login", json={"username": "admin", "password": "AdminNew@2026"})

    print("== re-enable + new password works ==")
    c.patch(f"/api/auth/users/{uid}", json={"is_active": True})
    r = c.post("/api/auth/login", json={"username": "nocoperator", "password": "ResetPw@2026"})
    check("re-enabled user login 200", r.status_code == 200, str(r.status_code))
    c.post("/api/auth/login", json={"username": "admin", "password": "AdminNew@2026"})

    print("== safety guards ==")
    r = c.delete("/api/auth/users/1")
    check("cannot delete self (400)", r.status_code == 400, str(r.status_code))
    r = c.patch("/api/auth/users/1", json={"is_superuser": False})
    check("cannot demote last superuser (400)", r.status_code == 400, str(r.status_code))

    print("== delete test user ==")
    r = c.delete(f"/api/auth/users/{uid}")
    check("delete 200", r.status_code == 200, str(r.status_code))
    users = c.get("/api/auth/users").json()
    check("only admin remains", [u["username"] for u in users] == ["admin"], str([u["username"] for u in users]))

print("\n" + "=" * 50)
if FAILS:
    print(f"USER-MGMT TEST FAILED ({len(FAILS)}): {FAILS}")
else:
    print("USER-MGMT TEST PASSED - all checks OK")

for suffix in ("", "-wal", "-shm"):
    try:
        (TEST_DB.parent / (TEST_DB.name + suffix)).unlink()
    except OSError:
        pass
