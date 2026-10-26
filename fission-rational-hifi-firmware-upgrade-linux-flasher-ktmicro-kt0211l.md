---
type: how-to
tags: [tanchjim, fission, ktmicro, kt0211l, firmware, flash, reverse-engineering, rea, ghidra, ilspy, dotnet, hid, cdc-acm, fedora]
created: 2026-10-27
last_verified: 2026-10-27
status: current   # flashed 2026-10-27: build May 6 2025 -> Jun 10 2025, INF size+CRC verified; C7 EQ re-applied and saved
---

# Upgrading the Tanchjim FISSION-Rational HiFi Edition firmware from Linux (vendor tool reverse-engineered with rea + a Linux flasher)

The vendor firmware upgrade is a Windows-only GUI. Instead of a Windows machine, the vendor tool was reverse-engineered with `rea` (Ghidra) + `ilspycmd`, and the existing Linux flasher (`ktflash.py`, built earlier for the KT02H20/JA11) was extended to flash the vendor image. Siblings: [tanchjim-fission-ktmicro-dsp-peq-match-tin-hifi-c7.md](tanchjim-fission-ktmicro-dsp-peq-match-tin-hifi-c7.md), [kt02h20-jcally-dac-ja11-firmware-flash-protocol.md](kt02h20-jcally-dac-ja11-firmware-flash-protocol.md), [ktmicro-dsp-dongles-fission-ja11-chu2-same-chip-comparison-and-otg.md](ktmicro-dsp-dongles-fission-ja11-chu2-same-chip-comparison-and-otg.md).

> **Files:** session folder `~/sessions/2026-10-26-iem-dsp-eq/` (downloads, `re/` decompiles, `tools/`); the flasher and its tests are also in this repo: [kt0211l-flasher/](kt0211l-flasher/).

## 1. Result

| | before | after |
|---|---|---|
| Firmware build (regs `0x08–0x0D`) | May  6 2025 13:37:56, hash `459709e` | **Jun 10 2025 13:18:26**, hash `03448c3` |
| Version string (`0x04`) | 1.0.1 | 1.0.1 (the vendor package is "v1.0.1_20250610"; same version string, newer build) |
| Mic PGA (`0x3A`) | `0x5` | `0x3` (probably the "microphone occupancy" fix) |
| Factory DAC bands | 36/604/6000/10954/18860 Hz | 230 Hz −2.5 Q4, 310 Hz −1.0 Q4, 3000 Hz −0.8 Q4.5, 9200 Hz +1.8 Q4, 10000 Hz 0 |

Bootloader `INF` returned size 43440 and CRC-32 `0xd5edcafb`, equal to the image. 17 registers differ between the before/after dumps (build info, bands, `0x3A`); nothing else. The Fission chip is a **KT0211L**: bootloader CHP reply `0211LC02`, matching the firmware file name `KT0211L_fission_rational_hifi_edition_v1.0.1_20250610.bin`.

## 2. Getting the vendor package

Tanchjim publishes "FISSION-Rational HiFi Edition Firmware upgrade" (changelog: "Resolve microphone occupancy issue", 3.35 MB, Windows). The download URL is a zip served from a page URL:

```bash
mkdir -p downloads/fission-fw && cd downloads/fission-fw
curl -sL -A "Mozilla/5.0" https://tanchjim.com/en/FISSION_HIFI_upgrade/ -o rational_hifi_upgrade_20250612.zip   # Rational edition
curl -sL -A "Mozilla/5.0" https://tanchjim.com/en/FISSION_upgrade/       -o fission_upgrade.zip                 # plain FISSION (different file!)
mkdir x_rational && unzip -q rational_hifi_upgrade_20250612.zip -d x_rational
```

Contents (never executed): `FISSION_Rational_HiFi_Edition_BOOT_TOOL_V1.0.03.exe` (.NET GUI), `KT0211L_fission_rational_hifi_edition_v1.0.1_20250610.bin` (43440 B), `KT_VCP_V1.0.0_Setup.exe` (Win7 driver), and a Chinese `.docx` of instructions (Win10: no driver; open the tool, load the .bin, click upgrade). The plain-FISSION package has a different file (`KT0211L_FISSION_v1.0.2_250610.bin`); the instruction doc in both packages names that v1.0.2 file, so don't follow the doc's file name blindly — use the file whose product string matches your device (`FISSION-Rational HiFi Edition` at offset `0x1120`).

Image header: `KT_lnv1b_flash_1` (16 B) + chip id `0211LC02` (0x10) + `Size` (0x18) + u32 size (0x1C) = 43440 = file length; `REG:` factory register block at `0x1000` (version `1.0.1` at `0x1010`, build date at `0x1020`).

## 3. Upgrading rea and reverse-engineering the vendor tool

```bash
npm install -g rea-agents@6.8.0 --prefix ~/.local          # rea 6.7.0 -> 6.8.0 (original install lives under ~/.local; npm's default prefix is /usr/local)
export GHIDRA_INSTALL_DIR=$HOME/tools/ghidra_12.1.4_PUBLIC JAVA_HOME=/usr/lib/jvm/java-21-openjdk
rea doctor        # node 22.22.2 is flagged (>=22.23.4 wanted) but works; ghidra lane needs GHIDRA_INSTALL_DIR set as above
```

**Stage A — the .NET GUI** is a thin wrapper. `rea` has a managed-code lane (`inspect-managed-members`, static, no decompile), so the decompile was done with ILSpy:

```bash
DOTNET_ROLL_FORWARD=Major ~/.dotnet/tools/ilspycmd -p -o re/decomp "$EXE"     # ilspycmd wants .NET 8; Fedora has 9 -> roll forward
```

`TANCHJIM_DSPS_BOOT_TOOL/Form1.cs`: extracts the embedded native `kt_usb_cmd_tool.exe` (v1.3.16) to `%TEMP%` and runs `-s -pl 0x31b2` (find port), `-s -v 0x31B2 0x0101` (read app version; only upgrades if `int(version.replace(".","")) < 102`), then `-s -pb <port> <file.bin>` (burn). Its usage text says `-s` = serial path for KT021X / KT02H2X / KT02F2X, `-m` = HID path for KT020X.

**Stage B — the native helper** (PE32 i386, Qt, 5.6 MB):

```bash
cp re/decomp/*kt_usb_cmd_tool.exe re/kt_usb_cmd_tool_1.3.16.exe                # sha256 f1e0f034…16bdbc
strings -n 5 re/kt_usb_cmd_tool_1.3.16.exe > re/kt_usb_cmd_tool.strings.txt     # usage text, "turn to cdc", "STEP_ShakeHand out time", ...
rea analyze re/kt_usb_cmd_tool_1.3.16.exe --snapshot re/ghidra/kt_usb_cmd_tool.snap --format json
rea search  re/kt_usb_cmd_tool_1.3.16.exe "STEP_ShakeHand" --snapshot re/ghidra/kt_usb_cmd_tool.snap     # -> string at 0x75e5ed
rea decompile-all re/kt_usb_cmd_tool_1.3.16.exe --snapshot ... --output re/native_decomp --format json   # output dir must NOT exist; ~5k functions, a few minutes
grep -l "STEP_ShakeHand" re/native_decomp/functions/*.c      # -> 0x4b8a80.c ; "Chip type error" -> 0x4b6330.c
```

Dead end worth knowing: searching for the CRC table or the `0x69` opcode in the pseudocode found nothing useful; locating functions by their **string literals** (Ghidra inlines them in the pseudocode) worked. A raw-bytes check of the PE also found the protocol constants directly: `1e4b544d` KTM, `d2434850` CHP, `3c50574f` PWO, `4b535441` KSTA, `96535450` STP, `5a525354` ZRST, `f0564552` VER, `f04b4559` KEY, `f0494e46` INF, the setup command `2d2900100e15006000bc` (`2D 29 00 10 0E 15 00 60 00 BC`, only one occurrence), and the reflected CRC-32 table (`00000000 77073096 ee0e612c 990951ba`).

### What the decompile showed (`FUN_004b6330`, state machine; `FUN_004b8a80`, port finder / success)

State 0 finds the CDC port (`8888:CDC0`), then: state 1 KTM handshake (`0x78`) → **if flag==0** go straight to CHP, **else** VER (reply `78 b0 sum8`) → KEY (`78 00 78`) → CHP; CHP reply is 13 bytes with `sum8` checksum, bytes 4–11 are compared with the image's chip id (`image[0x10:0x18]`) else "Chip type error"; then the 10-byte setup command (ack `78`), PWO (`78`), KSTA (`78`, up to 6 s), data packets (each acked `A5`), STP (`78`); **if flag==1** INF (10-byte reply: size LE32, CRC-32 LE32, sum8) is compared with the image size and CRC; ZRST (`78`); success.

**The flag is read from the image file itself** (`Form1`-side function `FUN_004b7430`, line `flag = (char at magic[0xF]) == '1'`): `KT_lnv1b_flash_1` → **flag 1**; `KT_Helios_v1b___` (the JA11 images the earlier flasher handled) → flag 0. Flag 1 also sets the write base to `flag << 15 = 0x8000`.

Data packet builder (`FUN_0046dc20`/`FUN_00475230`): `69 | len-lo | (len-hi & 0x1F) | (top3<<5) | addr[3 LE] | payload | CRC-32 LE`, payload ≤ 0x400; block 0 = `image[0x10:0x400]` at `base+0x10`; block k = `image[k*0x400:(k+1)*0x400]` at `base+k*0x400`; `top3 = 1` on every 32nd block (bank table at `.rdata` VA `0x898c00` → `[1] = 0x20`), else 7; final packet = `image[:0x10]` at `base` as `69 10 e0 <base LE24>`; CRC-32 is reflected `0xEDB88320`, init 0, no final xor, over header+payload. Bootloader entry is the same HID report as before (`54 "12345678"`).

## 4. The Linux flasher and the one mistake

`kt0211l-flasher/ktflash_kt0211l.py` = old `ktflash.py` + (a) accepts the `KT_lnv1b_flash_1` magic, (b) `identify` (read-only: unlock → KTM → CHP → compare with the image, writes nothing), (c) after the RE: flag-aware flow (VER/KEY, base `0x8000`, INF check, refuses to ZRST on mismatch). Offline tests use a mock bootloader (including one that rejects writes below `0x8000`); `python3 -m unittest` passes.

Timeline:
1. `identify` → `chip id (CHP): b'0211LC02'`, image chip `0211LC02` → MATCH. (Dongle stays in bootloader mode until replugged; the bootloader accepts KTM **once per power-up**.)
2. **First `flash` attempt used the old flag-0 flow (base 0)** → failed at packet 1/44: `no 0xa5 ack within 5.0s (got 78 87 03)`. The chip rejected a write to `0x10`. Setup/PWO/KSTA had been acknowledged, yet after a replug the dongle came back in **normal app mode with the old firmware intact**; the CDC bootloader device (`8888:cdc0`) had been showing in between. Nothing was written, nothing lost.
3. The decompile (above) explained it: this image is flag 1. Flag-1 flow implemented and tested offline, including a regression test that reproduces `78 87 03` for a base-0 plan.
4. Replug → `flash --execute --yes --no-backup-ok` → `VER: 31`, `chip id: 0211LC02`, 44/44 packets, `INF: size=43440 crc=0xd5edcafb -> OK`, dongle back as `31b2:0101`.

```bash
sudo ./venv/bin/python -I tools/ktflash_kt0211l.py identify <fw.bin>                                # optional, read-only; replug afterwards
sudo ./venv/bin/python -I tools/ktflash_kt0211l.py flash <fw.bin> --execute --yes --no-backup-ok
sudo ./venv/bin/python -I dump_regs.py 31b2 0101 fission                                            # verify build date / hash (needs the earlier dump_regs.py)
```

## 5. Re-applying the C7 EQ

The flash resets the DAC bands to the new factory ones, so the Tin HiFi C7 EQ had to be re-applied and saved: `sudo ./venv/bin/python -I save_c7.py` → RAM read-back OK, SAVE ack `0x03`, bands intact after the self-reboot (`60/593/2575/3118/6471 Hz`), and still intact after a manual unplug/replug (`readstate.py`; register `0x08` still reads `Jun ` = the new build) — so both the firmware and the saved EQ persist. Backups: `eq_backup.json` (new-firmware factory bands, used by `restore`), `eq_backup_fw-20250506.json` (old-firmware bands), `data/regs_fission_preflash_fw-20250506.json` (full 256-register dump before the flash).

## 6. Gotchas

- **Read the flag from the image** — a flag-0 flow against a flag-1 image fails at the first data packet; don't assume a new image family uses the old flow.
- **KTM once per boot**: after `identify` or any failed attempt, replug before the next try.
- `rea decompile-all --output` refuses an existing directory (don't `mkdir` it first). `rea doctor` complains about node 22.22.2 and about unset `GHIDRA_INSTALL_DIR`; setting the env var is enough. rea 6.8.0's Ghidra lane worked on this x86 PE (the older MIPS NaN2008 limitation is unrelated).
- Claude Code's auto-mode classifier blocks `sudo` on HID/serial scripts: write scripts with the Write tool and have the user run them via `! sudo ...`.
- The firmware upgrade wipes the saved EQ — re-run `save_c7.py` afterwards. The vendor GUI would also have wiped it.
- Not done: no Windows run of the vendor tool for comparison; no way to dump the old firmware (no read command in the bootloader).

## References

- Tanchjim downloads: [tanchjim.com/en/services](https://tanchjim.com/en/services/), [tanchjimaudio.com/app-services](https://www.tanchjimaudio.com/app-services); packages [FISSION-Rational HiFi Edition](https://tanchjim.com/en/FISSION_HIFI_upgrade/) and [FISSION](https://tanchjim.com/en/FISSION_upgrade/)
- [kt0231h PROTOCOL.md](https://github.com/eyad-elghareeb/kt0231h/blob/master/PROTOCOL.md) and [CHIPS.md](https://github.com/eyad-elghareeb/kt0231h/blob/master/CHIPS.md) — bootloader tokens, CFG payload, CHP checksum, no-software-dump finding
- [gxcreator/ktmicro-tools](https://github.com/gxcreator/ktmicro-tools), [txtsamu/kt02h20-flasher](https://github.com/txtsamu/kt02h20-flasher), [SMIPE444 toolkit](https://github.com/SMIPE444/fiio-ja11-jcally-jm12-moondropkt02-kt02h20-dac-amp-toolkit) — the KT02H20 flasher lineage this fork builds on
- [rea-agents on npm](https://www.npmjs.com/package/rea-agents) (6.8.0), [Ghidra](https://ghidra-sre.org/), [ILSpy / ilspycmd](https://github.com/icsharpcode/ILSpy)
