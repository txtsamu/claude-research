---
type: how-to
tags: [kt02h20, ktmicro, fiio-ja11, jcally-jm12, moondrop, usb-dac, firmware, ktflash, rust, fedora, linux]
created: 2026-11-26
last_verified: 2026-11-27
status: current
---

# Flashing a KT02H20 dongle from Fedora with the upstream `ktflash` Rust toolkit

**Repo:** `ParkWardRR/fiio-ja11-jcally-jm12-moondropkt02-kt02h20-dac-amp-toolkit` @ `1ede0a9` (v1.2.0)
**Host:** Fedora 43, kernel 6.x, dongle on a direct root-hub port (`1-1`)
**Image:** `JadeAudio JA11_V2.2.bin`, 67,312 bytes, sha256 `65fea4995a4425064bc737c7bc8ec64e212c8b6297c6b9dfcc2b90a5814103de`

This is the same cross-flash already documented in [[kt02h20-jcally-dac-ja11-firmware-flash-protocol]], but driven by the upstream project's own tool instead of the hand-written Python one. It worked first try. The interesting parts are the two things that differ from the README's happy path: the dongle was **already sitting in the bootloader** when the flash started (so `unlock` was never needed), and a reflash **wipes the saved PEQ curve**.

> [!CAUTION]
> There is still **no firmware read-back**. A reflash overwrites the image and the EQ config region. Have a known-good image before you start.

## Time estimate

| Step | Time |
|---|---|
| clone + `cargo build --release` | **12.9 s** (measured) |
| `ktflash image` validation | <1 s |
| dry-run plan | <1 s |
| actual write (`--execute`) | **5 s** from first packet to RESET ack (measured from the journal: staged 1795650345 → reset-issued 1795650348), + 2 s reprobe |
| verification (lsusb, ALSA, `speaker-test`, register dump) | ~2 min |
| **Total** | **under 10 minutes** wall clock, most of it verification |

The flash itself is fast enough that the main risk is not time but picking the wrong image or the wrong device.

## 0. What was actually plugged in

```bash
lsusb | grep -iE '31b2|2972|8888'
# Bus 001 Device 028: ID 2972:0102 FiiO Electronics Technology JadeAudio JA11
```

Already on JA11 firmware, serial `2020-02-20-0000-0000-0000` (the KTMicro SDK default, so it does not identify the model). The JCALLY JM12 flashed on 2026-10-20 carries the same serial string, and a stock Moondrop KT02H20 dongle is also `31B2:0111`, so **after a flash the two are indistinguishable by USB ID**. No stock `31B2:0111` device was attached, so this run was a same-image reflash of the already-JA11 unit.

Journal check for what came before:

```bash
journalctl -k --no-pager | grep -iE 'moondrop|31b2|2972|ja11'
# Nov 26 06:32:41 ... idVendor=2972, idProduct=0102, bcdDevice= 2.20
# Nov 26 06:44:30 usb 1-1: USB disconnect
# Nov 26 06:44:36 ... idVendor=8888, idProduct=cdc0   <- bootloader
```

## 1. Build the tool from source

```bash
mkdir -p ~/scratch && cd ~/scratch
git clone --depth 1 https://github.com/ParkWardRR/fiio-ja11-jcally-jm12-moondropkt02-kt02h20-dac-amp-toolkit ktflash-repo
cd ktflash-repo/flasher && cargo build --release
# Finished `release` profile [optimized] target(s) in 12.94s
```

`rust-toolchain.toml` pins 1.98.0, but Fedora's own `cargo` (1.99.1) does not read that file — no rustup needed, and 1.99 is newer than the pin. Only `libusb`-adjacent crates matter and they built clean.

## 2. Identify (read-only)

```bash
ktflash probe
```

`probe` only scans and prints; it does **not** send the unlock report. In this run it reported `8888:cdc0` because the dongle had already dropped into the bootloader on its own about six seconds earlier (journal above). If yours answers with `2972:0102` or `31b2:0111`, you are in normal mode and need `ktflash unlock` first.

### If the device answers with some other `31b2:*` PID

`ktflash unlock` only accepts `31b2:0111` and `2972:0102`. The check is in `flasher/src/main.rs`, `open_hid`:

```rust
let is_normal = (d.vendor_id() == KTMICRO_VID && d.product_id() == NORMAL_PID)  // 31b2:0111
    || (d.vendor_id() == FIIO_VID && d.product_id() == JA11_PID);              // 2972:0102
```

Any other KTMicro PID is skipped, and the tool reports that it found no normal-mode dongle. The firmware still speaks the same protocol, so send the unlock report yourself. Verified 2026-11-27 on a generic `31b2:1052 "KT02H20 Hifi Audio"` dongle:

```bash
cd ~/sessions/2026-10-26-iem-dsp-eq
sudo ./venv/bin/python -I -c "
import hid
d = hid.device(); d.open(0x31b2, 0x1052); d.write(b'T12345678\x00')
print('sent T12345678 (10B)')
"
```

The 10 bytes are report ID `0x54` (which is also ASCII `T`), the string `12345678`, and a NUL terminator. The dongle re-enumerates as `8888:cdc0` in about two seconds, and everything from section 3 onward applies unchanged. `/dev/hidrawN` is `0600 root:root`, so this half needs `sudo` or a fresh `setfacl` ACL. Full run: [[kt02h20-generic-31b2-1052-crossflash-ja11-v21-2026-11-27]].

## 3. Validate the image, then dry-run

```bash
ktflash image "/home/moo/Downloads/Archived/JadeAudio JA11 Firmware V2.2/JadeAudio JA11 Firmware V2.2/Firmware/JadeAudio JA11_V2.2.bin"
# magic KT_Helios_v1b / chip KT02H20B / declared 67312 (0x106F0) / size matches file length

ktflash flash-cdc --image ".../JadeAudio JA11_V2.2.bin"
# flag=0 (CHP-only, direct RESET)  write base=0x00000
# packets 66 data + 1 final = 67 total, 67982 wire bytes
# [dry run] no hardware touched.
```

`flag=0` is derived from image byte `0x0F`; the `flag=1` path adds VER/KEY and writes at base `0x8000`.

## 4. Write

Because the bootloader was already up and nothing had sent `KTM` yet, `unlock` was skipped. **Do not run `ktflash bootdiag --send` before flashing** — it consumes the one-shot handshake and you have to re-unlock.

```bash
ktflash flash-cdc --image ".../JadeAudio JA11_V2.2.bin" --execute --yes --expect 2972:0102
```

```
[execute] transport: serial /dev/ttyACM0
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

`--expect` makes the tool halt if the device comes back as anything other than the expected ID. `/dev/ttyACM0` was `root:dialout 0660` and the user is in `dialout`, so no udev rules or sudo were needed. The `packaging/99-ktflash.rules` file (uaccess + plugdev + ModemManager ignore) is only required for the **hidraw unlock** path on a stock device.

## 5. Verification

```bash
lsusb | grep 2972
# Bus 001 Device 030: ID 2972:0102 FiiO ... JadeAudio JA11
lsusb -v -d 2972:0102 | grep bcdDevice      # 2.20
cat /proc/asound/cards                      # card 3 [JA11]
grep -E 'Endpoint|Sync' /proc/asound/card3/stream0
# Endpoint: 0x04 (4 OUT) (ASYNC) / Sync Endpoint: 0x85 (5 IN)
speaker-test -D plughw:JA11 -c 2 -t sine -f 1000 -l 1   # clean, no xruns
```

Register read via the session scripts confirmed the version string `2.2.0` and PID `0x1022972`:

```bash
cd ~/sessions/2026-10-26-iem-dsp-eq
sudo ./venv/bin/python -I dump_regs.py 2972 0102 ja11_after_ktflash
# strings: version 2.2.0 | manuf FIIO | product JadeAudio JA11
```

ASYNC endpoint plus sync feedback EP is the same post-flash signature recorded on 2026-10-20, and it is the opposite of the stock ADAPTIVE endpoint.

## Gotchas

- **A reflash resets the saved PEQ.** Diffing the pre-flash register dump against the post-flash one: exactly 10 registers differ, all of them the DAC bands `0x26..0x2F`, and they went back to the image's factory curve (141 Hz −2.4 dB, 447 Hz +2.1 dB, …). Every other register, including version, strings, mic PGA and volume, was byte-identical. The C7 fit applied on 2026-10-26 is gone; re-apply with `ja11_c7.py apply` then `save` (see [[fiio-ja11-peq-match-tin-hifi-c7-hidraw]]).
- **The bootloader state machine is one-shot per boot.** `KTM` is consumed once. Anything that sends it (`bootdiag --send`, a failed flash) means unplug/replug before trying again.
- **`probe` is read-only**, so a `8888:cdc0` answer means the device was already in the bootloader, not that probe put it there.
- **USB ID no longer identifies the model.** `2972:0102` after a flash tells you nothing about whether the hardware is a JM12, a Moondrop or a JA11.
- **`unlock` is PID-gated.** Only `31b2:0111` and `2972:0102` get the automatic unlock. Other KTMicro PIDs (e.g. `31b2:1052`) need the 10-byte `T12345678` HID write by hand, as shown in section 2.
- **No backup.** Confirmed again by the tool's own warning; the journal only records the image hash, not the old firmware.

## What was not verified

- No stock `31B2:0111` Moondrop KT02H20 was attached, so the "flash a stock Moondrop" path was not exercised; the run was a same-image reflash of an already-JA11 unit.
- Mic, charging behaviour and the FiiO control app / PEQ UI were not tested.
- The udev-rule + `unlock` path was not exercised in the original run (device was already in bootloader). It was exercised later, on 2026-11-27, but only via the hand-rolled `T12345678` HID write against a `31b2:1052` board, because `ktflash unlock` does not accept that PID. The packaged udev rules themselves remain untested.

## References

- [Repo README](https://github.com/ParkWardRR/fiio-ja11-jcally-jm12-moondropkt02-kt02h20-dac-amp-toolkit) — tool surface, Linux-native claim, no-backup caveat
- [`docs/FLASHING.md`](https://github.com/ParkWardRR/fiio-ja11-jcally-jm12-moondropkt02-kt02h20-dac-amp-toolkit/blob/main/docs/FLASHING.md) — dry-run then `--execute --yes`, one-shot bootloader note
- [`docs/COMPATIBILITY.md`](https://github.com/ParkWardRR/fiio-ja11-jcally-jm12-moondropkt02-kt02h20-dac-amp-toolkit/blob/main/docs/COMPATIBILITY.md) — Moondrop `31B2:0111` marked confirmed
- [`docs/REVERT.md`](https://github.com/ParkWardRR/fiio-ja11-jcally-jm12-moondropkt02-kt02h20-dac-amp-toolkit/blob/main/docs/REVERT.md) — revert needs a stock image, reset-button bootloader entry
- [`packaging/99-ktflash.rules`](https://github.com/ParkWardRR/fiio-ja11-jcally-jm12-moondropkt02-kt02h20-dac-amp-toolkit/blob/main/packaging/99-ktflash.rules) — uaccess/plugdev/ModemManager rules
- Local: [[kt02h20-jcally-dac-ja11-firmware-flash-protocol]], [[kt02h20-generic-31b2-1052-crossflash-ja11-v21-2026-11-27]], [[fiio-ja11-stuck-bootloader-recover-wrong-firmware-2026-11-27]], [[fiio-ja11-peq-match-tin-hifi-c7-hidraw]], [[ktmicro-dsp-dongles-fission-ja11-chu2-same-chip-comparison-and-otg]], [[fission-rational-hifi-firmware-upgrade-linux-flasher-ktmicro-kt0211l]]
