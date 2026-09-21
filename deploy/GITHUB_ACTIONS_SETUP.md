# Run NetPulse 24/7 with GitHub Actions (no server, no PC)

GitHub's own runners do the monitoring on a schedule, so **your PC can be
switched off** and you still get Telegram alerts in your client groups.

```
GitHub Actions (every 15 min)
   -> scripts/cloud_check.py reads cloud/config.json
   -> pings / tcp / http checks each device
   -> sends DOWN / UP alerts to that device's client group
   -> writes cloud/state.json back to the repo
```

Cost: **$0**. Private repo gets 2,000 Actions minutes/month (a run here is
~20 s, so a 15-minute schedule uses roughly 1,700 min/month). A **public** repo
gets unlimited minutes and can use a 5-minute schedule.

---

## ⚠️ What this can and cannot monitor

| Target | Works? |
|--------|--------|
| Public IPs, websites, DNS, your ISP gateway (`220.247.163.33`) | ✅ |
| Office LAN devices (`192.168.x.x`) | ❌ — GitHub runners are on the internet and cannot reach a private network |
| SNMP (CPU/RAM/interfaces) | ❌ — needs a tunnel; keep it on a VM deployment |

For office LAN + SNMP you still need the Azure/Oracle VM with WireGuard
(`AZURE_SETUP.md`, `WIREGUARD_SETUP.md`). This Actions setup is the free
"always on, no PC" option in the meantime.

---

## Setup (3 steps)

### Step 1 — Add the bot token as a secret

The token must never be committed. Store it as an encrypted Actions secret:

```
GitHub -> repo -> Settings -> Secrets and variables -> Actions
       -> New repository secret
Name:  TELEGRAM_BOT_TOKEN
Value: 8766673044:AAE...          (your @BotFather token)
```

Or from a terminal with the `gh` CLI:

```powershell
gh secret set TELEGRAM_BOT_TOKEN --repo mahfuztitas01/netpulse
```

### Step 2 — Create the device list

The Actions runner has no database, so export the device list from the local
dashboard into a small committed file:

```powershell
cd netpulse
.venv\Scripts\python.exe scripts\export_cloud_config.py
```

That writes `cloud/config.json`:

```json
{
  "default_chat_id": "7516353938",
  "groups": {
    "client01": "-5304688578",
    "client02": "-1003950882653",
    "client03": "-1003915079958"
  },
  "devices": [
    { "name": "ISP Gateway", "host": "220.247.163.33", "alert_group": "default",
      "checks": [{"type": "ping", "params": {}}] }
  ]
}
```

Re-run the export and push whenever you add or change a device.

### Step 3 — Enable the workflow

The workflow lives at `.github/workflows/monitor.yml`. Adding it needs the
OAuth **`workflow`** scope — a plain `repo` token gets a 404.

**Option A (recommended):** re-authorise the `gh` CLI once:

```powershell
cd netpulse
.\tools\gh.exe auth refresh -s workflow
```

A browser opens — click **Authorize**. Then push the workflow file.

**Option B (web UI):** open
<https://github.com/mahfuztitas01/netpulse/new/main?filename=.github/workflows/monitor.yml>,
paste the contents of `.github/workflows/monitor.yml`, and commit.

After that, open **Actions → NetPulse Monitor → Run workflow** to test it
immediately. It will then run automatically every 15 minutes.

---

## Testing locally first

You can run the exact same script on your PC without touching Telegram:

```powershell
$env:DRY_RUN = "1"
.venv\Scripts\python.exe scripts\cloud_check.py
```

It prints the alerts it *would* send. Remove `DRY_RUN` to send them for real
(requires `TELEGRAM_BOT_TOKEN` in the environment).

---

## Tuning

| Want | Do |
|------|-----|
| Faster checks (5 min) | Make the repo public, then change the cron to `*/5 * * * *` |
| Fewer Actions minutes | Change the cron to `*/30 * * * *` |
| No repeated "still down" alerts | Raise `renotify_minutes` in `cloud/config.json` |
| No periodic summary | Set `digest_minutes` to a very large number |
| Different latency warning | Set `latency_threshold_ms` |

---

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| Workflow never appears | The file is not under `.github/workflows/` on the **default branch** |
| `404` when adding the file | Token lacks the `workflow` scope — see Step 3 |
| No Telegram messages | `TELEGRAM_BOT_TOKEN` secret missing, or the bot is not in that group |
| `ping: no ICMP reply` for everything | The host blocks ICMP — switch that check to `tcp` (e.g. port 443) |
| State commits every run | Normal — it commits only when the state actually changes |
| "state unchanged" then nothing | Expected: no transition, nothing to report |
