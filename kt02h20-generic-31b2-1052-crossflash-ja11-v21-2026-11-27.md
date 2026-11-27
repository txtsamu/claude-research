---
type: how-to
tags: [kt02h20, ktmicro, 31b2-1052, crossflash, ja11, fiio, jadeaudio, ktflash, firmware, usb-dac, hid, fedora, linux, alsa, pipewire]
created: 2026-11-27
last_verified: 2026-11-27
status: current
---

# Cross-flashing a generic KT02H20 dongle (`31b2:1052`) to FiiO JA11 V2.1

**Host:** Fedora 43, kernel 7.3.5, dongle on a direct root-hub port (`1-1`)
**Tool:** `ktflash` 1.2.0 at `~/scratch/ktflash-repo/flasher/target/release/ktflash`
**Image:** `JadeAudio JA11_V2.1.bin`, 67,312 bytes, sha256 `470ba6c0270efd5885c8e9015c381e6279e6c2299d6795843de12c89c10adfff`
**Unlock helper:** the local `KT02H20` Python class at `~/sessions/2026-10-26-iem-dsp-eq/ktm/`

A generic KTMicro reference dongle, `31b2:1052 "KTMicro / KT02H20 Hifi Audio"` running stock firmware `1.0.1`, was reflashed with the FiiO JadeAudio JA11 V2.1 image. It came back as a fully working `2972:0102 "JadeAudio JA11"`: card 3, high speed, UAC 2.0, ASYNC endpoint with a sync feedback EP, and a clean 1 kHz tone.

This is a *cross-flash*, not a recovery. The device was healthy and booted its own firmware. The recovery path for a dongle that ends up stuck in the bootloader is [[fiio-ja11-stuck-bootloader-recover-wrong-firmware-2026-11-27]]; the tool build and protocol background is [[ktflash-rust-toolkit-linux-kt02h20-reflash-2026-11-26]].

> **The original firmware cannot be recovered.** There is no read-back path on this chip. Stock `1.0.1` is gone after the erase. Everything below assumes you accept that.

## Time estimate

| Step | Time | Source |
|---|---|---|
| record the pre-flash identity (`probe` + register dump) | ~20 s | measured |
| unlock (HID `T12345678` → bootloader) | **< 1 s** plus ~2 s re-enumeration | measured |
| actual write (`flash-cdc --execute --yes`) | **4 s** from `staged` to `confirmed` in the tool journal (`1795768364` → `1795768368`, 15:32:44 → 15:32:48) | measured |
| verify card, stream, tone, register version | ~2 min | measured |
| **Total** | **under 4 minutes** | |

The write time is not an estimate. It comes from the tool's own journal timestamps.

## 0. Record what you are about to destroy

Do this first. It is read-only, and it is the only record of the original firmware that will ever exist.

```bash
cd ~/scratch/ktflash-repo/flasher
./target/release/ktflash probe
```

```
● 31b2:1052  [KTMicro dongle]  "" — ""  serial=""
    IF0 Audio (1/1/32)  []
    IF1 Audio (1/2/32)  []
    IF1 Audio (1/2/32)  [0x84 IN iso]
    IF2 Audio (1/2/32)  []
    IF2 Audio (1/2/32)  [0x04 OUT iso]
    IF2 Audio (1/2/32)  [0x04 OUT iso]
    IF2 Audio (1/2/32)  [0x04 OUT iso]
    IF3 HID (3/0/0)  [0x83 IN intr, 0x03 OUT intr]
```

The USB identity:

```bash
$ lsusb -v -d 31b2:1052 | grep -E "idVendor|idProduct|bcdDevice|iManufacturer|iProduct|bcdADC|Negotiated"
  Negotiated speed: High Speed (480Mbps)
  idVendor           0x31b2 KTMicro
  idProduct          0x1052 KT02H20 Hifi Audio
  bcdDevice            0.01
  iManufacturer           1 KTMicro
  iProduct                3 KT02H20 Hifi Audio
  bcdADC               2.00
```

And the firmware's own version, straight from register space:

```bash
cd ~/sessions/2026-10-26-iem-dsp-eq
sudo ./venv/bin/python -I dump_regs.py 31b2 1052 kt02h20_1052_stock_2026-11-27
```

```
kt02h20_1052_stock_2026-11-27: 256/256 registers answered
0x00 (REG: marker): 0x3a474552
0x01 model flags: 0x200
0x5B vid/pid: 0x105231b2
0x24 DAC EQ en: 0x2
0x18 ADC EQ en: 0x2
0x3A: 0x3
0x3B: 0xd
strings: version 1.0.1 | manuf KTMicro | product KT02H20 Hifi Audio | serial 2020-02-20-0000-0000-0000
DAC bands: 1000/2000/5000/8000/10000 Hz, 0.0 dB, Q 0.707
```

Save that JSON. `data/regs_kt02h20_1052_stock_2026-11-27.json` is the only fingerprint of the stock firmware that will exist after the flash.

Two things in that dump were quietly reassuring. The register marker `0x3a474552` ("REG:" little-endian) and model flags `0x200` are identical to the JA11, so this is the same firmware family, not a lookalike. And `0x3A = 3` with `0x3B = 0xd` (ADC +14 dB, DAC 0 dB) already matched the JA11 V2.1 PerfCfg defaults, which makes it plausible that the amp gain behaviour will not shift.

## 1. Unlock: `ktflash unlock` refuses this PID

The bootloader is not entered by a button. It is entered by a vendor HID command, the 10-byte string `T12345678\0`. The first byte doubles as ASCII `T` and as HID report ID `0x54`.

`ktflash unlock` only looks for two identities (`flasher/src/main.rs`, `open_hid`):

```rust
let is_normal = (d.vendor_id() == KTMICRO_VID && d.product_id() == NORMAL_PID)  // 31b2:0111
    || (d.vendor_id() == FIIO_VID && d.product_id() == JA11_PID);              // 2972:0102
```

`31b2:1052` is neither, so the tool skips it and reports that it found no normal-mode dongle. This was established by reading the source, not by running the command against the device. The same HID command works fine on this PID, so the fix is to send that one packet directly:

```bash
cd ~/sessions/2026-10-26-iem-dsp-eq
sudo ./venv/bin/python -I -c "
import hid
d = hid.device()
d.open(0x31b2, 0x1052)
d.write(b'T12345678\x00')
print('sent T12345678 (10B)')
"
```

```
sent T12345678 (10B)
```

Two seconds later:

```bash
$ lsusb | grep -iE '8888|31b2'
Bus 001 Device 010: ID 8888:cdc0 KTMicro 2021-07-15-0000-0000
$ ls -l /dev/ttyACM0
crw-rw----. 1 root dialout 166, 0   Nov 27 15:32 /dev/ttyACM0
```

Root is needed for the unlock because `/dev/hidrawN` is `0600 root:root`. `sudo` is the short route. The alternative is `setfacl -m u:$USER:rw /dev/hidrawN`, reapplied after every replug.

Do not use the local `KT02H20` class's `hid_path` to find the node. `HIDTransport.find_hidraw()` computes `'/dev/' + basename(dirname(uevent))`, which yields `/dev/device` rather than `/dev/hidraw6`. It fails harmlessly and falls back to opening by VID:PID, which is why the direct `hid.device()` snippet above is simpler and more honest.

## 2. Flash

The bootloader is one-shot per boot, so confirm it is there and write immediately.

```bash
cd ~/scratch/ktflash-repo/flasher
IMG="/tmp/opencode/user-v21/JadeAudio JA11 Firmware V2.1/JadeAudio JA11_V2.1.bin"
sha256sum "$IMG"
./target/release/ktflash probe
./target/release/ktflash flash-cdc --image "$IMG" --execute --yes --expect 2972:0102
```

```
470ba6c0270efd5885c8e9015c381e6279e6c2299d6795843de12c89c10adfff  .../JadeAudio JA11_V2.1.bin
● 8888:cdc0  [KT_USB_BOOT bootloader]  "" — ""  serial=""
    IF0 CDC (2/2/1)  [0x82 IN intr]
    IF1 CDC-Data (10/0/0)  [0x83 IN bulk, 0x03 OUT bulk]

flash-cdc plan for .../JadeAudio JA11_V2.1.bin
  image      67312 bytes  chip="KT02H20B" magic="KT_Helios_v1b"
  flag=0 (CHP-only, direct RESET)  write base=0x00000  (from image[0x0F]=0x5f)
  packets    66 data + 1 final = 67 total, 67982 wire bytes

  KTM    -> [78]  ok
  CHP    -> [b2, 85, 40, 12, 4b, 54, 30, 32, 48, 32, 30, 42, 76]  (13 bytes)
  ERASE  -> [78]  ok
  PWO    -> [78, 78]  ok
  KSTA   -> [78]  ok (erase complete)
  pkt   0/67 @0x00010 len=1008 -> [78, a5]
  ... all 67 packets -> [78, a5]
  STP    -> [78]  ok
  RESET  -> [78]  ok

UPGRADE FIRMWARE SUCESS — device should re-enumerate to normal mode.
[reprobe] ✅ 2972:0102 — Flash confirmed.
```

`/dev/ttyACM0` is `root:dialout 0660` and the user is in `dialout`, so the flash half needs no sudo, no ACL and no udev rule. ModemManager is inactive on this host.

## 3. Verify

```bash
$ lsusb -v -d 2972:0102 | grep -E "Negotiated speed|bcdDevice|bcdADC|iProduct"
  Negotiated speed: High Speed (480Mbps)
  bcdDevice            2.10
  bcdADC               2.00
  iProduct                3 JadeAudio JA11

$ cat /proc/asound/cards | tail -2
 3 [JA11 ]: USB-Audio - JadeAudio JA11
            FIIO JadeAudio JA11 at usb-0000:13:00.0-1, high speed

$ grep -E "Interface|Format|Endpoint|Rates|Sync" /proc/asound/card3/stream0 | head -8
  Interface 2
    Altset 1
    Format: S16_LE
    Endpoint: 0x04 (4 OUT) (ASYNC)
    Rates: 44100, 88200, 176400, 352800, 48000, 96000, 192000, 384000
    Sync Endpoint: 0x85 (5 IN)

$ speaker-test -D plughw:JA11 -c 2 -t sine -f 1000 -l 1
Time per period = 4.993484
```

Capture also enumerates, from the firmware descriptor set:

```
Capture:
  Interface 1
    Altset 1
    Format: S16_LE
    Channels: 1
    Endpoint: 0x84 (4 IN) (ASYNC)
```

The definitive version check is the register dump:

```bash
for h in /sys/class/hidraw/hidraw*; do
  n=$(basename "$h")
  grep -qi 2972 "$h/device/uevent" && sudo setfacl -m u:moo:rw "/dev/$n"
done
cd ~/sessions/2026-10-26-iem-dsp-eq
sudo ./venv/bin/python -I dump_regs.py 2972 0102 kt02h20_1052_ja11v21_2026-11-27
```

```
kt02h20_1052_ja11v21_2026-11-27: 256/256 registers answered
0x01 model flags: 0x200
0x5B vid/pid: 0x1022972
0x24 DAC EQ en: 0x4
0x3A: 0x3
0x3B: 0xd
strings: version 2.1.0 | manuf FIIO | product JadeAudio JA11 | serial 2020-02-20-0000-0000-0000
```

`bcdDevice 2.10`, version string `2.1.0`, and `0x3A = 3` all agree. `cmd 0x0b` still reports `02 02` on V2.1, so it remains useless for version identification, exactly as on the real JA11.

## 4. What changed, before and after

| | Before (stock `1.0.1`) | After (FiiO `2.1.0`) |
|---|---|---|
| USB ID | `31b2:1052` | `2972:0102` |
| Product string | `KT02H20 Hifi Audio` | `JadeAudio JA11` |
| `bcdDevice` | `0.01` | `2.10` |
| Card name | `[Audio]` | `[JA11]` |
| `0x24` DAC EQ en | `0x2` | `0x4` |
| `0x18` ADC EQ en | `0x2` | `0x2` |
| `0x3A` ADC PGA | `3` (+14 dB) | `3` (+14 dB) |
| `0x3B` DAC PGA | `0xd` (0 dB) | `0xd` (0 dB) |
| Serial string | `2020-02-20-0000-0000-0000` | unchanged |

The gain indices did not move, because the stock board already used the same values the JA11 V2.1 image carries. Only `0x24` (DAC EQ enable bits) differs. Whether that bit difference means anything audible was not established; the tone played fine with flat bands either way.

## Gotchas

- **`ktflash unlock` does not support `31b2:1052`.** Only `31b2:0111` and `2972:0102` are accepted by `open_hid`. Once flashed, the device becomes `2972:0102` and the normal `ktflash unlock` path works for every future flash.
- **The pre-flash identity is unbackupable.** No read-back exists. If you care about the stock image more than the FiiO DSP, stop before step 1.
- **The serial string is not unique.** Stock and JA11 firmware both report `2020-02-20-0000-0000-0000`, and the real FiiO JA11 does too. With two same-chip dongles plugged in, tell them apart by `lsusb` bus/device address and by ALSA card number, never by serial. Expect `JA11` and `JA11_1` as card names.
- **`sudo` is the path of least friction for the HID half.** `/dev/hidrawN` is `0600 root:root` and is recreated on replug, so ACLs have to be reapplied every time.
- **This PID is not in the confirmed compatibility roster.** `docs/COMPATIBILITY.md` lists only `31b2:0111` as proven in that repo, and "unknown generic KT02H20 adapters" as low confidence. The flash worked, but it is one data point.
- **The erase wipes the PEQ sector.** The stock board had flat bands, so nothing was lost here, but any saved curve would have gone.

## What was not verified

- **Microphone hardware.** The capture device, endpoint `0x84` and the `Mic Capture Volume` / `Mic Capture Switch` controls all enumerate after the flash, but whether this board physically has a mic, and whether the JA11 mic gain patch suits it, was not tested with actual audio.
- **Amp gain and output level on this specific board.** A 1 kHz tone played at OS level without xruns. Nobody listened, so loudness, channel balance and distortion at high volume are unknown. The matching PerfCfg indices make a surprise unlikely, not impossible.
- **Long-run stability.** Everything above is a few minutes of uptime.
- **The V2.2 upgrade path on this unit.** Only V2.1 was written, by request. The V2.1-then-FiiO-Control order documented in the recovery note was not run on this device either.
- **`ktflash unlock` on `31b2:1052` was not attempted.** The limitation comes from source inspection, not from an observed failure message.

## References

- [ParkWardRR KT02H20 toolkit](https://github.com/ParkWardRR/fiio-ja11-jcally-jm12-moondropkt02-kt02h20-dac-amp-toolkit) — `ktflash` and the protocol docs
- [`docs/COMPATIBILITY.md`](https://github.com/ParkWardRR/fiio-ja11-jcally-jm12-moondropkt02-kt02h20-dac-amp-toolkit/blob/main/docs/COMPATIBILITY.md) — which dongles are proven and which are guesses
- [`docs/REVERT.md`](https://github.com/ParkWardRR/fiio-ja11-jcally-jm12-moondropkt02-kt02h20-dac-amp-toolkit/blob/main/docs/REVERT.md) — recovery and the no-backup caveat
- [FiiO JA11 firmware thread](https://forum.fiio.com/note/showNoteContent.do?id=202406211150090736905) — V2.1 and V2.2 ZIPs
- Local: [[fiio-ja11-stuck-bootloader-recover-wrong-firmware-2026-11-27]], [[ktflash-rust-toolkit-linux-kt02h20-reflash-2026-11-26]], [[kt02h20-jcally-dac-ja11-firmware-flash-protocol]], [[fiio-ja11-firmware-reverse-engineering-output-diagnosis-2026-11-26]]
