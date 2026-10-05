---
type: how-to
tags: [mikrotik, pppoe, vsol, gpon, onu, bridge-mode, double-nat, cgnat]
created: 2026-10-05
last_verified: 2026-10-05
status: current
---

# MikroTik hEX S behind V-SOL GPON ONU: remove double NAT (PPPoE on the MikroTik)

**Result: working.** ONU VLAN 2000 channel is a bridge (`2_INTERNET_B_VID_2000`, br1483, MTU 1480); the MikroTik dials PPPoE **untagged on ether1**. Credentials are not stored here (PPPoE user = customer ID, ONU admin login = ISP support account; see the ONU's own config export).

## Before: what the ONU config showed
- V-SOL V2802DAC GPON ONU, LAN 192.168.1.1, ISP ACS (TR-069) on VLAN 88.
- WAN2 = VLAN 2000, PPPoE, NAPT, MTU 1492, WAN MAC 4c:46:d1:38:2e:06. DMZ pointed at the MikroTik (192.168.1.34) = double NAT.
- GPON SN / LOID / PLOAM / firmware live in the ONU and are checked at the OLT. The MikroTik needs none of them; only the PPPoE login.
- The WAN IP is CGNAT (100.64/10), so inbound port-forwards / the old L2TP VPN could never work from outside.

## Final working recipe
1. Back up first:
```bash
ssh admin@192.168.50.1 '/system backup save name=pre-bridge-<ts> dont-encrypt=yes; /export show-sensitive file=pre-bridge-<ts>'
scp admin@192.168.50.1:pre-bridge-<ts>.backup admin@192.168.50.1:pre-bridge-<ts>.rsc .
```
2. Stage the MikroTik first (safe while the ONU still routes; rules use the `WAN` interface list so they work in both states):
```
/interface pppoe-client add name=pppoe-out1 interface=ether1 user=<id> password=<pw> add-default-route=yes default-route-distance=1 use-peer-dns=no max-mtu=1480 max-mru=1480
/interface list member add interface=pppoe-out1 list=WAN
/ip address add address=192.168.1.2/24 interface=ether1 comment="ONU mgmt access"
/ip firewall nat set [find comment~"NAT: LAN"] out-interface-list=WAN
/ip firewall nat set [find comment~"NAT: LAN"] !out-interface
# same pattern for the LAN->WAN forward rule, the BebasIT drops, and the two ether1 mangle rules (in-interface-list=WAN + !in-interface)
/ip firewall mangle add chain=forward action=change-mss new-mss=clamp-to-pmtu protocol=tcp tcp-flags=syn out-interface=pppoe-out1
```
3. ONU web UI (login page needs a "verification code" that is printed in the page JS, fresh per page load): WAN page `net_eth_links.asp`, post to `/boaform/admin/formEthernet` with `lkmode=0` (bridge), `cmode=0`, `vid=2000`, `mtu=1480`, `itfGroup=531` (bound ports), `applicationtype=1`, `action=sv`, `lst=2_INTERNET_R_VID_2000`. Script: `~/nethome/onu.sh bridge|revert`.
4. Within ~1 minute the MikroTik logged `pppoe-out1: authenticated` (CHAP) and got a 100.69.x.x address.

## Dead ends / gotchas (each cost real time)
- **PPPoE on a VLAN 2000 sub-interface is wrong.** The ISP VLAN is on the PON side; the ONU LAN port is untagged. A scan on `vlan2000` / `vlan88` finds nothing; scan on plain `ether1` works. Use `/interface pppoe-client scan interface=ether1 duration=8`.
- **MAC clone is unnecessary and harmful.** `/interface vlan` refuses `mac-address` on this build; cloning the ONU's WAN MAC onto `ether1` made the ONU unreachable. PPPoE authenticated with the MikroTik's own MAC. Skip it.
- **ONU LAN1 link flaps for several minutes after the bridge change** (`ether1 link down` right after link up). It recovers by itself; do not judge success inside the first 2 minutes. An auto-revert that fires at 2 min will wrongly revert.
- **First auth attempts were rejected** ("failed to authenticate ourselves to peer") with both known passwords, then succeeded minutes later with the same login. Likely the BNG still holding the ONU's old session. Do not change credentials; wait and retry.
- **Stale `10.10.10.2/24` address** (orphan from a deleted WireGuard interface) attached itself to `pppoe-out1` (interface id reuse). Router pings and masquerade then used 10.10.10.2 and the ISP dropped them: PPPoE up, LAN no internet. Fix: `/ip address remove [find address="10.10.10.2/24"]`.
- RouterOS `find src-address=...` returned nothing in scripts; match rules by `comment~"..."`. Clear a field with `!out-interface`, not `out-interface=""`.
- Router had its own PC-tether backup default route (distance 10), which kept the LAN online during the whole outage.
- The rtk `diff` wrapper printed "identical" for differing files; use `rtk proxy diff`.

## Rollback
`./onu.sh revert` (VLAN 2000 back to routed PPPoE, MTU 1492) and restore `pre-bridge-<ts>.backup` on the MikroTik. Backups live in `~/nethome/backup/` (contain secrets, chmod 600).
