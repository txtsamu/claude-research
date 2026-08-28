---
type: troubleshooting
tags: [cloudflared, cloudflare-tunnel, systemd, homelab]
created: 2026-08-28
last_verified: 2026-08-28
status: current
---

# All Cloudflare Tunnel hostnames down at once — cloudflared quietly stopped days earlier

## Symptom

Every `cloudflared access ssh --hostname ...`-based SSH alias (multiple
different hostnames, all under the same personal domain) failed at once.
Assumed it was related to same-session router/reboot work happening
elsewhere at the time.

## Diagnosis

All of those hostnames are served by a **single** `cloudflared` instance on
one central homelab box — one tunnel, multiple ingress hostnames, standard
Cloudflare Tunnel pattern. That box itself:
```
systemctl list-units ... | grep cloudflare
cloudflared.service   loaded inactive dead
```
`journalctl -u cloudflared` showed a **clean** stop —
`Stopping cloudflared... Deactivated successfully` — three days before this
session, not a crash. `uptime -s` on that box confirmed it hadn't rebooted
since well before that stop event either. So: unrelated to anything from
this session, and not actually a reboot-triggered failure — something/someone
ran `systemctl stop cloudflared` days earlier and it was never restarted.

## Fix

```
systemctl start cloudflared
```
Reconnected to Cloudflare edge within seconds (new tunnel connections
registered immediately, confirmed in the logs).

**Also found it was only `enabled-runtime`**, not permanently enabled — would
not have survived an actual reboot of that box. Fixed:
```
systemctl enable cloudflared
```

## Lesson

"All my tunnels died after a reboot" was the initial framing, but the actual
timeline (from logs, not assumption) showed a clean stop several days earlier
on a box that hadn't rebooted at all. Worth always checking `journalctl`
timestamps and `uptime -s` before accepting the reporter's causal story —
the real cause here long predated the reboot it got blamed on.
