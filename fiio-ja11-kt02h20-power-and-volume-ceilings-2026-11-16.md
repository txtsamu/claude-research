---
type: investigation
tags: [fiio, jadeaudio, ja11, kt02h20, usb-dac, uac, power, vbus, volume, peq, hid, diskos, snowsky-disc]
created: 2026-11-16
last_verified: 2026-11-16
status: current
---

# FiiO JadeAudio JA11: what it draws, what its output ceiling really is, and where the lost volume sits

Request: "how much power is being use for the my JA11 now? can we adjust it so it can give maximum sound output? check on internet how JA11 works so we can maximize the JA11 potential". Context: the JA11 was playing through diskOS on the Snowsky Disc over the `OUT_USB` route (see [[diskos-usb-audio-normal-build-hotload-2026-11-16]]).

By the time the measurements were wanted, the JA11 had been unplugged: `dmesg` `[882.088853] usb 1-1: USB disconnect, device number 3`, `/proc/asound/cards` back to `x2000` only, no `/dev/hidraw*`. The disconnect was handled cleanly: `diskos_journal.log` shows `dacvol: left, Player volume back to 72`, `usbhid: closed event2`, and `audio: reapply gain=1 dre=-1 filter=4`.

## What the JA11 is

- USB `2972:0102`, `bcdUSB 2.01`, high speed, one configuration.
- Chip: **KT Micro KT02H20** DSP, not a Cirrus, ESS or AKM DAC. Confirmed by the open tool `Ircama/ja11-config`, which targets `2972:0102` as a known KT02H20 device.
- FiiO rates it at **30 mW per channel into 32 ohms** (PCM up to 384 kHz/32-bit, DSD128 (DoP only), 3.5 mm single-ended, mic and CTIA/OMTP inline controls), output impedance 0.5 ohm, output noise 1.7 uV.
- Published draw: **0.03 A / 0.16 W** (Ichos Reviews and the same reviewer on Head-Fi, 2024), idle until a headphone is plugged in.
- DSP features, all configurable over USB HID: 5-band parametric EQ, five DAC reconstruction filters (FAST-LL, FAST-PC, Slow-LL, Slow-PC, NON-OS), and a global preamp of **-12 to +12 dB**, persistable to the dongle's flash.

## How the port powers it

The OTG port is not a fixed 5 V rail. The **SGM41513** charger IC (i2c-2, `0x1a`) runs in boost mode and makes VBUS from the battery:

```
$ dmesg | grep SGM41513
[  909.499803]  SGM41513_OTG_ON: OTG enabled, 5V output
[  910.267084]  SGM41513_OTG_ON: OTG enabled, 5V output
[  910.301376]  SGM41513_OTG_ON: OTG enabled, 5V output
```

Registers read with a small static mipsel `i2cget` (`/tmp/i2cr 2 1a 00 12`, ioctl `I2C_RDWR`):

```
reg 0x01 = 0x26   D5 OTG_CONFIG=1 (OTG on), D4 CHG_CONFIG=0 (charging off)
reg 0x02 = 0x21   D7 BOOST_LIM=0  -> 0.5 A boost current limit
reg 0x06 = 0xe6   D5:4 BOOSTV=10  -> 5.15 V VBUS
reg 0x08 = 0xe0   VBUS_STAT=111   -> the Disc is sourcing VBUS (OTG)
```

Datasheet (SGM41513/SGM41513A/SGM41513D, April 2025): `BOOST_LIM` is `0 = 0.5 A`, `1 = 1.2 A (default)`, and `BOOSTV` `10 = 5.15 V (default)`. So this unit runs a **0.5 A boost**, even though the chip can do 1.2 A. Boost efficiency at 0.5 A is quoted at 93.5 percent.

That sets the supply ceiling at `5.15 V x 0.5 A = 2.6 W`.

## Power: what the JA11 actually takes

Published measurements, not estimates. Ichos Reviews (Petros Laskis, July 2024) and the same reviewer's Head-Fi entry both state **0.03 A / 0.16 W**, and add that "the JA11 remains inactive until you connect an earphone, ensuring no power is wasted". At 5.15 V that is `0.03 A x 5.15 V = 0.155 W`, so the two figures agree.

Against the port's 2.6 W ceiling that is about **16x headroom**, and it means the `BOOST_LIM = 0.5 A` setting is nowhere near a bottleneck. Draw nothing when idle, 0.16 W when playing sensitive IEMs: that is the whole power story.

The USB descriptor over-declares for safety:

```
/sys/bus/usb/devices/1-1/bMaxPower = 98mA
```

At 5.15 V that is 0.50 W, three times the measured figure. USB devices routinely declare a class budget rather than their real draw, which is exactly why the measured number matters.

On the battery side, 0.16 W through the boost at 93.5 percent efficiency costs about **0.17 W**. Negligible next to the SoC, the screen and Wi-Fi.

The Disc still cannot measure any of this live. `/sys/class/power_supply/cw221X-bat/current_now` reads `0`, there is no `power_now`, the OTG port exposes no accounting, and the SGM41513's ADCs measure the input side, not the boost output.

Raising `BOOST_LIM` to 1.2 A is possible in principle (write REG02 bit 7), but pointless here: the JA11 measured 0.03 A against a 0.5 A allowance, more current cannot raise its 30 mW amplifier, and writing a charger register behind the driver's back invites the watchdog to undo it.

## Where the missing volume actually is

Measured from the device while the JA11 was attached:

```
$ amixer -c1 get PCM
Front Left: Playback 57 [57%] [-21.50dB] [on]
Front Right: Playback 57 [57%] [-21.50dB] [on]

$ grep -a -E 'max_vol|usb_audio_vol' /usr/data/diskos.conf
max_vol=100
usb_audio_vol=60
```

Two attenuators stack:

1. `max_vol=100` caps the UI scale at 100 of `VOL_MAX` 120, and `dacvol_map()` maps 100 to **83 of 100 on the DAC's feature unit**, about -8.5 dB.
2. The current level was 57%, about **-21.5 dB**.

The player itself is held at 120 (unity) by `dacvol`, so it contributes no attenuation. `dac_safe_start=60` percent caps the level at attach (`SAFE_START_PCT`), which is a hearing-safety start, not a hardware limit.

Reaching 0 dB means removing the `max_vol` cap and setting `usb_audio_vol` to 120, or writing the feature unit to 100 directly. That is **+21.5 dB**, roughly 12x the voltage. It is a volume change, not more power.

## Can the DSP make it louder?

No, and this is the part worth being blunt about. The global preamp is digital gain **before** the PEQ. Raising it +12 dB raises the digital level into the DAC and clips as soon as the material approaches 0 dBFS. It cannot lift the amplifier's 30 mW. The five DAC filters change character, not level.

So the JA11's ceiling is fixed by its hardware: 30 mW into 32 ohms. It suits sensitive IEMs. For real loudness the Disc's own 4.4 mm balanced output from the four CS43131s has far more headroom, which is the opposite direction from routing through USB.

## Reusable facts

- `amixer -c1 get PCM` is the live view of the JA11's feature unit: percent and dB, `0..100` over `-50..0 dB`.
- `bMaxPower` under `/sys/bus/usb/devices/<bus>-<port>/bMaxPower` is the only power figure the Disc can report for a bus-powered device.
- The JA11's HID config protocol, from `Ircama/ja11-config`: HID output report ID `0x02`, set packet `aa 0a 00 00 <cmd> <len> [payload] ee`, commands 17 DAC filter, 21 PEQ band, 23 global gain, 24 apply, 25 save to flash. Gain is signed Q12 (value x 10) big-endian, frequency unsigned 16-bit big-endian, Q is Q2 (value x 100), global gain is value x 2560 little-endian.
- FiiO firmware for the JA11 has a web PEQ editor and app-driven updates (V1.9 changelog notes PEQ on the computer webpage and a fix for a custom gain that would not save).

## Not verified

- Actual JA11 current draw, only its 98 mA declaration. Nothing on the Disc measures boost output current, and no external USB power meter was in the path.
- Whether the driver set `BOOST_LIM = 0.5 A` on purpose or inherited it from the chip's driver default. The bit is clear, the datasheet default is 1.2 A.
- Whether `dacvol`'s 0 dB level sounds acceptable before the JA11's amp clips into the user's IEMs. Must be stepped up by ear.
- Whether a 0 dB feature unit plus a near-0 dBFS file clips at the KT02H20's digital stage.
- Any diskOS-side HID tool for the JA11. The protocol is documented, but nothing was built or run on the Disc.

## References

- `Ircama/ja11-config` (EUPL-1.2): TUI plus `ja11-boot`/`ja11-flash`, protocol and packet layouts.
- FiiO JA11 product page and support articles.
- [[diskos-usb-audio-normal-build-hotload-2026-11-16]]
- [[diskos-usb-audio-headset-click-gestures-and-flash]]
