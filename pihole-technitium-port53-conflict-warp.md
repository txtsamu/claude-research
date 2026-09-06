---
type: troubleshooting
tags: [dns, pihole, technitium, warp-vm, iptables, port-conflict]
created: 2026-09-06
last_verified: 2026-09-06
status: current — pihole disabled permanently, technitium is sole resolver on warp
---

# Pi-hole silently still answering DNS after "migrating" to Technitium on warp

## Symptom

`px1.lan` (and, it turned out, potentially any `.lan` record) reported as "not
reachable" despite the record and its Caddy reverse-proxy route both being correctly
configured. The user believed they'd already migrated warp's local DNS from Pi-hole
to Technitium.

## Root cause

Both Pi-hole **and** a separately-installed Technitium instance were running on warp
(192.168.50.200) simultaneously, each a rootful Podman container bound to port 53.
Pi-hole had bound to the **specific** address `192.168.50.200:53`; Technitium had
only bound the **wildcard** `0.0.0.0:53`. On Linux, a socket bound to a specific IP
always wins over one bound to the wildcard for traffic addressed to that IP — so
**Pi-hole was silently intercepting all real LAN DNS traffic**, and Technitium (while
genuinely running and reachable on other addresses) never actually received queries
sent to warp's main IP.

Confirmed by checking listeners directly:

```bash
sudo ss -tulnp | grep ':53'
# udp   ...   192.168.50.200:53   pihole-FTL
# udp   ...        0.0.0.0:53     dotnet        (Technitium is a .NET app)
```

The DNS *record itself* was never wrong or missing — `px1.lan` resolved correctly
the whole time, just via the stale server (Pi-hole), whose answer happened to also
be correct in this case, so the actual reachability problem was purely "which daemon
answers `192.168.50.200:53`", not a record/config issue.

## Fix

```bash
sudo systemctl stop pihole.service pihole-pod.service
sudo systemctl disable pihole.service pihole-pod.service
```

After Pi-hole releases the specific-IP bind, Technitium's wildcard bind naturally
takes over `192.168.50.200:53`:

```bash
sudo ss -tulnp | grep ':53'   # now shows the Technitium (dotnet) process only
```

## Verification

```bash
for d in px1.lan rancher.lan nextcloud.lan grafana.lan jellyfin.lan; do
  getent hosts -s dns "$d"
done
```
All resolved correctly via Technitium — confirming records had already been fully
migrated, this was purely the port-53 shadowing issue.

## Lesson

When "migrating" a DNS server on the same host, **stop/disable the old one before or
immediately after standing up the new one** — don't leave both running "just in
case," since a specific-IP bind on the old service will silently win over the new
service's wildcard bind with no error on either side. Neither Pi-hole nor Technitium
logged anything indicating a conflict; this only surfaces as "wrong answers" or, as
here, "right answer from the wrong/stale source" that happens to also be correct
until the old service is later touched/removed.
