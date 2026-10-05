---
type: investigation
tags: [mikrotik, routeros, hex-s, audit, hardening, dhcp, leases, subnet, ipv6, firmware]
created: 2026-10-05
last_verified: 2026-10-05
status: current
---

# MikroTik hEX S: setup review (best-practice check), DHCP lease cleanup, subnet-expansion options

Context: done right after bridging the ONU ([mikrotik-pppoe-bridge-vsol-onu-plan.md](mikrotik-pppoe-bridge-vsol-onu-plan.md)). Router `192.168.50.1`, RouterOS 7.24.4. Everything below was read-only except the one lease removal.

## 1. Is the setup "the best"? Verdict: good, not best
**Healthy / already good:** RouterOS 7.24.4 = latest stable; CPU 5%, temp 55 C, 190 MiB free; NTP synced; bridge ports HW-offloaded (`H` flag) with fast-path on; input chain default-drop with services LAN-only; FastTrack + drop-invalid; MSS clamp on `pppoe-out1`; SSH strong-crypto; no L2TP/UPnP/SNMP/socks/proxy; `ether1` zero errors; DNS fallback chain; PPPoE MTU consistent (1480).

**Commands used (one per ssh call, a failing command aborts a `;` chain):**
```
/system resource print ; /system routerboard print ; /system routerboard settings print
/interface bridge print detail ; /interface bridge port print ; /interface bridge settings print
/ip settings print ; /ipv6 address print ; /ipv6 firewall filter print count-only ; /ipv6 settings print
/system ntp client print ; /system health print ; /ip dhcp-server print detail
/queue simple print count-only ; /system scheduler print count-only ; /user print detail
```

**Findings, in priority order:**
1. **RouterBOOT firmware outdated**: `current-firmware 6.46.8` vs `upgrade-firmware 7.24.4`. Fix: `/system routerboard upgrade` then reboot (~1 min downtime). `auto-upgrade: no`.
2. **Admin password is a short word**, one `admin` user, reachable from the whole LAN. Replace it (and ideally use a non-default user).
3. **IPv6 has no firewall** (`/ipv6 firewall filter` empty) while `forward: yes`. Low risk today (only link-local addresses, no DHCPv6 client), but either disable IPv6 (`/ipv6 settings set disable-ipv6=yes`) or configure it properly.
4. **IPv6 could help**: IPv4 is CGNAT (no inbound). The ONU config had IA_PD enabled, so the ISP may delegate a prefix. Plan: `/ipv6 dhcp-client` on `pppoe-out1` with `request=prefix`, an address pool, RA on the bridge, plus an IPv6 firewall (drop WAN input, allow established, ICMPv6). Not tested yet.
5. **No scheduled backups** (`/system scheduler` empty). Add a monthly `/system backup` + `/export`, and copy off the router.
6. **DoH certificate verification is off** (`/ip dns`: `verify-doh-cert=no`). Import the CA and enable it.
7. Nice-to-have: **no queue/bufferbloat control** (add fq_codel/cake on `pppoe-out1` at ~90% of measured speed; needs a speed test); DHCP lease-time 30 m (1 d is usual); plain-HTTP `www` service enabled for LAN; `rp-filter` off (loose is a cheap hardening); stale leftovers (invalid WireGuard peer on `*9`, disabled `real-wan-default-2`/Tier1 routes, kid-control dummy, sniffer config, system identity "Redmi Note 13 Pro"); `192.168.50.42` in the DHCP DNS list does not answer.
8. `ipv4-fast-path-active: no` in `/ip settings`, but FastTrack still carries most traffic (forward dummy-rule counters); leave unless a speed test is below the ISP plan.

## 2. DHCP lease cleanup (done)
Listed with `/ip dhcp-server lease print detail without-paging` (status, last-seen). Result:
- **12 dynamic leases, all `bound`**: nothing to clean; ones that look old are normal 30-minute leases that age out by themselves.
- **Static reservations** (`fedora`, `trueNAS`, `px1`, `arm1-4`, `hermes-static`) are deliberate, even when "never seen" (fixed-IP hosts; the reservation keeps DHCP from handing the address out). Kept.
- **Removed** the one clearly unused reservation: `192.168.50.12` / `60:A4:4C:6E:CA:0C`, no comment, last seen 19 weeks ago:
```
/ip dhcp-server lease remove [find address=192.168.50.12 mac-address=60:A4:4C:6E:CA:0C]
```
Lease count 21 -> 20. Backup before the change: `~/nethome/backup/pre-dhcpclean-<ts>.rsc` (chmod 600).
- **Left, flagged:** `hermes-static` (`.200`) reserves the old VM's MAC `BC:24:11:53:DC:CF`; the Technitium host now has `BC:24:11:06:47:F2`. Harmless; update the MAC if wanted.

## 3. Can the subnet be expanded? (analysis, nothing changed)
Current: `192.168.50.0/24`, pool `.3-.254` (252 addresses), 20 leases, 26 devices on the LAN = ~8% used, so capacity is not a problem.

Config that hardcodes the `/24` on the router: `/ip address 192.168.50.1/24`; DHCP pool and `/ip dhcp-server network` (`netmask=24`); the masquerade rule `src-address=192.168.50.0/24` (a wider range would get **no internet** until changed); `/ip service` `available-from` for ssh/www/winbox/api-ssl (new range would be locked out of management); the `to-vpn` route. Off-router, many hosts and notes hardcode it (Technitium zone/ACL, Caddy, Kubernetes/MetalLB, NixOS configs, fixed-IP hosts with `/24` masks); a `/23` makes `.51.x` <-> `.50.x` traffic asymmetric via the router.

Options: (1) do nothing; (2) **add a second subnet** (e.g. `192.168.51.0/24`) with its own address, DHCP pool and NAT rule for IoT/guest separation, leaving existing hosts untouched and firewalling between them; (3) widen to `/23` only if one flat network is required, after planning the host-side changes.

## References
No external sources; read from the router and the local export.
