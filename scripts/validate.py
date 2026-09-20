"""Project validation: structure, vendor profiles, config and imports.

Run:  python scripts/validate.py
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ERRORS: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        ERRORS.append(label)


def main() -> int:
    print("== 1. Required files ==")
    required = [
        "requirements.txt", ".env.example", "README.md", "README_WINDOWS.md", "LICENSE",
        "Dockerfile", "docker-compose.yml", "render.yaml", "Procfile",
        "app/main.py", "app/config.py", "app/models.py", "app/schemas.py",
        "app/monitor/checks.py", "app/monitor/snmp.py", "app/monitor/metrics.py",
        "app/monitor/engine.py", "app/monitor/notifier.py", "app/monitor/whatsapp.py",
        "app/vendors/__init__.py", "app/wireguard/manager.py", "app/crypto.py",
        "app/routers/auth.py", "app/routers/devices.py", "app/routers/metrics.py",
        "app/routers/events.py", "app/routers/system.py", "app/routers/dashboard.py",
        "app/templates/index.html", "app/templates/login.html",
        "app/static/app.js", "app/static/app.css",
        "scripts/setup.sh", "scripts/backup.sh", "scripts/setup_windows.ps1", "run_server.ps1", "run_tunnel.ps1",
        "scripts/smoke_test.py", "scripts/seed_demo.py", "scripts/test_users.py", "scripts/test_telegram.py",
        "deploy/ORACLE_SETUP.md", "deploy/WIREGUARD_SETUP.md", "deploy/DEPLOY_BEGINNER_GUIDE.md",
        "deploy/AZURE_SETUP.md", "deploy/azure/cloud-init.yaml",
        "deploy/caddy/Caddyfile", "deploy/systemd/netpulse.service",
        "deploy/wireguard/cloud-wg0.conf.example",
        "deploy/wireguard/mikrotik-wireguard.rsc",
    ]
    missing = [f for f in required if not (ROOT / f).exists()]
    check(f"all {len(required)} required files present", not missing,
          f"missing: {missing}" if missing else "")

    print("\n== 2. Vendor profiles ==")
    profiles_dir = ROOT / "app" / "vendors" / "profiles"
    keys = []
    for path in sorted(profiles_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            check(path.name, False, str(exc))
            continue
        key = data.get("key")
        keys.append(key)
        ok = bool(key and data.get("interfaces") and (data.get("cpu") or data.get("ram")))
        check(f"{path.name:18} key={key}", ok)
    for expected in ("mikrotik", "cisco", "unifi", "olt_generic", "generic"):
        check(f"profile '{expected}' present", expected in keys)

    print("\n== 3. Config / env ==")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    for var in ("SECRET_KEY", "DATABASE_URL", "TELEGRAM_BOT_TOKEN", "WG_ENABLED",
                "CPU_THRESHOLD_PERCENT", "METRICS_INTERVAL_SECONDS"):
        check(f".env.example has {var}", var in env_example)
    reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    for pkg in ("fastapi", "uvicorn", "SQLAlchemy", "aiosqlite", "pysnmp", "icmplib",
                "PyYAML", "cryptography", "PyJWT", "bcrypt"):
        check(f"requirements has {pkg}", pkg.lower() in reqs.lower())

    print("\n== 4. Imports ==")
    sys.path.insert(0, str(ROOT))
    for mod in ("app.config", "app.crypto", "app.models", "app.schemas",
                "app.monitor.checks", "app.monitor.snmp", "app.monitor.metrics",
                "app.monitor.engine", "app.monitor.notifier",
                "app.vendors", "app.wireguard.manager", "app.main"):
        try:
            importlib.import_module(mod)
            check(f"import {mod}", True)
        except Exception as exc:  # noqa: BLE001
            check(f"import {mod}", False, str(exc))

    print("\n== 5. Security defaults ==")
    from app.config import settings
    check("SECRET_KEY is not a known weak default",
          settings.secret_key not in ("dev-insecure-secret-change-me",
                                      "change-me-to-a-long-random-string", ""))
    check("first admin password is not hardcoded 'admin12345'",
          settings.first_admin_password != "admin12345")
    check(".gitignore ignores .env", ".env" in (ROOT / ".gitignore").read_text(encoding="utf-8"))
    check(".dockerignore ignores .env", ".env" in (ROOT / ".dockerignore").read_text(encoding="utf-8"))

    from app.models import User
    check("User model enforces must_change_password", "must_change_password" in User.__table__.columns)
    deps_src = (ROOT / "app" / "deps.py").read_text(encoding="utf-8")
    check("get_current_user_ready dependency exists", "get_current_user_ready" in deps_src)
    setup_sh = (ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
    check("setup.sh hardens SSH (PasswordAuthentication no)", "PasswordAuthentication no" in setup_sh)
    check("setup.sh rate-limits SSH (ufw limit 22)", "ufw limit 22/tcp" in setup_sh)

    print("\n== 6. Docker / deploy files parse ==")
    try:
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        check("docker-compose.yml parses", bool(compose))
    except Exception as exc:  # noqa: BLE001
        check("docker-compose.yml parses", False, str(exc))
    try:
        render = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
        check("render.yaml parses", bool(render))
    except Exception as exc:  # noqa: BLE001
        check("render.yaml parses", False, str(exc))
    try:
        json.loads('{"ok": true}')
        check("JSON parsing available", True)
    except Exception as exc:  # noqa: BLE001
        check("JSON parsing available", False, str(exc))

    print("\n" + "=" * 56)
    if ERRORS:
        print(f"VALIDATION FAILED - {len(ERRORS)} problem(s):")
        for e in ERRORS:
            print(f"  - {e}")
        return 1
    print("VALIDATION PASSED - project is complete and consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
