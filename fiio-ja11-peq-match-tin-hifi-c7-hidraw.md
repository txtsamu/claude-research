---
type: how-to
tags: [fiio, ja11, jadeaudio, ktmicro, kt02h20, dsp, peq, hid, hidraw, squig-link, iem, eq, tin-hifi, fedora]
created: 2026-10-26
last_verified: 2026-10-26
status: current   # C7 PEQ written to USER1 slot, saved, verified surviving unplug/replug
---

# FiiO JadeAudio JA11 (cross-flashed KT02H20): PEQ-match a Tin HiFi C7 over raw hidraw, no app

> **Update 2026-10-28:** USER1 now holds a CrinEar Daybreak EQ for a Moondrop Chu II (not the C7 bands below); see [tanchjim-fission-peq-match-crinear-daybreak.md](tanchjim-fission-peq-match-crinear-daybreak.md). Same protocol and script pattern (`ja11_daybreak_chu2.py`); the C7 section below is still the protocol reference. `ja11_c7.py restore` returns the factory USER1.

> **Files:** scripts, backups, measurement data and venv for both dongles live in `~/sessions/2026-10-26-iem-dsp-eq/` (see its `README.md`); run the commands below from that folder. Factory-band backups: `eq_backup.json` (Fission) and `ja11_backup.json` (JA11) — keep them, `restore` depends on them.

Sibling of [tanchjim-fission-ktmicro-dsp-peq-match-tin-hifi-c7.md](tanchjim-fission-ktmicro-dsp-peq-match-tin-hifi-c7.md) (different dongle, different protocol, same target). The dongle is the one flashed with JA11 firmware in [kt02h20-jcally-dac-ja11-firmware-flash-protocol.md](kt02h20-jcally-dac-ja11-firmware-flash-protocol.md).

## Identify

```bash
lsusb      # 2972:0102 FiiO Electronics Technology JadeAudio JA11
for d in /sys/class/hidraw/hidraw*; do echo "$d $(grep -E 'HID_NAME|HID_ID' $d/device/uevent | tr '\n' ' ')"; done
# hidraw6 HID_ID=0003:00002972:00000102 HID_NAME=FIIO JadeAudio JA11   (node is root:root 0600)
python3 -c "print(open('/sys/class/hidraw/hidraw6/device/report_descriptor','rb').read().hex(' '))"
```

HID descriptor has report IDs `0x01` (consumer keys), `0x4B` and `0x54` (10 B, the old KTMicro register/bootloader channel), and **`0x02` (20 B in/out) = the FiiO PEQ channel**. Unlike the Tanchjim dongle (KTMicro `0x4B` registers, `0x53` save) this firmware speaks FiiO's framing.

## Protocol (what actually worked on this unit)

Over `/dev/hidraw*`: write `bytes([0x02]) + frame.ljust(20, 0)`; reads come back with the report ID as byte 0 (strip it).

```
write: AA 0A 00 00 <cmd> <len> <payload...> 00 EE      (the 00 before EE is a dummy CRC; no real CRC needed)
read : BB 0B 00 00 <cmd> <len> <payload...> 00 EE      (reply starts BB 0B ..., cmd at byte 4, data from byte 6)
0x15 band   [idx, gain*10 i16 BE, freq u16 BE, Q*100 u16 BE, type 0=PK 1=LS 2=HS]   (read: payload [idx])
0x16 preset [0 Vocal, 1 Classic, 2 Bass, 3 USER1, 4 EQ off]
0x18 band count   0x17 global gain (NOT touched)   0x19 save [slot]
```

Notes: ParkWardRR's spec (CRC-8/MAXIM, little-endian variants) is static-RE only and disagrees in places; the byte layout above is the devicePEQ / ja11-eq one and is what the hardware accepted (reads returned sane values on first try). Limits: 5 bands, gain ±12 dB, Q 0.1–10, only USER1 (slot 3) is writable; saving slot N makes N the boot preset. The save must be given ~1 s before closing the handle or it may not reach flash (upstream bug). Factory presets 0–2 are read-only. Avoid `0x1B/0x1C` (reset) and `0x17` (global gain, encoding disputed).

## Target: refit against the Fission *analog* measurement

JA11 is a flat DAC, so the EQ is `C7 − IEM with no EQ`. The IEM here is assumed to be the Tanchjim Fission (analog cable). Data from the CSI-Zone squig.link (same rig for both):

```bash
curl -sL "https://csi-zone.squig.link/data/Tin%20C7%20L.txt" -o Tin_C7_L.txt      # and R
curl -sL "https://csi-zone.squig.link/data/Tanchjim%20Fission%20AtS3%20L.txt" -o Fission_AtS3_L.txt   # Atmosphere switch, filter S, analog 3.5 mm
```

Fit script (`fit4.py`, needs `fit.py` loader pieces: `load()`, `peq()`, `model()` RBJ peaking biquads at 48 kHz, normalise at 1 kHz) — 5 bands, 60 Hz–10 kHz, gain ±6, Q 0.5–3, small gain penalty, 12 random restarts:

```python
import numpy as np
exec(open('fit.py').read().split("x0=[]")[0])
f2,fa=load('Fission_AtS3_L.txt')
raw=n(fa)
diff=n(c7)-raw
m=(f>=60)&(f<=10000); fm,dm=f[m],diff[m]
print("rms needed:",np.sqrt(np.mean(dm**2)))
lo=[];hi=[]
for a,b in [(60,300),(200,1500),(1000,3500),(3000,6500),(5500,10000)]: lo+=[a,-6,0.5]; hi+=[b,6,3]
x0=[]
for f0 in [80,500,2500,5000,9000]: x0+=[f0,0,1.0]
lam=0.05
r=lambda p:np.concatenate([model(p,fm)-dm, lam*np.array([p[3*i+1] for i in range(5)])*np.sqrt(len(fm))/5])
best=None
for s in range(12):
    xs=np.clip(np.array(x0)+np.tile([0,np.random.RandomState(s).randn()*2,0],5),lo,hi)
    o=least_squares(r,xs,bounds=(lo,hi))
    if best is None or o.cost<best.cost: best=o
p=best.x
print("fit rms:",np.sqrt(np.mean((model(p,fm)-dm)**2)))
for i in range(5): print(f"band{i}: {round(p[3*i])} Hz {p[3*i+1]:+.1f} dB Q {p[3*i+2]:.2f}")
print("max boost:",max(model(p,fm)))

```

Result: needed correction 1.65 dB RMS, fit residual 0.35 dB RMS, max boost +1.1 dB (no preamp). The fit insists on a +4.9 dB / −4.8 dB pair at 3.5 / 3.15 kHz (net a shaped dip); an unregularised fit gave +6/−5.7 so it is a real feature of the difference, not an optimiser artefact.

| Band | Freq | Gain | Q |
|---|---|---|---|
| 0 | 62 Hz | +1.7 | 1.46 |
| 1 | 230 Hz | −2.4 | 0.50 |
| 2 | 3500 Hz | +4.9 | 0.80 |
| 3 | 3150 Hz | −4.8 | 1.91 |
| 4 | 7039 Hz | −4.8 | 0.69 |

Note these differ from the Tanchjim-dongle bands (that fit subtracted the Fission's built-in DSP EQ).

## Run it

`ja11_c7.py` (my own script; reads state first, backs up, verifies RAM before saving):

```bash
sudo ./venv/bin/python -I ja11_c7.py read      # read-only dump
sudo ./venv/bin/python -I ja11_c7.py           # backup + write USER1 + verify + save
sudo ./venv/bin/python -I ja11_c7.py restore   # put backed-up USER1 bands back and save
```

```python
"""Apply a Tin HiFi C7 PEQ to the FiiO JadeAudio JA11 (2972:0102) USER1 slot and save it.

Protocol (devicePEQ / faxesystem/ja11-eq, 0BSD), via /dev/hidraw, report ID 2, 20-byte payload:
  frame = AA 0A 00 00 <cmd> <len> <payload...> 00 EE      (write)
          BB 0B 00 00 <cmd> <len> ...        00 EE        (read; reply starts BB 0B)
  0x15 band: [idx, gain*10 i16 BE, freq u16 BE, Q*100 u16 BE, type(0=PK,1=LS,2=HS)]
  0x16 preset (0 Vocal,1 Classic,2 Bass,3 USER1,4 EQ off), 0x18 band count, 0x19 save [slot]

Usage:  sudo ./venv/bin/python -I ja11_c7.py            # backup, apply to USER1, verify, save
        sudo ./venv/bin/python -I ja11_c7.py restore    # put backed-up USER1 bands back and save
        sudo ./venv/bin/python -I ja11_c7.py read       # read-only dump
Does NOT write the global gain (0x17), reset (0x1B/0x1C) or anything outside USER1.
"""
import glob
import json
import os
import select
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, 'ja11_backup.json')
RID = 2
USER1 = 3
C7 = [(62, +1.7, 1.46), (230, -2.4, 0.50), (3500, +4.9, 0.80),
      (3150, -4.8, 1.91), (7039, -4.8, 0.69)]   # (freq Hz, gain dB, Q), all peaking


def find_hidraw():
    for ue in sorted(glob.glob('/sys/class/hidraw/hidraw*/device/uevent')):
        try:
            if '00002972:00000102' in open(ue).read().upper().replace('0003:', ''):
                return '/dev/' + ue.split('/')[4]
        except OSError:
            pass
    return None


def open_dev(timeout=0.0):
    end = time.time() + timeout
    while True:
        p = find_hidraw()
        if p:
            try:
                return os.open(p, os.O_RDWR | os.O_NONBLOCK)
            except OSError:
                pass
        if time.time() >= end:
            return None
        time.sleep(0.5)


def send(fd, frame):
    os.write(fd, bytes([RID]) + bytes(frame).ljust(20, b'\0'))


def drain(fd):
    while select.select([fd], [], [], 0.05)[0]:
        try:
            os.read(fd, 64)
        except OSError:
            break


def query(fd, cmd, payload=()):
    drain(fd)
    send(fd, [0xBB, 0x0B, 0, 0, cmd, len(payload), *payload, 0, 0xEE])
    end = time.time() + 1.5
    while time.time() < end:
        if select.select([fd], [], [], 0.2)[0]:
            r = os.read(fd, 64)
            r = r[1:] if r and r[0] == RID else r       # drop report ID
            if len(r) > 6 and r[0] == 0xBB and r[1] == 0x0B and r[4] == cmd:
                return r
    return None


def s16(hi, lo):
    v = (hi << 8) | lo
    return (v - 65536 if v & 0x8000 else v) / 10.0


def read_state(fd):
    pr = query(fd, 0x16)
    cr = query(fd, 0x18)
    if pr is None or cr is None:
        return None
    st = {'preset': pr[6], 'count': cr[6], 'bands': []}
    for i in range(st['count']):
        r = query(fd, 0x15, [i])
        if r is None:
            return None
        st['bands'].append({'idx': r[6], 'gain': s16(r[7], r[8]), 'freq': (r[9] << 8) | r[10],
                            'q': ((r[11] << 8) | r[12]) / 100.0, 'type': r[13]})
    return st


def set_band(fd, i, freq, gain, q, ftype=0):
    g = int(round(gain * 10)) & 0xFFFF
    qv = int(round(q * 100)) & 0xFFFF
    send(fd, [0xAA, 0x0A, 0, 0, 0x15, 8, i, g >> 8, g & 0xFF, freq >> 8, freq & 0xFF,
              qv >> 8, qv & 0xFF, ftype, 0, 0xEE])


def set_preset(fd, p):
    send(fd, [0xAA, 0x0A, 0, 0, 0x16, 1, p, 0, 0xEE])


def set_count(fd, n):
    send(fd, [0xAA, 0x0A, 0, 0, 0x18, 1, n, 0, 0xEE])


def save(fd, slot):
    send(fd, [0xAA, 0x0A, 0, 0, 0x19, 1, slot, 0, 0xEE])
    time.sleep(1.0)            # let the dongle write flash before anything closes the handle


def close(fd):
    try:
        os.close(fd)
    except OSError:
        pass


def same(b, w):
    return b['freq'] == w[0] and abs(b['gain'] - w[1]) < 0.05 and abs(b['q'] - w[2]) < 0.011 and b['type'] == w[3]


mode = sys.argv[1] if len(sys.argv) > 1 else 'apply'
fd = open_dev()
if fd is None:
    sys.exit("JA11 (2972:0102) hidraw not found / not accessible")
st = read_state(fd)
if st is None:
    sys.exit("no/odd reply from the dongle; nothing written. Raw protocol assumption may be wrong.")
print("current:", json.dumps(st))
if mode == 'read':
    sys.exit(0)

if mode == 'restore':
    bk = json.load(open(BACKUP))
    want = [(b['freq'], b['gain'], b['q'], b['type']) for b in bk['bands']]
    orig_preset = bk['preset']
else:
    if not os.path.exists(BACKUP):
        # Only the USER1 slot's own bands are meaningful: switch to it briefly (live only) to read them.
        orig = st['preset']
        set_preset(fd, USER1)
        time.sleep(0.2)
        u1 = read_state(fd)
        if u1 is None:
            sys.exit("could not read USER1; nothing written")
        json.dump({'preset': orig, 'count': u1['count'], 'bands': u1['bands']}, open(BACKUP, 'w'), indent=1)
        print("backup saved to", BACKUP, "(USER1 bands:", u1['bands'], "; original preset", orig, ")")
    want = [(f, g, q, 0) for f, g, q in C7]
    orig_preset = None

set_preset(fd, USER1)
time.sleep(0.15)
set_count(fd, len(want))
time.sleep(0.1)
for i, (f, g, q, t) in enumerate(want):
    set_band(fd, i, f, g, q, t)
    time.sleep(0.02)
time.sleep(0.1)
rb = read_state(fd)
if rb is None or rb['preset'] != USER1 or len(rb['bands']) != len(want) \
        or not all(same(b, w) for b, w in zip(rb['bands'], want)):
    print("RAM read-back MISMATCH, NOT saving:", json.dumps(rb))
    sys.exit(1)
print("RAM read-back OK on USER1")

save(fd, USER1)
close(fd)
print("saved; waiting for the dongle (it may re-enumerate)...")
time.sleep(2)
fd = open_dev(20)
if fd is None:
    sys.exit("dongle did not come back in 20 s; replug it and run with 'read'")
after = read_state(fd)
print("after save:", json.dumps(after))
ok = after is not None and after['preset'] == USER1 and all(same(b, w) for b, w in zip(after['bands'], want))
print("USER1 holds the target bands and is active:", ok)
if orig_preset is not None and orig_preset != USER1:
    set_preset(fd, orig_preset)
    print("restore: switched live preset back to", orig_preset, "(boot preset left as saved)")
close(fd)
print("Now unplug/replug and run 'read' to confirm it persisted.")
```

Results 2026-10-26:
- `read` before: preset 1 (Classic), bands 230/−4.9, 80/+2.5, 2500/+2.5, 6000/−2.9, 8000/0 (Classic factory curve).
- USER1 factory bands (saved to `ja11_backup.json`): 29 Hz +6.0, 81 Hz +3.8, 600 Hz −0.4, 7460 Hz +5.1, 15660 Hz +5.4, all Q 0.7, peaking. Original preset 1.
- apply: RAM read-back OK, save sent, dongle answered again within the 2 s wait, `preset 3` with all five C7 bands.
- After a manual unplug/replug: `read` still shows preset 3 with the C7 bands → **persists**.

## Firmware status check (2026-10-27): already on the latest

The dongle reports firmware `2.2.0` (register dump: build Jul 8 2025 19:24:29, hash `75503ea`; USB `bcdDevice` 2.20, UAC 2.0). FiiO's [JA11 firmware post](https://forum.fiio.com/note/showNoteContent.do?id=202406211150090736905) lists V2.2 (2025-07-09) as the newest: fixes lost in-line control after pausing on some phones, optimised mic input gain (V2.1 2024-10-29 ticking fix; V2.0 2024-08-05 UAC1.0 fix; V1.9 2024-07-29 web PEQ + online upgrade; V1.7 2024-06-21 channel-balance fix). [FiiO's V2.2 announcement](https://www.fiio.com/newsinfo/1065234.html) and a search for V2.3/V2.4 found nothing newer. Official upgrade paths: web at fiiocontrol.fiio.com (Windows/macOS, WebHID browser) or a local tool from the forum post. Note this unit is a cross-flashed JCALLY JM12 (KT02H20); FiiO's tools are meant for genuine JA11s, so an official upgrade on it is untested.

## Gotchas hit

- Claude Code's auto-mode classifier blocks `sudo` on scripts that open HID devices as root, even my own and even after approval; the file creation inside the blocked command is skipped too. Write the script with the Write tool and let the user run it with `! sudo ...`. A udev rule (`SUBSYSTEM=="hidraw", ATTRS{idVendor}=="2972", ATTRS{idProduct}=="0102", TAG+="uaccess"`) would avoid root; not installed.
- "Which IEM is on the DAC?" was never confirmed — the fit assumes Fission analog. Refit if it is another IEM.
- Not done: no listening A/B or re-measurement. The C7 and Fission were measured on a coupler; the Rational edition may differ.

## References

- [FiiO forum: JA11 firmware download and history](https://forum.fiio.com/note/showNoteContent.do?id=202406211150090736905), [FiiO: V2.2 announcement](https://www.fiio.com/newsinfo/1065234.html)

- [faxesystem/ja11-eq](https://github.com/faxesystem/ja11-eq) — `lib/fiioUsbHidHandler.js` and `lib/ja11Config.js`: frame layout, report ID 2, USER1 slot 3, save `0x19`, awaited-save fix
- [jeromeof/devicePEQ](https://github.com/jeromeof/devicePEQ) — upstream FiiO HID handler (0BSD)
- [ParkWardRR ktctl `docs/PROTOCOL.md`](https://github.com/ParkWardRR/fiio-ja11-jcally-jm12-moondropkt02-kt02h20-dac-amp-control/blob/main/docs/PROTOCOL.md) — static-RE spec of the same frame (CRC/endianness differ; not what the hardware needed)
- [CSI-Zone squig.link, Tin C7](https://csi-zone.squig.link/?share=Tin_C7) — measurement data
