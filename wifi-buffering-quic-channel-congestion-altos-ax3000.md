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
and buffering stopped immediately.

Channel-selection rules used (dense-neighbor environment):

- **2.4 GHz**: only **1 / 6 / 11** are non-overlapping — pick the emptiest,
  and use **20 MHz** width (40 MHz in a crowded band just collides more).
- **5 GHz non-DFS** = **36/40/44/48** and **149/153/157/161**: rock-solid,
  never interrupted. Prefer these.
- **5 GHz DFS** = **52–144**: usually emptier (good for dodging neighbors) BUT
  the AP must vacate for up to **60 s** if it detects radar — that vacate looks
  *exactly* like a mid-video freeze. Only use DFS if non-DFS is congested and
  you don't then get random dropouts.
- Width **80 MHz** if the band is fairly clean, drop to **40 MHz** if busy.
- Keep streaming devices on the **5 GHz** SSID.
- Use the AP's own Wi-Fi scan/survey (Altos: Basic → WiFi → Advance) to see
  which channels neighbors occupy instead of guessing.

## Altos AX3000 web API notes (for future automation)

Did NOT end up needing to script the AP login (user read/changed settings in
the UI), but for next time — the Altos web app is a React SPA calling:
- Endpoint: `POST /wjob/web?r=<lastPathSegment>`, JSON body
  `[{"method":"<m>","from":"web","data":{...}}]`.
- Login is **challenge/response**, not plaintext: first
  `get/system/loginChallenge` (`data:{userName}`) returns a `challenge`, then
  the password is HMAC'd with it and sent to `act/system/login`. Bundle
  references HmacSHA256 (also SHA1/MD5/SHA512 present).
- Useful read methods: `get/wireless/scanList` (neighbor APs),
  `get/wireless/wlanChannelList`, `get/wireless/wlanRadioConfig`,
  `get/wireless/wlanRadioInfo`, `get/network/staList` (associated clients +
  signal). Write: `set/wireless/wlanRadioConfig` (channel/width).

## Key takeaways

- **Mid-stream buffering on a known-flaky ISP is not automatically the ISP.**
  Rule out layer by layer from the router outward: ISP throughput+bufferbloat,
  MTU, router CPU/WAN errors, QUIC conntrack reply flags, wired-to-AP latency,
  then Wi-Fi air.
- The single clearest signal was **wired-to-AP 0.5 ms vs Wi-Fi-to-phone
  150–510 ms** — that isolates the problem to the air in one comparison.
- On a bridge-mode AP in a dense area, **channel choice is the fix**: non-DFS
  5 GHz (36–48 / 149–161), 2.4 GHz only on 1/6/11.

## References

- [UDP-based videos (YouTube) suffer major packet loss, buffering — Ubiquiti Community](https://community.ui.com/questions/UDP-based-videos-Youtube-suffer-major-packet-loss-buffering-issues/422f9548-a0de-4af7-b0e8-2b8f0840904d)
- [why youtube is not blocked? (QUIC/UDP-443 vs TLS-host matching) — MikroTik forum](https://forum.mikrotik.com/viewtopic.php?t=173937)
- [RT-AX3000 firmware breaks WAN detection — SNBForums](https://www.snbforums.com/threads/rt-ax3000-firmware-v-3-0-0-4-386_45898-breaks-wan-detection.75134/)
