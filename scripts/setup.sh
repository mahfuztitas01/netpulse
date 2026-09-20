#!/usr/bin/env bash
# ============================================================================
# NetPulse - automated installer for Ubuntu 22.04 / 24.04 (Oracle Cloud Free Tier)
#
# Usage (run as a sudo-capable user, from the project root):
#     chmod +x scripts/setup.sh
#     sudo ./scripts/setup.sh
#
# What it does:
#   1. installs OS packages (python, ping, wireguard, caddy)
#   2. creates a dedicated `netpulse` system user
#   3. copies the app to /opt/netpulse and builds a virtualenv
#   4. generates .env with a random SECRET_KEY (no secrets are hardcoded)
#   5. installs + starts a systemd service
#   6. configures the local firewall (ufw)
#
# [MANUAL ACTION] steps are printed at the end (Oracle Security List, DNS, WG keys).
# ============================================================================
set -euo pipefail

APP_NAME="netpulse"
APP_DIR="/opt/${APP_NAME}"
APP_USER="${APP_NAME}"
SERVICE="/etc/systemd/system/${APP_NAME}.service"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log()  { echo -e "\033[1;34m[setup]\033[0m $*"; }
warn() { echo -e "\033[1;33m[warn]\033[0m $*"; }
die()  { echo -e "\033[1;31m[error]\033[0m $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Please run as root:  sudo ./scripts/setup.sh"

log "Updating package index..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip git curl ca-certificates \
    iputils-ping wireguard-tools ufw

log "Creating system user '${APP_USER}'..."
if ! id -u "${APP_USER}" >/dev/null 2>&1; then
    useradd --system --create-home --shell /usr/sbin/nologin "${APP_USER}"
fi

log "Installing application to ${APP_DIR}..."
mkdir -p "${APP_DIR}"
# copy project (excluding venv / db / env)
tar -C "${SRC_DIR}" \
    --exclude='.venv' --exclude='venv' --exclude='__pycache__' \
    --exclude='*.db' --exclude='*.sqlite3' --exclude='.env' --exclude='.git' \
    -cf - . | tar -C "${APP_DIR}" -xf -

log "Creating virtualenv and installing Python dependencies..."
python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --upgrade pip >/dev/null
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

if [[ ! -f "${APP_DIR}/.env" ]]; then
    log "Generating .env with a random SECRET_KEY..."
    SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
    ADMIN_PW="$(python3 -c 'import secrets; print(secrets.token_urlsafe(12))')"
    cat > "${APP_DIR}/.env" <<EOF
APP_NAME=NetPulse
SECRET_KEY=${SECRET}
ACCESS_TOKEN_EXPIRE_MINUTES=720
DATABASE_URL=sqlite+aiosqlite:///${APP_DIR}/netpulse.db
MONITOR_TICK_SECONDS=5
MAX_CONCURRENCY=200
PING_PRIVILEGED=true
DOWN_FAILURE_THRESHOLD=1
UP_SUCCESS_THRESHOLD=1
HISTORY_RETENTION_DAYS=30
METRICS_RETENTION_DAYS=14
ALERT_RENOTIFY_MINUTES=30
LATENCY_ALERT_COOLDOWN_MINUTES=10
SNMP_TIMEOUT=3
SNMP_RETRIES=1
METRICS_INTERVAL_SECONDS=60
CPU_THRESHOLD_PERCENT=85
RAM_THRESHOLD_PERCENT=90
TELEGRAM_ENABLED=false
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
FIRST_ADMIN_USERNAME=admin
FIRST_ADMIN_PASSWORD=${ADMIN_PW}
FIRST_ADMIN_EMAIL=admin@example.com
COOKIE_SECURE=false
WG_ENABLED=false
WG_INTERFACE=wg0
EOF
    chmod 600 "${APP_DIR}/.env"
    echo
    echo "  ============================================================"
    echo "   Admin password (SAVE IT NOW):  ${ADMIN_PW}"
    echo "   Config file:                   ${APP_DIR}/.env"
    echo "  ============================================================"
    echo
else
    log ".env already exists, keeping it."
fi

log "Setting ownership..."
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"
# NOTE: ICMP raw sockets are granted via systemd AmbientCapabilities=CAP_NET_RAW
# in the unit below (safer than setcap on the shared system python binary).

log "Writing systemd service..."
cat > "${SERVICE}" <<EOF
[Unit]
Description=NetPulse network monitoring
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
# hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
AmbientCapabilities=CAP_NET_RAW
CapabilityBoundingSet=CAP_NET_RAW

[Install]
WantedBy=multi-user.target
EOF

log "Configuring firewall (ufw)..."
ufw --force reset >/dev/null 2>&1 || true
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
# `limit` adds rate-limiting against SSH brute-force (6 connections / 30s per IP)
ufw limit 22/tcp >/dev/null      # [MANUAL ACTION] restrict to your IP in Oracle Security List
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw allow 51820/udp >/dev/null   # WireGuard (phase 2)
ufw --force enable >/dev/null

log "Hardening SSH (key-only, no password login)..."
# Oracle Ubuntu images ship PasswordAuthentication no; enforce it explicitly.
if [[ -d /etc/ssh/sshd_config.d ]]; then
    cat > /etc/ssh/sshd_config.d/99-netpulse-hardening.conf <<'SSHEOF'
PasswordAuthentication no
PermitRootLogin no
PubkeyAuthentication yes
ChallengeResponseAuthentication no
KbdInteractiveAuthentication no
MaxAuthTries 4
SSHEOF
    systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || \
        warn "Could not reload ssh; verify sshd_config.d manually."
fi

log "Starting service..."
systemctl daemon-reload
systemctl enable --now "${APP_NAME}.service"
sleep 3
systemctl --no-pager --full status "${APP_NAME}.service" | head -n 12 || true

cat <<'EOF'

============================================================================
 NetPulse installed.
============================================================================
 [MANUAL ACTION] Oracle Cloud Console -> VCN -> Security List:
    - allow ingress TCP 80  from 0.0.0.0/0
    - allow ingress TCP 443 from 0.0.0.0/0
    - allow ingress TCP 22  from YOUR home IP only (recommended)
    - allow ingress UDP 51820 (only when you set up WireGuard)

 [MANUAL ACTION] Open the dashboard:
    http://<VM_PUBLIC_IP>:8000      (log in with the admin password above)

 [MANUAL ACTION] Enable HTTPS (free, no domain needed):
    sudo apt-get install -y caddy
    sudo cp deploy/caddy/Caddyfile /etc/caddy/Caddyfile
    # edit the site address to <VM_PUBLIC_IP>.sslip.io
    sudo systemctl restart caddy
    # then set COOKIE_SECURE=true in /opt/netpulse/.env and restart netpulse

 [MANUAL ACTION] Telegram alerts:
    edit /opt/netpulse/.env  ->  TELEGRAM_ENABLED=true, token, chat id
    sudo systemctl restart netpulse

 [MANUAL ACTION] WireGuard: see deploy/WIREGUARD_SETUP.md
============================================================================
EOF
