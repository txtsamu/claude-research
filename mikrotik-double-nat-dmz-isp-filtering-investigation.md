---
type: troubleshooting
tags: [mikrotik, routeros, nat, dmz, isp, firewall, digitalocean]
created: 2026-08-28
last_verified: 2026-08-28
status: blocked
---

# Diagnosing "VPN unreachable from outside" — double NAT, DMZ, and a red herring

## Symptom

L2TP/IPsec VPN server on the home MikroTik works fine from the LAN but is
completely unreachable from outside (mobile data, off-WiFi).

## Step 1: confirm double NAT

MikroTik's WAN interface (`ether1`) gets a **private** address (`192.168.1.x`)
via DHCP from the ISP-provided modem — not a public IP. `/ip cloud print`
confirms it directly:

```
public-address: <redacted, but a real dedicated IP per WHOIS — not shared CGNAT>
warning: Router is behind a NAT. Remote connection might not work.
```

Textbook double NAT: `internet → real public IP (on the ISP modem) →
192.168.1.1 → MikroTik (private WAN IP) → LAN`.

## Step 2: modem has no bridge-mode option

Checked the modem admin UI — no bridge/passthrough setting exposed in the
consumer-facing menu. Common on ISP-locked modems; the option is often either
hidden behind a technician-only account or only enabled by ISP support on
request, neither available here. Fell back to DMZ instead.

## Step 3: set up DMZ + static reservation — still didn't work

- Static DHCP reservation on the modem, pinning the MikroTik's WAN MAC to its
  current `192.168.1.x` address (so the DMZ target doesn't drift on lease
  renewal).
- DMZ host pointed at that same address.

Verification method: baseline a MikroTik firewall rule's packet counter
(`/ip firewall filter print stats where comment="..."`), have an external
prober hit the public IP, re-check the counter. More reliable than trusting
"it should work now" — and it caught that nothing was actually arriving.

**Still zero packets reaching the router.** Ruled out obvious causes:
`canyouseeme.org`-style external TCP probe returned `Connection timed out`
(not "refused" — meaning something dropped it silently before it ever reached
the MikroTik, not that a port was actively closed).

## Step 4: found the actual blocker — modem's "Attack Protection"

The modem (V-SOL ONT/HGU) has a **Security → Attack Protection** toggle,
separate from the DMZ/port-filtering pages, defaulting to Enabled with
Firewall Level "Low". This is the modem's own IPS/anti-scan layer and sits
*after* the DMZ forwarding decision — DMZ says "send this to the LAN device,"
but Attack Protection can still inspect and drop it before it leaves the
modem, especially anything that looks like an unsolicited scan (which an
external port probe on a random port absolutely does).

Disabling it, then a full modem reboot (needed for the change to fully take —
a quick toggle wasn't enough), was the real fix for *this specific layer*.

## Step 5: the plot twist — it wasn't actually the ISP

Ran a proper port scan against the same public VPS IP (used elsewhere this
session) from the same network path, expecting to further characterize ISP
filtering. Result:

```
tcp/22   OPEN
tcp/443  OPEN
everything else: "No route to host"
```

`No route to host` is a *fast, active* rejection (an ICMP unreachable came
back synchronously) — categorically different from the silent
`Connection timed out` behavior seen with actual ISP-level UDP blocking
elsewhere this session (see the OpenVPN/WARP-relay doc). Fast active reject on
everything except two allowed ports, uniformly, at the destination side, is
the signature of a cloud provider's edge firewall (e.g. DigitalOcean Cloud
Firewall) — not an ISP mid-path block.

**Conclusion:** at least part of what looked like "my ISP blocks everything"
was actually the *destination's own* cloud firewall, layered on top of the
real ISP-side issues found elsewhere (the Attack Protection toggle above, and
the separate raw-UDP blocking documented in the WARP-relay doc). Two
unrelated blockers were stacked, easy to misattribute to one cause.

## Status: blocked

Left pending confirmation from the account owner on whether a DigitalOcean
Cloud Firewall is actually attached to that VPS (not visible from inside the
VM — `ufw`/`iptables` both showed nothing, consistent with an edge-level
firewall the guest OS can't see). Update this doc once confirmed either way.

## Takeaway

When "X is unreachable from outside" has multiple possible culprits (home
router NAT, ISP filtering, destination-side firewall), test each layer with a
method that can *distinguish* them — timeout vs. active reject is the cheapest
signal available, and it directly separates "silently dropped somewhere in
the middle" from "actively rejected right at the end."
