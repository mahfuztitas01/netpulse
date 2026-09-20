# Oracle Cloud Free Tier — Step-by-Step Setup

Everything here is **free**. Items you must do by hand are marked **[MANUAL ACTION]**.

---

## 0. Prerequisites

- A **credit / credit-like debit card** (no PIN) — for identity verification only.
- A mobile number (OTP).
- Your name/address **exactly as on the card**.
- VPN/proxy **turned off** while signing up.

> Oracle's policy: *"We accept credit cards and debit cards that function like
> credit cards. We do not accept debit cards with a PIN or virtual, single-use,
> or prepaid cards."* A temporary authorization hold (3–5 days) may appear and
> is released — **no actual charge** for Always Free resources.

---

## 1. Create the account

**[MANUAL ACTION]**

1. Go to `https://signup.cloud.oracle.com`
2. Country: **Bangladesh**, enter your email, verify the code.
3. Enter your real name (as on the card) and a strong password.
4. **Cloud Account Name**: e.g. `netpulse2026`.
5. **Home Region**: `Singapore (ap-singapore-1)` — this **cannot be changed later**.
6. Address = card billing address. Mobile `+880...`.
7. Enter card details, verify the mobile OTP.
8. Accept the Cloud Services Agreement → **Start my free trial**.
9. Wait for the activation email.

**Do NOT click** “Upgrade to Pay As You Go”.

---

## 2. Create the free VM

**[MANUAL ACTION]** — Console → **Compute → Instances → Create instance**

| Field | Value |
|-------|-------|
| Name | `netpulse` |
| Compartment | (root) |
| Image | **Ubuntu 24.04** (Always Free eligible) |
| Shape | **Ampere → VM.Standard.A1.Flex** |
| OCPUs | **2** |
| Memory | **12 GB** |
| Boot volume | **50 GB** (default) |
| SSH keys | paste your **public** key (see below) |
| Public IP | **Assign a public IPv4 address** |

> ⚠️ Keep OCPU ≤ 2 and RAM ≤ 12 GB. Larger instances created with trial credits
> are **deleted** when the trial ends.
>
> If you see **“Out of host capacity”**, try a different **Availability Domain**,
> or wait and retry (Singapore is busy).

### SSH key (generate on your phone with Termius)

**[MANUAL ACTION]**

1. Install **Termius** (free) → **Keychain → New Key → Ed25519**.
2. Add a passphrase, then **copy the public key**.
3. Paste it into the instance creation form’s *SSH keys* field.

Never share the **private** key. Back it up encrypted (Termius export → cloud).

---

## 3. Open the network ports

**[MANUAL ACTION]** — Console → **Networking → VCN → Security Lists → Default**

Add **Ingress** rules:

| Source | Protocol | Port | Purpose |
|--------|----------|------|---------|
| `0.0.0.0/0` | TCP | 80 | HTTP (cert challenge / redirect) |
| `0.0.0.0/0` | TCP | 443 | HTTPS dashboard |
| **your home IP** | TCP | 22 | SSH (do not leave `0.0.0.0/0`) |
| `0.0.0.0/0` | UDP | 51820 | WireGuard (add in phase 2) |

> Ubuntu images also ship with an internal `iptables`/`netfilter` policy.
> `scripts/setup.sh` configures `ufw` for you.

---

## 4. Connect and deploy

**[MANUAL ACTION]** — from Termius (or any SSH client):

```bash
ssh ubuntu@<VM_PUBLIC_IP>
```

Then run the automated installer:

```bash
git clone <your-repo-url> netpulse     # or upload the folder
cd netpulse
sudo ./scripts/setup.sh
```

The script prints your **admin password** — save it.

---

## 5. Open the dashboard

```
http://<VM_PUBLIC_IP>:8000
```

Log in as `admin` with the generated password, then **Add Device**.

---

## 6. Enable free HTTPS (no domain purchase)

**[MANUAL ACTION]**

```bash
sudo apt-get install -y caddy
sudo cp deploy/caddy/Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile     # set <VM_IP>.sslip.io as the site address
sudo systemctl restart caddy
```

Then:

```bash
sudo nano /opt/netpulse/.env       # set COOKIE_SECURE=true
sudo systemctl restart netpulse
```

Your dashboard is now at `https://<VM_IP>.sslip.io` with a valid certificate.

---

## 7. Cost-safety checklist

- [ ] Never click **Upgrade to Pay As You Go**
- [ ] Only Always Free shapes (A1.Flex 2 OCPU / 12 GB, 50 GB boot)
- [ ] Set a **Budget alert** (Governance → Budgets) — notification only
- [ ] Optionally set a **Compartment quota** to cap CPU/storage (real prevention)
- [ ] Log in at least once every 30 days (idle accounts may be suspended)

---

## 8. Backup plan (recommended)

Free Tier has no SLA. Protect the monitoring data:

- **Nightly DB backup** → `scripts/backup.sh` uploads `netpulse.db` to Object Storage (20 GB free).
- **Config in Git** → keep `.env.example`, vendor profiles and device exports in a private repo.
- **External health check** → point UptimeRobot (free) at `https://<host>/health`.
- **Rebuild runbook** → this document.

> Idle reclamation note: Oracle may reclaim *idle* Always Free instances
> (CPU/network/memory 95th-percentile < 20% over 7 days). NetPulse generates
> light, legitimate monitoring traffic; the backup plan is your safety net.
> We deliberately do **not** generate artificial load.
