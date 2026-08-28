---
type: troubleshooting
tags: [mikrotik, routeros, cloudflare-warp, policy-routing, ip-rule, outage, postmortem]
created: 2026-08-28
last_verified: 2026-08-28
status: current
---

# Postmortem: a mis-scoped `ip rule` took down the whole LAN's internet

## Goal

Extend the existing WARP-relay box (see the OpenVPN/WARP-relay doc) from
"one narrow bypass destination" to "primary path for *all* outbound LAN
traffic," with automatic failover: WARP-relay → VPS tunnel → direct ISP →
existing USB-tether backup, in that priority order.

## What was already there

The relay box already ran Cloudflare WARP with a deliberate **exclude-by-
default** design: its own table-based routing (`ip rule` priority 32761,
`not from all fwmark 0x100cf lookup <warp-table>`) meant *forwarded* LAN
traffic was normally kept OFF WARP, with one narrow carve-out rule (priority
32762) sending traffic to one specific destination through WARP. This was
intentional — the box's own local traffic and most forwarded traffic used the
normal ISP path; WARP was opt-in per rule, not the default.

## The mistake

To route all LAN traffic through WARP, added a new higher-priority rule:
```
ip rule add from <lan-subnet> lookup <warp-table> priority 32760
```
This is missing the `iif <lan-if>` qualifier the *existing* narrow rule had.
Without it, the rule matches on source address alone — which also matches
the relay box's **own** locally-generated reply traffic (ping replies, SSH's
own TCP handshake responses, the TCP relay's own responses), since the box's
own LAN-facing IP is inside that same subnet. All of that got redirected into
the WARP table instead of back out normally, and since WARP's routing table
deliberately excludes private RFC1918 ranges (it only covers public-internet
CIDR blocks), any of it addressed back into the LAN just vanished.

**Effect:** the relay box stopped being able to reply to *anything* on the
LAN — including new SSH connections trying to reach it to fix the bug. A
self-inflicted lockout: the fix required SSH, and SSH was exactly what the
bug broke.

## Why it caused a full outage, not just a broken relay

The MikroTik's new failover route to this box used
`check-gateway=ping distance=1` as its top-priority default route. Ping
health-checks only prove the *next hop is alive* — not that traffic sent to
it can actually reach the real internet. Since the relay box was still up and
answering ARP (just not ICMP, due to the bug above)... actually check-gateway
also failed since ping replies were swallowed by the same bug, so the route
*did* correctly fail over on liveness grounds. The larger risk this exposed:
if WARP itself had merely disconnected (interface gone) while the box stayed
otherwise pingable, `check-gateway=ping` would have kept using that route
anyway, black-holing all LAN traffic with no automatic failover — pure luck
that the same bug that broke the relay also broke its own health check and
triggered failover. **Lesson for next time: a next-hop-liveness check is not
an end-to-end reachability check; a route like this needs a health check that
actually validates the far side of the tunnel/relay, not just the near
side.**

## Fix

1. Live: removed the broken rule, re-added scoped correctly:
   ```
   ip rule del priority 32760
   ip rule add from <lan-subnet> iif <lan-if> lookup <warp-table> priority 32760
   ```
2. Persisted the same fix into the systemd-managed setup script that
   (re)applies these rules on boot — **and initially typo'd it during a
   manual `vi` edit** (`if <lan-if>` instead of `iif <lan-if>`, a single
   missing character). Combined with `set -e` at the top of that script, the
   typo made the *whole* rule-setup script abort after the first line,
   silently skipping the second (narrow bypass) rule too. Only surfaced on
   the next actual reboot of that box, days-feeling-like-minutes later in the
   same session, when the systemd unit showed `failed` with
   `argument "if" is wrong: Failed to parse rule type`.
3. Immediate internet restoration (before chasing the root cause) was done by
   disabling the MikroTik's top-priority failover route, forcing traffic back
   onto the still-healthy direct-ISP tier. **Restoring service and diagnosing
   root cause were treated as separate steps, deliberately in that order** —
   don't leave a household offline while debugging.

## Verifying the fix

`ip rule show` alone isn't enough — it only proves the rule was *added*, not
that it fixed anything (the exact false confidence that shipped the original
bug). Confirmed the real fix by testing from three angles:
- Local console ping to the LAN gateway (not over SSH — SSH itself was one of
  the broken paths, so testing through it would've been circular).
- `ip route get <destination>` to see which rule/table the kernel actually
  picks for a specific destination — cuts through `ip rule` list-reading
  entirely and gives a direct, authoritative answer instead of tracing
  precedence by hand.
- Only after both of those passed, re-verified the original SSH access
  itself.

## Broader takeaway, raised independently afterward

Even with this whole multi-tier setup working exactly as designed, it only
defends against the ISP *filtering/mangling specific traffic* (the actual,
confirmed problem — see the OpenVPN/WARP-relay doc). Every tier (WARP relay,
VPS tunnel, direct) still shares the *same physical uplink*
(`router WAN → ISP modem → ISP`). None of it is a second physical internet
connection, so a genuine ISP outage (not filtering, the whole link going
down) takes out all three tiers simultaneously. The only tier that's actually
independent is the pre-existing USB-tether-via-phone backup at the bottom of
the priority list, since that's the only path that doesn't touch the primary
uplink at all.
