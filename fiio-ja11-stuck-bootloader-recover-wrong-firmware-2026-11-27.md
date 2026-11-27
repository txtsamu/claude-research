---
type: troubleshooting
tags: [fiio, jadeaudio, ja11, kt02h20, ktmicro, usb-dac, firmware, brick, bootloader, ktflash, fiio-control, android, otg, fedora, linux, alsa, pipewire]
created: 2026-11-27
last_verified: 2026-11-27
status: current
---

# Recovering a FiiO JA11 that a wrong firmware flash left stuck in the KTMicro bootloader

**Host:** Fedora 43, kernel 7.3.5, dongle on a direct root-hub port (`1-1`)
**Tool:** `ktflash` 1.2.0, already built at `~/scratch/ktflash-repo/flasher/target/release/ktflash`
**Image:** `JadeAudio JA11_V2.2.bin`, 67,312 bytes, sha256 `65fea4995a4425064bc737c7bc8ec64e212c8b6297c6b9dfcc2b90a5814103de`

The dongle stopped appearing as a sound card and showed up as `8888:cdc0` (a CDC serial device) instead of `2972:0102`. That was self-inflicted: the wrong firmware had been flashed onto it earlier. A stock V2.2 reflash through the CDC bootloader fixed it on the first attempt, in four seconds of wire time.

This note is the *recovery* path. The full flashing walkthrough, including how the tool was built, is [[ktflash-rust-toolkit-linux-kt02h20-reflash-2026-11-26]].

## Recommended order: V2.1 over the bootloader, then upgrade to V2.2 in FiiO Control

**Practice recommended by the user after this repair** (see the provenance note at the end of this section). The idea is to land a known-good official image first and let the vendor's own upgrade path do the last step:

1. **Flash the official V2.1 image through the CDC bootloader** with `ktflash`, exactly as in sections 3 to 5 below.
2. **Verify V2.1 is really running** before going further: `bcdDevice` must read `2.10`, and the register dump must report version `2.1.0` with ADC PGA `0x3A = 3`.
3. **Upgrade to V2.2 through the FiiO Control Android app**, not through a second hand-rolled flash: plug the dongle into an Android phone over USB-C OTG and let the app do the upgrade (the app's firmware update flow, same path FiiO documents for V1.9 onward). Desktop alternatives exist if no phone is handy: the local `JadeAudio JA11 Upgrade Tool.exe` from the ZIP, or the WebHID page at <https://fiiocontrol.fiio.com/>.
4. **Re-verify after the upgrade:** `bcdDevice` back to `2.20`, register version string `2.2.0`, ADC PGA `0x3A = 4`.

Why this order, in practical terms:

- The V2.1 image is a small, well-known, 67,312-byte payload that the bootloader accepts cleanly, so step 1 rules out a corrupt or truncated image.
- FiiO's own upgrade flow then rewrites the same regions using the vendor's protocol and its own error reporting, which is the closest thing to a "factory" state short of a service centre.
- If something still fails afterwards, you know the hardware is suspect rather than the image, because two independent write paths both went through.

Be aware of three things before relying on step 3:

- **FiiO Control is an Android app.** The phone route is a USB-C OTG connection with the dongle in normal mode, not in the bootloader.
- **If the app does not see the dongle, try UAC 1.0.** FiiO's V2.0 changelog names "UAC1.0 mode" as something the app has to recognise, and the mode is switchable from the host with FiiO command `0x20` (`0` = UAC 1.0, `1` = UAC 2.0). In UAC 1.0 the dongle enumerates as `2972:0101` at full speed with `bcdADC 1.00` and caps at 96 kHz. Toggle it back to `1` afterwards.
- The desktop web page is listed as **Windows and macOS only** (Chrome, Edge or Opera for WebHID), so on Fedora it may not see the device at all. That is another reason to prefer the phone.

Provenance: this ordering is the user's recommendation from this repair. It was **not** exercised in this session, which flashed V2.2 directly through `ktflash` and stopped there, and it is not a hard requirement: the direct V2.2 write also worked. Treat it as the belt-and-braces path, not the only path.

## Time estimate

| Step | Time |
|---|---|
| identify + confirm state (`lsusb`, `journalctl`, `/proc/asound/cards`) | ~1 min |
| `ktflash probe`, `ktflash image`, dry run | **< 1 s** each (measured) |
| actual write (`--execute --yes`) | **4 s** from `staged` to `confirmed` in the tool journal (`1795767065` → `1795767069`) |
| verify card, stream, tone | ~1 min |
| **Total** | **under 5 minutes**, dominated by verification |

Switching image later (normal mode → bootloader → flash) adds an `unlock` step of about 30 s plus the same 4 s write.

## 1. Symptom: no sound card, a serial port instead

```bash
$ lsusb | grep -iE '2972|31b2|8888'
Bus 001 Device 005: ID 8888:cdc0 KTMicro 2021-07-15-0000-0000

$ cat /proc/asound/cards
 0 [HDMI     ]: HDA-Intel - HDA ATI HDMI
 1 [Generic  ]: HDA-Intel - HD-Audio Generic
 2 [Generic_1]: HDA-Intel - HD-Audio Generic
```

No `JA11` card, and `lsusb -t` showed both interfaces bound to `cdc_acm`:

```
Port 001: Dev 005, If 0, Class=Communications, Driver=cdc_acm, 12M
Port 001: Dev 005, If 1, Class=CDC Data,       Driver=cdc_acm, 12M
```

`dmesg`/`journalctl` gave the whole story in six lines:

```
Nov 27 15:04:32 usb 1-1: new full-speed USB device number 5 using xhci_hcd
Nov 27 15:04:32 usb 1-1: New USB device found, idVendor=8888, idProduct=cdc0, bcdDevice= 2.00
Nov 27 15:04:32 usb 1-1: Product: 2021-07-15-0000-0000
Nov 27 15:04:32 usb 1-1: Manufacturer: KTMicro
Nov 27 15:04:32 usb 1-1: SerialNumber: KT Virtual Com Port
```

`8888:cdc0` is the bootloader personality. It came up that way on plug-in and stayed there, which is the signature of a device whose flashed image will not boot: the boot ROM falls back to the USB bootloader. No host-side action put it there. (That is an inference from the behaviour, not something the boot ROM announced.)

Two things worth knowing from the earlier notes:

- `2972:0101` and `2972:0102` are normal mode, UAC 1.0 and UAC 2.0 respectively. `8888:cdc0` is bootloader. That is the only ID split that matters here.
- The saved PEQ state lives in a flash sector outside the firmware image, so a reflash erases it. See [[fiio-ja11-firmware-reverse-engineering-output-diagnosis-2026-11-26]].

## 2. Confirm the tool sees it as bootloader (read-only)

```bash
cd ~/scratch/ktflash-repo/flasher
./target/release/ktflash probe
```

```
● 8888:cdc0  [KT_USB_BOOT bootloader]  "" — ""  serial=""
    IF0 CDC (2/2/1)  [0x82 IN intr]
    IF1 CDC-Data (10/0/0)  [0x83 IN bulk, 0x03 OUT bulk]
```

`probe` is read-only and does **not** consume the one-shot `KTM` handshake. Use it freely. Do not run `bootdiag --send` before a flash; that eats the handshake and forces an unplug/replug.

## 3. Validate the image, then dry-run

```bash
IMG="/home/moo/Downloads/Archived/JadeAudio JA11 Firmware V2.2/JadeAudio JA11 Firmware V2.2/Firmware/JadeAudio JA11_V2.2.bin"
sha256sum "$IMG"
./target/release/ktflash image "$IMG"
./target/release/ktflash flash-cdc --image "$IMG"
```

Image parse:

```
● .../JadeAudio JA11_V2.2.bin  (67312 bytes)
    magic       KT_Helios_v1b
    chip        KT02H20B
    declared    67312 (0x106F0)
    build       75503ea 2025-06-30 V:1.0
    ℹ declared size matches file length (67312 bytes)
    ⚠ ENTY size 0x1D188 is larger than the whole file (0x106F0)
```

The `ENTY` warning is present on this official image and is harmless; the header carries no checksum, and `0x48` reads the same value in all five official versions.

Dry-run plan:

```
  flag=0 (CHP-only, direct RESET)  write base=0x00000  (from image[0x0F]=0x5f)
  packets    66 data + 1 final = 67 total, 67982 wire bytes
  [dry run] no hardware touched.
```

`flag=0` comes from image byte `0x0F`. This is the same plan shape as the 2026-11-26 run, so the image and path are unchanged.

## 4. Write

No `unlock` was needed: the device was already parked in the bootloader and nothing had sent `KTM` yet.

```bash
cd ~/scratch/ktflash-repo/flasher
./target/release/ktflash flash-cdc --image "$IMG" --execute --yes --expect 2972:0102
```

```
[execute] transport: serial /dev/ttyACM0
[execute] journal: /home/moo/.local/share/ktflash/1795767065-8888-cdc0.journal.json
  KTM    -> [78]  ok
  CHP    -> [a2, 85, 40, 12, 4b, 54, 30, 32, 48, 32, 30, 42, 66]  (13 bytes)
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

The `CHP` reply decodes to `KT02H20B` plus a trailing status byte (`0x66` here, `0x76` on the 2026-11-26 run). The trailing byte differs between runs and does not affect the flash. Do not read anything into it.

`/dev/ttyACM0` was `root:dialout 0660` and the user is in `dialout`, so no sudo and no udev rule were needed. `ModemManager` is inactive on this host, so it never grabbed the port.

## 5. Verification

```bash
$ lsusb -d 2972:0102
Bus 001 Device 006: ID 2972:0102 FiiO Electronics Technology JadeAudio JA11
  Negotiated speed: High Speed (480Mbps)
  bcdUSB    2.01
  bcdDevice 2.20
  bcdADC    2.00

$ cat /proc/asound/cards
 3 [JA11 ]: USB-Audio - JadeAudio JA11
            FIIO JadeAudio JA11 at usb-0000:13:00.0-1, high speed

$ grep -E "Endpoint|Sync" /proc/asound/card3/stream0 | head -4
    Endpoint: 0x04 (4 OUT) (ASYNC)
    Rates: 44100, 88200, 176400, 352800, 48000, 96000, 192000, 384000
    Sync Endpoint: 0x85 (5 IN)

$ pactl list short sinks
294  alsa_output.usb-FIIO_JadeAudio_JA11_2020-02-20-0000-0000-0000-00.analog-stereo  PipeWire  s32le 2ch 48000Hz  SUSPENDED

$ speaker-test -D plughw:JA11 -c 2 -t sine -f 1000 -l 1
Time per period = 4.993490
```

ASYNC out endpoint plus sync feedback EP is the post-flash signature; stock ADAPTIVE is the opposite. Playback was clean, no xruns.

## 6. Switching to V2.1 afterwards (unlocking from normal mode)

Once the dongle is healthy again, every further change of image starts from normal mode, so the bootloader has to be entered deliberately.

Official V2.1 link, from the same FiiO post:

```
https://fiio-firmware.fiio.net/JA11/%E8%8B%B1%E6%96%87%E5%9B%BA%E4%BB%B6/JadeAudio%20JA11%20Firmware%20V2.1.zip
```

```bash
cd /tmp/opencode
curl -fsSL -o ja11-v2.1.zip "https://fiio-firmware.fiio.net/JA11/%E8%8B%B1%E6%96%87%E5%9B%BA%E4%BB%B6/JadeAudio%20JA11%20Firmware%20V2.1.zip"
unzip -q -o ja11-v2.1.zip -d ja11-v21
sha256sum "ja11-v21/JadeAudio JA11 Firmware V2.1/JadeAudio JA11_V2.1.bin"
# 470ba6c0270efd5885c8e9015c381e6279e6c2299d6795843de12c89c10adfff
```

The `ktflash image` parse matches the documented V2.1 build: `b84a747 2024-10-10`, 67,312 bytes, `KT02H20B`, same harmless `ENTY` warning.

### Unlock: the permission trap

The dongle was in normal mode (`2972:0102`), so `unlock` had to be sent over HID. `ktflash unlock` failed even with the hidraw ACL in place:

```
$ ./target/release/ktflash unlock
error: open: Access denied (insufficient permissions)
```

The tool also opens the usbfs node, which is `root:root 0664`. ACLs on **both** nodes are needed:

```bash
for h in /sys/class/hidraw/hidraw*; do
  n=$(basename "$h")
  grep -qi 2972 "$h/device/uevent" 2>/dev/null && sudo setfacl -m u:moo:rw "/dev/$n"
done
# usbfs node for bus 001 device 008 in this run
sudo setfacl -m u:moo:rw /dev/bus/usb/001/008
```

Then:

```bash
$ ./target/release/ktflash unlock
sent T12345678 (10B) → device rebooting to bootloader 8888:cdc0
```

Both nodes are recreated on every replug, so both ACLs have to be reapplied each time. Doing the whole thing with `sudo` avoids the dance, at the cost of root-owned journal files.

### Flash

```bash
cd ~/scratch/ktflash-repo/flasher
IMG="/tmp/opencode/ja11-v21/JadeAudio JA11 Firmware V2.1/JadeAudio JA11_V2.1.bin"
./target/release/ktflash flash-cdc --image "$IMG" --execute --yes --expect 2972:0102
```

```
  KTM    -> [78]  ok
  CHP    -> [b2, 85, 40, 12, 4b, 54, 30, 32, 48, 32, 30, 42, 76]  (13 bytes)
  ERASE  -> [78]  ok
  ... 67/67 packets [78, a5]
  RESET  -> [78]  ok
[reprobe] ✅ 2972:0102 — Flash confirmed.
```

Note the `CHP` reply ends in `0x76` here and ended in `0x66` on the V2.2 write, so the trailing byte really does vary per image. Neither value means anything to the flash path.

### Proving which version is actually running

`bcdDevice` is the cheap check, and it moved: `2.20` → `2.10`.

```bash
$ lsusb -v -d 2972:0102 | grep -E "bcdDevice|Negotiated speed"
  Negotiated speed: High Speed (480Mbps)
  bcdDevice            2.10
```

The register dump is the decisive one. V2.1 carries ADC PGA index `3` (+14 dB) where V2.2 carries `4` (+20 dB):

```bash
sudo setfacl -m u:moo:rw /dev/hidraw6
cd ~/sessions/2026-10-26-iem-dsp-eq
sudo ./venv/bin/python -I dump_regs.py 2972 0102 ja11_v21_2026-11-27
```

```
ja11_v21_2026-11-27: 256/256 registers answered
0x3A: 0x3          <- V2.1 PerfCfg, was 0x4 on V2.2
0x3B: 0xd          <- DAC PGA 0 dB
0x24 DAC EQ en: 0x4
strings: version 2.1.0 | manuf FIIO | product JadeAudio JA11
DAC bands: 1000/2000/5000/8000/10000 Hz, 0.0 dB, Q 0.707
```

`cmd 0x0b` still reports `02 02` on V2.1, so do not use it to identify the image. `bcdDevice`, the register strings, and the PerfCfg index all agree.

## Gotchas

- **The bootloader state machine is one-shot per boot.** `KTM` is consumed once. If a flash fails partway, unplug and replug before retrying. A crashed attempt does not leave a second chance in the same session.
- **A `8888:cdc0` device that never leaves bootloader is a failed image, not a normal-mode device.** Do not try `unlock`; there is nothing to unlock.
- **The stock V2.2 image resets things you may have tuned.** It carries `PerfCfg` DAC PGA index `0x0d` = 0 dB and ADC PGA `0x04` = +20 dB, and the ERASE wipes the saved PEQ sector. The previously patched −12 dB DAC / 0 dB ADC gains and the flat EQ are gone after this flash. Re-patch the image and reflash if you want them back, and re-apply the EQ curve from the host.
- **`unlock` needs two ACLs, not one.** `ktflash unlock` on Linux opens both `/dev/hidrawN` and `/dev/bus/usb/BBB/DDD`, and the second is the one that produces `error: open: Access denied`. Both nodes change on replug.
- **No read-back.** There is no way to dump the old image, so no backup exists. Keep the official `.bin` somewhere permanent.
- **USB ID does not identify the model.** After a flash, a JA11, a JCALLY JM12 and a Moondrop KT02H20 all answer `2972:0102`.
- `utun`/vendor string `2021-07-15-0000-0000` and serial `KT Virtual Com Port` in bootloader mode are SDK defaults, not board identifiers.

## What was not verified

- **Why the wrong firmware bricked the boot.** Not investigated. The bootloader stays accessible, which is what made recovery possible; the failed image was never read back and cannot be.
- **Which wrong image was flashed**, and whether it was for a different chip (KT0211L vs KT02H20) or a different board. The CHP stage accepted the good image either way.
- **That the dongle sat in bootloader immediately after the bad flash.** The journal only shows it enumerating as `8888:cdc0` at 15:04:32 on 2026-11-27, not what happened before.
- The mic path, the FiiO app PEQ UI, and inline controls were not exercised after recovery. Playback was.

## References

- [ParkWardRR toolkit repo](https://github.com/ParkWardRR/fiio-ja11-jcally-jm12-moondropkt02-kt02h20-dac-amp-toolkit) — the flasher used here
- [`docs/REVERT.md`](https://github.com/ParkWardRR/fiio-ja11-jcally-jm12-moondropkt02-kt02h20-dac-amp-toolkit/blob/main/docs/REVERT.md) — bootloader entry, stock image sourcing, no-backup caveat
- [FiiO JA11 firmware thread](https://forum.fiio.com/note/showNoteContent.do?id=202406211150090736905) — source of the official V2.2 ZIP
- Local: [[ktflash-rust-toolkit-linux-kt02h20-reflash-2026-11-26]], [[kt02h20-generic-31b2-1052-crossflash-ja11-v21-2026-11-27]], [[kt02h20-jcally-dac-ja11-firmware-flash-protocol]], [[fiio-ja11-firmware-reverse-engineering-output-diagnosis-2026-11-26]], [[fiio-ja11-kt02h20-power-and-volume-ceilings-2026-11-16]]
