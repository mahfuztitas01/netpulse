# 🚀 NetPulse — Beginner Deployment Guide (Oracle Cloud, $0)

Follow the parts **in order**. Each part is small. Items you must do by hand are
marked **[MANUAL ACTION]**.

> **You need:** a credit/debit card (verification only), a phone, and ~45 minutes.
> **You will get:** a monitoring dashboard running 24/7 on a free cloud server.

---

## 📦 Part 0 — What you need ready

- [ ] Email address
- [ ] Mobile phone (for OTP)
- [ ] Credit card **or** debit card that works like credit (no PIN), international ON
- [ ] Your name + address **exactly as on the card**
- [ ] The project ZIP: `netpulse-v1.0.0.zip`

---

## 🧾 Part 1 — Create your Oracle account  **[MANUAL ACTION]**

1. Open <https://signup.cloud.oracle.com>
2. Country: **Bangladesh** → enter email → click **Verify my email** → enter the code
3. Fill your **real name** (as on the card) and a **strong password**
4. Cloud Account Name: e.g. `netpulse2026`
5. **Home Region: `Singapore (ap-singapore-1)`** ⭐ (cannot be changed later)
6. Address + mobile `+880...`
7. Enter card details → mobile OTP
8. Accept the agreement → **Start my free trial**
9. Wait for the **"Welcome"** email

> ❌ Do **not** click "Upgrade to Pay As You Go".
> ⚠️ If you see "Out of host capacity" later, try a different Availability Domain.

---

## 🔑 Part 2 — Create your SSH key  **[MANUAL ACTION]**

1. Install **Termius** (free) on your phone
2. **Keychain → New Key → Ed25519** → add a passphrase
3. **Copy the public key** (starts with `ssh-ed25519 ...`)
4. Keep the app open — you'll paste this into Oracle next

> Never share the **private** key. Back it up via Termius export later.

---

## 🖥️ Part 3 — Create the free VM  **[MANUAL ACTION]**

Oracle Console → **Compute → Instances → Create instance**

| Field | Value |
|-------|-------|
| Name | `netpulse` |
| Image | **Ubuntu 24.04** |
| Shape | **Ampere → VM.Standard.A1.Flex** |
| OCPUs | **2** |
| Memory | **12 GB** |
| Boot volume | **50 GB** |
| SSH keys | paste the **public key** from Part 2 |
| Public IP | **Assign a public IPv4 address** |

Click **Create**. Wait ~1 minute. **Copy the Public IP address** — you'll need it.

> ⚠️ Keep OCPU ≤ 2 and RAM ≤ 12 GB to stay Always Free.

---

## 🔓 Part 4 — Open the ports  **[MANUAL ACTION]**

Oracle Console → **Networking → Virtual Cloud Networks → your VCN → Security Lists → Default Security List → Add Ingress Rules**

Add these rules:

| Source CIDR | Protocol | Destination Port | Why |
|-------------|----------|------------------|-----|
| `0.0.0.0/0` | TCP | `80` | HTTP |
| `0.0.0.0/0` | TCP | `443` | HTTPS |
| **your home IP** | TCP | `22` | SSH (find it at <https://ifconfig.me>) |
| `0.0.0.0/0` | UDP | `51820` | WireGuard (Part 9) |

---

## 📤 Part 5 — Upload and install NetPulse  **[MANUAL ACTION]**

1. In Termius, create a host:
   - Address: your **VM public IP**
   - Username: `ubuntu`
   - Key: the key from Part 2
2. Connect, then run:

```bash
# upload the project (easiest: use Termius SFTP, or `scp` from a PC)
# then:
cd ~/netpulse
sudo ./scripts/setup.sh
```

> The script installs everything, generates `.env` with a **random secret**,
> creates the admin user, sets up the firewall and starts the service.

**📌 Copy the admin password it prints** — you'll change it at first login.

Quick sanity check before running:

```bash
bash -n scripts/setup.sh && echo "SYNTAX OK"
```

---

## 🌐 Part 6 — First login  **[MANUAL ACTION]**

Open in a browser:

```
http://<VM_PUBLIC_IP>:8000
```

1. Username: `admin`
2. Password: the one from Part 5
3. **You will be forced to change the password** (this is intentional security)
4. After changing, log in again with the new password 🎉

---

## 🔒 Part 7 — Enable free HTTPS  **[MANUAL ACTION]**

```bash
sudo apt-get install -y caddy
sudo cp deploy/caddy/Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile      # set  <VM_IP>.sslip.io  as the site address
sudo systemctl restart caddy

sudo nano /opt/netpulse/.env        # set  COOKIE_SECURE=true
sudo systemctl restart netpulse
```

Now visit `https://<VM_IP>.sslip.io` — valid certificate, no domain purchase.

---

## 🧩 Part 8 — Add your first device  **[MANUAL ACTION]**

Dashboard → **+ Add Device**

| Field | Example |
|-------|---------|
| Name | `Core MikroTik` |
| IP / Host | `192.168.1.1` (reachable only after Part 9) |
| Vendor profile | `MikroTik RouterOS` |
| Check | `Ping (ICMP)` |
| Enable SNMP metrics | ✅ → version `2c`, community `public` |

Save. The first result appears within one interval.

---

## 🔐 Part 9 — WireGuard tunnel (reach your LAN)  **[MANUAL ACTION]**

Without this, the cloud can only monitor **public** IPs. Follow
`deploy/WIREGUARD_SETUP.md`:

1. On the VM: generate keys, create `/etc/wireguard/wg0.conf`
2. On the MikroTik: run `deploy/wireguard/mikrotik-wireguard.rsc` (RouterOS v7+)
3. Exchange public keys
4. Verify from the VM: `ping 192.168.1.1`

Now add devices using their **private IPs**.

---

## 📨 Part 10 — Telegram alerts  **[MANUAL ACTION]**

1. Telegram → **@BotFather** → `/newbot` → copy the token
2. Message your bot, open `https://api.telegram.org/bot<TOKEN>/getUpdates`, copy the chat id
3. On the VM:

```bash
sudo nano /opt/netpulse/.env
#   TELEGRAM_ENABLED=true
#   TELEGRAM_BOT_TOKEN=...
#   TELEGRAM_CHAT_ID=...
sudo systemctl restart netpulse
```

4. Dashboard → **Test Telegram**

---

## 🛟 Troubleshooting

| Problem | Fix |
|---------|-----|
| Can't open `:8000` | Check Oracle Security List **and** `sudo ufw status` |
| "Out of host capacity" | Try another Availability Domain, or retry later |
| Service not starting | `sudo journalctl -u netpulse -n 50` |
| Forgot admin password | `sudo nano /opt/netpulse/.env` → set a new `FIRST_ADMIN_PASSWORD`, then delete `/opt/netpulse/netpulse.db` **only if you accept losing data**, or add a new user via API |
| Ping fails | Check `AmbientCapabilities` in the unit: `systemctl cat netpulse` |
| SNMP timeout | Device SNMP enabled? Community correct? UDP 161 allowed internally? |

---

## 💰 Cost safety

- Only Always Free shapes (A1.Flex 2 OCPU / 12 GB, 50 GB boot)
- **Never** click "Upgrade to Pay As You Go"
- Set a Budget alert (Governance → Budgets) — it only **notifies**
- Log in at least once every 30 days

---

## ✅ Manual action checklist

- [ ] Part 1 — Oracle signup
- [ ] Part 2 — SSH key in Termius
- [ ] Part 3 — Create VM (A1, 2 OCPU / 12 GB)
- [ ] Part 4 — Open ports 80 / 443 / 22(your IP) / 51820
- [ ] Part 5 — Upload + run `setup.sh`
- [ ] Part 6 — First login + forced password change
- [ ] Part 7 — Caddy HTTPS
- [ ] Part 8 — Add first device
- [ ] Part 9 — WireGuard tunnel
- [ ] Part 10 — Telegram alerts

**Done!** Your free, 24/7 network monitoring is live. 🎉
