---
type: how-to
tags: [tanchjim, fission, ktmicro, dsp, peq, hid, hidraw, squig-link, iem, eq, fedora, tin-hifi]
created: 2026-10-26
last_verified: 2026-10-26
status: current   # applied and read back OK on the dongle; persistence across unplug NOT checked
---

# Tanchjim FISSION (Rational HiFi Edition) DSP dongle: PEQ-match a Tin HiFi C7 from squig.link data

Goal: the user plugged in their USB-C DSP IEM and asked to "set the EQ to Tin HiFi C7". Interpreted as: make the FISSION sound like the C7 by fitting the 5 on-dongle PEQ bands to `C7 − FISSION`. Result is an approximation (coupler measurements, one IEM standing in for the other).

## Device identification

```bash
lsusb          # 31b2:0101 KTMicro FISSION-Rational HiFi Edition
wpctl status   # sink "FISSION-Rational HiFi Edition Analog Stereo"
for d in /sys/class/hidraw/hidraw*; do echo $d; grep -E 'HID_NAME|HID_ID' $d/device/uevent; done
# -> hidraw6 = KTMicro FISSION-Rational HiFi Edition (root:root 0600)
```

- It is a Tanchjim FISSION with the DSP in the USB-C plug. Chip is KTMicro (KT02H20 family).
- The community tool [gxcreator/ktmicro-tools](https://github.com/gxcreator/ktmicro-tools) documents PID `0x0111`; this dongle is `0x0101`. Register layout turned out identical (verified by read-back below).
- No EasyEffects / JamesDSP on the box, so PEQ has to go into the dongle itself (survives app/OS changes, applies to any host).

## Is there a C7? Where the target data came from

- Web searches for "Tin HiFi C7" found nothing, and tinhifi.com's C-series page returned 302 to WebFetch. The user then supplied `https://csi-zone.squig.link/?share=Tin_C7`.
- The squig.link front-end is static; raw data is fetchable:

```bash
curl -sL https://csi-zone.squig.link/data/phone_book.json -o pb.json
grep -n -i -E '"C7"|Fission' pb.json      # -> file "Tin C7"; Fission files "Tanchjim Fission AtSDdf" etc.
curl -sL "https://csi-zone.squig.link/data/Tin%20C7%20L.txt" -o Tin_C7_L.txt   # also R
curl -sL "https://csi-zone.squig.link/data/Tanchjim%20Fission%20AtSDdf%20L.txt" -o Fission_L.txt
```

- Same site, same rig (REW 5.31.3, 1/12 oct smoothing, Aug/Sep 2025) for both IEMs, so the difference is meaningful.
- Fission has no right-channel file on that site (404); L only. Fission "AtSDdf" = Atmosphere switch, filter S, **DSP jack, Default tuning**.

## Reading the current DSP state (read-only)

Needs root because `/dev/hidraw6` is `root:root 0600` (a udev rule would avoid sudo; not added).

```bash
python3 -m venv venv && ./venv/bin/pip install hidapi numpy scipy
git clone https://github.com/gxcreator/ktmicro-tools ktm
sudo ./venv/bin/python -I readstate.py
```

`readstate.py` (opens `KT02H20(0x31B2, 0x0101)`, only calls `.read()`):

```python
import sys
sys.path.insert(0, 'ktm')
from kt02h20 import KT02H20
d = KT02H20(0x31B2, 0x0101)
if not d._hid.open(): sys.exit("open failed")
for a in [0x00,0x01,0x04,0x5B,0x18,0x24]: print(hex(a), hex(d.read(a)))
for n in range(5):
    A = d.read(0x26+n*2); B = d.read(0x27+n*2)
    g = A & 0xFFFF
    if g & 0x8000: g -= 0x10000
    print(n, "freq", A>>16, "gain", g/10, "type", (B>>16)&7, "Q", (B&0xFFFF)/1000)
```

Result: `0x5B = 0x010131b2` (PID 0101 / VID 31b2, matches), DAC EQ enable `0x24 = 1`, and these bands (the factory "Default" tuning, almost certainly):

| Band | Freq | Gain | Q |
|---|---|---|---|
| 0 | 36 Hz | −0.9 | 0.39 |
| 1 | 604 Hz | −0.5 | 6.75 |
| 2 | 6000 Hz | +1.7 | 1.02 |
| 3 | 10954 Hz | −2.5 | 0.53 |
| 4 | 18860 Hz | −2.7 | 0.46 |

## Fitting 5 bands

Steps:
1. Normalise C7 (avg L+R) and Fission to 0 dB at 1 kHz.
2. The Fission measurement was taken with the Default EQ active, so subtract the current 5-band response (RBJ peaking biquads at 48 kHz) to get the Fission with EQ off. Assumption: current bands == the EQ present when it was measured.
3. `target = C7 − Fission_EQ_off`; least-squares fit 5 peaking bands over 60 Hz–10 kHz (below 60 Hz and above 10 kHz the coupler data is unreliable), gain ±6 dB, Q 0.5–3, each band confined to a frequency window, 10 random restarts (`scipy.optimize.least_squares`).

First attempt (30 Hz–12 kHz, ±12 dB) produced two huge opposing bands at ~6 kHz (−12/+9 dB) — fitting noise. Restricting the range and gain bounds fixed that. Raw difference was only ~1.2 dB RMS, so the IEMs are already close; final fit residual 0.17 dB RMS, max boost +1.3 dB (no preamp needed).

Final bands:

| Band | Freq | Gain | Q |
|---|---|---|---|
| 0 | 60 Hz | +1.2 | 0.51 |
| 1 | 593 Hz | −1.8 | 1.06 |
| 2 | 2575 Hz | +2.6 | 0.69 |
| 3 | 3118 Hz | −3.2 | 1.94 |
| 4 | 6471 Hz | −4.7 | 2.90 |

Side effect: all 5 bands are replaced, so the factory roll-off above 10 kHz is gone (not fitted).

## Applying (with backup) and restoring

```python
# apply_c7.py -- backup current bands to eq_backup.json, write, read back
import json, os, sys
sys.path.insert(0, 'ktm')
from kt02h20 import KT02H20
C7 = [(60,+1.2,0.51),(593,-1.8,1.06),(2575,+2.6,0.69),(3118,-3.2,1.94),(6471,-4.7,2.90)]
d = KT02H20(0x31B2, 0x0101); d._hid.open() or sys.exit("open failed")
if len(sys.argv) > 1 and sys.argv[1] == 'restore':
    bands = [(b['freq'], b['gain'], b['q'], b['ftype']) for b in json.load(open('eq_backup.json'))]
else:
    cur = [d.get_eq_band('dac', i) for i in range(5)]
    assert all(cur)
    if not os.path.exists('eq_backup.json'): json.dump(cur, open('eq_backup.json', 'w'), indent=1)
    bands = [(f, g, q, 0) for f, g, q in C7]
for i, (f, g, q, t) in enumerate(bands):
    ok = d.set_eq_band('dac', i, freq=f, gain=g, ftype=t, q=q)
    print(i, "ack" if ok else "NO ACK", d.get_eq_band('dac', i))
print("DAC EQ enabled:", d.get_eq_en('dac'))
```

```bash
sudo ./venv/bin/python -I apply_c7.py            # apply
sudo ./venv/bin/python -I apply_c7.py restore    # undo (factory Default bands above)
```

Result: all 5 writes ACKed (`status 0x03`) and read back identical; DAC EQ still enabled. Register protocol: 11-byte HID reports, `0x52` read / `0x57` write, DAC EQ bands at `0x26 + 2n` (A: `freq<<16 | gain×10`; B: `type<<16 | Q×1000`).

## Gotchas hit

- The Claude Code auto-mode classifier blocked `sudo` execution of the cloned third-party Python (twice, even after the user said go ahead, and it also swallowed the `cat > file` in the same command, so the file never got created). Workaround that respects the block: write the script with the Write tool, let the user run it via `! sudo ...` in the session.
- WebFetch can't read `tinhifi.com` (302).

## Not verified / open

- Persistence: unknown whether the bands survive unplug/replug. If not, re-run `apply_c7.py` after reconnect.
- No listening A/B or re-measurement; this is a measurement-based approximation. The FISSION "Rational HiFi Edition" may differ slightly from the standard FISSION measured on squig.link.
- Other known register map variants (JM12 stock firmware with commit `0x53`, FiiO JA11 framing `AA 0A`/`BB 0B`) were not needed here; plain `0x57` writes took effect immediately.

## References

- [gxcreator/ktmicro-tools](https://github.com/gxcreator/ktmicro-tools) — KT02H20 HID tool + `KT_USB_PROTOCOL.md` register map
- [eyad-elghareeb/kt0231h](https://github.com/eyad-elghareeb/kt0231h) — fork documenting the same HID protocol and register ranges
- [jeromeof/devicePEQ](https://github.com/jeromeof/devicePEQ) — multi-vendor DSP PEQ handlers (incl. KTMicro)
- [Tanchjim FISSION Rational HiFi Edition](https://tanchjim.com/en/products/earphones/iem/fission-rational-hifi/) — product page (DSP in USB-C plug)
- [CSI-Zone squig.link, Tin C7](https://csi-zone.squig.link/?share=Tin_C7) — C7 and Fission measurement data
- See also [kt02h20-jcally-dac-ja11-firmware-flash-protocol.md](kt02h20-jcally-dac-ja11-firmware-flash-protocol.md) for the same chip family's flashing protocol.
