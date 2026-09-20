# 🎓 NetPulse on Azure for Students — Beginner Guide ($0, no card)

**What makes this easy:** a **cloud-init** script installs NetPulse automatically
on the VM's first boot. You only do 3 things by hand.

> ✅ No credit card required · ✅ $0 · ✅ 24/7 · ✅ ARM64 compatible

---

## 🧭 The 3 things only YOU can do

1. **Verify you are a student** (identity)
2. **Create the VM** (Azure console — 1 screen + paste)
3. **Set up WireGuard** later (key exchange with your MikroTik)

Everything else is automated. **[MANUAL ACTION]** marks your steps.

---

## Part 1 — Verify your student status  **[MANUAL ACTION]**

Pick **one** route:

### Route A — Direct with Azure (simplest)
1. Go to <https://azure.microsoft.com/en-us/free/students/>
2. Click **Start free**
3. Sign in with your **school email** (e.g. `you@student.university.edu.bd`)
4. Complete phone verification
5. You get: **$100 credit + 750 hrs/month of free VMs, no card**

### Route B — Via GitHub Student Pack
1. Go to <https://github.com/settings/education/benefits>
2. Apply with your school email / student ID
3. After approval, claim the **Microsoft Azure** offer

> ⚠️ Azure for Students requires **full-time university student** status.
> If your school email isn't recognized, keep a **student ID / admission letter**
> ready for document verification.

---

## Part 2 — Create the VM  **[MANUAL ACTION]**

Azure Portal → **Virtual machines → Create → Azure virtual machine**

### Basics tab
| Field | Value |
|-------|-------|
| Subscription | **Azure for Students** |
| Resource group | *Create new* → `netpulse-rg` |
| VM name | `netpulse` |
| Region | **Southeast Asia** (Singapore) |
| Image | **Ubuntu Server 24.04 LTS** |
| Size | **Standard_B2pts_v2** (ARM, more RAM) or **Standard_B1s** |
| Authentication | **SSH public key** |
| Username | `azureuser` |
| SSH key | paste your **public key** (Termius → Keychain → Ed25519) |

### Disks tab
- OS disk type: **Standard SSD** (keep it cheap/free)

### Networking tab
- Public IP: **Create new** (dynamic is free)
- NIC security group: **Basic** → allow **SSH (22)** for now

### Advanced tab ⭐ (this is the magic)
- **Custom data** → tick the box → paste the **entire contents** of
  `deploy/azure/cloud-init.yaml`

Click **Review + create → Create**.

> ⚠️ Do **not** pick a size bigger than the free allowance (B1s / B2pts v2 /
> B2ats v2). Other sizes consume your $100 credit.

---

## Part 3 — Open the ports  **[MANUAL ACTION]**

Azure Portal → your VM → **Networking → Add inbound port rule**

| Port | Protocol | Source | Why |
|------|----------|--------|-----|
| 80 | TCP | Any | HTTP |
| 443 | TCP | Any | HTTPS |
| 22 | TCP | **My IP** | SSH (restrict!) |
| 51820 | UDP | Any | WireGuard (Part 6) |

> Azure also has an internal firewall (`ufw`) — `setup.sh` already configures it.

---

## Part 4 — Get your admin password  **[MANUAL ACTION]**

Connect via SSH (Termius, or the portal's **Connect → SSH**):

```bash
ssh azureuser@<VM_PUBLIC_IP>
sudo cat /root/netpulse-admin.txt
```

You'll see something like:

```
FIRST_ADMIN_PASSWORD=Ab3xY9...
```

**Save this.** Then open in a browser:

```
http://<VM_PUBLIC_IP>:8000
```

Log in as `admin` → **you will be forced to change the password** → done 🎉

> If the dashboard isn't up yet, the installer may still be running. Check:
> `sudo systemctl status netpulse` and `sudo journalctl -u netpulse-bootstrap -n 50`

---

## Part 5 — Free HTTPS  **[MANUAL ACTION]**

```bash
sudo apt-get install -y caddy
sudo cp /opt/netpulse/deploy/caddy/Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile      # set  <VM_IP>.sslip.io  as the site address
sudo systemctl restart caddy

sudo nano /opt/netpulse/.env        # set  COOKIE_SECURE=true
sudo systemctl restart netpulse
```

Visit `https://<VM_IP>.sslip.io` — valid certificate, no domain purchase.

> 💡 The GitHub Student Pack also gives a **free domain** (Namecheap / Name.com)
> if you prefer a nicer name.

---

## Part 6 — WireGuard tunnel (reach your office LAN)  **[MANUAL ACTION]**

Follow `deploy/WIREGUARD_SETUP.md`:

1. On the VM: `wg genkey | tee cloud_private.key | wg pubkey > cloud_public.key`
2. Create `/etc/wireguard/wg0.conf` from `deploy/wireguard/cloud-wg0.conf.example`
3. On the MikroTik: run `deploy/wireguard/mikrotik-wireguard.rsc` (RouterOS v7+)
4. Exchange public keys, then `sudo systemctl enable --now wg-quick@wg0`
5. Verify: `ping 192.168.1.1`

> ⚠️ The VM's public IP may change on restart. Use a free **DuckDNS** hostname
> for the MikroTik endpoint so the tunnel keeps working.

---

## Part 7 — Add devices + Telegram  **[MANUAL ACTION]**

- Dashboard → **+ Add Device** → name, private IP, vendor profile, enable SNMP
- Telegram: `sudo nano /opt/netpulse/.env` → set `TELEGRAM_ENABLED=true`,
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` → `sudo systemctl restart netpulse`

---

## 🛟 Troubleshooting

| Problem | Fix |
|---------|-----|
| Dashboard not loading | `sudo systemctl status netpulse` ; `sudo journalctl -u netpulse-bootstrap -n 80` |
| `sudo cat /root/netpulse-admin.txt` empty | check `/opt/netpulse/.env` directly |
| Ping checks fail | `systemctl cat netpulse` → confirm `AmbientCapabilities=CAP_NET_RAW` |
| Port 8000 blocked | add the Azure inbound rule (Part 3) **and** check `sudo ufw status` |
| VM size not free | recreate with **Standard_B1s** or **B2pts_v2** |
| Student verification failed | use a student ID / admission document |

---

## 💰 Cost safety

- Use only **B1s / B2pts_v2 / B2ats_v2** sizes (free 750 hrs/month)
- Watch the **Cost Management** page — set a budget alert
- The $100 credit lasts ~12 more months if you ever exceed free hours
- Delete the resource group when you no longer need it

---

## ✅ Manual-action checklist

- [ ] Part 1 — Verify student status
- [ ] Part 2 — Create VM + paste `cloud-init.yaml`
- [ ] Part 3 — Open ports 80 / 443 / 22(your IP) / 51820
- [ ] Part 4 — Read admin password, first login, change password
- [ ] Part 5 — Caddy HTTPS
- [ ] Part 6 — WireGuard tunnel
- [ ] Part 7 — Add devices + Telegram

**That's it — your free, 24/7 monitoring is live.** 🚀
