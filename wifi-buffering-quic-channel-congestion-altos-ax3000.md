---
type: troubleshooting
tags: [wifi, altos-ax3000, mikrotik, quic, buffering, streaming, channel, dfs, 5ghz, isp, mtu, bufferbloat, nethome]
created: 2026-09-24
last_verified: 2026-09-24
status: current
---

# Video buffering mid-stream (YouTube/TikTok/Instagram) — Wi-Fi channel congestion on the Altos AX3000, not the ISP or QUIC

## Symptom

TikTok / Instagram / YouTube videos on phones **load fine, then stall in the
middle** of playback, intermittently. Everything else on the LAN felt normal.
Initial suspicion (given this ISP's known bad behavior — see
[[mikrotik-openvpn-warp-relay-bypass-isp-udp-block]] and
[[pod-internet-egress-isp-ttl-bug]]) was ISP-side connection drops or QUIC/UDP
interference. That turned out to be wrong: the cause was **2.4/5 GHz channel
congestion from neighboring APs** (house is physically in the middle of the
block, many overlapping neighbor SSIDs). Fix was moving the Altos AX3000
(bridge-mode AP) 5 GHz radio to a clean **non-DFS channel (48)**.

## Topology (for context)

- **MikroTik hEX S** (`192.168.50.1`, RouterOS 7.24.4) — main router/NAT, WAN on
  `ether1`. Behind ISP double-NAT (WAN IP is private `192.168.1.34`), ISP =
  PT NETHOME GROUP INDONESIA.
- **Ruijie Easy-Smart switch** (`192.168.50.254`) — LAN switch.
- **Altos AX3000** (`192.168.50.253`, Wi-Fi 6) — **bridge mode** (pure AP, does
  not route/NAT; MikroTik does DHCP). Web UI login `admin`/`admin`. All the
  phones associate here.
- Phones seen buffering: Redmi Note 12 Pro 5G (`.4`), an "I2512" phone (`.5`).

## Diagnosis — how the ISP/router/QUIC were ruled OUT

Worked outward from the router. Every layer below the Wi-Fi tested clean:

### 1. ISP line — healthy, no bufferbloat
```bash
# sustained direct-path download (bypass any VPN/WARP), from a LAN host:
curl -s --interface 192.168.50.20 -o /dev/null -m 25 \
  -w "dl: %{speed_download} B/s\n" "https://sin-speed.hetzner.com/1GB.bin"
# -> ~9.7 MB/s (~78 Mbit/s), 0% loss, code 200
# concurrent latency under that load stayed ~2.8 ms avg to 1.1.1.1 (no bufferbloat)
ping -c 50 -i 0.5 -I 192.168.50.20 1.1.1.1 -q
# -> min/avg/max 2.0/2.8/8.8 ms, 0% loss
```
Note: `speed.cloudflare.com/__down` returns **HTTP 403 to plain curl** (bot
check) — use Hetzner's `sin-speed.hetzner.com/1GB.bin` for a scriptable
throughput test instead.

### 2. Path MTU — fine (ISP MTU is 1492, not 1500)
```bash
# from a LAN host, don't-fragment probe: 1464-byte payload passes, 1472 fails
for s in 1472 1464 1452; do ping -c1 -M do -s $s 1.1.1.1 >/dev/null 2>&1 \
  && echo "$s ok" || echo "$s FAIL"; done
# 1472 FAIL, 1464 ok  => path MTU 1492 (PPPoE-style 8-byte overhead)
```
The 1492 MTU is a red herring here — the MikroTik/ISP already clamp TCP MSS and
large TCP downloads run without stalls. Not the cause. (MikroTik has a
`change-ttl set:64` mangle rule for the ISP's low-TTL quirk, unrelated to this.)

### 3. MikroTik router — not loaded, no WAN errors
```bash
# login with sshpass (key auth not set up for admin on this box):
sshpass -p '<PW>' ssh -o PubkeyAuthentication=no admin@192.168.50.1 \
  '/system resource print; /interface ethernet print stats where name=ether1'
# cpu-load 6-10%, ether1 rx-fcs-error/align-error/overflow all 0
```

### 4. QUIC (UDP/443) — flowing normally, getting replies
TikTok/IG/YouTube stream mostly over **QUIC = HTTP/3 over UDP 443**. This ISP
blocks most *other* outbound UDP (documented in the OpenVPN/WARP doc), so QUIC
was a prime suspect. But live conntrack showed QUIC working fine:
```bash
sshpass -p '<PW>' ssh -o PubkeyAuthentication=no admin@192.168.50.1 \
  '/ip firewall connection print without-paging where protocol=udp dst-port=443' \
  | tail -n +4 | awk '{print $2, $4, $6}' | sort | uniq -c | sort -rn
# -> 31 flows flagged "SAC" (Seen-reply, Assured, Confirmed) from the phone at .5
#    "SAC" = the S (SEEN-REPLY) flag is set => return traffic IS arriving.
#    If QUIC were being blackholed these would be stuck at "S" with no reply.
```
Firewall-connection flag legend (RouterOS): `S`=seen-reply, `A`=assured,
`C`=confirmed, `F`=fasttrack. Presence of `S` on the UDP/443 flows = QUIC
round-trips completing. So not a QUIC block. (Common internet advice is to
*block* UDP/443 to force TCP fallback — that would NOT have helped here and
would have made streaming worse.)

### 5. Wired path to the AP — clean; delay is past the AP on Wi-Fi
```bash
ping -c 40 -i 0.25 -q 192.168.50.253   # Altos, wired via switch
# -> 0.36/0.55/0.98 ms, 0% loss   (router->switch->AP cabling perfect)

ping -c 60 -i 0.25 -q 192.168.50.4     # Redmi Note 12 Pro over Wi-Fi
# -> avg 152 ms, MAX 510 ms, "pipe 2"   <-- the smoking gun
ping -c 60 -i 0.25 -q 192.168.50.5     # I2512 phone over Wi-Fi
# -> avg 10 ms, spikes to 93 ms
```
Wired = sub-ms. Wi-Fi to the phones = 150–510 ms latency spikes. The delay is
entirely **between the Altos and the phones (the air)**, i.e. Wi-Fi.
Caveat: idle phones inflate ping via power-save, so RSSI/channel data from the
AP is the real confirmation — but combined with the "house in the middle, many
neighbor SSIDs" observation, air congestion was the clear lead.

## Fix

On the Altos AX3000 web UI (`http://192.168.50.253`, `admin`/`admin`):
set the **5 GHz radio to a clean non-DFS channel**. User picked **channel 48**
and buffering stopped immediately. Later, both radios were **locked down via
the API** (see recipe below) to stop the AP re-selecting on its own:

| Band | Channel | Width | Note |
|---|---|---|---|
| 2.4 GHz | 1 | **20 MHz** (fixed) | channel still needs a real neighbor scan to optimize (1/6/11) |
| 5 GHz | **48** | **80 MHz** (fixed) | non-DFS; width pinned so it can't auto-widen into DFS |

**Important finding — the 5 GHz channel DRIFTS on its own.** When re-reading the
config later, 5 GHz had moved from 48 back to **36** by itself (Auto width/Auto
re-selection). So "just set channel 48 once in the UI" was not durable — it has
to be *pinned* (explicit channel + explicit width), otherwise the AP wanders and
the buffering can return. This is the main reason to script/lock it rather than
click it once.

### This AP's actual 5 GHz channel list (from `get/wireless/wlanChannelList`)

```json
[{"band":"2.4G","channels":[1..13],"radarChannels":[]},
 {"band":"5G","channels":[36,40,44,48,52,56,60,64,149,153,157,161,165],
  "radarChannels":[52,56,60,64]}]
```
- Non-DFS 5 GHz here = **36/40/44/48** and **149/153/157/161/165**.
- DFS (radar, must-vacate) = **52/56/60/64** only. The upper **100–144** DFS
  block that other APs use for a clean 160 MHz is **not offered** on this model.
- **160 MHz consequence**: a 160 MHz channel needs 8 contiguous 20 MHz slots.
  On this AP that only fits in the **36–64** block, which *forces DFS* (52–64).
  So 160 MHz here re-introduces radar-vacate freezes — **use 80 MHz**. Streaming
  needs <25 Mbps anyway; 80 MHz (~600–1200 Mbps) is never the bottleneck.

Channel-selection rules (dense-neighbor environment):

- **2.4 GHz**: only **1 / 6 / 11** are non-overlapping — pick the emptiest,
  **always 20 MHz** (40 MHz eats 2 of the only 3 lanes → more collisions).
- **5 GHz**: prefer non-DFS (36–48 / 149–161), **80 MHz**, pinned.
- Keep streaming devices on the **5 GHz** SSID. SSIDs are split here
  (`multiBandSyncEnable:false`), so a phone can get stuck on 2.4 GHz — forget
  + rejoin the 5 GHz SSID on that device.
- **Neighbor scan is unavailable in bridge mode**: `get/wireless/scanList`
  returns code **10005** persistently (the radio won't leave its operating
  channel while serving clients). Use a phone **WiFi Analyzer** app on-site to
  pick the 2.4 GHz channel instead.

## Altos AX3000 (MT602A) web API — VERIFIED working recipe

Device: `deviceModel MT602A`, `softwareVersion V1.0.0`, `workMode: bridge`.
The web app is a React SPA; API structure was reverse-engineered from its JS
bundle (`/static/js/main.<hash>.js`, served **without auth** — that's how the
protocol was mapped) and then confirmed live end-to-end.

**Transport & auth (confirmed):**
- Endpoint: `POST http://<ip>/wjob/web?r=<lastPathSegment>`, body is an **array**
  `[{"method":"<m>","from":"web","data":<obj-or-array>}]`. The `?r=` is just the
  method's last path segment (cosmetic); real routing is the `method` field.
- Login is **challenge/response**:
  1. `get/system/loginChallenge` with `data:{"userName":"admin"}` → returns
     `data.challenge`.
  2. hash = **`HMAC-SHA256(message=<password>, key=<challenge>)`** as lowercase
     hex. (Confirmed: bundle module exports `HmacSHA256`; crypto-js arg order is
     `HmacSHA256(message, key)`, and the call site is `Hmac(password, challenge)`.)
  3. `act/system/login` with `data:{"userName","password":<hash>,"challenge"}` →
     returns `data.token`.
- Authenticated calls send header **`Authorization: <token>`** (raw token, no
  `Bearer` prefix).

**Per-band payloads (gotcha):** the wireless radio methods need a band array or
they return code **10001** (empty). Correct payload:
`data = [{"freqBand":"2.4G"},{"freqBand":"5G"}]` (enum values are the literal
strings `"2.4G"` / `"5G"`). Width enum: `"AUTO"|"20"|"40"|"80"|"160"`.

**Read the current radio config** → returns array of
`{freqBand,bandwidth,wlanMode,channel,powerLevel}` (channel `0` = Auto).

**Set channel/width** — `set/wireless/wlanRadioConfig`, `data` = the **two full
radio objects** (read them first, modify, send back both):
```json
[{"freqBand":"2.4G","bandwidth":"20","wlanMode":"b/g/n/ax","channel":1,"powerLevel":2},
 {"freqBand":"5G","bandwidth":"80","wlanMode":"a/n/ac/ax","channel":48,"powerLevel":2}]
```
code `0` = ok. Radios re-init (a few seconds, briefly drops Wi-Fi clients);
re-read `get/wireless/wlanRadioConfig` (saved) **and**
`get/wireless/wlanRadioInfo` (on-air operating channel) to confirm it stuck.

**91 methods total** (`get/`×44, `set/`, `act/`). Handy reads:
`get/system/devInfo`, `get/network/workMode`, `get/network/staList`
(clients with `linkType` = `2.4G`/`5G`/`WIRED` — **no RSSI field** on this
firmware), `get/wireless/wlanChannelList`, `get/wireless/wlanRadioInfo`.
`get/wireless/scanList` (neighbor scan) returns **10005 in bridge mode** — not
usable here. `get/wireless/wlanSsidConfig` returns 10001 in bridge mode too.

**Reusable client** (built this session, kept in the homelab, not committed to
this repo): a small `altos.py` `Altos` class — `.login()` then `.call(method,
data)`. Re-derivable from this doc if lost.

## Key takeaways

- **Mid-stream buffering on a known-flaky ISP is not automatically the ISP.**
  Rule out layer by layer from the router outward: ISP throughput+bufferbloat,
  MTU, router CPU/WAN errors, QUIC conntrack reply flags, wired-to-AP latency,
  then Wi-Fi air.
- The single clearest signal was **wired-to-AP 0.5 ms vs Wi-Fi-to-phone
  150–510 ms** — that isolates the problem to the air in one comparison.
- On a bridge-mode AP in a dense area, **channel choice is the fix**: non-DFS
  5 GHz (36–48 / 149–161), 2.4 GHz only on 1/6/11.
- **Pin it, don't click it once.** This AP silently re-selected 5 GHz from 48
  back to 36 on its own — the fix only holds if channel *and* width are set
  explicitly (Auto width/channel lets it wander back into congestion/DFS).
- **80 MHz over 160 MHz** on this model: 160 forces DFS (only fits in 36–64),
  and streaming never needs the extra width anyway.

## References

- [UDP-based videos (YouTube) suffer major packet loss, buffering — Ubiquiti Community](https://community.ui.com/questions/UDP-based-videos-Youtube-suffer-major-packet-loss-buffering-issues/422f9548-a0de-4af7-b0e8-2b8f0840904d)
- [why youtube is not blocked? (QUIC/UDP-443 vs TLS-host matching) — MikroTik forum](https://forum.mikrotik.com/viewtopic.php?t=173937)
- [RT-AX3000 firmware breaks WAN detection — SNBForums](https://www.snbforums.com/threads/rt-ax3000-firmware-v-3-0-0-4-386_45898-breaks-wan-detection.75134/)
