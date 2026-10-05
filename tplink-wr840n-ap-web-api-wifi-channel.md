---
type: how-to
tags: [tp-link, tl-wr840n, access-point, wifi, channel, bandwidth, web-api, 2.4ghz]
created: 2026-10-05
last_verified: 2026-10-05
status: current
---

# TP-Link TL-WR840N (used as AP): diagnose slow Wi-Fi and set channel/width via its web API

Placeholders: `<AP_USER>` / `<AP_PASSWORD>` (web login of the AP, reachable at `192.168.50.15`, MikroTik port `ether5`). Real values not stored here.

## Findings (slow connection)
- Wired side is clean: MikroTik `ether5` link-ok, full duplex, 0 rx errors/FCS errors. AP answers pings in ~5 ms (other wired hosts ~0.6 ms), normal for a low-end router CPU.
- **2.4 GHz radio `wlan0`** (SSID enabled): standard `n`, auto channel (it had picked **10**), width `Auto` (20/40 MHz), TX power 100, regulatory domain DE.
- **5 GHz radio `wlan5` is disabled** (standard `ac`, channel 40). Everything runs on crowded 2.4 GHz: likely the main reason for "kinda slow". Enabling it was offered, not done (changes SSIDs/devices).
- Channel 10 overlaps channels 8-12 and 40 MHz on 2.4 GHz widens interference; both are common causes of slow Wi-Fi.
- This PC has no Wi-Fi adapter and the AP's site survey returned nothing via the API, so neighbouring channels were not measured. Channel 11 was chosen because the AP's own auto-select landed in that part of the band, and 1/6/11 are the non-overlapping set. Re-pick after a survey (phone Wi-Fi analyzer app) if still slow.

## How the web API works (firmware with `oid_str.js` / ACT-style `/cgi`)
1. **Login = a cookie**, no form post: `Cookie: Authorization=Basic base64(<AP_USER>:<AP_PASSWORD>)`; plain password, not hashed. Requests need `Referer: http://192.168.50.15/` (without it `lib.js` and pages return 403).
2. Pages live under `/main/` (e.g. `/main/wlBasic.htm`); the menu is `/frame/menu.htm`. Read the page source to find accepted field values (that is how the width values below were found).
3. Calls are `POST /cgi?<ACT>` with a text body, ACT codes from `lib.js`: GET=1, SET=2, ADD=3, DEL=4, GL=5 (list instances), GS=6, OP=7, CGI=8. Body format: `[OBJECT#stack#...]0,<fieldcount>\r\nField\r\n...` for reads; sets use `Field=value` lines and the instance in the stack, e.g. `[LAN_WLAN#1,1,0,0,0,0#0,0,0,0,0,0]0,3`.
4. Read (use ACT 5, one field per call is safest): `printf '[LAN_WLAN#0,0,0,0,0,0#0,0,0,0,0,0]0,1\r\nChannel\r\n' | curl -s -H "$COOKIE" -e http://192.168.50.15/ --data-binary @- 'http://192.168.50.15/cgi?5'`. Instances: `[1,1,...]` = wlan0 (2.4 GHz), `[1,2,...]` = wlan5 (5 GHz). `[error]0` at the end of a reply means success / end of list.

## Change applied (2.4 GHz)
```
POST /cgi?2   [LAN_WLAN#1,1,0,0,0,0#0,0,0,0,0,0]0,3
AutoChannelEnable=0
Channel=11
X_TP_Bandwidth=20M
```
Verified by re-reading: `channel=11`, `autoChannelEnable=0`, `X_TP_Bandwidth=20M`, AP still reachable.

## Gotchas
- Bandwidth values are exactly `Auto`, `20M`, `40M` (from the page's `BandWidth` array). `20Mhz` returns `[error]9007`.
- `[error]9003` = object/field not valid for ACT GET; use ACT 5 (list) for `LAN_WLAN`, and the field names the page uses (`X_TP_ShortGI` does not exist).
- Wi-Fi clients reconnect briefly after a radio change.

## Rollback
Same call with `AutoChannelEnable=1` and `X_TP_Bandwidth=Auto` (previous values: auto channel, it had chosen 10, width Auto).

## Open items
- Consider enabling the 5 GHz radio (`wlan5`) for dual-band; keep 2.4 GHz at 20 MHz.
- If still slow, check which devices are attached and their signal strength (client list API returned empty here), and try channels 1 or 6.

## References
No external sources; derived from the AP's own web UI JavaScript and responses.
