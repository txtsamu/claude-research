---
type: investigation
tags: [kt02h20, ktmicro, jcally, fiio-ja11, usb-dac, firmware, reverse-engineering, hid, cdc-acm, wine, capstone, fedora]
created: 2026-10-20
last_verified: 2026-10-20
status: current   # protocol decoded + cross-platform CLI built and unit-tested; the actual flash is NOT done (no software backup possible, user decision pending)
---

# Jcally (KTMicro KT02H20) USB-C DAC: flashing FiiO JA11 firmware — protocol RE + cross-platform CLI

**Goal:** flash `JadeAudio JA11 Firmware V2.2.zip` (FiiO JA11 firmware) onto a Jcally USB-C DAC adapter from Fedora (no Windows), backing up the original first, and build a multiplatform CLI.

**Outcome:**
- The vendor updater is Windows-only (Qt GUI). Its protocol was decoded (static disassembly + live probing) and matches public research.
- **A byte-exact backup of the original firmware is impossible in software** — the KT02H20 boot ROM has no read command (confirmed independently by public research). Revert = flash a stock image; for Jcally that is `jcally_jm12_v1.3.bin` (see References — I could not find a direct download).
- CLI built: `~/kt02h20-flasher/ktflash.py` (+ tests, README, udev rule). Dry-run by default.
- Chip ID reported by the dongle's bootloader = `KT02H20B` = chip ID in the JA11 image header, so the vendor "bin matches chip" check passes.

## 0. Identify the device (normal mode)

```bash
lsusb                       # 31b2:0111 KTMicro "KT02H20 HIFI Audio"
cat /proc/asound/cards      # card 3: USB-Audio - KT02H20 HIFI Audio
cat /proc/asound/card3/stream0   # S16/S24_3LE/S32, 44.1k..384k, mic 48k mono
amixer -c 3 contents        # PCM Playback Volume 0..85 (-42.5..0 dB), Mic
lsusb -v -d 31b2:0111       # UAC2, 4 interfaces, HID on interface 3
python3 - <<'EOF'
print(open('/sys/class/hidraw/hidraw6/device/report_descriptor','rb').read().hex(' '))
EOF
```

HID descriptor: report ID `0x01` (consumer keys), vendor reports `0x4B` and `0x54`, each 10 bytes in and out. (hidraw number varies — find it via `readlink -f /sys/class/hidraw/hidraw*/device | grep 31B2`.)

## 1. What's in the firmware zip

```bash
mkdir -p ~/scratch/ja11 && cd ~/scratch/ja11
unzip ~/Downloads/"JadeAudio JA11 Firmware V2.2.zip"
strings -n 6 "Firmware/JadeAudio JA11_V2.2.bin" | head -30
```

- `JadeAudio JA11_V2.2.bin` 67,312 bytes. Header: `KT_Helios_v1b___` (16 B magic) then `KT02H20B` (chip id, offset 0x10), LE32 file size at 0x1C (= 0x106F0 = file size), build `Jul 8 2025`, `PerfCfg:` block at 0x10D8 with product string `JadeAudio JA11`, USB string `TX-384Khz Hifi Type-C Audio`.
- `JadeAudio JA11 Upgrade Tool.exe` — Qt/MinGW 32-bit PE, 19.8 MB. Ini says `HomeVID=0x31b2` ("KT_USB_BOOT_UI 021X 0211L 02H0X 02F0X 1.2.10").

## 2. Dead ends (don't repeat)

1. **Wine GUI route.** `wine-11.0 (Staging)` runs the tool and its device combobox lists the dongle (needs `sudo setfacl -m u:moo:rw /dev/hidrawN`). But the tool finds its *serial* bootloader via Qt `QSerialPortInfo` VID/PID (`cmp ax,0x8888 / 0xcdc0` at `0xb8f3ab`) which Wine cannot supply for ttyACM. Would need a patched exe + fake `SERIALCOMM` registry entries. Abandoned for a native tool.
2. **usbmon capture** — `/sys/kernel/debug/usb/usbmon/*` returns `Operation not permitted` even as root (kernel lockdown / Secure Boot). Used `WINEDEBUG=+hid,+hidraw` instead — but Scan only reads descriptors, so no report traffic appeared until Upgrade. Static analysis was needed.
3. **Probing the bootloader out of order** — see §4 "one-shot state machine". Cost three replugs.
4. **Port power-cycle in software** (`echo 1 > /sys/bus/usb/devices/usb1/1-0:1.0/usb1-port1/disable`, or `authorized` 0/1) re-enumerates the device but does NOT reset the boot ROM state (VBUS stays up). Only a physical replug does.

## 3. Static reverse engineering of the vendor tool (no Ghidra needed)

```bash
python3 -m venv ~/scratch/venv && ~/scratch/venv/bin/pip install capstone pefile
# strings -> code xrefs: find "start upgrade", "hid device not found", HidD_* names, etc.
# (own scripts: parse PE sections, search for the 4-byte VA in .text, disassemble with capstone CS_MODE_32)
```

Pitfalls: don't name a helper `dis.py` (shadows the stdlib `dis`, capstone import breaks). In this environment an RTK grep hook mangles `grep` output — read dumps with the Read tool instead.

Findings (VAs in the 32-bit exe):
- `0x1090xxx` is **hidapi 0.10.1** (version string present). HID functions are `LoadLibrary("hid.dll")`/`GetProcAddress`.
- `0x6260b0` = **enter-bootloader**: `hid_write` of 10 bytes `54 31 32 33 34 35 36 37 38 00` = report ID `0x54` + ASCII `"12345678"` (padded to the 11-byte report).
- `0xb8f200` timer slot: state 0 scan serial ports for VID `0x8888` / PID `0xCDC0` (up to 500 tries), state 1 send handshake every tick (up to 1000 = 10 s: "ShakeHand out time").
- `0xb8c380` RX handler, 13-state jump table at `0x113e558`. Chinese log strings give state names (获取boot版本号 = get boot version, 获取ChipID, 设置参数 = set parameters, 切换时钟 = switch clock, 开始boot, 停止boot, 获取INF).
- Command tokens (opcode byte + 3 ASCII): `1e 4b 54 4d` KTM (handshake), `f0 56 45 52` VER, `f0 4b 45 59` KEY, `d2 43 48 50` CHP, `2d 29 00 10 0e 15 00 60 00 bc` (10-byte erase/setup block), `3c 50 57 4f` `<PWO`, `4b 53 54 41` KSTA, `96 53 54 50` STP, `f0 49 4e 46` INF, `5a 52 53 54` ZRST.
- Replies are matched with `QByteArray::indexOf`: `0x78` = command accepted, `0xA5` = data block accepted. The RX buffer is cleared after each match.
- Data packet builder `0x54d7d0`: `69 | Llo | (Lhi&0x1f)|(top3<<5) | addr[3 LE] | payload | CRC32`; CRC table at `0x120e020` is the reflected `0xEDB88320` table (verified all 256 entries), init 0, **no final xor**, over header+payload, appended LE. Bank table byte `0x13e90c4[1] = 0x20` → region = 32 blocks; `top3 = 1` on region starts else `0b111`. Block 0 = `image[0x10:0x400]` at `base+0x10`.
- Final packet `0x5733a0`: header `69 10 E0 <base>`, payload `image[0:0x10]` — the header is written **last** so an interrupted flash stays unbootable instead of half-valid.
- Size check: header LE32 @0x1C must equal file size ("file size is wrong"). Chip check: CHP reply bytes 4..12 must equal image bytes 0x10..0x18 ("bin文件与芯片型号对应关系错误").
- Flag at `[ebx+0x38]` (the "BOOT" button, default 0): 0 → CHP straight after handshake, base 0, `STP → RESET`; 1 → also VER/KEY, base 0x8000, `INF` size+CRC check.

## 4. Live probing of the dongle (read-only)

```bash
sudo setfacl -m u:moo:rw /dev/hidraw6        # ACL is lost on replug
python3 - <<'EOF'
import os,time,glob,select,tty
fd=os.open('/dev/hidraw6',os.O_RDWR); os.write(fd,bytes([0x54])+b'12345678'+b'\x00\x00'); os.close(fd)
while not glob.glob('/dev/ttyACM*'): time.sleep(0.02)      # appears ~1 s later: 8888:cdc0
time.sleep(0.15)
p=os.open(glob.glob('/dev/ttyACM*')[0],os.O_RDWR|os.O_NOCTTY); tty.setraw(p)
def rx(w):
    out=b''; end=time.time()+w
    while time.time()<end:
        r,_,_=select.select([p],[],[],0.01)
        if r: out+=os.read(p,4096); end=time.time()+0.05
    return out
os.write(p,bytes.fromhex('1e4b544d')); print('KTM ->',rx(0.3).hex(' '))   # 78
os.write(p,bytes.fromhex('d2434850')); print('CHP ->',rx(1.0).hex(' '))   # b2 85 40 12 | 4b 54 30 32 48 32 30 42 | 76
EOF
```

Results: `KTM → 78`; `CHP → b2 85 40 12 "KT02H20B" 76`. Boot ROM USB string: `2021-07-15-0000-0000`, CDC-ACM, EP 0x03 OUT / 0x83 IN.

**One-shot state machine (important):** the bootloader consumes `KTM` once per boot; after that it only accepts the *next expected* command. Sending `VER`/`KEY` out of order (I did, before reading the state machine) gave no / odd replies (`KEY → 78 00 78`), and afterwards even `KTM` got no answer. A software reset doesn't clear it; **unplug/replug returns the dongle to normal audio mode** (verified: boot flag is not persistent). `ZRST` is only honoured in the correct state.

## 5. Public research that confirms and extends this

Found via web search *after* the RE (the RE agrees byte-for-byte with their packet planner/CRC): `SMIPE444/...kt02h20-dac-amp-toolkit` (Rust CLI/TUI, docs `CDC-PROTOCOL.md`, `COMPATIBILITY.md`, `REVERT.md`) and `gxcreator/ktmicro-tools` (Python runtime register tool). Key claims, not independently verified by me:
- No firmware read exists (bootloader has no read command, runtime reads return zeros) → backup needs JTAG/SWD or chip-off.
- Cross-flash to JA11 firmware is widely reported working for JCALLY JM12, Audiocular A16x/C18, Moondrop KT02H20 (`31B2:0111`, same VID:PID as this unit). After flashing the dongle enumerates as `2972:0102 "JadeAudio JA11"` and gains FiiO DSP/PEQ.
- "Same chip is not enough": wiring, clocks, calibration and flash layout can differ → wrong-hardware flash can mute output or disable the mic until reflashed. Kiwi Ears AD1: avoid.
- A dongle left in `8888:cdc0` after a failed write is not bricked (boot ROM survives); re-flash a valid image.

## 6. The CLI

`~/kt02h20-flasher/` — `ktflash.py` (Python 3.8+, deps `pyserial`; `hidapi` optional, Linux falls back to `/dev/hidraw`), `test_ktflash.py`, `README.md`, `packaging/99-ktflash.rules`.

```bash
cd ~/kt02h20-flasher && pip install pyserial hidapi
python3 ktflash.py probe
python3 ktflash.py image "JadeAudio JA11_V2.2.bin"        # validate + packet plan (66 data + 1 final)
python3 ktflash.py flash  "JadeAudio JA11_V2.2.bin"        # DRY RUN
python3 ktflash.py flash  "JadeAudio JA11_V2.2.bin" --execute --yes --no-backup-ok   # writes
KT_TEST_IMAGE="JadeAudio JA11_V2.2.bin" python3 -m unittest test_ktflash -v   # 9 tests, mock bootloader
```

Safety rails: dry-run default; write needs three flags; aborts **before erase** if CHP chip id ≠ image chip id; erase block is only sent after the chip check; the 16-byte header is written last. Tests reassemble the flash from the packets through a mock bootloader and compare to the original image byte-for-byte.

## 7. Status / next steps

- [ ] User decision: flash with no software backup? Recommended first: obtain `jcally_jm12_v1.3.bin` (stock) so the device can be reverted, and confirm the exact Jcally model.
- [ ] Dongle is currently parked in bootloader mode (`8888:cdc0`) from the probing — replug to restore audio.
- [ ] If flashed: record the post-flash `lsusb`, mixer/volume behaviour, and whether the dongle needs the reverted image.

## References

- [SMIPE444/fiio-ja11-jcally-jm12-moondropkt02-kt02h20-dac-amp-toolkit (ktflash)](https://github.com/SMIPE444/fiio-ja11-jcally-jm12-moondropkt02-kt02h20-dac-amp-toolkit) — protocol, compatibility and revert docs (`docs/CDC-PROTOCOL.md`, `docs/COMPATIBILITY.md`, `docs/REVERT.md`, `flasher/src/proto/ktcdc.rs`)
- [gxcreator/ktmicro-tools](https://github.com/gxcreator/ktmicro-tools) — KT02H20 runtime control tool (HID report 0x4B register access)
