---
type: how-to
tags: [mikrotik, pppoe, vsol, gpon, onu, bridge-mode, double-nat]
created: 2026-10-05
last_verified: 2026-10-05
status: blocked
---

# MikroTik hEX S behind V-SOL GPON ONU: remove double NAT (PPPoE on the MikroTik)

**Status: prepared, NOT applied.** Waiting on the user to confirm the PPPoE password and do the ONU-side change. Nothing on the live router was changed apart from backup files.

## What the configs showed
- ONU = V-SOL V2802DAC (GPON), LAN 192.168.1.1, ISP ACS orbit.remala.id (TR-069).
- ONU WAN1: VLAN 88, IPoE, TR-069 management (MAC 4c:46:d1:38:2e:05).
- ONU WAN2: **VLAN 2000, PPPoE, NAPT, MTU 1492** (MAC 4c:46:d1:38:2e:06), user = customer ID. Dual-stack.
- MikroTik (RB760iGS, ROS 7.24.4) ether1 = DHCP client 192.168.1.34 from the ONU, ONU DMZ -> 192.168.1.34 => double NAT. Default route is a recursive probe via 192.168.1.1.
- Finding: `nethome.xml` PPPoE password differs from `original_vsol.xml`; ask which is current. Not guessed.
- GPON SN/PLOAM/LOID stay in the ONU. The MikroTik does not need them: the ISP authenticates the ONU at the OLT and the customer by PPPoE login. Only the WAN MAC is worth cloning.

## Steps done
```bash
# backup (router -> local ~/nethome/backup, chmod 600)
ssh admin@192.168.50.1 '/system backup save name=pre-bridge-<ts> dont-encrypt=yes; /export show-sensitive file=pre-bridge-<ts>'
scp admin@192.168.50.1:pre-bridge-<ts>.backup admin@192.168.50.1:pre-bridge-<ts>.rsc .
```
Dead end: `/interface vlan ... mac-address=` -> "bad parameter mac-address" on this build; clone the MAC on `ether1` instead.

## Plan (files in ~/nethome)
1. `nethome-bridge.xml`: VLAN 2000 channel ChannelMode 2->0 (bridge), NAPT 1->0, PPP creds cleared, MTU 1492->1480. Untested import; safer alternative is the ONU web UI (WAN -> VLAN 2000 -> Bridge). Leave VLAN 88 untouched.
2. `mikrotik-pppoe-cutover.rsc`: ether1 MAC = 4C:46:D1:38:2E:06, vlan2000-isp, pppoe-out1 (MTU 1480), WAN list, ether1 -> pppoe-out1 in NAT/filter/mangle, MSS clamp, 10-min failsafe scheduler.
3. `mikrotik-pppoe-rollback.rsc` or `/system backup load name=pre-bridge-<ts>.backup`.
Caveat: the ISP ACS may push the routed config back to the ONU after reboot.
