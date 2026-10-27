---
type: how-to
tags: [moondrop, chu-ii-dsp, ktmicro, dsp, peq, hid, hidraw, squig-link, iem, eq, tin-hifi, fedora]
created: 2026-10-27
last_verified: 2026-10-27
status: current   # C7 PEQ applied, saved with vendor SAVE 0x53, verified surviving unplug/replug
---

# Moondrop Chu II DSP (KTMicro 31b2:0113): PEQ-match a Tin HiFi C7 over raw hidraw, two-stage apply/save

Third dongle of the same session; siblings: [tanchjim-fission-ktmicro-dsp-peq-match-tin-hifi-c7.md](tanchjim-fission-ktmicro-dsp-peq-match-tin-hifi-c7.md) (same `0x4B` register protocol, PID 0101) and [fiio-ja11-peq-match-tin-hifi-c7-hidraw.md](fiio-ja11-peq-match-tin-hifi-c7-hidraw.md).

> **Files:** `~/sessions/2026-10-26-iem-dsp-eq/` (scripts, venv, data, backups; see its `README.md`). Original bands: `chu2_backup.json` — keep it, `restore` uses it.

## Identify and read first (read-only)

```bash
lsusb      # 31b2:0113 KTMicro Chu2 DSP
wpctl status   # sink "Chu2 DSP Analog Stereo"
# HID descriptor: report IDs 0x01, 0x4B (10 B), 0x54 (10 B) = same KTMicro register channel as the Fission dongle
sudo ./venv/bin/python -I readstate_any.py 31b2 0113     # dumps strings, EQ enable regs, DAC/ADC bands, volume regs; never writes
```

Findings: `0x5B = 0x011331b2` (PID 0113 matches), product string "Chu2 DSP", manufacturer "KTMicro", `0x01 = 0x200` (single-DAC model flag), **DAC EQ enable `0x24 = 0x3`** (Fission was 1; Iwakura's JM12 notes call 3 "Custom" and 2 "EQ off"), ADC EQ enable `0x18 = 0x2` with five flat bands. Register layout identical to the Fission dongle (bands at `0x26 + 2n`). Moondrop's factory DAC bands (all peaking):

| Band | Freq | Gain | Q |
|---|---|---|---|
| 0 | 40 Hz | −9.5 | 0.2 |
| 1 | 200 Hz | −2.9 | 0.6 |
| 2 | 1400 Hz | −2.5 | 1.6 |
| 3 | 3500 Hz | −4.8 | 1.0 |
| 4 | 9000 Hz | −2.0 | 1.5 |

Device limits (Pragmatic Audio review of the cable version): **5 filters, lowest frequency 40 Hz, gain −12..+3 dB**. The script asserts these before writing.

## Target

- CSI-Zone squig.link has the analog `MOONDROP CHU 2` but not the DSP cable, but Pragmatic Audio measured the DSP cable at 0 dB DSP gain as identical to the analog cable, so the raw baseline = analog Chu 2 (same rig as the C7).
- Data: `curl -sL "https://csi-zone.squig.link/data/MOONDROP%20CHU%202%20L.txt"` (and R), plus `Tin%20C7%20{L,R}.txt`. The Chu 2 file has a different frequency grid from the C7 files → interpolate onto the C7 grid (first fit crashed on mismatched lengths).
- `C7 − Chu 2` needs 2.4 dB RMS of correction; big feature: the Chu 2 has a ~9 kHz peak (−10.9 dB needed at 9 kHz). Unconstrained fit (−12 dB, Q 3) wanted a −11.2 dB notch there; because coupler data above ~8–10 kHz is unreliable, I capped cuts at −8 dB and Q at 2.5. Result 0.93 dB RMS residual, max boost +0.94 dB.

`fit_chu2_safe.py` (5 bands, 60 Hz–10 kHz, RBJ peaking at 48 kHz, gain −8..+3, Q 0.5–2.5, 15 restarts, small gain penalty):

```python
import numpy as np
from scipy.optimize import least_squares
def load(f):
    a=[]
    for l in open(f):
        if l.startswith('*') or not l.strip(): continue
        p=l.split(); a.append((float(p[0]),float(p[1])))
    a=np.array(a); return a[:,0],a[:,1]
f,cl=load('data/Tin_C7_L.txt'); _,cr=load('data/Tin_C7_R.txt')
fk,kl0=load('data/Chu2_L.txt'); fk2,kr0=load('data/Chu2_R.txt')
kl=np.interp(f,fk,kl0); kr=np.interp(f,fk2,kr0)
c7=(cl+cr)/2; chu=(kl+kr)/2
n=lambda y:y-np.interp(1000,f,y)
diff=n(c7)-n(chu)
def peq(fr,f0,g,q,fs=48000):
    A=10**(g/40);w=2*np.pi*f0/fs;al=np.sin(w)/(2*q);c=np.cos(w)
    b=np.array([1+al*A,-2*c,1-al*A]);a=np.array([1+al/A,-2*c,1-al/A])
    z=np.exp(-1j*2*np.pi*fr/fs)
    return 20*np.log10(np.abs((b[0]+b[1]*z+b[2]*z**2)/(a[0]+a[1]*z+a[2]*z**2)))
def model(p,fr):
    y=np.zeros(len(fr))
    for i in range(5): y+=peq(fr,p[3*i],p[3*i+1],p[3*i+2])
    return y
m=(f>=60)&(f<=10000); fm,dm=f[m],diff[m]
print("rms needed:",np.sqrt(np.mean(dm**2)))
lo=[];hi=[]
for a,b in [(40,300),(200,1500),(1000,3500),(3000,6500),(6500,10000)]: lo+=[a,-8,0.5]; hi+=[b,3,2.5]
x0=[]
for f0 in [80,500,2500,5000,9000]: x0+=[f0,0,1.0]
lam=0.05
r=lambda p:np.concatenate([model(p,fm)-dm, lam*np.array([p[3*i+1] for i in range(5)])*np.sqrt(len(fm))/5])
best=None
for s in range(15):
    xs=np.clip(np.array(x0)+np.tile([0,np.random.RandomState(s).randn()*2,0],5),lo,hi)
    o=least_squares(r,xs,bounds=(lo,hi))
    if best is None or o.cost<best.cost: best=o
p=best.x
print("fit rms:",np.sqrt(np.mean((model(p,fm)-dm)**2)))
for i in range(5): print(f"band{i}: {round(p[3*i])} Hz {p[3*i+1]:+.1f} dB Q {p[3*i+2]:.2f}")
print("max boost:",max(model(p,fm)))
print("target diff (C7 - Chu2) at:")
for fr in [60,100,200,400,700,1000,1500,2000,3000,4000,5000,6000,7000,8000,9000,10000]:
    print(fr, f"{np.interp(fr,fm,dm):+.1f}", end=" | ")
print()
```

| Band | Freq | Gain | Q |
|---|---|---|---|
| 0 | 108 Hz | −1.8 | 0.50 |
| 1 | 287 Hz | −1.2 | 0.50 |
| 2 | 2555 Hz | +2.9 | 0.95 |
| 3 | 3250 Hz | −5.1 | 1.70 |
| 4 | 9649 Hz | −8.0 | 2.50 |

## Apply (RAM) then save (flash)

Two stages on purpose: the SAVE command had no report on this exact model, so listen to the volatile version first (replug reverts it).

```bash
sudo ./venv/bin/python -I chu2_c7.py apply     # backup (once) + write + verify RAM; volatile
sudo ./venv/bin/python -I chu2_c7.py save      # vendor SAVE 0x53 on whatever is in RAM now
sudo ./venv/bin/python -I chu2_c7.py restore   # original bands -> RAM, then run 'save' to persist
sudo ./venv/bin/python -I chu2_c7.py read
```

SAVE frame: `4B 00 00 00 00 53 00 00 00 00 00` (11-byte HID report); reply `4b00000000530003000000` (status `0x03`), the dongle re-enumerates by itself within ~2 s.

```python
"""Tin HiFi C7 PEQ for the Moondrop Chu II DSP (KTMicro 31b2:0113), DAC EQ, two-stage.

  sudo ./venv/bin/python -I chu2_c7.py apply     # backup (once) + write 5 bands to RAM + verify. VOLATILE:
                                                 # unplug/replug reverts to Moondrop's tuning. Listen first.
  sudo ./venv/bin/python -I chu2_c7.py save      # commit the CURRENT RAM bands to flash with vendor SAVE 0x53
                                                 # (untested on this exact model; works on Tanchjim 0101)
  sudo ./venv/bin/python -I chu2_c7.py restore   # write the backed-up original bands to RAM (then 'save' to persist)
  sudo ./venv/bin/python -I chu2_c7.py read      # read-only

Device limits (Pragmatic Audio): 5 filters, >= 40 Hz, gain -12..+3 dB. Does NOT touch the EQ-enable
register (0x24 stays 3), 0x66, 0x11, 0x43 or 0x54.
"""
import json
import os
import struct
import sys
import time

sys.path.insert(0, 'ktm')
from kt02h20 import KT02H20

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, 'chu2_backup.json')
VID, PID = 0x31B2, 0x0113
C7 = [(108, -1.8, 0.50), (287, -1.2, 0.50), (2555, +2.9, 0.95),
      (3250, -5.1, 1.70), (9649, -8.0, 2.50)]   # all peaking


def open_dev(timeout=0.0):
    end = time.time() + timeout
    while True:
        d = KT02H20(VID, PID)
        try:
            if d._hid.open() and d.read(0x5B) == ((PID << 16) | VID):
                return d
        except Exception:
            pass
        try:
            d._hid.close()
        except Exception:
            pass
        if time.time() >= end:
            return None
        time.sleep(0.5)


def bands(d):
    return [d.get_eq_band('dac', i) for i in range(5)]


def show(tag, bs):
    print(tag)
    for i, b in enumerate(bs):
        print("  ", i, b)


def same(b, w):
    return b is not None and b['freq'] == w[0] and abs(b['gain'] - w[1]) < 0.05 \
        and abs(b['q'] - w[2]) < 0.002 and b['ftype'] == 0


mode = sys.argv[1] if len(sys.argv) > 1 else 'read'
d = open_dev()
if d is None:
    sys.exit("Chu2 DSP (31b2:0113) not found / PID register mismatch / no permission")
en = d.get_eq_en('dac')
cur = bands(d)
print("DAC EQ enable (reg 0x24):", hex(d.read(0x24)), "->", en)
show("current bands:", cur)
if any(b is None for b in cur):
    sys.exit("could not read all bands; nothing written")

if mode == 'read':
    sys.exit(0)

if mode in ('apply', 'restore'):
    if mode == 'apply':
        if not os.path.exists(BACKUP):
            json.dump(cur, open(BACKUP, 'w'), indent=1)
            print("backup saved to", BACKUP)
        want = [(f, g, q) for f, g, q in C7]
    else:
        want = [(b['freq'], b['gain'], b['q']) for b in json.load(open(BACKUP))]
    for w in want:
        assert w[0] >= 40 and -12 <= w[1] <= 3 and w[2] > 0, f"band outside device limits: {w}"
    for i, (f, g, q) in enumerate(want):
        ok = d.set_eq_band('dac', i, freq=f, gain=g, ftype=0, q=q)
        print(i, "ack" if ok else "NO ACK")
    rb = bands(d)
    show("read-back:", rb)
    print("RAM matches target:", all(same(b, w) for b, w in zip(rb, want)))
    print("EQ enable after:", hex(d.read(0x24)))
    print("This is RAM only. Listen, then run 'save' to persist.")
    d.close()

elif mode == 'save':
    frame = bytes([0x4B]) + struct.pack('<I', 0) + bytes([0x53, 0, 0, 0, 0, 0])
    assert len(frame) == 11
    d._hid.write_report(frame)
    try:
        rx = d._hid.read_report(1500)
        print("SAVE reply:", rx.hex() if rx else None)
    except Exception as e:
        print("no reply (probably rebooting):", e)
    try:
        d._hid.close()
    except Exception:
        pass
    time.sleep(2)
    d2 = open_dev(20)
    if d2 is None:
        sys.exit("dongle did not come back in 20 s; replug it and run 'read'")
    show("after save/reboot:", bands(d2))
    print("EQ enable:", hex(d2.read(0x24)))
    print("Now unplug/replug and run 'read' to confirm it persisted.")
else:
    sys.exit("modes: read | apply | save | restore")
```

## What happened (2026-10-27)

1. `readstate_any.py` dump as above.
2. First attempt ran `save` **before** `apply`: committed Moondrop's own bands back to flash (unchanged) — harmless, and showed `0x53` is ACKed (`0x03`) and the dongle reboots cleanly on this model. No backup file existed yet (apply creates it), but the printed bands are the originals.
3. `apply`: all 5 writes ACKed, read-back identical, EQ enable still `0x3`, backup saved.
4. `save`: ACK `0x03`, dongle returned with the C7 bands.
5. Manual unplug/replug, `read`: still 108/287/2555/3250/9649 Hz → **persists**.
6. Re-checked 2026-10-27 after the dongle had been disconnected and reconnected again (`chu2_c7.py read`): bands and `0x24 = 3` unchanged; USB still `31b2:0113`, `bcdDevice` 0.03, UAC 1.0, 98 mA.

## Firmware update? (searched 2026-10-27: none found)

- This unit reports version string `1.0.1` (register `0x04..`), `bcdDevice` 0.03, product `Chu2 DSP`, serial default `2020-02-20-0000-0000-0000`.
- Moondrop's official [download page](https://www.moondroplab.com/en/download) lists firmware only for the MOONRIVER2:TI and DAWN PRO USB DAC/AMPs; **no Chu II DSP entry**. Its [Moondrop Link page](https://www.moondroplab.com/en/moondrop-link) mentions OTA firmware upgrades in the app but its supported-device list (SPARXIE, EDGE2, MIRAGE, U.C.T.S., PUDDING, KLUKAI, DHA15, MOONRIVER3, GOLDEN AGES 2, SPACE TRAVEL 2 ULTRA) does not include the Chu II DSP; no version numbers given.
- [chu2-studio](https://github.com/jcharvet/chu2-studio/blob/main/docs/PROTOCOL.md) decompiled both official Android apps and found no Chu 2 / KT0210 / `0x31B2` device-matching code, i.e. the current official apps don't support this cable at all (the older "Moondrop Link 2.0" apparently did; Pragmatic Audio called it Android-only, and a forum user said the iOS version hides the firmware update button).
- Retailers/reviews ([Pragmatic Audio](https://www.pragmaticaudio.com/reviews/2024/04/moondrop-chu-ii-dsp/), headphonezone, hifigo) mention no firmware changelog. A low-quality buying guide claims users can self-update with "compatible software" — not credible.
- The CHIPS.md note refers to a community-extracted `Moondrop_CHU2_DSP_firmware_v1.0.0.bin`; this unit says 1.0.1, so it is probably not older than what is publicly known.
- Not attempted: flashing. The KTMicro flash tools can brick these dongles and a stock image cannot be backed up (see [kt02h20-jcally-dac-ja11-firmware-flash-protocol.md](kt02h20-jcally-dac-ja11-firmware-flash-protocol.md)); no vendor-sanctioned update exists to justify it.
- **Can the Chu II firmware be backed up? (searched 2026-10-27)** Not in software. The `kt0231h` notes ([PROTOCOL.md](https://github.com/eyad-elghareeb/kt0231h/blob/master/PROTOCOL.md) §7.7/§9.4/§10.1, [HARDWARE-DUMP.md](https://github.com/eyad-elghareeb/kt0231h/blob/master/HARDWARE-DUMP.md)) and both flasher projects agree: the CDC bootloader has 10 tokens and no read/dump token, `INF` returns only size + CRC-32, run-mode `0x08` reads unmapped space (returns zeros on KT02H20/JA11, hardware-checked by ParkWardRR), and the vendor `flash_read_all` is only for KT0712 external-SPI parts. The only documented route is **hardware**: SWD on GPIO4 (CLK)/GPIO5 (DAT) of the chip (2 Mbit = 256 KB internal flash, NDS32 core), needs the cable's control module opened, fine-pitch probing and an NDS32-aware probe (OpenOCD nds32 target); the guide itself marks this as datasheet-derived, and customer firmware may re-task those pins. No one reports having done it on a Chu II. What *can* be saved in software is the configuration: `chu2_backup.json` (original EQ bands) and `data/regs_chu2.json` (all 256 registers) in the session folder.
- **Bunny DSP firmware on the Chu II? (searched 2026-10-27) — blocked at step one: no Bunny DSP firmware is public.** [Tanchjim's download center](https://tanchjim.com/en/services/) ([also here](https://www.tanchjimaudio.com/app-services)) has firmware upgrades for FISSION, FISSION-Rational HiFi Edition, LUNA, LUNA AT, DSP S (V1.0.2) and SPACE, but nothing for Bunny / Bunny DSP, and [BunnyDSPLinux](https://github.com/onbot7/BunnyDSPLinux) ships only EQ presets (`presets/stock_backup.json`), no firmware. The Bunny's chip ID is `TURN2CDC` (feature report `0x54`) with `31b2:1112`; nothing links that boot path to the Chu II's `31b2:0113`, and KTMicro images are chip/product-specific (see above). Tanchjim's own page warns "Only applicable to TANCHJIM-DSP S. Other products flashing this firmware are at your own risk." Not attempted.
- **Has anyone flashed other firmware onto a Chu II DSP?** Searched 2026-10-27 (GitHub, Head-Fi/forum-style queries, flasher repos): **no report found** of a Chu II DSP being flashed with any firmware, nor of one being bricked/recovered. The cross-flash projects ([SMIPE444 toolkit](https://github.com/SMIPE444/fiio-ja11-jcally-jm12-moondropkt02-kt02h20-dac-amp-toolkit), [txtsamu/kt02h20-flasher](https://github.com/txtsamu/kt02h20-flasher)) cover **KT02H20 DAC dongles** (JCALLY JM12, Moondrop "KT02" dongle, Fransun T2 Pro, VE ODO → FiiO JA11 firmware), not the Chu II cable. Per [chu2-studio](https://github.com/jcharvet/chu2-studio/blob/main/docs/PROTOCOL.md) the Chu II is KT0210-class, a different part from the KT02H20, and KTMicro images carry a chip-specific flash tag (e.g. `KT_Helios_v1b___KT02H20B`), so a JA11/JM12 image is the wrong image for it; [kt0231h PROTOCOL.md](https://github.com/eyad-elghareeb/kt0231h/blob/master/PROTOCOL.md) says never flash a foreign BIN, and the flashers warn there is no read-back, so the original firmware cannot be saved first. I could not locate the "companion Moondrop RE project" with `Moondrop_CHU2_DSP_firmware_v1.0.0.bin` that CHIPS.md cites. Conclusion: untested territory; do not flash.
- How to check the vendor way if wanted: install the Android "MOONDROP" / Link app from the links on the Moondrop Link page and see whether it detects the cable and offers an OTA update (the apps may not recognise this device).

## Gotchas

- Claude Code's auto-mode classifier blocks `sudo` on HID scripts; the user ran each with `! sudo ...`. Write scripts with the Write tool, not a heredoc inside the (blocked) command.
- Do not run `save` first: it commits the current RAM state, whatever it is. Order is apply → listen → save.
- Never touch `0x66`, `0x11`, `0x43`, `0x54` (see the Fission doc). Fixed a garbled `open_dev` condition in the first draft of `chu2_c7.py` before it was ever run.
- The EQ-enable register stays 3; the scripts do not change it.
- Not done: no listening A/B or re-measurement; the fit assumes the DSP cable's raw response equals the analog Chu 2 and that the C7 is the target.

## References

- [Pragmatic Audio: EQ measurements of the Moondrop Chu II DSP](https://www.pragmaticaudio.com/reviews/2024/04/moondrop-chu-ii-dsp/) — 5 filters, 40 Hz minimum, −12..+3 dB; DSP cable at 0 gain = analog cable
- [Audio Science Review: Moondrop Chu II DSP EQ review](https://www.audiosciencereview.com/forum/index.php?threads/moondrop-chu-ii-dsp-eq-review.53470/) — "No DSP" ≈ original Chu II, Default profile differs
- [CSI-Zone squig.link](https://csi-zone.squig.link/) — C7 and Chu 2 measurements
- [Moondrop downloads](https://www.moondroplab.com/en/download) and [Moondrop Link page](https://www.moondroplab.com/en/moondrop-link) — firmware/app availability (no Chu II DSP)
- [jcharvet/chu2-studio PROTOCOL.md](https://github.com/jcharvet/chu2-studio/blob/main/docs/PROTOCOL.md) — official apps don't match this device
- [gxcreator/ktmicro-tools](https://github.com/gxcreator/ktmicro-tools) and [kt0231h PROTOCOL.md](https://github.com/eyad-elghareeb/kt0231h/blob/master/PROTOCOL.md) — register map, SAVE `0x53` (confirmed there on Tanchjim Bunny DSP)
