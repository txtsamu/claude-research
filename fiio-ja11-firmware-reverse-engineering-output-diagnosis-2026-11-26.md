---
type: investigation
tags: [fiio, jadeaudio, ja11, kt02h20, ktmicro, usb-dac, firmware, reverse-engineering, ghidra, rea, uac1, uac2, peq, dsp, hid, fedora]
created: 2026-11-26
last_verified: 2026-11-26
status: current   # ISA = Andes NDS32 (514/514 branch targets aligned); Ghidra decompiles NDS32 to nothing, assembly-only
---

# FiiO JA11 firmware: attempting a disassembly, and what the dongle is really doing

Request: "help me reverse engineer that firmware i think there is bug since the output of the sounds is weird" and then "try reverse engineer with morluto/rea and ghidra". Symptom reported when asked directly: **crackle/pops/dropouts, hiss/noise floor, and distorted/harsh peaks, on every host** (this PC, phone, Snowsky Disc).

Outcome in one line: the core is **Andes NDS32**, not any of the usual suspects, and once that was found the code disassembles cleanly (branch targets 514/514 on instruction boundaries, hardware init visible through `mtsr`/`mfsr`). The Ghidra decompiler still returns nothing for NDS32, so it is assembly-only. The dongle's DSP state and USB mode were captured live, and the image's register-write script tables and built-in EQ presets were decoded.

## Time estimate

| Step | Time |
|---|---|
| read existing notes + hash/paths checks | ~3 min |
| live device capture (lsusb, descriptors, registers, HID reads) | ~10 min |
| download 5 official firmware versions from FiiO + extract | ~2 min (download measured) |
| image anatomy + version diffs + script-table discovery | ~20 min |
| Ghidra imports and disassembly attempts (11 processors, then NDS32 analysis) | ~25 min, mostly JVM startup |
| **Total** | **about 1 hour 20 min** |

## 1. What is plugged in: the dongle changed USB mode

```bash
$ lsusb -d 2972:0101
Bus 001 Device 044: ID 2972:0101 FiiO Electronics Technology JadeAudio JA11

$ lsusb -v -d 2972:0101 | grep -E "bcdUSB|bcdDevice|Negotiated speed"
  Negotiated speed: Full Speed (12Mbps)
  bcdUSB               2.00
  bcdDevice            2.20

$ lsusb -v -d 2972:0101 | grep -E "bcdADC|bDescriptorSubtype"
        bDescriptorSubtype      1 (HEADER)
        bcdADC               1.00
        bDescriptorSubtype      2 (INPUT_TERMINAL)
        bDescriptorSubtype      6 (FEATURE_UNIT)
        bDescriptorSubtype      3 (OUTPUT_TERMINAL)
```

That is **UAC 1.0** (bcdADC 1.00, no Clock Source unit), full speed, PID `0x0101`. `/proc/asound/card3/stream0` confirms the cap:

```
FIIO JadeAudio JA11 at usb-0000:13:00.0-1, full speed : USB Audio
  Altset 1  S16_LE  44100, 48000, 88200, 96000
  Altset 2  S24_3LE 44100, 88200, 48000, 96000
```

Earlier the same day it was the UAC 2.0 identity, high speed, up to 384 kHz:

```bash
$ journalctl -k --no-pager | grep -E "2972:01|new (full|high)-speed"
Nov 26 06:45:49 usb 1-1: new high-speed USB device number 30 using xhci_hcd
Nov 26 06:45:49 usb 1-1: New USB device found, idVendor=2972, idProduct=0102, bcdDevice= 2.20
Nov 26 11:55:37 usb 1-1: new full-speed USB device number 44 using xhci_hcd
Nov 26 11:55:37 usb 1-1: New USB device found, idVendor=2972, idProduct=0101, bcdDevice= 2.20
```

So the dongle now sits in **UAC 1.0 / full-speed mode** (`0101`). Both identities report firmware `2.20`, same serial `2020-02-20-0000-0000-0000`. The mode changed between 06:47 and 11:55, i.e. by a replug, not by any flash. FiiO's own V2.0 changelog mentions "UAC1.0 mode" as a thing the FiiO Control app has to recognise, so the mode is a firmware feature; **the exact switch gesture was not verified** (button-at-plug is the usual FiiO convention, unconfirmed here).

Impact on sound quality: none by itself. It caps the format at 96 kHz/24-bit and removes DSD. It does not produce hiss or crackle.

## 2. DSP state: factory-default, not corrupted

Full 256-register dump (read-only, `0x4B` report, `0x52` command) is **byte-identical** to the dump taken right after this morning's reflash:

```bash
$ sudo ./venv/bin/python -I dump_regs.py 2972 0101 ja11_live_2026-11-26
ja11_live_2026-11-26: 256/256 registers answered
strings: version 2.2.0 | manuf FIIO | product JadeAudio JA11 | serial 2020-02-20-0000-0000-0000
0x01 model flags: 0x200 (single-DAC)
0x24 DAC EQ en: 0x5        <- bit0 set, DAC EQ active
0x3A ADC analog PGA: 0x4   -> +20 dB  (mic path)
0x3B DAC analog PGA: 0xD   -> 0.0 dB  (top of the -18..+3 dB range)
0x65 ADC digital: 0x100    -> 0.0 dB
0x66 DAC digital: 0x200    -> 0.0 dB
DAC bands
   0:  141 Hz  -2.4 dB type 0 Q 0.56
   1:  447 Hz  +2.1 dB type 0 Q 0.72
   2: 2098 Hz  -1.1 dB type 0 Q 0.77
   3: 4693 Hz  -1.4 dB type 0 Q 1.98
   4: 8464 Hz  -1.6 dB type 0 Q 3.00
ADC bands: 1k/2k/5k/8k/10k, all +0.0 dB, Q 0.707
```

Global preamp read back over the FiiO `0x02` report protocol:

```
read 0x17 -> 02 bb 0b 00 00 17 02 00 00 47 ee   => raw 0x0000 = 0.00 dB
```

Register map used for the decode (from `gxcreator/ktmicro-tools/KT_USB_PROTOCOL.md`): `0x3A` ADC analog PGA index, `0x3B` DAC analog PGA index (`0..15` → `1.5*(i-1)-18 dB`), `0x65`/`0x66` digital gains, `0x18`/`0x24` EQ enable, `0x1A..0x23` ADC bands, `0x26..0x2F` DAC bands.

Two consequences:

- Nothing in the DSP is out of range. Analog DAC gain is at 0 dB (the maximum), digital gains at unity, EQ is a mild FiiO curve, preamp 0 dB. There is **no corruption** to find.
- Analog DAC PGA at 0 dB is the hot end of the range. With sensitive IEMs, that alone raises the noise floor and leaves no headroom for a +2.1 dB EQ band. It is a plausible contributor to "hiss" and "harsh peaks", but it is also the chip default.

Reads that this firmware simply does not implement (no response, several packet shapes tried): DAC filter (`0x11`), amp mode (`0x1D`), gain mode (`0x19`). **The active DAC filter therefore cannot be read back**; only written. If `NON-OS` is selected, HF imaging noise and a harsher top end are expected, and it would follow the dongle across hosts.

## 3. The firmware image: anatomy and what is actually in it

Official images, all downloaded from FiiO's own links (see References):

```bash
$ sha256sum JadeAudio\tJA11_V2.2.bin
65fea4995a4425064bc737c7bc8ec64e212c8b6297c6b9dfcc2b90a5814103de
```

| Version | Size | Notes |
|---|---|---|
| V1.7 | 67,488 | oldest in the list |
| V1.9 | 67,264 | web PEQ + app upgrade |
| V2.0 | 67,264 | UAC1.0 recognition fix |
| V2.1 | 67,312 | ticking fix |
| V2.2 | 67,312 | inline-control + mic gain |

Byte-level diff map between versions (this is the cheapest way to learn the layout without an ISA):

| Diff | Changed bytes | Runs | What stands out |
|---|---|---|---|
| V1.7 → V1.9 | 49,619 | 131 | full recompile plus new PEQ code |
| V1.9 → V2.0 | **93** | 14 | the UAC1 fix: a 41-byte table at `0x485b`, and 8-byte patterns at `0xca95`/`0xcb9f` (`10 00 01 07 05 03 03 10` → `16 … 16`) |
| V2.0 → V2.1 | 45,897 | 112 | full recompile |
| V2.1 → V2.2 | **3,489** | 32 | one **3,328-byte replacement block at `0x6174..0x6e74`** = the mic-gain / inline-control change |

Header (V2.2): magic `KT_Helios_v1b___`, chip `KT02H20B`, LE32 size at `0x1C`, strings `2.2.0`, `Jul  8 2025`, `19:24:29`, hash `75503ea`, `2025-06-30 V:1.0`, `ENTY` tag at `0x40`. Layout: header/zeros `0x0000..0x2FFF`, code+data `0x3000..0xEFFF` (entropy 6.1–6.9), string table `0xC700..0xE000`, data tail to `0x106EF`.

### The find: 10-byte register-write scripts

Scanning for `[addr u32][cmd u16 = 0x0057][value u32]` turns up a clean table at `0xc804`:

```
0xc804  addr=0x24  cmd=0x57  val=0x00000004      <- DAC EQ enable = 4
0xc80e  addr=0x26  cmd=0x57  val=0x03e80000      <- 1000 Hz, 0.0 dB
0xc818  addr=0x27  cmd=0x57  val=0x000002c3      <- Q 0.707
...     (2000/5000/8000/10000 Hz, all flat, Q 0.707)
```

That is the **flat EQ script** the firmware uses on reset. Four more scripts follow at `0xf5e9`, `0xf657`, `0xf6c5`, `0xf733`, each enabling EQ (`0x24 = 5`) and writing five bands. Decoded:

| Preset | Band 0 | Band 1 | Band 2 | Band 3 | Band 4 |
|---|---|---|---|---|---|
| 1 | 40 Hz −1.9 | 180 Hz −4.9 | 600 Hz +5.0 | 2200 Hz +6.0 | 7000 Hz −2.9 |
| 2 | 230 Hz −4.9 | 80 Hz +2.5 | 2500 Hz +2.5 | 6000 Hz −2.9 | 8000 Hz 0.0 |
| 3 | 32 Hz +3.0 | 64 Hz +3.5 | 100 Hz +2.5 | 2500 Hz +2.5 | 6000 Hz −2.9 |
| 4 | 29 Hz +6.0 | 81 Hz +3.8 | 600 Hz −0.4 | 7460 Hz +5.1 | 15660 Hz +5.4 |

Preset 4 is a loudness curve with +6 dB in the bass and +5.4 dB at 15.6 kHz and no preamp compensation; if it were ever selected it would clip and hiss. It is **not** what the dongle is running.

### Correction to an earlier note

[[ktflash-rust-toolkit-linux-kt02h20-reflash-2026-11-26]] says a reflash resets the DAC bands to "the image's factory curve (141 Hz −2.4 dB, 447 Hz +2.1 dB, …)". That curve is **not in the image**. Searching the whole 67,312 bytes for those frequencies and gains as LE16/BE16/LE32/BE32/float32 (and for the five-value cluster within 400 bytes) finds nothing. The curve is the chip/DSP default that reappears whenever the DSP resets; the image carries the *flat* script instead. The observation in that note is right, the attribution was wrong.

## 4. rea, Ghidra, and the ISA

### rea: it runs, but it cannot see this core

`rea` 6.9.0 is installed at `~/.local/bin/rea` and it works. It just has no lane for this target:

```bash
$ rea analyze JadeAudio\ JA11_V2.2.bin --target-format raw-binary \
      --architecture arm --entry-point 0x3000 --provider ghidra --format json
# normalized_result: procedure_count 1, string_count 41, segments [ram 0x3000..0x136f0]
$ rea analyze ... --architecture m68k ...   # procedure_count 1, string_count 41
$ rea analyze ... --architecture 6502 ...
# Cannot open artifact: raw-binary mapping from 0x0 must fit in the 6502 address width.
$ rea instructions ... --architecture arm 0xf7b0
# No procedure exists at the requested address: 0xf7b0
```

`rea analyze --target-format raw-binary` accepts only `6502 | x86 | x86_64 | arm | arm64 | m68k`. There is no NDS32 value, and rea is a wrapper around providers, so it cannot invent one. Its architecture-independent commands still work (`inspect-byte-entropy` returned fine; `inspect-firmware-regions` wants `REA_BINWALK_COMMAND`), but for this image rea is the wrong tool.

### Ghidra headless with the right language: NDS32

The earlier sweep tried 8051-family, MCS96, Xtensa, ARM, MIPS, RISC-V, V850, HCS08, Loongarch and 68000, all garbage or zero. Adding **`NDS32:BE:32:default`** (Andes; in-tree Ghidra processor at `Ghidra/Processors/NDS32`) changes everything:

```
ram:00003000  movi gp,0x42000
ram:00003004  movi sp,0x4fe00
ram:00003008  jal 0x00009d98
ram:0000300c  jal 0x00009dac
ram:00003010  smw.adm s0,[sp],s2,0x2      <- push
ram:00003014  addi10.sp -0x10
...
ram:00003024  beqc s0,0x57,0x00003048     <- 'W' write
ram:00003028  bnec s0,0x52,0x00003030     <- 'R' read
ram:0000302c  j 0x00003178
ram:00003030  bnec s0,0x53,0x00003038     <- 'S'
ram:00003034  j 0x0000312c
ram:00003038  beqc s0,0x43,0x000030a4     <- 'C' handshake
ram:0000303c  beqc s0,0x9,0x00003120
ram:00003040  addi10.sp 0x10
ram:00003042  lmw.bim s0,[sp],s2,0x2      <- pop
ram:00003046  ret5 lp
```

That is the register-command dispatcher, and the immediates are the same ASCII command bytes the host protocol uses (`0x52` read, `0x57` write, `0x43` handshake). The prologue/epilogue pair matches (`smw.adm`/`lmw.bim` with `addi10.sp`), and further in the same function there is `movi a1,0xbb80` (48000) next to `slli333 a0,a0,0x2`.

The boot-time call targets are hardware init:

```
ram:00009d98  movi a0,0x40000
ram:00009d9c  ori a0,a0,0x1
ram:00009da0  mtsr a0,0x0138        <- write peripheral/CSR
ram:00009da4  dsb
ram:00009da8  ret5 lp
ram:00009dac  smw.adm s0,[sp],s0,0x2
ram:00009db0  movi55 a0,0x0
ram:00009db2  mtsr a0,0x0179
ram:00009db6  mtsr a0,0x00c0
```

`mtsr`/`mfsr` are the NDS32 special-register instructions; the sequence programs clock/power CSRs. That is not something an accidental decode produces.

Three independent checks, all passing:

| Check | Result |
|---|---|
| Branch/call targets landing on an instruction boundary | **514 / 514** in range |
| Prologue/epilogue pairing | `smw.adm` + `addi10.sp` up front, `addi10.sp` + `lmw.bim` + `ret5 lp` at exit |
| Immediates matching the known protocol | `0x57`, `0x52`, `0x53`, `0x43`, `0xbb80` |

Disassembly coverage from the entry point is 4,075 instructions / 11,798 bytes of the 55,024 between `0x3000` and `0x106ef`; the rest is data (strings, coefficient tables) and code not reachable from `0x3000` by static flow. Iterative seeding of every discovered jump target adds nothing, so there is no hidden code reachable that way.

### The decompiler is still a dead end

Ghidra 12.1.4 decompiles NDS32 to an **empty string**: `decompileCompleted() == true`, `getErrorMessage() == ""`, and `getDecompiledFunction().getC()` is blank, both for the auto-detected 16-byte body and for a forced body spanning the whole function. The `nds32.cspec` has a stack pointer, `a0..a5` arguments and a default prototype, so the spec is not obviously at fault. Treat this as assembly-only work for now.

Practical consequence: you can read the code, follow the register-command dispatch, and find the DSP write scripts, but you will not get C out of Ghidra for this image.

## 5. What GitHub already has (and what nobody has)

General web search was unusable in this session (DuckDuckGo served bot-check pages, Bing returned unrelated localised results), so this list is GitHub-only, gathered via the GitHub search API.

- [`Ircama/ja11-config`](https://github.com/Ircama/ja11-config) — the best protocol reference: HID report `0x02`, `aa 0a 00 00 <cmd> <len> … ee` set packets, `bb 0b 00 00 …` reads, Q12 gain encoding, filter indices 1–5 (FAST-LL … NON-OS), preamp ±12 dB.
- [`gxcreator/ktmicro-tools`](https://github.com/gxcreator/ktmicro-tools) — the register map used in section 2 (`KT_USB_PROTOCOL.md`), plus a runtime control TUI over the `0x4B` channel.
- [`ParkWardRR/fiio-ja11-jcally-jm12-moondropkt02-kt02h20-dac-amp-toolkit`](https://github.com/ParkWardRR/fiio-ja11-jcally-jm12-moondropkt02-kt02h20-dac-amp-toolkit) — Rust CLI flasher; `docs/COMPATIBILITY.md` and `docs/REVERT.md` are the honest source on cross-flash risk ("same chip is not enough… a wrong-hardware flash can mute output, kill the mic").
- [`ParkWardRR/…-dac-amp-control`](https://github.com/ParkWardRR/fiio-ja11-jcally-jm12-moondropkt02-kt02h20-dac-amp-control) — `ktctl`, runtime PEQ/presets.
- [`dragonzords/KT02H20-FLASHER-RE`](https://github.com/dragonzords/KT02H20-FLASHER-RE) — Termux flasher, protocol RE only.
- Web PEQ clients: `Cyfine/ja11-web-control`, `dylenq/ja11-eq`, `faxesystem/ja11-eq`, `Chronosauros/contour`, `kirby-eraser/ZhuAudio-…-tuner`.
- Sibling chips: `eyad-elghareeb/kt0231h` (KT0231H, 6-band), [`chu2-studio`](https://github.com/jcharvet/chu2-studio) (KT0210-class).

**Nobody has disassembled the firmware.** Every project stops at the HID register layer or the bootloader protocol. There is no ISA document, no disassembler, no Ghidra module, and no leaked SDK. KTMicro's own site lists the KT02H20 with a one-paragraph feature blurb and no datasheet or toolchain download.

## 6. What to test next, cheapest first

The static evidence does not support "firmware bug". It supports "this is a JM12 cross-flashed with JA11 firmware, running the chip defaults, possibly with a hot analog gain and an unknown DAC filter". Ordered by cost:

1. **Get out of UAC 1.0.** Unplug, replug without touching the button, confirm `lsusb` shows `2972:0102` and `/proc/asound/card*/stream0` shows high speed and 384 kHz. If the sound is identical in both modes, the mode is irrelevant (it should be).
2. **Kill the DSP variables.** Set the DAC EQ off (`0x24` bit0 = 0) or write the flat script, and write DAC filter `1` (FAST-LL) via `0x02`/cmd `0x11`. A hiss/harshness that disappears with FAST-LL points at `NON-OS`.
3. **Lower the analog gain.** Write `0x3B = 9` (−6 dB) and compare. If hiss drops and peaks stop breaking up, it was gain staging on sensitive IEMs, not a firmware fault.
4. **Change one piece of hardware at a time.** Different IEM/cable, and wiggle the plug while playing. Crackle plus hiss that follows the dongle everywhere and survives steps 1–3 is the amplifier/jack or the board calibration, and no amount of disassembly will fix it.
5. **Only then** consider the cross-flash. There is no software read-back, so the original JM12 image is gone; the only clean revert is a stock `jcally_jm12_v1.3.bin` from JCALLY's own store FAQ, which would also change the USB identity and tuning.

## Gotchas

- `hidraw` ACLs are dropped on every replug (`sudo setfacl -m u:moo:rw /dev/hidraw6`), and the node re-registers; re-check `/sys/class/hidraw/*/device/uevent` for `2972`.
- The `0x4B` register channel works on this firmware (256/256 answered), but the `0x02` FiiO channel is **write-only** for filter/amp/gain mode: reads return nothing. Do not conclude the filter is wrong from a missing read.
- Ghidra needs `GHIDRA_INSTALL_DIR` and `JAVA_HOME` set; the bundled `support/sleigh` is the compiler, not a decoder, so ISA testing has to go through `analyzeHeadless`.
- Importing a raw binary at base 0 is correct **only** for this family: the flash tool writes the image at base 0 with the 16-byte header written last, so file offset equals device address.
- The `0x3000` boundary is real: below it is header and zeros, so an importer that starts analysis at 0 will produce noise before the first real code.

## What was not verified

- Which DAC filter is active. Not readable on this firmware.
- Whether UAC 1.0 mode is entered by holding the button at plug-in. The mode change is documented by timestamp only.
- Whether the "weird sound" is the DAC/amp, the jack, the IEM, or the cross-flash calibration. No loopback recorder was available; the tests in section 6 were not run.
- The ISA turned out to be NDS32, but nothing beyond disassembly: no decompiler output, no function boundaries from auto-analysis (330 created by seeding branch targets), and 43 KB of the 55 KB code window is not reached from the entry point.
- How the four built-in EQ presets are selected. No reference to the `0xf5e9` script table appears as an immediate in the reachable code, so the selection path is unproven.

## References

- [FiiO forum: JA11 firmware download and changelog](https://forum.fiio.com/note/showNoteContent.do?id=202406211150090736905) — official V2.2/V2.1/V2.0/V1.9/V1.7 ZIP links used above
- [FiiO: JA11 V2.2 announcement](https://www.fiio.com/newsinfo/1065234.html)
- [KTMicro KT02H20 product page](https://www.ktmicro.com/?usb_104/394.html) — feature list, UAC1.0/2.0, "FLASH 允许客户二次开发程序", no CPU documentation
- Ghidra 12.1.4 in-tree `NDS32` processor (`Ghidra/Processors/NDS32`, `NDS32:BE:32:default`) — the language that decoded the image
- [`Ircama/ja11-config`](https://github.com/Ircama/ja11-config) — HID packet formats and filter table
- [`gxcreator/ktmicro-tools`](https://github.com/gxcreator/ktmicro-tools) — `KT_USB_PROTOCOL.md` register map
- [`ParkWardRR/…-toolkit`](https://github.com/ParkWardRR/fiio-ja11-jcally-jm12-moondropkt02-kt02h20-dac-amp-toolkit) — `docs/COMPATIBILITY.md`, `docs/REVERT.md` (cross-flash risk, stock image sourcing)
- [`dragonzords/KT02H20-FLASHER-RE`](https://github.com/dragonzords/KT02H20-FLASHER-RE)
- Local: [[ktflash-rust-toolkit-linux-kt02h20-reflash-2026-11-26]], [[kt02h20-jcally-dac-ja11-firmware-flash-protocol]], [[fiio-ja11-peq-match-tin-hifi-c7-hidraw]], [[fiio-ja11-kt02h20-power-and-volume-ceilings-2026-11-16]], [[ktmicro-dsp-dongles-fission-ja11-chu2-same-chip-comparison-and-otg]]
