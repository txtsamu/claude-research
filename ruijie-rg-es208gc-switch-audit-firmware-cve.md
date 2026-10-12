---
type: investigation
tags: [ruijie, reyee, rg-es208gc, switch, network, firmware, cve-2025-56752, security, web-scripting, arm-cluster, mikrotik]
created: 2026-10-12
last_verified: 2026-10-12
status: current
---

# Ruijie RG-ES208GC switch: config audit, "optimise performance", firmware + CVE check

**Goal:** optimise the performance and config of the 8-port Ruijie switch, reached at its factory address `10.44.77.200`.

**Outcome:** nothing was changed on the switch. The config was already correct for a flat home LAN and there is no performance left to tune. The one real finding is security: the switch runs firmware `ESW_1.0(1)B1P39`, which is affected by a critical unauthenticated password-change bug (CVE-2025-56752), fixed in `B1P48`. The upgrade is **not done yet** (needs the image downloaded in a browser and a go-ahead, since it reboots the switch).

## Device facts

| Item | Value |
|---|---|
| Model | Ruijie RG-ES208GC ("Easy-Smart", 8x gigabit, no PoE) |
| Hostname | `switch-home` |
| Hardware version | 1.20 |
| Firmware | `ESW_1.0(1)B1P39,Release(11222814)`, firmware date Aug 01 2024 |
| Management | HTTP port 80 only (22/23/443/161 closed) |
| LAN address | 192.168.50.254/24 via DHCP ("Auto Obtain IP" enabled), gateway 192.168.50.1, DNS 192.168.50.200 |
| Fallback address | 10.44.77.200/24, always answers alongside the LAN address |
| Ruijie Cloud | status "Connected" (cloud domain `iotrc.ruijienetworks.com:7683`) |

`10.44.77.200` is not a second configured network. It is the factory default address, and the switch keeps answering on it even after it has a LAN address. Use `http://192.168.50.254/` from the LAN instead.

## Steps, in order

### 1. Reach the switch

From fedora (192.168.50.20 on `br0`) the address was dead: no ping, no open ports, and `ip route get` showed it leaving via the default gateway to the ISP.

```bash
ip route get 10.44.77.200          # -> via 192.168.50.1 dev br0  (wrong: goes to the ISP)
sudo arping -c 3 -I br0 -s 192.168.50.20 10.44.77.200   # -> replies, so it is on the local L2 segment
```

ARP replied, so the switch was on-link but on a subnet the desktop had no address in. Added a temporary, non-persistent secondary address (after checking it was free):

```bash
sudo arping -D -c 2 -w 3 -I br0 10.44.77.20   # no reply = free
sudo ip addr add 10.44.77.20/24 dev br0
# ...work...
sudo ip addr del 10.44.77.20/24 dev br0       # removed at the end
```

This turned out to be unnecessary once the switch's own info page showed its LAN address (192.168.50.254).

### 2. Log in to the web UI from curl

The login page's `onLogin()` posts `passwd=md5(password)` to `index.cgi`. The session is a cookie named after the switch serial number, with `Max-Age=600`.

```bash
H=$(printf '%s' '<SWITCH_PASSWORD>' | md5sum | cut -d' ' -f1)
curl -sS -c jar.txt -b jar.txt --data "passwd=$H" http://192.168.50.254/index.cgi
curl -sS -b jar.txt http://192.168.50.254/logout.cgi   # when done
```

### 3. Read every config page (GET only)

| Page | Content |
|---|---|
| `info.cgi` | hostname, model, MAC, IP, SN, firmware, hardware version |
| `ip.cgi` | management IP / DHCP / DNS |
| `port.cgi` | per-port state, speed/duplex, flow control, EEE (config + actual) |
| `port.cgi?page=static` | per-port counters and Rx/Tx failures |
| `port.cgi?page=bw_ctrl` | rate limiting |
| `port.cgi?page=isolation` | port isolation toggle |
| `port.cgi?page=mirroring` | port mirroring |
| `fwd.cgi?page=storm_ctrl` | storm control |
| `loop.cgi` | loop prevention toggle |
| `dhcpsnoop.cgi` | DHCP snooping + trusted ports |
| `vlan_p.cgi?page=setting`, `?page=entry` | VLAN mode and list |
| `mac.cgi?page=fwd_tbl_json` | MAC table as JSON (`port`, `mac`, `vid`) |
| `get_syslog.cgi` | local log |
| `httpupg.cgi` | local/online upgrade page |
| `cloud.cgi` | Ruijie Cloud status and domain |

Not fetched on purpose: `reboot.cgi`, `reset.cgi`, `info.cgi?page=cable_diag` (cable diagnostics can drop a link). `port.cgi?page=type` returned an empty reply.

### 4. Map ports to devices

```bash
curl -sS -b jar.txt 'http://192.168.50.254/mac.cgi?page=fwd_tbl_json'
sudo nmap -sn -n 192.168.50.0/24      # IP <-> MAC for the LAN
```

| Port | Link | What is on it |
|---|---|---|
| 1 | 1000M full | TP-Link device (.15) plus clients behind it |
| 2 | down | empty |
| 3 | 1000M full | device at .253 plus several clients behind it |
| 4 | 100M full | ARM box (.41) |
| 5 | 100M full | ARM box (.43, `arm4`) |
| 6 | 100M full | ARM box (.42, `arm3`) |
| 7 | 100M full | ARM box (.40, `arm1`) |
| 8 | 1000M full | uplink to the MikroTik (.1); fedora and the Proxmox/homelab VMs are behind it |

### 5. Are the 100M links a cable/config problem? No

```bash
ssh arm3-local 'ethtool eth0 | grep -A2 "Supported link modes"; cat /proc/device-tree/model'
```

`arm1` (Amlogic S905X P212), `arm3` and `arm4` (ZTE B860H) all report supported modes of 10/100 only. The 100M links are a NIC hardware limit. `.41` did not answer SSH, so it was not checked directly; it is the same class of box.

### 6. Baseline through the switch

```bash
ping -q -c 30 -i 0.2 <host>
```

| Target | Loss | Avg RTT |
|---|---|---|
| 192.168.50.254 (switch management CPU) | 0% | 3.5 ms |
| 192.168.50.42 (arm3, port 6) | 0% | 0.52 ms |
| 192.168.50.253 (port 3) | 0% | 0.50 ms |
| 192.168.50.15 (port 1) | 0% | 5.0 ms, max 19 ms |

The 3.5 ms to the switch itself is its management CPU answering ICMP, not forwarding latency. The .15 jitter is that device, not the switch (the other port on the same switch is flat).

## Config found vs. recommended

| Setting | Found | Recommended for this LAN | Action |
|---|---|---|---|
| Speed/duplex | Auto on all ports | Auto | none |
| Flow control | Off on all ports | Off (tiny 1.5 Mbit buffer; pause frames can stall other flows) | none |
| EEE | Off on all ports | Off (negligible power saving, known cause of link flaps) | none |
| Rate limiting | None | None | none |
| Storm control | Off on all ports | Off, or broadcast-only limit on edge ports; never limit unknown multicast (no IGMP snooping, so mDNS/IPv6 ND count as unknown) | none (optional) |
| Loop prevention | On | On | none |
| DHCP snooping | On, port 8 trusted | Fine as long as every DHCP server is behind port 8 (the MikroTik is) | none |
| VLAN | Disabled (transparent) | Disabled for a flat LAN | none |
| Port isolation / mirroring | Off / none | Off | none |
| Management IP | DHCP, 192.168.50.254 | DHCP with a router reservation or static, either is fine | none |
| Port errors | 0 Rx/Tx failures on every port | - | - |

Features this model does not have at all: QoS/priority queues, IGMP snooping, STP/RSTP, an MTU/jumbo setting, SNMP, SSH. So there is no throughput tuning to do.

## Firmware and CVE-2025-56752

The switch's own online check (`httpupg.cgi`) says "The current version is the latest". That is wrong: Ruijie's download page lists a newer build.

| Version | Release date (Ruijie page) | Notes |
|---|---|---|
| ESW_1.0(1)B1P48 | 2025-06-05 | Marked "Latest". Fixes repeated Ruijie Cloud connect/disconnect under heavy LAN protocol traffic, and is the fixed version in the security bulletin below. |
| ESW_1.0(1)B1P39 | 2025-04-02 | Installed. |
| ESW_1.0(1)B1P35 | 2024-07-15 | Added EEE on the ES208GC. |

**CVE-2025-56752 / Ruijie bulletin RJPSIRT-2025-07090** (CVSS 9.4): an unauthenticated POST to `/user.cgi` can change the eWeb login password. The bulletin lists RG-ES208GC on B1P27, B1P35 and B1P39 as affected, fixed in "ESW_1.0(1)B1P48 or later", temporary fix "None". Anyone on the LAN can take over this switch until it is upgraded.

Open points before flashing:

- The B1P48 page does not list hardware versions and shows an odd notice ("This version is for customers only", with the condition left blank). The B1P35 configuration guide lists ES208GC hardware 1.0x-1.3x for this firmware line, and the image is shared across ES205GC/ES208GC/ES210GS-P, so hardware 1.20 should be covered. The B1P48 release notes PDF (not previewable online) has the definitive table.
- RG-ES208GC-V2 is a different product with its own firmware. Do not cross-flash.
- The download is behind a "Continue Downloading" click, so it has to be fetched in a browser. No MD5 is published on the page.
- Flash via the web UI's Local Upgrade with "Keep Old Config" ticked. The switch reboots, so ports 1-8 drop for a minute or two.

## Other observations

- The web UI embeds the admin password in clear text in the JavaScript of the logged-in pages (a `'<password>'=='admin'` comparison), served over plain HTTP. Treat the password as exposed to anything that can sniff the LAN.
- The switch is connected to Ruijie Cloud. There is no documented toggle to turn that off; only the cloud domain is editable. Blocking it at the router is the only way to stop it.
- Lockout paths on this model: disabling all ports, enabling VLAN with a wrong uplink/management VLAN, or setting an unreachable IP. Recovery is holding Reset for more than 5 s (factory defaults, 10.44.77.200).

## Dead ends

- Probing `10.44.77.200` directly from the LAN without an on-link address: looks like the switch is off. It is only a routing problem.
- Trusting the switch's built-in "latest version" check: it does not offer B1P48.
- Blaming cables for the four 100M links: the ARM boxes only have 10/100 NICs.

## Notes on secrets

The switch password is not recorded here (`<SWITCH_PASSWORD>`). The serial number and MAC addresses are omitted.

## References

- [Ruijie RG-ES Series Switches Firmware (ES205GC, ES208GC) - version list, B1P35 notes](https://reyee.ruijie.com/en-global/resources/software/rg-es-es205gc-es208gc-firmware/es205gc-b1p35-firmware/)
- [ESW_1.0(1)B1P48 firmware page](https://reyee.ruijie.com/en-global/resources/software/rg-es-es205gc-es208gc-firmware/es205gc-es208gc-b1p48-firmware/)
- [ESW_1.0(1)B1P39 firmware page](https://reyee.ruijie.com/en-global/resources/software/rg-es-es205gc-es208gc-firmware/es205gc-b1p39-firmware/)
- [ESW_1.0(1)B1P48 Release Notes (V1.1), download only](https://reyee.ruijie.com/resources/preview/es-b1p48-releasenote/)
- [Ruijie security bulletin RJPSIRT-2025-07090](https://www.ruijie.com/en-global/support/securityBulletins/cybersecurity_bulletins/10004)
- [NVD: CVE-2025-56752](https://nvd.nist.gov/vuln/detail/CVE-2025-56752)
- [GitHub advisory GHSA-5m6q-c52m-c8v4 (CVE-2025-56752)](https://github.com/advisories/GHSA-5m6q-c52m-c8v4)
- [Researcher write-up for CVE-2025-56752](https://raw.githubusercontent.com/TNCX-byte/Vulnerability_Research/main/CVE-2025-56752/README.md)
- [Tenable: CVE-2025-56752](https://www.tenable.com/cve/CVE-2025-56752)
- [RG-ES2 Series Switches 1.0(1)B1P35 Configuration Guide](https://reyee.ruijie.com/en-global/support/documents/slide_rg-es2-series-switches-1-0-1-b1p35-configuration-guide/)
- [RG-ES200 Series Web-based Configuration Guide (B1P27)](https://reyee.ruijie.com/en-global/support/documents/slide_rg-es200-series-switches-web-based-configuration-guide/)
- [RG-ES200 Series Web-based Configuration Guide (B1P20 mirror)](https://storage.googleapis.com/guides.broadbandbuyer.com/Ruijie%20Reyee/RG-ES200%20Series%20Switches-Web-based%20Configuration%20Guide.pdf)
- [RG-ES200 Series Cloud Managed Switch Datasheet](https://aacgroup.com.my/uploads/product_pdf/RG-ES200%20Series%20Cloud%20Managed%20Switch%20Datasheet.pdf)
- [ES_1.0(1)B1P20 release notes (hardware versions, upgrade procedure)](https://reyee.ruijie.com/en-global/support/documents/slide_77152)
- [RG-ES208GC product page](https://reyee.ruijie.com/en-global/products/reyee-switch/smart-cctv-switch/es208gc/)
- [Ruijie community: ES switches do not support IGMP snooping](https://community.ruijie.com/forum.php?mod=viewthread&tid=5214)
- [Ruijie community: ES200 has no SSH](https://community.ruijie.com/forum.php?mod=viewthread&tid=8356)
- [Ruijie community: ES200 loop prevention is Loop Guard](https://community.ruijie.com/forum.php?mod=viewthread&tid=5968)
