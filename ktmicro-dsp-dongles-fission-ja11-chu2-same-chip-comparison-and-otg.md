---
type: investigation
tags: [ktmicro, helios, kt02h20, fission, ja11, chu2-dsp, usb-audio, uac, otg, xiaomi, hidraw, fedora]
created: 2026-10-27
last_verified: 2026-10-27
status: current   # family match established; exact die NOT provable without a bootloader chip-ID read (deliberately not done); OTG cause unresolved
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
- **Same *die* is not provable** without a bootloader chip-ID read (`0x54`-class commands that can put the dongle into flash mode) — not done on purpose. The differences above could be firmware configuration alone.
- **A source claims the Chu 2 DSP is "not KTMicro at all" (Bestechnic ARM Cortex-M).** The user's unit contradicts that: USB manufacturer "KTMicro" under VID `31b2`, the `REG:` register map, Helios mic-EQ defaults, and the vendor SAVE `0x53` all worked. That claim may describe another Chu 2 variant or be wrong; treat it as unverified.
- **UAC version does not explain the OTG behaviour.** JA11 (UAC 2.0) and Fission (UAC 1.0) work without the toggle; Chu II (UAC 1.0, same as the Fission) does not. The USB descriptors of Fission and Chu II are near-identical (UAC1, 4 interfaces, 1-ch mic, HID iface 3, ~100 mA), and the register config of Chu II equals JA11's, which also works without OTG. So neither audio class, descriptor shape, power draw nor register config separates the Chu II. The cause is more likely phone-side (per-device handling on MIUI/HyperOS, cable, or the OTG switch timing).

## OTG on Xiaomi (what the internet says)

- Xiaomi's own FAQ: HyperOS/MIUI has a separate OTG switch (Settings → Additional settings → OTG) to be turned on before connecting a third-party device, and it **turns itself off after about 10 minutes of inactivity**.
- A Samsung community thread: a USB-C DAC failed on a direct C-to-C cable but worked through an OTG adapter.
- One low-quality Chu II article: USB mode must not be "Charging only"; random dropouts on a Redmi Note 9T fixed by disabling MIUI optimisation (single anecdote).
- Android's native USB audio is UAC1-centred; UAC2 is the variable one (a Fairphone 4 saw a UAC2 interface as a headset but silent).
- No source found explaining why one specific dongle needs the toggle. Untested ideas: `adb shell dumpsys usb` with OTG off to see whether the phone enumerates the Chu II at all; test with a different cable; check whether the toggle's 10-minute auto-off is what looks like "needs OTG".

## References

- [kt0231h CHIPS.md](https://github.com/eyad-elghareeb/kt0231h/blob/master/CHIPS.md) and [PROTOCOL.md](https://github.com/eyad-elghareeb/kt0231h/blob/master/PROTOCOL.md) — Helios-class chip table, per-chip register differences, the "Chu 2 DSP not KTMicro" claim
- [gxcreator/ktmicro-tools](https://github.com/gxcreator/ktmicro-tools) — register map incl. `0x01` bit9 = single-DAC model
- [Xiaomi support FAQ: OTG on Redmi Note 14 Pro+](https://www.mi.com/global/support/faq/details/KA-529828/)
- [techbone: Xiaomi USB-OTG](https://www.techbone.net/xiaomi/smartphone/usb-otg)
- [Samsung community: USB-C DAC not working](https://us.community.samsung.com:443/t5/Galaxy-S-Phones/USB-C-to-USB-C-DAC-Not-Working/m-p/2318847)
- [Fairphone forum: UAC2 interface not working](https://forum.fairphone.com/t/audio-interface-not-working-with-fp4-driver-problems/81953)
- [SoundGuys: Android USB audio class](https://www.soundguys.com/android-usb-audio-class-3-0-18494/) and [Android Open Source Project: USB digital audio](https://source.android.com/docs/core/audio/usb)
