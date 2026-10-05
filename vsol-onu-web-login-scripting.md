---
type: how-to
tags: [vsol, onu, gpon, web-ui, curl, automation, bridge-mode]
created: 2026-10-05
last_verified: 2026-10-05
status: current
---

# Scripting the V-SOL ONU web UI (login, read WAN status, switch bridge/route)

Used to bridge the ONU for [mikrotik-pppoe-bridge-vsol-onu-plan.md](mikrotik-pppoe-bridge-vsol-onu-plan.md). Tested on V2802DAC firmware V3.2.01 at 192.168.1.1. Placeholders: `<ONU_ADMIN_USER>`, `<ONU_ADMIN_PASS>` (ISP support account; not stored in this repo).

## Reach the ONU
From any LAN client behind the MikroTik: `http://192.168.1.1` (the MikroTik has `192.168.1.2/24` on `ether1` and masquerades via the `WAN` list). A client with another default route (e.g. phone tether) needs `sudo ip route add 192.168.1.0/24 via 192.168.50.1 dev br0`. Bridged ports do not expose the ONU for a few minutes after a change.

## Login (curl)
The login form posts to `/boaform/admin/formLogin` and requires a CSRF token **and a "verification code" that is printed in the page's own JavaScript** (`CreateCode()` sets `check_code` value). Both change per page load, so read them from the same fetch you log in with:
```bash
curl -s -c cj http://192.168.1.1/admin/login.asp -o l.html
T=$(grep -o "csrftoken' value='[0-9a-f]*" l.html | sed "s/.*value='//")
C=$(grep -o "value='[A-Za-z0-9]*';" l.html | head -1 | sed "s/value='//;s/';//")
curl -s -b cj -c cj -e http://192.168.1.1/admin/login.asp \
  --data-urlencode "username=<ONU_ADMIN_USER>" --data-urlencode "psd=<ONU_ADMIN_PASS>" \
  -d "username1=<ONU_ADMIN_USER>&sec_lang=0&loginSelinit=0&ismobile=0&verification_code=$C&csrftoken=$T" \
  http://192.168.1.1/boaform/admin/formLogin -w '%{http_code}\n'      # 302 = success
```
A wrong code returns 200 with "Verification code is not correct". The code from an earlier fetch of the page is not valid.

## Useful pages (after login)
- `net_eth_links.asp`: WAN config. Channels are `links.push(new it_nr("<name>", new it("napt",..), new it("cmode",..), ...))`; `cmode` 0 = bridge, 1 = IPoE, 2 = PPPoE. `lkname` = channel index.
- `status_net_connet_info.asp`: WAN status (name, protocol, IP, MAC, status).
- `status_ethernet_info.asp`: per-port byte counters. `diag_lan_status.asp`: port link state. `top.asp`: menu (lists every page).
- `mgm_config_file.asp`: config backup/restore (XML export, same format as the files in `~/nethome/`).

## Switch the Internet channel bridge/route
Post to `/boaform/admin/formEthernet` with the CSRF token from `net_eth_links.asp`. Fixed fields: `lkname=1 lst=2_INTERNET_R_VID_2000 action=sv vlan=on vid=2000 vprio=0 IpProtocolType=3 applicationtype=1 itfGroup=531 dgw=on` (plus four `chkpt=on` and the IPv6 defaults). Variable part:
- bridge: `lkmode=0 cmode=0 mtu=1480` (no PPP credentials)
- route: `lkmode=1 ipmode=2 cmode=2 napt=on mtu=1492 encodePppUserName=<b64 user> encodePppPassword=<b64 pass>`
`itfGroup` is a port bitmask (0=LAN1, 1=LAN2, then Wi-Fi SSIDs); the page JS computes it from the "Bind Port" checkboxes. Confirm afterwards by re-reading the row: the channel name changes `_R_` → `_B_` and `napt`/`cmode` flip. The reference script is `~/nethome/onu.sh`. The server answers `200` with an empty body even on success; always re-read the page.

## Gotchas
- Applying a bridge change makes the bound LAN link flap for several minutes; wait before judging.
- Do not touch `1_TR069_R_VID_88`, it is the ISP's management channel.
