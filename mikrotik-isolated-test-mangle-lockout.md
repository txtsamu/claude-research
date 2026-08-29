---
type: troubleshooting
tags: [mikrotik, routeros, firewall, mangle, policy-routing, lockout]
created: 2026-08-30
last_verified: 2026-08-30
status: current
---

# A "safely isolated" test mangle rule locked out the router itself

## What happened

While debugging why LAN-forwarded traffic through the `wg-bypass` VM's
NetBird exit node wasn't reliable, built a test intended to be safe: scope
a `mark-routing` mangle rule to one specific source IP (a single test PC on
the LAN) pointing at a throwaway routing table, rather than touching the
household-wide default route. The reasoning was that limiting the rule to
one source address made it low-risk regardless of what the routing table
behind it did.

```
/ip firewall mangle add chain=prerouting src-address=192.168.50.20 \
    action=mark-routing new-routing-mark=test-bypass \
    comment="isolated test - sandbox only"
```

That source address turned out to be the user's own primary PC. The rule
had **no destination restriction** — it matched every packet from that PC,
including packets destined for the router itself (`192.168.50.1`). Once
matched, those packets were routed via the `test-bypass` table, which had
no route back to the router's own management interface — so the PC lost
SSH/web access to the MikroTik entirely (`No route to host`), while
retaining normal access to every other LAN host (which weren't affected
since the mangle rule only touched traffic *from* that PC, and the PC's
own outbound-to-everything-except-router traffic still worked by
coincidence of table contents).

## Root cause

`src-address`-only scoping is not equivalent to "isolated" — a mark-routing
rule scoped only by source still intercepts that source's traffic to
**every** destination, including the router's own local addresses and the
rest of the LAN, unless the destination is explicitly excluded. "Only this
one device is affected" and "only this one device's *internet* traffic is
affected" are different claims, and only the second one was actually true
of this rule.

This is the same class of mistake as the earlier, larger household-wide
outage documented in
[lan-wide-warp-failover-routing-outage.md](lan-wide-warp-failover-routing-outage.md)
— a policy-routing rule whose destination scope was wider than intended —
just at a much smaller blast radius (one device instead of the whole
household) because the source scoping this time was deliberate.

## Fix

Recovery had to go through the `wg-bypass` VM's own SSH access (unaffected,
since it wasn't the PC the mangle rule matched), from which the MikroTik's
CLI was still reachable directly:

```
/ip firewall mangle remove [find comment="isolated test - sandbox only"]
/ip route remove [find comment="isolated test route - sandbox only"]
/routing/table remove [find name=test-bypass]
```

Removing the mangle rule alone restored the PC's access immediately — the
route and routing table were inert without it, just cleanup.

## Fix going forward

Any future test mark-routing rule gets an explicit destination exclusion
before it gets a source restriction, e.g.:

```
/ip firewall mangle add chain=prerouting src-address=<test-ip> \
    dst-address=!192.168.50.0/24 action=mark-routing new-routing-mark=<test-table>
```

`dst-address=!192.168.50.0/24` (or at minimum `!192.168.50.1/32` for the
router itself) keeps LAN-local and router-management traffic on the normal
table regardless of source, so a mistake in the *source* scoping can't
turn into a lockout the way this one did. Source-only scoping is not a
safety net by itself.
