---
type: investigation
tags: [ktmicro, helios, kt02h20, fission, ja11, chu2-dsp, usb-audio, uac, otg, xiaomi, hidraw, fedora]
created: 2026-10-27
last_verified: 2026-10-27
status: current   # JA11=KT02H20 (firmware chip ID), Chu II=KT0210-class (chu2-studio), Fission chip unconfirmed; same KTMicro family/protocol, not provably identical parts; OTG cause unresolved
---

# Are the Fission, JA11 and Chu II DSP dongles the same chip? (and why only the Chu II needs OTG on)

Context: three USB-C DSP dongles got the same Tin HiFi C7 EQ (see [tanchjim-fission-ktmicro-dsp-peq-match-tin-hifi-c7.md](tanchjim-fission-ktmicro-dsp-peq-match-tin-hifi-c7.md), [fiio-ja11-peq-match-tin-hifi-c7-hidraw.md](fiio-ja11-peq-match-tin-hifi-c7-hidraw.md), [moondrop-chu2-dsp-ktmicro-peq-match-tin-hifi-c7.md](moondrop-chu2-dsp-ktmicro-peq-match-tin-hifi-c7.md)). The user's phone only recognises the Chu II when Android/MIUI "OTG" is enabled, but not the other two. Questions: same chip? is it the UAC version?

> **Files:** `~/sessions/2026-10-26-iem-dsp-eq/` — `dump_regs.py`, `data/regs_{chu2,fission,ja11}.json` (full 256-register dumps).

## Method (all read-only)

USB descriptors need no root:

```bash
lsusb -v -d 31b2:0113 | grep -E "idVendor|idProduct|bcdDevice|iManufacturer|iSerial|bcdADC|MaxPower|bNumInterfaces"
lsusb -v -d 31b2:0101 | grep ...        # Fission
lsusb -v -d 2972:0102 | grep ...        # JA11
```

Registers: `dump_regs.py` reads `0x00..0xFF` with the KTMicro `0x52` read command only (never `0x57`/`0x53`/`0x43`/`0x54`):

```python
import json, os, sys
sys.path.insert(0, 'ktm')                      # gxcreator/ktmicro-tools clone
from kt02h20 import KT02H20
vid, pid, label = int(sys.argv[1], 16), int(sys.argv[2], 16), sys.argv[3]
d = KT02H20(vid, pid)
if not d._hid.open(): sys.exit("open failed")
regs = {a: d.read(a) for a in range(0x100)}
json.dump({hex(a): (None if v is None else hex(v)) for a, v in regs.items()}, open(f'data/regs_{label}.json', 'w'))
d.close()
```

```bash
sudo ./venv/bin/python -I dump_regs.py 31b2 0113 chu2
sudo ./venv/bin/python -I dump_regs.py 31b2 0101 fission
sudo ./venv/bin/python -I dump_regs.py 2972 0102 ja11
```

All 256 registers answered on all three, including the JA11 on FiiO firmware (its HID descriptor still has the `0x4B` KTMicro channel next to FiiO's report ID `0x02` channel).

## Results

| | Fission `31b2:0101` | JA11 `2972:0102` | Chu II DSP `31b2:0113` |
|---|---|---|---|
| `REG:` marker `0x00` | `0x3a474552` | same | same |
| Version string | 1.0.1 | **2.2.0** | 1.0.1 |
| Manufacturer / product | KTMicro / FISSION-Rational HiFi Edition | FIIO / JadeAudio JA11 | KTMicro / Chu2 DSP |
| Serial string | `2021-11-15-0000-0000-0000-` | `2020-02-20-0000-0000-0000` | `2020-02-20-0000-0000-0000` |
| Mic EQ factory bands | 1000/2000/5000/8000/10000 Hz Q0.707 | same | same |
| DAC EQ band regs | `0x26–0x2F` | same | same |
| Model flags `0x01` | `0x1` | `0x200` | `0x200` |
| DAC EQ enable `0x24` | `0x1` | `0x5` (USER1 active) | `0x3` |
| ADC EQ enable `0x18` | `0x0` | `0x2` | `0x2` |
| PGA ADC `0x3A` / DAC `0x3B` | `0x5` / `0xd` | `0x4` / `0xd` | `0x3` / `0xd` |
| `0x65` / `0x66` | `0x0` / `0x0` | `0x100` / `0x200` | `0x100` / `0x200` |
| UAC | 1.0 | **2.0** (IAD, `bcdUSB` 2.01) | 1.0 |
| `bcdDevice` | 1.01 | 2.20 | 0.03 |
| Power | bus, 100 mA | bus, 98 mA | bus, 98 mA |
| Interfaces | 4 (control, mic, playback, HID) | 4 | 4 |
| Needs phone OTG on | no | no | **yes** |

## Conclusions

- **Same family, yes.** All three speak the same Helios-class KTMicro register protocol with an identical band layout (DAC bands `0x26–0x2F`), `REG:` marker and mic-EQ factory defaults. The JA11 (FiiO firmware flashed onto a KT02H20, see [kt02h20-jcally-dac-ja11-firmware-flash-protocol.md](kt02h20-jcally-dac-ja11-firmware-flash-protocol.md)) shows the **same DAC band values through the `0x4B` registers that were written through FiiO's report-ID-2 protocol**, so both channels address one DSP state.
- **Chu II and JA11 are the most alike**: same model flag (`0x200` = single-DAC, per ktmicro-tools protocol notes), same `0x18`, `0x65`, `0x66` values and the same SDK-default serial string. The Fission is configured differently (`0x01 = 0x1`, simple `0x24` bit0 enable).
- **Same *die* is not provable from the device, but the internet answers most of it** (searched 2026-10-27; no teardown/die photo exists for any of the three):
  - **JA11 = KTMicro KT02H20.** FiiO never names the chip, but the community flasher projects report the chip-ID handshake returns `KT02H20B` ([SMIPE444 toolkit](https://github.com/SMIPE444/fiio-ja11-jcally-jm12-moondropkt02-kt02h20-dac-amp-toolkit), [txtsamu/kt02h20-flasher](https://github.com/txtsamu/kt02h20-flasher)); the same silicon is in the JCALLY JM12 and Moondrop KT02 dongles. Firmware-derived, not a teardown.
  - **Chu II DSP = "KT0210-class".** [jcharvet/chu2-studio](https://github.com/jcharvet/chu2-studio) (`docs/PROTOCOL.md`) tested this exact `31b2:0113` unit on hardware: identity registers `PerfCfg:`, `KTMicro`, `Chu2 DSP`, `2020-02-20-0000-0000-0000`, VID/PID `31b2:0113`; read/write/commit `0x52/0x57/0x53` work, commit restarts the dongle, an unsaved write is lost on unplug — all matching what we saw. The "KT0210" label is their inference from KTMicro's marketing pages plus [devicePEQ](https://github.com/jeromeof/devicePEQ)'s `ktmicroUsbHidHandler.js` (which lists "Chu2 DSP", 5 bands ±12 dB, shelves allowed). Also noted there: shelf types 3/4 (low/high) work on this device.
  - **Fission = KTMicro KT0211L** (found 2026-10-27, after the original search): the vendor firmware file is named `KT0211L_fission_rational_hifi_edition_v1.0.1_20250610.bin` and the dongle's bootloader answers CHP `0211LC02` (see [fission-rational-hifi-firmware-upgrade-linux-flasher-ktmicro-kt0211l.md](fission-rational-hifi-firmware-upgrade-linux-flasher-ktmicro-kt0211l.md)). So the three dongles are three different part numbers of one family: JA11 = KT02H20, Fission = KT0211L, Chu II = KT0210-class (inferred).
  - So they are **probably two different KTMicro part numbers (KT02H20 in the JA11, KT0210-class in the Chu II), in one family with one HID protocol**, not literally one identical part. KTMicro's own comparison of KT0210/KT0211/KT0211L ([warmseaic](https://warmseaic.com/kt-article/quantum-micro-kt0210-kt0211-kt0211l-comparison)): similar core architecture, KT0210 and KT0211 share a QFN40 package and differ mainly in DSP feature set (KT0211L is QFN32 with built-in DC/DC); all 2-ch DAC 24-bit/96 kHz, 1 ADC, UAC 1.0. KT02H20 is not covered on either KTMicro-side page, so its relationship to KT0210 is not documented. [kt0231h CHIPS.md](https://github.com/eyad-elghareeb/kt0231h/blob/master/CHIPS.md) lists KT02H20 and KT0210 as separate rows with the same protocol.
- **"Chu 2 DSP is not KTMicro / is Bestechnic" (CHIPS.md) is contradicted** by chu2-studio's hardware testing and by our own device (KTMicro manufacturer string under VID `31b2`, `REG:` map, SAVE `0x53` works). Treat the CHIPS.md claim as wrong or about a different variant.
- **UAC version does not explain the OTG behaviour.** JA11 (UAC 2.0) and Fission (UAC 1.0) work without the toggle; Chu II (UAC 1.0, same as the Fission) does not. The USB descriptors of Fission and Chu II are near-identical (UAC1, 4 interfaces, 1-ch mic, HID iface 3, ~100 mA), and the register config of Chu II equals JA11's, which also works without OTG. So neither audio class, descriptor shape, power draw nor register config separates the Chu II. The cause is more likely phone-side (per-device handling on MIUI/HyperOS, cable, or the OTG switch timing).

## Register-by-register diff: JA11 vs Chu II (2026-10-27)

From the saved dumps (`data/regs_ja11.json`, `data/regs_chu2.json`, `data/regs_fission.json` in the session folder):

```bash
python3 - <<'PY'
import json
a=json.load(open('data/regs_ja11.json')); b=json.load(open('data/regs_chu2.json'))
diff=[k for k in a if a[k]!=b[k]]
print(len(a)-len(diff), 'identical of', len(a))
for k in diff: print(k, a[k], b[k])
PY
```

**229 of 256 registers identical; 27 differ**, all explained: version string (`0x04–0x05`: 2.2.0 vs 1.0.1), build date/time + hash (`0x08–0x11`), DAC EQ enable (`0x24`) and the five DAC bands (`0x26–0x2F`, set by us to the C7 fits), mic PGA (`0x3A`: 4 vs 3), USB manufacturer/product strings and VID/PID (`0x40–0x4B`, `0x5B`). Everything else matches, including model flag `0x01 = 0x200`, mic EQ bank and defaults, and gain regs `0x65/0x66`. Fission matches the Chu II on 218/256 and the JA11 on 215/256 (it differs additionally in `0x01`, `0x18`, `0x65`, `0x66`), so JA11 and Chu II are the closest pair, but most of the map is shared factory defaults.

Firmware build stamps (registers `0x04`, `0x08–0x0D`) show three different builds:

| Dongle | Version | Build date | Build time |
|---|---|---|---|
| Chu II DSP | 1.0.1 | Aug 28 2023 | 10:41:48 |
| Fission | 1.0.1 | May 6 2025 | 13:37:56 |
| JA11 | 2.2.0 | Jul 8 2025 | 19:24:29 |

"Layout" here means register layout; physical board/chip layout cannot be determined from software (needs a teardown).

## Glossary (plain-language)

- **Register** — a numbered slot inside the chip holding one setting or readout (e.g. `0x24` = EQ enable, `0x26–0x2F` = the five EQ bands). Read with `0x52`, written with `0x57`. A write changes RAM only.
- **Flash memory** — storage that keeps data without power (as opposed to RAM). Holds the firmware and saved settings; the vendor SAVE `0x53` copies the current register values into flash, which is what made the EQ survive unplugging. Limited write cycles; these chips have ~256 KB internal flash and no software read-back.
- **Firmware** — the program the chip runs (stored in flash): presents the USB audio device, drives the DAC, applies EQ, answers register commands. Changing EQ bands is a settings change; flashing firmware replaces the program and is risky (no backup possible in software).

## Where the three dongles stand (2026-10-27)

| Dongle | Chip (evidence) | Firmware | C7 EQ |
|---|---|---|---|
| Tanchjim FISSION-Rational HiFi Edition `31b2:0101` | KT0211L (firmware file name + bootloader CHP `0211LC02`) | upgraded May 6 2025 -> **Jun 10 2025** from Linux ([how-to](fission-rational-hifi-firmware-upgrade-linux-flasher-ktmicro-kt0211l.md)) | saved, survives replug |
| FiiO JadeAudio JA11 `2972:0102` (cross-flashed JM12) | KT02H20 (`KT02H20B` from flasher projects) | V2.2 (2.2.0, build Jul 8 2025) = latest FiiO release | saved, survives replug |
| Moondrop Chu II DSP `31b2:0113` | KT0210-class (inferred, chu2-studio) | 1.0.1 (build Aug 28 2023); no update published | saved, survives replug |

## Other devices that share the Chu II's chip family (searched 2026-10-27)

Source of truth for "speaks the same KTMicro `0x4B` register protocol": [jeromeof/devicePEQ `usbDeviceConfig.js`](https://github.com/jeromeof/devicePEQ/blob/master/devicePEQ/usbDeviceConfig.js) (VID `0x31B2` block), cross-checked with [BunnyDSPLinux](https://github.com/onbot7/BunnyDSPLinux) and [kt0231h CHIPS.md](https://github.com/eyad-elghareeb/kt0231h/blob/master/CHIPS.md).

| Device | Brand | Evidence | Chip claim |
|---|---|---|---|
| **Tanchjim Bunny DSP** | Tanchjim | BunnyDSPLinux: hardware-tested, USB `31b2:1112`, "KTMicro KT0210" | **KT0210 (explicit)** — the only device I found with the KT0210 label. CHIPS.md also lists its EQ-enable as `0x24`: `0x03` = custom on, `0x02` = bypass — the same encoding the Chu II shows (`0x24 = 3`) |
| **Moondrop CDSP** (cable) | Moondrop | devicePEQ entry, same config as Chu2 DSP | not stated; same maker/protocol |
| **Moondrop Chu2 DSP** | Moondrop | devicePEQ + chu2-studio hardware tests | KT0210-class (inferred) |
| Tanchjim One DSP | Tanchjim | devicePEQ (`baseRegisterOffset 0x26`) | not stated |
| Tanchjim Fission / Fission DSP | Tanchjim | devicePEQ; our dump | not stated |
| Kiwi Ears Allegro PRO / Allegro Mini | Kiwi Ears | devicePEQ (5 bands from `0x26`, `disconnectOnSave`) | not stated |
| Kiwi Ears KT_0211L / KT_1132L / KT_3016L | Kiwi Ears | devicePEQ, matched by productId; names suggest KT0211L / KT1132L / KT3016L parts | KT0211L-class etc. (names only) |
| JCally "KT02H20 HIFI Audio" (JM12), Moondrop KT02 dongle, FiiO JA11, Tanchjim DSP S | various | flasher projects, CHIPS.md | KT02H20 / KT0211L (related, different part numbers) |
| Space Gaming IEM (`31b2:0001`) | — | devicePEQ marks it experimental; it does **not** answer the `0x4B` protocol | unknown |

Caveats: no teardown names the chip in any of these cabinets except the Bunny DSP (KT0210, via the Linux driver's hardware testing); the rest is "same vendor ID + same protocol + same maker pipeline". KTMicro's [KT0210 page](https://www.ktmicro.com/?usb_104/301.html) lists no customers. A KZ Duet USB-C listing claims a "built-in DSP sound card" but names no chip, so I did not count it.

## OTG on Xiaomi (what the internet says)

- Xiaomi's own FAQ: HyperOS/MIUI has a separate OTG switch (Settings → Additional settings → OTG) to be turned on before connecting a third-party device, and it **turns itself off after about 10 minutes of inactivity**.
- A Samsung community thread: a USB-C DAC failed on a direct C-to-C cable but worked through an OTG adapter.
- One low-quality Chu II article: USB mode must not be "Charging only"; random dropouts on a Redmi Note 9T fixed by disabling MIUI optimisation (single anecdote).
- Android's native USB audio is UAC1-centred; UAC2 is the variable one (a Fairphone 4 saw a UAC2 interface as a headset but silent).
- No source found explaining why one specific dongle needs the toggle. Untested ideas: `adb shell dumpsys usb` with OTG off to see whether the phone enumerates the Chu II at all; test with a different cable; check whether the toggle's 10-minute auto-off is what looks like "needs OTG".

## References

- [jeromeof/devicePEQ usbDeviceConfig.js](https://github.com/jeromeof/devicePEQ/blob/master/devicePEQ/usbDeviceConfig.js) — list of VID `0x31B2` devices and their handlers
- [onbot7/BunnyDSPLinux](https://github.com/onbot7/BunnyDSPLinux) — Tanchjim Bunny DSP = KTMicro KT0210, `31b2:1112`

- [kt0231h CHIPS.md](https://github.com/eyad-elghareeb/kt0231h/blob/master/CHIPS.md) and [PROTOCOL.md](https://github.com/eyad-elghareeb/kt0231h/blob/master/PROTOCOL.md) — Helios-class chip table, per-chip register differences, the "Chu 2 DSP not KTMicro" claim
- [jcharvet/chu2-studio PROTOCOL.md](https://github.com/jcharvet/chu2-studio/blob/main/docs/PROTOCOL.md) — hardware-tested Chu 2 DSP (`31b2:0113`) protocol, KT0210-class attribution
- [jeromeof/devicePEQ](https://github.com/jeromeof/devicePEQ) — `ktmicroUsbHidHandler.js`, lists "Chu2 DSP"
- [KTMicro KT0210 product page](https://www.ktmicro.com/?usb_104/301.html) and [warmseaic KT0210/KT0211/KT0211L comparison](https://warmseaic.com/kt-article/quantum-micro-kt0210-kt0211-kt0211l-comparison)
- [SMIPE444 KT02H20 toolkit](https://github.com/SMIPE444/fiio-ja11-jcally-jm12-moondropkt02-kt02h20-dac-amp-toolkit) and [txtsamu/kt02h20-flasher](https://github.com/txtsamu/kt02h20-flasher) — JA11 chip ID `KT02H20B`
- [gxcreator/ktmicro-tools](https://github.com/gxcreator/ktmicro-tools) — register map incl. `0x01` bit9 = single-DAC model
- [Xiaomi support FAQ: OTG on Redmi Note 14 Pro+](https://www.mi.com/global/support/faq/details/KA-529828/)
- [techbone: Xiaomi USB-OTG](https://www.techbone.net/xiaomi/smartphone/usb-otg)
- [Samsung community: USB-C DAC not working](https://us.community.samsung.com:443/t5/Galaxy-S-Phones/USB-C-to-USB-C-DAC-Not-Working/m-p/2318847)
- [Fairphone forum: UAC2 interface not working](https://forum.fairphone.com/t/audio-interface-not-working-with-fp4-driver-problems/81953)
- [SoundGuys: Android USB audio class](https://www.soundguys.com/android-usb-audio-class-3-0-18494/) and [Android Open Source Project: USB digital audio](https://source.android.com/docs/core/audio/usb)
