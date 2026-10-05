---
type: how-to
tags: [mikrotik, pppoe, vsol, gpon, onu, bridge-mode, double-nat, cgnat, routeros]
created: 2026-10-05
last_verified: 2026-10-05
status: current
---

# MikroTik hEX S behind a V-SOL GPON ONU: remove double NAT (PPPoE on the MikroTik)

**Result: working.** The ONU's VLAN 2000 channel is a bridge (`2_INTERNET_B_VID_2000`, protocol `br1483`, MTU 1480). The MikroTik dials PPPoE **untagged on ether1** and is the only NAT. Verified: PPPoE `connected`, default route via `pppoe-out1`, LAN pings/HTTPS fine. Observed for only a few minutes; the first power-cycle test is still outstanding. Companion docs: [vsol-onu-web-login-scripting.md](vsol-onu-web-login-scripting.md), [technitium-servfail-quad9-forwarder-dead-route-after-bridge.md](technitium-servfail-quad9-forwarder-dead-route-after-bridge.md).

## Notes on secrets
No credentials in this repo. Placeholders used below:
- `<PPPOE_USER>` / `<PPPOE_PASS>`: the ISP PPPoE login (customer ID). Read it from the ONU config export (`ATM_VC_TBL` index 1, `pppUser`/`pppPasswd`) or the ISP.
- `<ONU_ADMIN_USER>` / `<ONU_ADMIN_PASS>`: the ISP support account on the ONU web UI at 192.168.1.1.
- `<MIKROTIK_PASSWORD>`: admin on 192.168.50.1.
Real values live in the user's `~/nethome/` files (kept out of this repo) and the ISP.

## Starting point (read from `mikrotik.rsc` and the ONU XML export)
- **ONU**: V-SOL V2802DAC (GPON, firmware V3.2.01), LAN 192.168.1.1, two LAN ports (LAN1/LAN2), Wi-Fi disabled in the user's export. Two WAN channels:
  - `1_TR069_R_VID_88`: IPoE, ISP remote management (TR-069 ACS).
  - `2_INTERNET_R_VID_2000`: PPPoE, NAPT on, MTU 1492, dual stack, port binding `itfGroup=531` (bits 0,1 = LAN1/LAN2, plus two Wi-Fi bits).
  - ONU DMZ pointed at the MikroTik (192.168.1.34) = classic double NAT.
- **MikroTik**: RB760iGS (hEX S), ROS 7.24.4. `ether1` was a DHCP client on the ONU LAN (192.168.1.34); default route was a recursive probe route (9.9.9.9 via 192.168.1.1) plus a PC-tether backup default route (distance 10) via the Fedora PC; NAT/firewall/mangle all keyed on `in/out-interface=ether1`.
- **Two ONU exports differ**: `original_vsol.xml` (older) vs `nethome.xml` (current export). Differences are mostly session IDs, boot counter, Wi-Fi disabled, and the PPP password field. The older export stores an obfuscated password; the current export has the real one. The ONU's web page shows the password as `*****` and a base64 `encodePppPassword`, which decodes to the same value as the current export. Use the current export.
- **What the ISP checks**: GPON SN / LOID / PLOAM / firmware version live in the ONU and are checked at the OLT. A PPPoE client on the MikroTik presents none of them, only the PPPoE login. "Hardware ID" cannot and need not be copied.
- **CGNAT**: the PPPoE address is 100.64.0.0/10 both before and after bridging, so inbound port-forwards (and the old L2TP VPN) cannot work from the internet regardless.

## Final working recipe
1. **Back up first** (router config + both ONU exports):
```bash
ssh admin@192.168.50.1 '/system backup save name=pre-bridge-<ts> dont-encrypt=yes; /export show-sensitive file=pre-bridge-<ts>'
scp admin@192.168.50.1:pre-bridge-<ts>.backup admin@192.168.50.1:pre-bridge-<ts>.rsc .
chmod 600 *            # these contain secrets
```
2. **Stage the MikroTik first.** It is safe while the ONU still routes, because the rules use the `WAN` interface list and work in both states:
```
/interface pppoe-client add name=pppoe-out1 interface=ether1 user=<PPPOE_USER> password=<PPPOE_PASS> \
  add-default-route=yes default-route-distance=1 use-peer-dns=no max-mtu=1480 max-mru=1480 disabled=no
/interface list member add interface=pppoe-out1 list=WAN        # ether1 is already in WAN
/ip address add address=192.168.1.2/24 interface=ether1 comment="ONU mgmt access"
/ip firewall nat set [find comment~"NAT: LAN"] out-interface-list=WAN
/ip firewall nat set [find comment~"NAT: LAN"] !out-interface
# same two-step pattern (list=WAN, then !interface) for: the LAN->WAN forward accept rule,
# both "BebasIT" DPI drop rules, "Mark WAN-inbound", "Fix ISP low incoming TTL"
/ip firewall mangle add chain=forward action=change-mss new-mss=clamp-to-pmtu protocol=tcp tcp-flags=syn out-interface=pppoe-out1
/ip firewall mangle add chain=forward action=change-mss new-mss=clamp-to-pmtu protocol=tcp tcp-flags=syn in-interface=pppoe-out1
```
3. **Remove L2TP** (user no longer uses it):
```
/interface l2tp-server server set enabled=no use-ipsec=no ipsec-secret=""
/ip firewall filter remove [find comment~"IPsec|L2TP|l2tp"]
/ip firewall nat remove [find comment~"masq. vpn"]
/ppp secret remove [find name=vpn]
/ip pool remove [find name=vpn]
```
4. **Bridge the ONU** (script in `~/nethome/onu.sh`, details in the companion doc): web WAN page, VLAN 2000 channel → `lkmode=0` (bridge), `cmode=0`, `vid=2000`, `mtu=1480`, `itfGroup=531`, `applicationtype=1`. Leave the VLAN 88 channel alone.
5. **Wait, do not judge early.** LAN1 link flaps for several minutes (see gotchas). Within ~1 to 7 minutes the MikroTik logged `pppoe-out1: authenticated` (CHAP) and `connected`.
6. **Verify**: `/interface pppoe-client monitor pppoe-out1 once`; `/ip route print where dst-address=0.0.0.0/0 and active` must show `pppoe-out1`; ping and HTTPS from a LAN client.
7. **Clean up** a stale address if present (see below), then take a post-change backup.

## How to debug the PPP login
Temporary debug logging shows the exact CHAP/IPCP exchange; remove it afterwards:
```
/system logging add topics=ppp,debug,packet action=memory prefix=zzdbg
/system logging add topics=pppoe,debug action=memory prefix=zzdbg
/log print where message~"pppoe-out1"
/system logging remove [find prefix=zzdbg]
```
`/interface pppoe-client scan interface=ether1 duration=8` lists answering PPPoE servers (empty while the ONU still routes, because the ONU is then the PPPoE client itself).

## Finding which ONU LAN port the MikroTik is on
The ONU has no host table. Compare byte counters over ~10 s: `status_ethernet_info.asp` (Port_1/Port_2 rx/tx) against `/interface print stats where name=ether1` on the MikroTik. The port whose rx moves with the MikroTik's tx is the one (here LAN1; LAN2 had another device). `diag_lan_status.asp` only says Connected / Not Connected per port.

## Timeline and dead ends (each cost real time)
1. **PPPoE on a `vlan2000` sub-interface is wrong.** The ISP VLAN is on the PON side; the ONU LAN port is untagged. Scans on `vlan2000` and `vlan88` found nothing. Plain `ether1` works.
2. **MAC clone is unnecessary and harmful.** `/interface vlan` rejects `mac-address` on this build (`bad parameter mac-address`), so the clone went on `ether1`. Using the ONU's own WAN MAC on the MikroTik made the ONU stop answering on 192.168.1.1. PPPoE authenticated with the MikroTik's own MAC. Skip it. Also changing `ether1`'s MAC before bridging would break the ONU's static DHCP/DMZ mapping.
3. **ONU LAN1 link flaps for minutes after the bridge change** (`ether1 link up` then `link down` one second later, link dark on the ONU). It recovered by itself after about 5 minutes. A 2-minute auto-revert therefore fires too early and, because the revert needs the ONU reachable, it failed (`login 000`). The LAN stayed online only because of the pre-existing PC-tether backup route (distance 10) via the Fedora PC.
4. **PC looked cut off from the ONU** only because the phone USB tether had a lower-metric default route; traffic to 192.168.1.1 left via the phone. Fix: temporary `ip route add 192.168.1.0/24 via 192.168.50.1 dev br0`.
5. **First auth attempts were rejected** ("failed to authenticate ourselves to peer") with both known passwords, then the same login succeeded minutes later. Most likely the BNG still held the ONU's previous session. Switching to the "original" obfuscated password did not help and was reverted. Do not change credentials; wait and retry.
6. **Stale `10.10.10.2/24` address.** The backup config had `10.10.10.2/24` on interface `*9` (a deleted WireGuard interface, shown invalid). RouterOS reused id `*9` for `pppoe-out1`, so the address attached to it. The router's own pings and the masquerade then used 10.10.10.2 as source and the ISP dropped them: PPPoE up, LAN no internet, while pings with `src-address=<pppoe ip>` worked. Fix: `/ip address remove [find address="10.10.10.2/24"]`.
7. **RouterOS scripting quirks**: `find src-address=...` returned nothing inside scripts, so match rules by `comment~"..."`. Clear a field with `!out-interface`, not `out-interface=""` (ambiguous-value error). `/tool pppoe-scan` and `/tool torch ... protocol=` do not exist/accept those args on ROS 7. A script aborts at the first error; check what already applied before re-running.
8. **Tooling**: the `rtk diff` wrapper printed "identical" for differing files; use `rtk proxy diff`. A hand-edited `nethome-bridge.xml` (ChannelMode 0, NAPT 0, MTU 1480) was produced but never uploaded; the web-form post was used instead.
9. **Old probe routes broke Quad9, which broke Technitium (fast.com would not start its speed test). Full write-up: [technitium-servfail-quad9-forwarder-dead-route-after-bridge.md](technitium-servfail-quad9-forwarder-dead-route-after-bridge.md).** The MikroTik still had `9.9.9.9/32` and `149.112.112.112/32` static routes via `192.168.1.1` (comment `probe-hop-1/2 ... PC-backup-wan-setup`, plus the recursive `real-wan-default-1` via 9.9.9.9). Harmless while the ONU routed; once the ONU bridged they sent all Quad9 traffic into a dead end. Technitium (`192.168.50.200`, native `DnsServerApp`, forwarders = DoH to Cloudflare, Google **and Quad9**) then timed out whenever it picked a Quad9 forwarder, so some names returned SERVFAIL at random (netflix.com, wikipedia.org, openai.com; `api.fast.com` is a CNAME chain so the speed test failed while the fast.com page itself loaded). Symptoms: `dig <name> @192.168.50.200` SERVFAIL for some names but NOERROR from `.40`/`1.1.1.1`; `+cd` (no DNSSEC) worked; Technitium log `/var/log/technitium/dns/<date>.log` showed `request timed out for name servers [https://dns.quad9.net/dns-query (9.9.9.9), ...]` (1331 lines that day vs 14 the day before); `/tool traceroute 9.9.9.9` on the MikroTik went to 192.168.1.1. Fix (reversible):
```
/ip route disable [find comment~"probe-hop-1"]
/ip route disable [find comment~"probe-hop-2"]
/ip route disable [find comment~"real-wan-default-1"]
```
After that 9.9.9.9 and 149.112.112.112 answer over `pppoe-out1` and every name resolved. Lesson: after bridging, grep the old config for anything pointing at `192.168.1.1` and any `/32` probe routes. Ruled out first: PPPoE MTU (1480-byte DF pings pass; 1.4 KB DNS replies arrive), DNSSEC data itself, ISP DNS.

## Rollback
- ONU: `~/nethome/onu.sh revert` (VLAN 2000 back to routed PPPoE, MTU 1492). Needs the ONU reachable (give it ~5 minutes after any change).
- MikroTik: `/system backup load name=pre-bridge-<ts>.backup` (or re-import the `.rsc`), then remove nothing else. Backups: `~/nethome/backup/` (`pre-bridge-*` original, `post-bridge-*` working), chmod 600.
- Leave the PC-tether backup default route (distance 10) in place as a safety net.

## Open items
- Decide whether to delete the disabled `PC-backup-wan-setup` probe routes for good (kept disabled, not removed).
- `192.168.50.42` (arm3) listed in the DHCP DNS servers does not answer DNS.
- Power-cycle test of ONU and MikroTik to prove the bridge survives a reboot.
- If the ISP's TR-069 management re-pushes the routed config, the bridge reverts itself; re-run `onu.sh bridge`.
- IPv6 was not configured on the MikroTik (the channel is dual stack).

## References
No external web sources were used; everything above was derived on-box from the two ONU exports, the MikroTik config, the ONU web UI source, and RouterOS logs.
