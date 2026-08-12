---
type: troubleshooting
tags: [mikrotik, routeros, failover, wan-backup, usb-tethering, firewalld, nat, warp]
created: 2026-08-12
last_verified: 2026-08-12
status: current
---

# ISP modem down: using a PC + Android USB tether as an automatic MikroTik WAN backup

## Goal

ISP told the user their modem outage would take ~2 days to fix. The daily-driver
PC was already Ethernet-connected into the MikroTik's LAN (`br0` bridging
`enp8s0`, static `192.168.50.20/24`), and an Android phone was already
USB-tethered to that PC with working mobile data (`enp19s0u4`). Wanted:

1. Share the phone's mobile data out to the whole LAN via the MikroTik, without
   re-wiring anything.
2. **Automatic failover**, not manual switching and not true load-balancing —
   when the ISP comes back, traffic should return to it on its own, and the
   phone's mobile data should stop being used automatically (explicitly *not*
   PCC/ECMP load-balancing, which would keep splitting traffic across both
   links forever and quietly burn mobile data even after the real WAN is back).

## Topology found

- MikroTik `hEX S`, RouterOS 7.23.2, WAN on `ether1` (DHCP client), LAN on
  `bridgeLocal` = `192.168.50.0/24`.
- PC already sits *on* the MikroTik's LAN (not a separate point-to-point WAN
  link) — `br0`/`enp8s0` at `192.168.50.20`, same broadcast domain as the LAN
  clients.
- Phone tether (`enp19s0u4`) had a real working default route + internet the
  whole time; confirmed with `ping -I enp19s0u4 1.1.1.1`.
- Important early finding: `ether1`'s DHCP lease was still `bound` and its
  route still showed **active** even though there was no real internet —
  classic "modem alive locally, ISP backhaul dead" outage. `ping 192.168.1.1`
  (the modem) succeeded from the router; `ping 1.1.1.1` timed out. This meant
  plain interface-up/link-state failover would never trigger — needed an
  actual reachability check through the WAN, not just modem-liveness.

Because the PC is already LAN-side, no MikroTik WAN-port rewiring was needed —
just: (a) make the PC NAT/forward LAN traffic out through the tether, and
(b) give the MikroTik a backup default route pointing at the PC, gated by a
real internet health check.

## PC side: routed NAT (not NetworkManager "shared" mode)

Was about to use `nmcli` `ipv4.method shared` (the normal one-liner tethering
recipe) but rejected it: `shared` mode also spins up its own dnsmasq DHCP
server on the shared interface. Here the shared interface would have to be
`br0`, which is on the exact same subnet the MikroTik is *already* serving
DHCP on — two DHCP servers on one broadcast domain would hand out conflicting
leases to every device in the house. Used a plain routed/NAT setup instead,
leaving `br0`'s existing static IP and the MikroTik's DHCP server completely
untouched.

```bash
# persist IP forwarding
echo "net.ipv4.ip_forward=1" | sudo tee /etc/sysctl.d/99-backup-router.conf
sudo sysctl --system

# br0 (LAN) and enp19s0u4 (tether) were already in the same firewalld zone
# (FedoraWorkstation), which already had forward=yes — so masquerade was the
# only missing piece:
sudo firewall-cmd --zone=FedoraWorkstation --add-masquerade --permanent
sudo firewall-cmd --reload
```

If the LAN-facing and tether interfaces are in *different* firewalld zones,
you'd also need `--add-forward` (or a policy) between them — check
`firewall-cmd --get-active-zones` first.

## MikroTik side

Exported and saved the full config before touching anything:
`/export verbose` → copied off-box. Standard first move before editing a
router that's the only path to the rest of the LAN.

### 1. Stop the DHCP client from installing a route that lies about being up

```
/ip dhcp-client set [find interface=ether1] add-default-route=no
/ip dhcp-client release [find interface=ether1]
/ip dhcp-client renew [find interface=ether1]
```

`add-default-route=yes` (the `defconf` default) creates a dynamic default
route whose "active" flag only tracks the DHCP lease/link state, not real
reachability — exactly the route that was silently dead in this outage. Later
steps replace it with routes that actually check.

### 2. A default route that only counts as "up" if the internet actually responds

RouterOS's `check-gateway=ping` pings the route's own `gateway` field — so if
the gateway is the *local* modem, all it proves is the modem answers ARP,
which was already known to be useless here. The fix (documented pattern, not
invented here — see MikroTik's official
[Failover (WAN Backup)](https://help.mikrotik.com/docs/spaces/ROS/pages/26476608/Failover+WAN+Backup)
doc) is a **recursive** default route: give it a gateway that is itself a
public IP, resolved indirectly through a lower-scope "hop" route to the real
next-hop. `check-gateway=ping` then pings the *public* IP, which only
succeeds if the ISP backhaul is actually up.

```
# hop route: how to physically reach the probe IPs (via the modem)
/ip route add dst-address=9.9.9.9/32 gateway=192.168.1.1 scope=10 \
  comment="probe-hop-1 PC-backup-wan-setup"
/ip route add dst-address=149.112.112.112/32 gateway=192.168.1.1 scope=10 \
  comment="probe-hop-2 PC-backup-wan-setup"

# recursive default routes: gateway is the public IP itself, so check-gateway
# tests real internet, not just the modem
/ip route add dst-address=0.0.0.0/0 gateway=9.9.9.9 check-gateway=ping \
  distance=1 target-scope=11 comment="real-wan-default-1 PC-backup-wan-setup"
/ip route add dst-address=0.0.0.0/0 gateway=149.112.112.112 check-gateway=ping \
  distance=1 target-scope=11 comment="real-wan-default-2 PC-backup-wan-setup"

# backup default route through the PC, higher distance = only used when
# both routes above go inactive
/ip route add dst-address=0.0.0.0/0 gateway=192.168.50.20 distance=10 \
  comment="PC-USB-tether-backup PC-backup-wan-setup"
```

Two probe hosts (ECMP at distance 1) rather than one, matching the MikroTik
doc's recommendation — avoids a single flaky host causing a spurious failover.
`check-gateway` doesn't reconverge instantly; allow ~20–30s after adding/
changing these routes before trusting `/ip route print detail`.

**Gotcha hit and fixed**: first pass used `1.1.1.1` / `8.8.8.8` as the probe
targets. Both are also two of the router's own configured DNS servers
(`/ip dns print`). The `/32` hop route created for probing is *more specific*
than the default route, so it permanently pins that exact address behind the
dead modem — meaning any DNS query that happened to land on `1.1.1.1` would
silently blackhole instead of falling back. Confirmed via `tcpdump` on the
PC's `br0` (zero packets arrived for pings to `1.1.1.1`/`8.8.8.8`, but a
throwaway address like `9.9.9.9` sailed through with real ~20-40ms RTTs).
Fix: pick probe targets that don't overlap anything else in the config —
switched to Quad9 (`9.9.9.9`, `149.112.112.112`), which weren't in the DNS
list. General rule: **never reuse an address that's referenced anywhere else
in the router's config (DNS servers, NAT rules, other static routes, etc.) as
a check-gateway probe target** — the `/32` hop route it creates will hijack
that address for everything, permanently, not just for the probe.

### 3. Unrelated landmine: pre-existing WARP/VPN policy blackholed everything

Found by accident while the above still wasn't passing traffic: a `mangle`
rule was diverting **all** LAN traffic (src `192.168.50.0/24`, including the
router's own forwarded/transit traffic) into a separate `to-vpn` routing
table via `mark-routing`, pointed at a VPN/WARP gateway box at
`192.168.50.200`. That table's only default route was disabled — the `.200`
box apparently also lost its own path out through the same dead modem — so
literally nothing reached the `main` table's routing logic (the failover
routes above included) regardless of how correct they were.

The mangle rule already had an escape hatch: a `warp-bypass` address-list
that traffic is exempted from if the source matches. Used that instead of
touching the rule itself:

```
/ip firewall address-list add list=warp-bypass address=192.168.50.0/24 \
  comment="TEMP outage bypass - remove when ISP restored - added 2026-08-12"
```

This is the one piece of this setup that is **not** automatic — see Cleanup
below.

## Verification

```
/ping 9.9.9.9 count=3      # stays dead (by design — it's the probe target,
                            # permanently pinned to the dead modem path)
/ping 1.1.1.1 count=3      # real replies, ~20-30ms — routed via the PC now
/ping www.google.com count=3   # DNS + connectivity both good, ~30ms
```

`/ip route print detail where dst-address=0.0.0.0/0 and routing-table=main`
showed the two `real-wan-default-*` routes as `I` (inactive) and
`PC-USB-tether-backup` as the only `A` (active) route — exactly the expected
state while the ISP is down.

## What's automatic vs. what needs manual cleanup

**Automatic**: the moment `9.9.9.9`/`149.112.112.112` become reachable again
through `ether1`, `check-gateway` flips those routes back to active, their
distance (1) beats the PC backup route's distance (10), and all LAN traffic
reverts to the real WAN with no intervention.

**Manual** — do this once the ISP is confirmed back:

```
/ip firewall address-list remove [find comment~"TEMP outage bypass"]
```

The WARP bypass has no auto-revert condition tied to it (deliberately — it
was added as a blunt "get traffic flowing" fix, not routed through the same
health-check logic as the WAN failover). Leaving it in place after the ISP
returns means LAN traffic keeps skipping the WARP/VPN path indefinitely.

Optional, not required — the routes above are harmless to leave in place
long-term as a standing DR mechanism (poor-man's dual-WAN) if the phone
stays available as a tether:

- Re-enable the DHCP client's own default route:
  `/ip dhcp-client set [find interface=ether1] add-default-route=yes`
  (not necessary — the new recursive routes fully replace what it did, plus
  health-checking — but restores the router to its original `defconf` shape
  if preferred).
- Remove the PC-side forwarding/masquerade (`sudo firewall-cmd --zone=... 
  --remove-masquerade --permanent`, drop the sysctl file) once the PC is no
  longer meant to be a backup path.

## Notes on secrets

The MikroTik admin SSH password used during this session is intentionally
not reproduced here — placeholder convention: `<MIKROTIK_PASSWORD>`. All IPs
in this doc are LAN-internal (`192.168.50.0/24`, `192.168.1.0/24`) or public
well-known resolvers (Cloudflare, Google, Quad9) — none identify the homelab
itself, per the repo's secrets policy.
