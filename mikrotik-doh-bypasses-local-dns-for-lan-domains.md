---
type: troubleshooting
tags: [mikrotik, routeros, dns, doh, dns-over-https, lan, cloudflare]
created: 2026-08-31
last_verified: 2026-08-31
status: current
---

# MikroTik's own `.lan` resolution failed despite a healthy local DNS server

## Symptom

`:resolve pihole.lan` on the router itself consistently returned
`failure: dns name does not exist`, while:
- `dig pihole.lan @192.168.50.200` from any other device on the network
  resolved correctly.
- The router had 0% packet loss / sub-1ms pings to `192.168.50.200`.
- `/ip dns cache print where name~"pihole"` showed no stale/negative
  cache entry at all — ruling out a simple cache issue.

Re-tested immediately after confirming the clean ping, twice more — same
failure both times. Reproducible, not transient.

## Root cause

`/ip dns print` showed both a normal server list (`servers:
192.168.50.200`, plus public fallbacks) *and* `use-doh-server:
https://cloudflare-dns.com/dns-query` configured (from an earlier
hardening pass on this router).

Once DoH is configured, **RouterOS routes the router's own DNS resolution
exclusively through DoH** — the plain `servers` list becomes a fallback
used only if the DoH endpoint itself fails to respond, not if it returns a
legitimate answer. Cloudflare's public DoH resolver correctly has no
record of a private-only name like `pihole.lan`, so it returns a valid
NXDOMAIN — which RouterOS treats as final, never falling through to the
local server at all.

This only affects the **router's own** resolution (`:resolve`, NTP,
scripts, etc.) — it does not affect LAN clients, which query
`192.168.50.200` directly per DHCP and never touch the router's DoH path.
That's why this only ever surfaced when testing from the router itself,
and why the DNS cache had nothing cached from the local server for that
name — it was never actually queried.

## Fix

Kept DoH enabled (real privacy/security benefit for general router
traffic) but added a static forward rule so `.lan` queries specifically
bypass DoH and go straight to the local DNS server:
```
/ip dns static add type=FWD forward-to=192.168.50.200 regexp="^.*\.lan$" comment="forward .lan to local DNS, bypass DoH"
```

Verified:
```
:put [:resolve pihole.lan]   # → 192.168.50.200
:put [:resolve github.com]   # → still resolves fine over DoH
```

## Note

`forward-to` targets a single server, not a list — if the target node
becomes unreachable, this specific rule has no automatic failover. Kept
pointed at `warp-vm` (192.168.50.200), which is also the primary node in
the [3-node Technitium
deployment](technitium-dns-3node-cluster-deployment.md) this rule now
resolves against.
