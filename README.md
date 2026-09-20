# NetPulse — Free & Open-Source Network Monitoring

A lightweight, Zabbix-style monitoring tool for **MikroTik, Cisco, UniFi and OLT**
devices: ICMP ping, SNMP CPU/RAM, interface traffic, UP/DOWN detection, Telegram
alerts and a web dashboard. Runs on a **free Oracle Cloud Always Free VM**.

---

## ⚠️ Read this first

| Scenario | Can a cloud VM monitor it? |
|----------|----------------------------|
| Public IPs / hostnames | ✅ Yes |
| **Private IPs** (192.168.x.x, 10.x.x.x) | ✅ **only over a VPN** |
| ICMP raw ping | ✅ on a real VM (root) — ❌ on PaaS (Render/Koyeb) |

Because your devices are on a private network, NetPulse is designed for a
**WireGuard site-to-site tunnel** between the cloud VM and your office router.
The MikroTik **initiates** the tunnel, so **no management port is ever exposed
to the internet** (no port-forwarding needed). See `deploy/WIREGUARD_SETUP.md`.

---

## Features

- **Checks:** ICMP ping, TCP connect, HTTP(S), SNMP GET
- **Metrics:** CPU %, RAM %, interface in/out traffic (rates from IF-MIB counters)
- **Vendors:** MikroTik, Cisco, UniFi, OLT (generic) + editable YAML profiles
- **UP/DOWN** detection with anti-flap thresholds
- **Alerts (Telegram):** device DOWN, device UP, high latency, high CPU, high RAM
- **Dashboard:** live status, latency/CPU/RAM charts, interface table, event log
- **Security:** JWT in HttpOnly cookie, bcrypt passwords, **SNMP secrets encrypted at rest**
- **Storage:** SQLite by default (PostgreSQL-ready), automatic history retention
- **Deploy:** automated `setup.sh`, systemd unit, free HTTPS via Caddy + sslip.io

---

## Architecture

```
                    ┌──────────────────────────────────────────────┐
   Telegram ◄───────┤                 NetPulse                     │
                    │  FastAPI ─ HTML dashboard + REST API          │
   Browser ◄───────►│     │                                         │
                    │  Monitor Engine (asyncio)                     │
                    │     ├─ checks: ping / tcp / http / snmp       │
                    │     └─ metrics: CPU / RAM / interfaces        │
                    │            (vendor profile → OIDs)            │
                    │     │                                         │
                    │  SQLAlchemy async → SQLite / PostgreSQL       │
                    └───────────────┬──────────────────────────────┘
                                    │  🔒 WireGuard (UDP 51820)
                    ┌───────────────▼──────────────┐
                    │   Office MikroTik (initiator) │
                    │   10.200.0.2  ·  LAN 192.168.x │
                    └───────────────┬──────────────┘
                                    │
                     MikroTik · Cisco · UniFi · OLT
```

### Project layout

```
netpulse/
├── app/
│   ├── main.py              # FastAPI app + lifespan
│   ├── config.py            # settings (.env)
│   ├── crypto.py            # encrypt SNMP secrets at rest
│   ├── database.py  models.py  schemas.py
│   ├── security.py  deps.py
│   ├── monitor/
│   │   ├── checks.py        # ping / tcp / http / snmp
│   │   ├── snmp.py          # async SNMP client (v1/v2c/v3)
│   │   ├── metrics.py       # CPU / RAM / interface collector
│   │   ├── engine.py        # scheduler + state machine + alerts
│   │   └── notifier.py      # Telegram
│   ├── vendors/
│   │   ├── __init__.py      # YAML profile loader
│   │   └── profiles/*.yaml  # mikrotik · cisco · unifi · olt_generic · generic
│   ├── wireguard/manager.py # wg status + config rendering
│   ├── routers/             # auth · devices · metrics · events · system · dashboard
│   ├── templates/  static/
├── scripts/
│   ├── setup.sh             # automated Oracle/Ubuntu installer
│   ├── backup.sh            # nightly DB + config backup
│   ├── seed_demo.py         # sample devices
│   └── smoke_test.py        # end-to-end test
├── deploy/
│   ├── ORACLE_SETUP.md      # cloud VM guide  ([MANUAL ACTION] markers)
│   ├── WIREGUARD_SETUP.md   # site-to-site tunnel guide
│   ├── caddy/Caddyfile      # free HTTPS
│   ├── systemd/netpulse.service
│   └── wireguard/           # cloud wg0 + MikroTik script
├── Dockerfile  docker-compose.yml  render.yaml  Procfile
└── requirements.txt  .env.example
```

---

## Quick start (local)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # paste into SECRET_KEY

uvicorn app.main:app --reload --port 8000
# open http://localhost:8000  (admin / the FIRST_ADMIN_PASSWORD from .env)
```

Add sample devices: `python -m scripts.seed_demo`
Run tests: `python scripts/smoke_test.py`

---

## Deploy to Oracle Cloud (free)

```bash
ssh ubuntu@<VM_PUBLIC_IP>
git clone <your-repo> netpulse && cd netpulse
sudo ./scripts/setup.sh          # installs, generates .env, starts systemd
```

Then follow **`deploy/ORACLE_SETUP.md`** for the console steps (Security List,
Caddy HTTPS) and **`deploy/WIREGUARD_SETUP.md`** for the tunnel.

---

## Adding a device

1. Dashboard → **Add Device**
2. Fill **Name**, **IP/Host**, choose a **Vendor profile**
3. Enable **SNMP metrics** → choose v2c (community) or v3 (user/auth/priv)
4. Set thresholds (latency ms, CPU %, RAM %)
5. Save — the first poll appears within one interval

> Device names/IPs and SNMP secrets are stored in the DB; secrets are encrypted
> with a key derived from `SECRET_KEY`. Never commit `.env` or `netpulse.db`.

---

## Vendor profiles

Profiles live in `app/vendors/profiles/*.yaml` and define the OIDs used for CPU,
RAM, uptime and interfaces. Each metric can declare a `fallback` that is used
automatically if the primary OID returns nothing.

To support a new device, copy `olt_generic.yaml`, adjust the OIDs, set the device
**vendor** to the new file’s `key`, then **POST /api/system/vendors/reload**.

---

## Security notes

- Passwords: **bcrypt** (cost 12). Sessions: **JWT** in an **HttpOnly** cookie.
- SNMP community / v3 passwords: **encrypted at rest** (`app/crypto.py`).
- WireGuard: office initiates; **no SNMP/management port exposed**.
- Firewall: `ufw` + Oracle Security List; restrict SSH to your IP.
- HTTPS: Caddy with automatic Let’s Encrypt (free).
- No secrets are hardcoded anywhere in the repo.

---

## Cost & backup

- **$0**: only Always Free resources (A1.Flex 2 OCPU / 12 GB, 50 GB boot).
- Never click *Upgrade to Pay As You Go*.
- Free Tier has **no SLA** → run `scripts/backup.sh` nightly and keep the repo in
  Git. Point an external uptime check at `/health`.

---

## License

MIT — free and open-source.
