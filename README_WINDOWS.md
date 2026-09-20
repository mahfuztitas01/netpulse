# NetPulse — Windows Local Run Guide

This guide runs NetPulse on your Windows PC for **local development/testing**.
For production, deploy to the Oracle Cloud Free Tier VM (`deploy/ORACLE_SETUP.md`).

> ⚠️ **Windows limitations:** ICMP raw sockets may need Administrator rights;
> NetPulse automatically falls back to the OS `ping` binary. WireGuard status is
> Linux-only (the WireGuard *feature* works, but status parsing needs `wg`).

---

## 1. Prerequisites

| Requirement | Notes |
|-------------|-------|
| **Python 3.11 or 3.12** | Recommended. 3.13/3.14 also work. [python.org](https://www.python.org/downloads/) — tick **"Add python.exe to PATH"** during install |
| PowerShell | Built into Windows |
| ~500 MB free disk | For the virtual environment |

Check Python:

```powershell
python --version
```

---

## 2. Automated setup (recommended)

From the project folder:

```powershell
cd "C:\path\to\netpulse"
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
```

The script:
1. creates `.venv`
2. installs `requirements.txt`
3. generates `.env` with a **random SECRET_KEY** and a random **admin password**
4. runs an import self-test
5. prints the admin password and start command

> 📌 **Save the admin password** it prints. You can also set your own in `.env`.

To set it up **and** start the server in one go:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 -Run
```

---

## 3. Manual setup (alternative)

```powershell
cd "C:\path\to\netpulse"

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt

# create config
Copy-Item .env.example .env

# generate a secret key and paste it into .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

If PowerShell blocks activation, allow scripts for the session:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

---

## 4. Run

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```

Open **http://localhost:8000** and log in with:
- username: `admin`
- password: the value of `FIRST_ADMIN_PASSWORD` in `.env`

---

## 5. Verify it works

```powershell
# health check
curl.exe http://localhost:8000/health

# run the end-to-end test (login, create device, metrics, dashboard)
$env:PYTHONPATH = "."
python scripts\smoke_test.py

# add a few sample devices
python -m scripts.seed_demo
```

---

## 6. Configure Telegram (optional)

1. In Telegram, message **@BotFather** → `/newbot` → copy the **token**.
2. Message your bot, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy the **chat id**.
3. Edit `.env`:

   ```ini
   TELEGRAM_ENABLED=true
   TELEGRAM_BOT_TOKEN=123456:ABC...
   TELEGRAM_CHAT_ID=123456789
   ```

4. Restart the server and click **Test Telegram** in the dashboard.

---

## 7. Troubleshooting

| Problem | Fix |
|---------|-----|
| `python` not found | Reinstall Python and tick *Add to PATH* |
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` |
| Ping check fails | Run the terminal **as Administrator** (raw sockets), or rely on the TCP check |
| Port 8000 already in use | `uvicorn app.main:app --port 8010` |
| SNMP timeouts | Device SNMP disabled or wrong community string; check Windows Firewall |
| `email-validator is not installed` | `pip install -r requirements.txt` again |

---

## 8. Security reminders

- `.env` holds your `SECRET_KEY` and admin password — **never commit or share it**.
- Change the admin password after first login (dashboard → change password API).
- SNMP community strings are stored **encrypted** in the database.
- For any internet-facing deployment, use **HTTPS** (`COOKIE_SECURE=true`).

---

## 9. What's next

- Deploy to Oracle Cloud → `deploy/ORACLE_SETUP.md`
- Set up the WireGuard tunnel to your office LAN → `deploy/WIREGUARD_SETUP.md`
- Tune vendor OIDs → `app/vendors/profiles/*.yaml`
