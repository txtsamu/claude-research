---
type: investigation
tags: [samsung, tizen, kants2, t6500, power, standby, wol, ex-link, mdc, suspend, sdb]
created: 2026-10-25
last_verified: 2026-10-25
status: current
---

# The nine ways to turn a Samsung TV "off" — and which ones you can undo from software

Target: `UA43T6500AKXXD`, Samsung KantS2 / Novatek NT72172, Tizen 5.5, kernel 4.1.10 armv7,
firmware tag `20_KANTS2_FHD`, `192.168.50.31`, root via the `/dev/ntkhdma` + UEP chain.

Written after powering the set off over the network with `systemctl poweroff` from the root
shell and then being **unable to wake it again**: ~4 minutes of Wake-on-LAN bursts (UDP 9 and 7 to
`255.255.255.255`, `192.168.50.255` and the TV's own IP) did nothing, because a systemd power-off
is not standby — it takes the network controller down with the SoC. Only the IR remote brought it
back. The taxonomy below is what the research turned up, with our own measurements mixed in.

## 1. Taxonomy: every "off" this class of TV has

### Panel-level (SoC stays fully powered)

**Picture Off / Screen Off.** Panel and backlight go black; CPU, Wi-Fi/Ethernet, audio decoder keep
running, and audio continues if it was playing. Saves on the order of 60–70 % of the active
draw — still tens of watts, so it is *not* off in any useful sense.
Menu: `Settings > All Settings > General & Privacy > Accessibility > Picture Off`.
Wake: any remote key.
Useful when you want the TV "silent" but reachable — services, sdb and `:8001` all keep answering.

### Standby-class (the remote can always undo these)

**Standard standby** — what the remote's power button does. The MICOM (always-on
microcontroller) keeps the 5 V standby rail: IR receiver, front LED, and the network interface if
network standby is enabled. Typical draw ~0.5–1 W. Wake paths: IR, HDMI-CEC, WoL magic packet,
SmartThings, Ex-Link "power on". This is the **only** off-state that is reversible without
physical access.

**Network standby / WoWLAN ("Power on with Mobile").**
`Settings > Connection (or General) > Network > Expert Settings > Power on with Mobile`
(older firmware calls it "Mobile Device Connection" or "Remote Start"). Keeps the NIC listening in
a low-power state for magic packets, SmartThings and BLE handshakes; prerequisite for WoL. Wired
Ethernet is markedly more reliable than Wi-Fi — plenty of APs drop magic packets to sleeping
wireless clients.

**Timers / eco transitions.** Sleep Timer, Off Timer, Auto Power Off (no signal), Eco Solution
ambient dimming. All of them land in plain standby; none do a full power-down.

### Software-level (what we can drive with root)

**Suspend.** This kernel offers `freeze mem` in `/sys/power/state`, so `echo mem > /sys/power/state`
suspends the SoC. Closest thing to a wakeable screen-off we can trigger ourselves. Not yet
measured on this set (see "Open measurements").

**Full system power-off (`systemctl poweroff`).** MICOM drops the SoC rail. Measured timeline
below. One-way from software.

**Wall unplug.** 0 W, nothing wakes it. What a real "off" costs.

### Vendor extras (not on the T6500)

**Art / Ambient mode** (The Frame, QLED Ambient): panel shows artwork at low brightness; draw
above standby, below normal viewing. Not present on this firmware.

## 2. Measured: what `systemctl poweroff` actually does here

Sent as root through the SUID helper: `/opt/hermes_root -p -c 'systemctl poweroff --no-block'` →
`rc=0`, no output, no error. Then:

| t | observation |
|---|---|
| +12 s | `:8001` (app framework) and `:8002` (remote-control websocket) refuse connections; ICMP still answers at ~9 ms |
| +37 s | same, **but `:26101` (sdbd) still has a listener** — a stale socket in the residual stack, not a live daemon |
| +90 s | ICMP **100 % loss**, no ARP reply from `arping`, no ports |
| +90 s…~5 min | 3 WoL bursts × 3 destinations × UDP 9/7, plus repeats: **nothing**. The NIC is off, so there is nothing to receive the packet |

Two lessons: an open `:26101` is **not** proof the TV is awake (check `:8001`), and
`systemctl poweroff` must never be scheduled unattended — only the remote or the physical button
brings the set back. `systemctl reboot` from the same shell still refuses with `Must be root.`, so
cold-boot tests stay with the user.

## 3. Control channels, from best to worst for automation

**Ex-Link (3.5 mm jack on consumer sets, RS-232 over an Ex-Link/USB-serial dongle).**
Frame starts `08 22`; power commands append `00 00 00 01` (off) or `00 00 00 02` (on); checksum is
`256 − sum(all bytes after the header)` expressed as hex.

- TV off: `08 22 00 00 00 01 D5`
- TV on: `08 22 00 00 00 02 D6`

Enable on a consumer set: TV off, `MUTE 1 8 2 Power` on the IR remote (service menu) →
`Control > Sub Option` → **EXT Link Support** and **USB Serial** = ON → power cycle.
Two documented quirks: the reply to *power off* is a stable acknowledgement (`03 0C F1` style)
while the reply to *power on* is ragged garbage, so never gate logic on parsing it; and in deep
eco standby the serial receiver may be powered down, in which case **power-off works and power-on
can never work** — the same failure shape as our WoL result.

**MDC over TCP/1515** (commercial displays; header `0xAA`, command `0x11` = power, ID `0x01`,
broadcast `0xFE`, checksum = low byte of the sum of command+id+len+data).
Power off: `AA 11 01 01 00 13`. Power on is widely reported **not** to work over IP even when
power off does.

**SmartThings / websocket `:8002`** (`ms.remote.control`, `KEY_POWER`). Needs a per-TV token that
must be approved on screen. On this T6500 the `ms.channel.connect` handshake never completes, so no
key is ever delivered — that is why the obvious "turn it off over the network" route never worked
here, and it means KEY_POWER is not available to us either (see
[samsung-tv-t6500-root-and-persistence.md](samsung-tv-t6500-root-and-persistence.md) for the token attempts).

**WoL magic packet** — `64:E7:D8:EC:38:EE`, UDP 9/7 broadcast; works **from standby only**, and
only with network standby/"Power on with Mobile" enabled.

**Root shell + `/sys/power/state`** — suspend (`freeze mem`), the only software path that has a
chance of staying wakeable.

**HDMI-CEC** — out of scope here, no CEC controller on the host side.

## 4. What to use

- Want it to go dark but stay reachable (deploys, sdb sessions, hook work)? **Picture Off** or
  **suspend**, never `poweroff`.
- Want it off the way a human means it, but still recoverable? **`KEY_POWER` via a token'd
  websocket**, or **Ex-Link power off** if the port is enabled and the dongle is wired.
- Anything scheduled or unattended: **standby-class only**. A `systemctl poweroff` in a cron job
  ends with a TV that needs a human standing in front of it.

## 5. Open measurements

1. Does suspend (`echo mem > /sys/power/state`) keep `:26101` / `:8001` / ICMP alive, i.e. is it
   wakeable over the network? Highest-value unknown.
2. Confirm **IR wakes from a `systemctl poweroff`** state (expected: yes, MICOM's IR receiver runs
   off the standby rail) — the practical escape hatch if 1 fails.
3. Whether this firmware exposes "Power on with Mobile", and whether WoL from true standby is
   reliable on wired Ethernet here. Worth testing before trusting WoL in any automation.
4. Whether Ex-Link exists on this chassis at all (jack or service-menu option).

## References

- Samsung, *Consumer RS-232 Control* worksheet (command list + service-menu setup):
  <https://image-us.samsung.com/SamsungUS/samsungbusiness/tv-ci-resources/Samsung-RS232-Control.pdf>
- SoftControl, *Samsung Ex-Link Commands: Pinout, Hex Codes and a Checksum Worth Verifying* —
  source of the verified `08 22 00 00 00 01 D5` "TV off" frame, the checksum rule, the ragged
  power-on reply, and the deep-standby caveat:
  <https://softcontrol.io/en/blog/samsung-ex-link-commands>
- Just Add Power, *Samsung RS232 Codes (Ex-Link)*: <https://support.justaddpower.com/kb/article/16-samsung-rs232-control-exlink/>
- Remote Central, *Samsung TV RS232 Codes for Ex-Link* (service-menu `MUTE 1 8 2 Power` entry):
  <https://www.remotecentral.com/cgi-bin/mboard/rs232-ip/thread.cgi?603>
- Samsung, *Multiple Display Control (MDC) Protocol* v13.7c (the `0xAA` framing used by commercial
  panels): <https://aca.im/driver_docs/Samsung/MDC%20Protocol%202015%20v13.7c.pdf> ·
  mirror <https://vgavro.github.io/samsung-mdc/MDC-Protocol.pdf>
- Samsung support: *Power on with Mobile / Network Standby* location (Connection → Network →
  Expert Settings), and the general standby-vs-screen-off distinction (Samsung community + support
  articles surfaced via search; no single canonical page).
