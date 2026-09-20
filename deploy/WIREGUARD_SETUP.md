# WireGuard Site-to-Site — Cloud VM ↔ Office MikroTik

Goal: let the cloud VM reach your **private LAN** (`192.168.x.x`) to run
Ping/SNMP/TCP checks — **without exposing any management port to the internet**.

The **MikroTik initiates** the tunnel, so you do **not** need port-forwarding on
the office side. Only the cloud VM listens on UDP 51820.

```
 Cloud VM 10.200.0.1  ──(WireGuard, UDP 51820)──  MikroTik 10.200.0.2  ──  LAN devices
```

---

## Part A — Cloud VM (run as root)

**[MANUAL ACTION]**

```bash
# 1. Install (already done by setup.sh) and create keys
sudo apt-get install -y wireguard
cd /etc/wireguard
umask 077
wg genkey | tee cloud_private.key | wg pubkey > cloud_public.key

cat cloud_public.key      # <-- give this to the MikroTik step
cat cloud_private.key     # <-- keep secret, goes in wg0.conf
```

```bash
# 2. Create wg0.conf from the template
sudo cp /opt/netpulse/deploy/wireguard/cloud-wg0.conf.example /etc/wireguard/wg0.conf
sudo nano /etc/wireguard/wg0.conf
#   <CLOUD_PRIVATE_KEY>   -> contents of cloud_private.key
#   <MIKROTIK_PUBLIC_KEY> -> printed on the MikroTik (Part B step 3)
#   <OFFICE_LAN_CIDR>     -> e.g. 192.168.1.0/24
```

```bash
# 3. Bring the tunnel up
sudo systemctl enable --now wg-quick@wg0
sudo wg show
```

---

## Part B — MikroTik (RouterOS v7+)

**[MANUAL ACTION]** — open the terminal and follow `deploy/wireguard/mikrotik-wireguard.rsc`,
replacing the placeholders:

1. Create the interface + tunnel IP (`10.200.0.2/24`).
2. Read the MikroTik **public key** it prints.
3. Put the **cloud public key** and **cloud public IP** into the peer config.
4. Allow the tunnel in the firewall and add a **srcnat masquerade** so LAN
   devices can reply to the cloud.

> ⚠️ Never expose SNMP (UDP 161) or Winbox/SSH to the internet. The tunnel makes
> that unnecessary — this is the whole point of the design.

---

## Part C — Verify

From the cloud VM:

```bash
ping -c 3 10.200.0.2                 # tunnel peer
ping -c 3 192.168.1.1                # office router LAN IP
snmpwalk -v2c -c public 192.168.1.1 1.3.6.1.2.1.1.1.0   # if snmpwalk installed
```

If the pings work, add devices in the dashboard using their **private IPs** —
NetPulse will reach them through the tunnel.

---

## Enabling WireGuard status in the dashboard

Set in `/opt/netpulse/.env`:

```ini
WG_ENABLED=true
WG_INTERFACE=wg0
```

The app user needs permission to read the interface. Add a sudoers rule:

```bash
# [MANUAL ACTION] run as root
echo 'netpulse ALL=(root) NOPASSWD: /usr/bin/wg show wg0 dump' | sudo tee /etc/sudoers.d/netpulse-wg
sudo chmod 440 /etc/sudoers.d/netpulse-wg
sudo systemctl restart netpulse
```

Then **System → WireGuard** in the API/dashboard shows interface + peers.

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| `wg show` empty | `sudo systemctl status wg-quick@wg0`; check keys match |
| Ping peer fails | MikroTik firewall `input`/`forward` allow rules |
| Ping LAN fails | MikroTik **srcnat masquerade** on the LAN interface |
| SNMP times out | Device community string; device SNMP enabled; UDP 161 allowed internally |
| Handshake never completes | Office public IP changed; `PersistentKeepalive=25` set on both sides |
