---
type: investigation
tags: [fiio, jadeaudio, ja11, kt02h20, ktmicro, usb-dac, firmware, reverse-engineering, ghidra, rea, uac1, uac2, peq, dsp, hid, fedora]
created: 2026-11-26
last_verified: 2026-11-27
status: current   # ISA = Andes NDS32 (independently confirmed); UAC2 restored via cmd 0x20 and persists across a real replug; PerfCfg patched ADC 0x04->0x00 and DAC 0x0d->0x05, flashed and verified (0x3A=0, 0x3B=5, mic -91.7 dBFS); cmd 0x12=0 gives a playback-only descriptor set; V2.1 compared, no playback regression; amp 0x1D write-only, 0x16 read-only
---

# FiiO JA11 firmware: attempting a disassembly, and what the dongle is really doing

Request: "help me reverse engineer that firmware i think there is bug since the output of the sounds is weird" and then "try reverse engineer with morluto/rea and ghidra". Symptom reported when asked directly: **crackle/pops/dropouts, hiss/noise floor, and distorted/harsh peaks, on every host** (this PC, phone, Snowsky Disc).

Outcome in one line: the core is **Andes NDS32** at flash base `0x80000`, and once that was found the code disassembles cleanly (branch targets 514/514 on instruction boundaries, hardware init visible through `mtsr`/`mfsr`). Ghidra's NDS32 decompiler returns nothing, so it is assembly-only. The USB personality selector, both descriptor sets, and the `PerfCfg` analog-gain path were located; the stock EQ was flattened and saved, and the image was patched and reflashed to move the DAC analog PGA from 0 dB to −6 dB, verified on the device.

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

### The same register map on a second, stock board

On 2026-11-27 a generic KTMicro dongle was dumped before being cross-flashed: `31b2:1052 "KT02H20 Hifi Audio"`, stock firmware string `1.0.1`. All 256 registers answered, with the same marker `0x3a474552` and the same model flags `0x200`. The PerfCfg defaults were `0x3A = 3` (ADC +14 dB) and `0x3B = 0xd` (DAC 0 dB), which are exactly the values the JA11 V2.1 image carries. The single difference worth recording is `0x24` (DAC EQ enable) at `0x2` rather than the FiiO `0x4`.

So the vendor strings are firmware-specific, but the register map, the EQ band layout and the PerfCfg gain defaults are shared across the firmware family, not invented by FiiO. That is a small but useful confirmation: decoding a non-FiiO KT02H20 board with this register map is sound. See [[kt02h20-generic-31b2-1052-crossflash-ja11-v21-2026-11-27]].

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

[[ktflash-rust-toolkit-linux-kt02h20-reflash-2026-11-26]] says a reflash resets the DAC bands to "the image's factory curve (141 Hz −2.4 dB, 447 Hz +2.1 dB, …)". That curve is **not in the image**. Searching the whole 67,312 bytes for those frequencies and gains as LE16/BE16/LE32/BE32/float32 (and for the five-value cluster within 400 bytes) finds nothing. What the image *does* contain, at `0x106a` (DAC) and `0x109a` (ADC), is a five-entry table of 8-byte records in the layout `[freq u16][Q×1000 u16][gain×10 s16][type u16]`, and it is **flat**:

```
0x106a: e8 03 c3 02 00 00 00 00   1000 Hz  Q 0.707  0.0 dB  type 0
0x1072: d0 07 c3 02 00 00 00 00   2000 Hz  Q 0.707  0.0 dB  type 0
0x107a: 88 13 c3 02 00 00 00 00   5000 Hz  Q 0.707  0.0 dB  type 0
0x1082: 40 1f c3 02 00 00 00 00   8000 Hz  Q 0.707  0.0 dB  type 0
0x108a: 10 27 c3 02 00 00 00 00  10000 Hz  Q 0.707  0.0 dB  type 0
0x109a: (same five entries again, ADC bank)
```

So the image's own default is flat, matching the flat write script at `0xc804`, and the dark 141/447 curve comes from elsewhere (chip ROM or the saved config sector). The observation in that note is right, the attribution was wrong.

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

An independent project reaches the same conclusion. `eyad-elghareeb/kt0231h/ARCHITECTURE.md` identifies the KT02H20 core as an **Andes AndeStar v3 (NDS32) 32/16-bit mixed-length RISC**, reporting about 94% coverage and 95 clean decompiles, and names the Andes intrinsics it finds (`setgie`, `dsb`). That matches the `mtsr`/`mfsr` and `dsb` sequences in this image. They use the little-endian variant; here both `NDS32:BE:32:default` and `NDS32:LE:32:default` produced identical output, so the file's byte order is ambiguous under Ghidra's two NDS32 definitions but the instruction set is not in doubt.

### Code base 0x80000 and the pointer tables

The code does not run at address 0. Every pointer in the image is `0x80000 + file offset`, for example the table entry at `0xf878` is `e8 68 08 00` = `0x000868e8`, which is file offset `0x68e8`. Confirming this unlocked the parts that flow-following from `0x3000` never reached: scanning for every LE32 value in `0x80000..0x906ef` yields **148 unique code targets**, and seeding disassembly at those targets grows coverage from 4,075 instructions / 11,798 bytes to **8,324 instructions / 25,770 bytes**. The target list is `/tmp/opencode/targets.txt`, and the seed-and-scan script is `NdsPeriph.java` in the Ghidra script directory.

### The UAC1/UAC2 personality selector

Two functions in the previously unreachable block decide the USB personality:

```
ram:00006758  lwi.gp a2,[+ -0xd04]
ram:0000675c  lwi.gp a3,[+ -0xd1c]
ram:00006760  cmovz a3,a2,a0
ram:00006766  lbi333 a3,[a3 + 0x3]
ram:00006768  lbi333 a2,[a0 + 0x2]
ram:0000676a  slli a0,a3,0x8
ram:0000676e  or33 a0,a2
ram:00006770  beqc a0,0x201,0x00006782     <- bcdUSB == 0x0201 ?
ram:00006774  movi55 a0,0x0
ram:00006778  sethi a0,0x8d
ram:0000677c  ori a0,a0,0x5f8               <- 0x8d5f8 / file 0xd5f8
ram:00006782  movi55 a0,0xc
ram:00006786  sethi a0,0x8d
ram:0000678a  ori a0,a0,0x5f8
```

and the descriptor selection right after it:

```
ram:000067a2  movi a0,0x417f0
ram:000067ac  sethi a1,0x8d
ram:000067b0  ori a1,a1,0x844               <- 0x8d844 / file 0xd844
ram:000067b4  movi55 a0,0x2
ram:000067b6  swi.gp a1,[+ -0x17fc]
...
ram:000067e0  sethi a1,0x8d
ram:000067e4  ori a1,a1,0x72c               <- 0x8d72c / file 0xd72c
...
ram:00006808  movi a0,0x41758
```

So the personality follows the negotiated `bcdUSB`: `0x0201` selects the UAC 2.0 set, anything else selects a UAC 1.0 set, and three descriptor pointer blocks exist at file offsets `0xd844`, `0xd72c`, `0xd758`. The stored descriptor sets are:

| Location | What it is |
|---|---|
| `0xca04` | UAC 1.0 config: `0xcb` bytes, 3 interfaces, AC header `09 24 01 00 01` (bcdADC 1.00) |
| `0xd338` | UAC 2.0 device descriptor: bcdUSB 2.01, class `0xEF` (IAD), PID 0x0102 |
| `0xd34c` | UAC 2.0 config: `0x1e8` bytes, 4 interfaces, bcdADC 2.00 |
| `0xf7c0`, `0xf7d4` | UAC 1.0 device descriptors: bcdUSB 2.00, class 0, PID 0x0102, differing only in `iSerialNumber` |

No stored descriptor carries PID `0x0101`; the byte pair `72 29 01 01` appears nowhere in the image. The `0x0101` the host sees is patched in at runtime by the UAC 1.0 path, which is why a hex search for it in the file finds nothing.

A port reset alone did not change it: `USBDEVFS_RESET` (`ioctl 0x5514`) on `/dev/bus/usb/001/046` re-enumerated straight back to full speed. The mode is not a hardware latch, though. It is a **config register written by FiiO command `0x20`**, documented by `Cyfine/ja11-web-control/PROTOCOL.md` from the FiiO Control APK: `0 = UAC 1.0`, `1 = UAC 2.0`. The device reported `0x20 = 0` while it was in UAC 1.0.

Writing `0x20 = 1` (`aa 0a 00 00 20 01 01 00 ee`) flipped it instantly:

```bash
$ lsusb -d 2972:
Bus 001 Device 050: ID 2972:0102 FiiO Electronics Technology JadeAudio JA11
# usb 1-1: new high-speed USB device number 50 using xhci_hcd
# bcdUSB 2.01 / bcdADC 2.00 / Negotiated speed: High Speed (480Mbps)
# stream0: 125 us packet interval, rates 44100..384000
# cmd 0x20 reads back 1
```

It survived a port reset in that state (device 050 still `2972:0102` at high speed), 384 kHz playback works again, and a later physical unplug/replug proved it is stored rather than runtime: device 061 came back as `2972:0102` at high speed with both patched PerfCfg gains intact. The same document also explains the other readable registers seen earlier: `0x02` = device volume (`60`), `0x09` = stream-rate label (`2` = 48k), `0x0b` = firmware 2.20, `0x12` = headset mic detection (`1`), `0x16` = active EQ program where `0..4` are Vocal/Classic/Bass/User 1/Off. The device reports `0x16 = 3`, i.e. **User 1**, which is the flat curve saved earlier.

### The analog gains are not in the firmware

The `PerfCfg` block at file `0x10d8` holds the only per-board analog values (ADC PGA index 4, DAC PGA index 13). Scanning all 8,324 decoded instructions for `0x810d8` or `0x10d8` returns **zero hits**, and no instruction references the block either directly or through the pointer tables. The conclusion is that the **boot ROM** parses the image header and applies those gains before jumping to `0x3000`; the application firmware never touches them. That is why a host-side write to `0x3B` cannot persist: the value is re-applied from flash by code we cannot see or patch from the application side.

The peripheral window is USB-dominated: the decodes reference `0x443a0`, `0x4439c`, `0x44520`, `0x446a8`, `0x446c4`, `0x446d4`, `0x446e8`, `0x44700`, `0x44704`, `0x44730`, and the endpoint/DMA block at `0x44780`/`0x44810` (`0x9d14` writes a 0x18-byte descriptor per endpoint: `0x80`, `0x85`, `0x04`, `0x84`, `0x83`, `0x03`, with packet sizes `0x40`, `0x10`, `0x400`, `0x200`, `0x40`, `0x40`). No codec or DC-DC register block appears in the reached code.

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

## 6. What was done on the dongle, and what the measurements say

### The host and the link are cleared

```bash
$ /usr/bin/time -f "wall=%e" aplay -D plughw:JA11 t30.wav     # 30.000 s of 48k/24 audio
wall=30.02
$ cat /proc/asound/card3/pcm0p/sub0/status
state: RUNNING
delay       : 18912
avail       : 5760
```

`delay` stayed inside 18,864–18,912 frames for the whole file, 44.1/48/96 kHz all played with wall times 15.01–15.04 s for 15.000 s of audio, and the same file under 12 busy CPU loops produced no `underrun!!!`. Through PipeWire the node ran `QUANT 2048 / 48000 Hz / W/Q 0.00 / ERR 0`. The link, the async feedback endpoint and host scheduling are healthy, so crackle is not a URB or scheduling problem on this host.

### Persistence: the `0x4B` channel is RAM-only, the `0x02` channel is what saves

Two saves were made and the difference matters:

1. Wrote `0x24 = 4` plus flat bands over the `0x4B` register channel, then sent FiiO `SAVE_FLASH` (`0x19`, payload `03`). The dongle re-enumerated (device 44 → 45) and came back with the **factory curve** (`0x24 = 5`, 141 Hz −2.4 dB …). Register-channel writes are not what the save captures.
2. Wrote the flat curve through the FiiO band command (`0x15`, 8-byte payload `idx, gain_be16, freq_be16, q_be16, type`), then `APPLY` (`0x18`) and `SAVE_FLASH` (`0x19`). It re-enumerated again (45 → 46) and came back **flat**:

```
0x24 = 0x00000005
0x26 = 0x03e80000  1000 Hz   0.0 dB       0x27 = 0x000002c6  Q 0.710
0x28 = 0x07d00000  2000 Hz   0.0 dB       0x29 = 0x000002c6  Q 0.710
0x2a = 0x13880000  5000 Hz   0.0 dB       0x2b = 0x000002c6  Q 0.710
0x2c = 0x1f400000  8000 Hz   0.0 dB       0x2d = 0x000002c6  Q 0.710
0x2e = 0x27100000 10000 Hz   0.0 dB       0x2f = 0x000002c6  Q 0.710
```

Three consequences:

- The saved PEQ state lives in a **flash sector outside the 67,312-byte firmware image**. The image contains no copy of the curve, and the 10-byte write scripts at `0xc804`/`0xf5e9` are flat/preset data that nothing references. The bootloader's `ERASE` wipes that sector, which is why a reflash returns the chip defaults.
- `SAVE_FLASH` **resets the device**, so a save doubles as the cleanest persistence test.
- Q is scaled per channel: the FiiO band command takes `Q × 100` (`71` = 0.710) while the register map stores `Q × 1000` (`710` = 0.710). Mixing them yields a Q of 7.1.

### Why flat is the right baseline

The stock curve boosts 447 Hz by +2.1 dB and cuts 141 Hz by 2.4 dB with the preamp at 0.0 dB (`0x17 → 00 00`, verified). Tracks mastered near 0 dBFS clip at 447 Hz, and the low-mid forwardness is easy to hear as "off" next to a flat source. Flat bands with 0 dB preamp are unity, so there is nothing left to clip.

The DRC paths were checked too, since a misconfigured limiter or gate would match the symptoms exactly. Both are off:

```
0x71 = 0x3ce2dad3   byte3 0x3c: gate EN = 0   (THhigh -38 dB, THlow -45 dB, GateVol -30 dB, but disabled)
0x78 = 0x000000fd   byte3 0x00: limiter EN = 0, soft knee = 0   (threshold -3 dB, disabled)
0x79 = 0x012c000a   release 300 ms, attack 10 ms
```

Previous state is at `/tmp/opencode/ja11_dsp_before.json`; the revert is the same write with 141 Hz −2.4, 447 Hz +2.1, 2098 Hz −1.1, 4693 Hz −1.4, 8464 Hz −1.6 dB and Q 56/72/77/198/300 (`Q × 100`).

Both directions are now scripted, so the last variable can be A/B'd in seconds:

```bash
cd ~/sessions/2026-11-26-ja11-sound
sudo setfacl -m u:$USER:rw /dev/hidraw6
./ja11_eq.py show            # current preamp + five bands (read over 0x4B)
./ja11_eq.py stock --save    # restore FiiO's curve (dongle resets)
./ja11_eq.py flat  --save    # go back to flat
```

Verified final state after the last save and reset (device 46 → 47):

```
preamp: +0.00 dB
DAC EQ enable 0x24: 0x5
band0:  1000 Hz  +0.0 dB Q 0.710
band1:  2000 Hz  +0.0 dB Q 0.710
band2:  5000 Hz  +0.0 dB Q 0.710
band3:  8000 Hz  +0.0 dB Q 0.710
band4: 10000 Hz  +0.0 dB Q 0.710
```

One oddity worth knowing: writing bands over `0x02` without saving can leave `0x24` reading `0x03` instead of `0x05` (bit 2 clears). The applied+`SAVE_FLASH` state reads `0x05`. Both have the EQ enabled (bit 0), so the curve applies either way.

### The `PerfCfg` block is not calibration

At `0x10d8` it is eight zero bytes, then two LE32 values: **ADC PGA index 4 (+20 dB)** and **DAC PGA index 13 (0.0 dB)**, then the FIIO / JadeAudio JA11 / serial strings. V2.1 → V2.2 changed only byte `0x10e8` (`03` → `04`), the "optimised microphone input gain" entry in the changelog. So the image carries no per-board analog calibration at all, only those two gains, and they match what the chip reports.

### Flashing the patched PerfCfg (DAC PGA −6 dB)

Since no firmware code references `PerfCfg`, the only durable way to change the analog gain is to patch the image header and reflash. Done, and verified end to end:

```bash
cp JadeAudio_JA11_V2.2.bin /tmp/opencode/ja11_pga9.bin
# 0x10ec: 0x0d -> 0x09
sha256  f4aada7a2384390c1f8e2cc2aa666545398da2dbbb96fdf1cdd9997dbaaae7a6
ktflash image /tmp/opencode/ja11_pga9.bin
#   magic KT_Helios_v1b / chip KT02H20B / declared 67312 (0x106F0) — same findings as the original
```

The header has no checksum: `0x48` is the ENTY payload size and reads `0x0001d188` in **all five** official versions (V1.7, V1.9, V2.0, V2.1, V2.2), so a one-byte change cannot invalidate a hash. The Rust flasher refuses to *unlock* `2972:0101` (its normal-mode list only has `0102`), so the unlock was sent directly:

```bash
# hidraw write: 54 31 32 33 34 35 36 37 38 00 00   -> 8888:cdc0, /dev/ttyACM0
ktflash flash-cdc --image /tmp/opencode/ja11_pga9.bin --execute --yes
#  KTM ok, CHP -> KT02H20B, ERASE ok, all 67 packets [78 a5], STP ok, RESET ok
#  [reprobe] no recognised device — only because the tool does not know 0101
```

It came back as `2972:0101` (device 049), and the decisive read showed the patched DAC gain applied:

```
0x3b DAC PGA index  = 0x00000009     (-6 dB, was 0x0d = 0 dB)
0x3a ADC PGA index  = 0x00000004     (still 20 dB at that stage)
0x65 ADC digital    = 0x00000100
0x66 DAC digital    = 0x00000200
0x24 DAC EQ en      = 0x00000005
DAC bands           = 1000/2000/5000/8000/10000 Hz, 0.0 dB, Q 0.710
```

So the boot ROM does parse `PerfCfg` and the patched value took effect. The flat EQ also survived the erase+reflash, which is consistent with the image's own flat table at `0x106a` being what the firmware loads.

### Stage 2: ADC PGA 0x10e8 0x04 → 0x00, with a measured effect

The same `PerfCfg` block holds the mic preamp at `0x10e8` (index 4 = +20 dB). Patched that to `0` (0 dB) on top of the DAC patch, in `/tmp/opencode/ja11_pga9_adc0.bin` (sha256 `31ff1ed2…db6b`), flashed the same way. The device is V2.2 with both patches and reads:

```
0x3a ADC PGA index  = 0x00000000     (0 dB, was 0x04 = +20 dB)
0x3b DAC PGA index  = 0x00000009     (-6 dB)
0x24 DAC EQ en      = 0x00000005     flat bands
cmd 0x20            = 1              (UAC 2.0)
```

This one has an **objective measurement**, because the ADC is the one analog path the host can capture. Recording 5 s from `hw:3,0` with the same source and gain settings:

| Build | ADC PGA | mic peak | mic RMS |
|---|---|---|---|
| V2.2 stock | +20 dB | 29 | 5.75 (−75.1 dBFS) |
| V2.2 official V2.1 | +14 dB | 13 | 2.74 (−81.5 dBFS) |
| V2.2 patched | 0 dB | 3 | 0.88 (−91.4 dBFS) |

A 16.3 dB drop for a 20 dB gain change, monotonic with the V2.1 middle value. The patched `PerfCfg` is therefore provably applied to the analog front end, not just to the header.

Playback with both patches is clean at every rate (44.1/48/96/384: 15.04/15.03/15.02/10.02 s) and through PipeWire.

### Stage 3: V2.1 comparison, to rule out a V2.2-specific regression

The official V2.1 image (`sha256 470ba6c0…0adfff`, build `b84a747 2024-10-10`) was flashed and measured the same way. Its `PerfCfg` is `0x10e8 = 03`, `0x10ec = 0d`, which the device confirmed (`0x3A = 3`, `0x3B = 13`), and the mic path landed between the two V2.2 values (−81.5 dBFS), so V2.1 really was running. Playback was identical and clean at all four rates.

One caveat: `cmd 0x0b` still reported `02 02` on V2.1. The version strings live at `0x1010` (`2.1.0` vs `2.2.0`), so that command is evidently not reading the image version, and the PerfCfg difference is the reliable proof of which image is running.

Conclusion: no V2.2-specific playback regression is detectable. The only V2.1→V2.2 difference on the audio path is the mic gain (14 → 20 dB) plus the inline-control code, neither of which changes the DAC path. V2.2 with both patches was restored afterwards and re-verified.

Playback after the flash is clean at every rate, twice, and through PipeWire:

```
t44  wall=15.03   t48  wall=15.02   t96  wall=15.01      (15.000 s of audio)
pw-top  QUANT 2048 / 48000 Hz / W/Q 0.00 / ERR 0
```

With UAC 2.0 restored the full rate ladder works as well:

```
h192000  wall=10.03      (10.000 s)
h384000  wall=10.02
h384_30  wall=30.03      (30.000 s at 384 kHz, no underruns)
cmd 0x09 while playing 384k -> 8   (rate label: 8 = 384k)
```

**Honest limit of this change.** Lowering the analog PGA by 6 dB does not by itself lower the noise floor at a fixed listening level: it attenuates signal and DAC noise together, and the amp noise after the PGA is unchanged. If the user raises the digital volume by 6 dB to compensate, the signal and DAC noise come back up and the amp noise stays, so the result at equal SPL is neutral. What it does give is 6 dB more digital range before the analog stage, a 6 dB lower maximum output, and a lower absolute noise floor when listening quietly. Whether that is an improvement is an ears question, not a register question.

Revert: `ktflash` the original `JadeAudio JA11_V2.2.bin` back (sha256 `65fea499…4103de`), then re-apply the flat curve if wanted.

### Stage 4: DAC PGA to −12 dB, and the headset-detection toggle

Patched `0x10ec` from `0x09` to `0x05` on the ADC-zero base → `/tmp/opencode/ja11_pga5_adc0.bin` (sha256 `563908fa…0468f`), flashed the same way. Verified:

```
0x3a = 0x00000000   0x3b = 0x00000005   0x24 = 0x00000005
44.1/48/96/384 kHz: 15.04 / 15.03 / 15.02 / 10.03 s
mic capture: -91.7 dBFS   (unchanged, as expected: the DAC PGA is not in the ADC path)
```

Headset detection (`0x12`) turned out to be a real structural toggle, not just a flag:

- `0x12 = 0` re-enumerates the dongle as a **playback-only device**: 3 interfaces, no Capture section in `stream0`, `arecord -l` shows no JA11 capture, and the device descriptor switches to the `0xf7c0` variant with `iSerial = 0`.
- `0x12 = 1` re-enumerates back with the capture interface present.

Both directions were observed on the bus (`lsusb`, `stream0`, `arecord -l`). It is left at `1` so the mic still works; `0` is the option if the mic path is ever suspected of coupling noise.

Trade-off of this stage: the DAC analog gain is now 12 dB below stock, which costs 12 dB of maximum output. At equal loudness the digital volume compensates and the noise behaviour should be roughly neutral, so this is a headroom and low-level-noise change, not a proven hiss fix.

### Amp mode (command `0x1D`) is write-only and invisible to the register map

`Audiocular-Aura` (the source Ircama's header cites for `CMD_AMP_MODE 29`) implements it as `setDacWorkMode(device, isClassAB)`: `0 = Class H`, `1 = Class AB`. On this firmware it is write-only and leaves no trace in the DSP map:

```
read 0x1d before write: (none)
write 0x1d = 1 (Class AB): accepted, no reply, no re-enumeration
read 0x1d after write:  (none)
0x3a = 0x04   0x3b = 0x09   0x24 = 0x05        (unchanged)
```

A full 256-register A/B settles it: write `1` → dump, write `0` → dump, write `1` → dump gives **0 differing registers** in both directions. The amp mode is applied straight to the analog block, so there is no readback path and no way to prove the change from the host. Playback after the exercise is unchanged (384 kHz 10.02 s, 48 kHz 15.03 s, device 050 still high speed). It is left at Class AB (the more linear mode); switch back with `aa 0a 00 00 1d 01 00 00 ee`.

### `0x16` (EQ program) is read-only here

The APK-derived table lists `0x16` as the active EQ program (`0..4`), but on this firmware it only reports: after the reflash it read `1`, and writes of `4`, `0`, `2` and `1` all left it at `1`. The DSP applies the band registers (`0x26..0x2f`), which are flat, so the audible result is flat regardless of the label. Not worth chasing further.

## 7. What is still unexplained

### Both objective measurement routes are physically blocked

The analog output cannot be captured on this machine as configured:

- **ALC897 line-in.** `Line Jack` reads `off`, so no cable is in the jack. A 5 s capture at 48 kHz came back at −8.3 dBFS RMS, which looks like signal until you look at the spectrum: a Goertzel sweep gives magnitude **123.9 at 50 Hz** against **under 15** at 60/100/120/440/997/1000/3000/10000 Hz. It is mains hum on an open input at `Capture Volume 63/63` and `Front Mic Boost 30 dB`.
- **The JA11's own capture endpoint.** Playing the 997 Hz tone to the dongle while recording 5 s from `hw:3,0` gives `peak=30`, `rms=5.2` (**−76.1 dBFS**). There is no internal DAC-to-ADC loopback, and no acoustic pickup. The mic path is quiet, which also clears it as a hiss source.

So THD+N and noise-floor numbers for the DAC/amp cannot be produced without a 3.5 mm to 3.5 mm cable between the dongle and the line-in, or a measurement rig.

### What remains

- **Hiss.** With EQ flat and preamp at 0 dB, the only gain left is the factory DAC PGA at 0 dB plus the amp. The value comes from the boot ROM via `PerfCfg`, so changing it durably requires patching `0x10ec` and reflashing, which erases the saved EQ sector and is unproven without ears.
- **Crackle/pops.** Link, clock, host and DRC are all measured clean. What remains is the 3.5 mm contact, the cable, or the amp's Class-G/DC-DC behaviour on this board.
- **Distortion on loud parts.** Reduced by the flat curve, but 30 mW into a low-impedance load is a hardware ceiling.

The remaining tests need ears and hands: a different IEM and cable, wiggling the plug, and a pause with the source silent to hear whether hiss survives with no signal. If it does, it is the board, not the firmware.

## 8. Rejected fixes

- **Blind-writing `0x12` as a guessed UAC flag.** It is actually headset-mic detection, so writing it would have changed the wrong thing. The real mode command is `0x20`, and it was only written after the community protocol doc identified it as `0 = UAC 1.0, 1 = UAC 2.0`.
- **Patching `0x10ec` (DAC PGA index) and reflashing** for a speculative 6 dB noise improvement. The reflash erases the saved EQ sector, and the gain change is unproven without ears.
- **Writing the amp mode** (`0x1D`). Write-only, undocumented values, and a wrong Class-G setting is a plausible way to make things worse.
- **`uhubctl` power cycle.** Installed (2.6.0) but the root hub reports no compatible port power switching, so the dongle cannot be VBUS-cycled to re-latch the UAC mode.

## Gotchas

- `hidraw` ACLs are dropped on every replug (`sudo setfacl -m u:moo:rw /dev/hidraw6`), and the node re-registers; re-check `/sys/class/hidraw/*/device/uevent` for `2972`.
- The `0x4B` register channel works on this firmware (256/256 answered), but the `0x02` FiiO channel is **write-only** for filter/amp/gain mode: reads return nothing. Do not conclude the filter is wrong from a missing read.
- Ghidra needs `GHIDRA_INSTALL_DIR` and `JAVA_HOME` set; the bundled `support/sleigh` is the compiler, not a decoder, so ISA testing has to go through `analyzeHeadless`.
- Importing a raw binary at base 0 is correct **only** for this family: the flash tool writes the image at base 0 with the 16-byte header written last, so file offset equals device address.
- The `0x3000` boundary is real: below it is header and zeros, so an importer that starts analysis at 0 will produce noise before the first real code.

## What was not verified

- Which DAC filter is active. Not readable on this firmware; `0x11` was written with value 1 (FAST-LL) and may or may not have persisted through the save.
- Whether writing `0x1D` actually changed the amp class. The command is write-only and a 256-register A/B shows zero differences, so the effect is unobservable from the host.
- What sets UAC 1.0 mode in the first place. The `0x20` command explains how to change it, not why it was `0` at 11:55 while `0102` was in use at 06:45. It may have been written by an app or the button gesture.
- Whether the −12 dB DAC PGA actually reduces perceived hiss. At equal loudness it should be roughly neutral, since raising the digital volume cancels the analog cut; only a listening test settles it.
- THD+N and noise floor of the analog output. Both capture routes are physically closed: the ALC897 line-in has no cable (50 Hz hum only, −8.3 dBFS) and the JA11 capture shows no loopback (−76.1 dBFS while a 997 Hz tone plays).
- The ISA is confirmed as NDS32, but only as disassembly: no decompiler output. Coverage is now 25,770 of 55,024 bytes (8,324 instructions) after seeding the 148 pointer targets; roughly 29 KB remains data or code reached by computed dispatch.
- How the four built-in EQ presets are selected. No reference to the `0xf5e9` script table appears as an immediate in the reached code.
- Whether the analog noise floor changes with the DAC PGA. That needs a measurement rig, not a register read.

## 9. Final device state

```
lsusb        2972:0102  high speed (480 Mbps), bcdADC 2.00, firmware 2.20
stream0      S16/S24_3LE, 44100..384000, 125 us microframes, ASYNC + sync EP
cmd 0x20     1        UAC 2.0
cmd 0x16     1        EQ program label (read-only on this firmware)
0x3a         0        ADC PGA  0 dB   (patched PerfCfg, 0x10e8 0x04 -> 0x00)
0x3b         5        DAC PGA -12 dB  (patched PerfCfg, 0x10ec 0x0d -> 0x05)
0x12         1        headset/mic on (0 = playback-only descriptor set)
0x24         5        DAC EQ enabled
0x26..0x2f   flat     1000/2000/5000/8000/10000 Hz, 0.0 dB, Q 0.710
preamp       0.00 dB
DRC          off      gate EN=0, limiter EN=0
amp mode     Class AB (0x1d = 1, write-only, no register trace)
playback     44.1/48/96/192/384 kHz clean, no underruns
persistence  verified across a real unplug/replug: device 061 came back 2972:0102
             high speed with 0x3a=0, 0x3b=5 and the flat EQ intact
```

Revert paths: reflash the official `JadeAudio JA11_V2.2.bin` to restore DAC PGA 0 dB and the image's own flat EQ; `aa 0a 00 00 1d 01 00 00 ee` restores Class H; `aa 0a 00 00 20 01 00 00 ee` restores UAC 1.0.

## References

- [FiiO forum: JA11 firmware download and changelog](https://forum.fiio.com/note/showNoteContent.do?id=202406211150090736905) — official V2.2/V2.1/V2.0/V1.9/V1.7 ZIP links used above
- [FiiO: JA11 V2.2 announcement](https://www.fiio.com/newsinfo/1065234.html)
- [KTMicro KT02H20 product page](https://www.ktmicro.com/?usb_104/394.html) — feature list, UAC1.0/2.0, "FLASH 允许客户二次开发程序", no CPU documentation
- Ghidra 12.1.4 in-tree `NDS32` processor (`Ghidra/Processors/NDS32`, `NDS32:BE:32:default`) — the language that decoded the image
- [`Ircama/ja11-config`](https://github.com/Ircama/ja11-config) — HID packet formats and filter table
- [`Cyfine/ja11-web-control`](https://github.com/Cyfine/ja11-web-control) — `PROTOCOL.md` command table from the FiiO Control APK: `0x20` UAC mode, `0x16` EQ program, `0x12` headset detection, `0x02` device volume, `0x09` rate label
- [`adithyasource/fiiocontrol-oss`](https://github.com/adithyasource/fiiocontrol-oss) — `src/libs/devices/fiioJa11.js`, the JA11 packet builder (bands, master gain, save)
- [`mandy321/Audiocular-Aura`](https://github.com/mandy321/Audiocular-Aura) — `src/dsp.ts` amp mode (`0x1D`: 0 = Class H, 1 = Class AB) and the register UI it drives
- [`eyad-elghareeb/kt0231h`](https://github.com/eyad-elghareeb/kt0231h) — `ARCHITECTURE.md` (independent NDS32 identification), `PROTOCOL.md` (image layout, EQ entry format)
- [`gxcreator/ktmicro-tools`](https://github.com/gxcreator/ktmicro-tools) — `KT_USB_PROTOCOL.md` register map
- [`ParkWardRR/…-toolkit`](https://github.com/ParkWardRR/fiio-ja11-jcally-jm12-moondropkt02-kt02h20-dac-amp-toolkit) — `docs/COMPATIBILITY.md`, `docs/REVERT.md` (cross-flash risk, stock image sourcing)
- [`dragonzords/KT02H20-FLASHER-RE`](https://github.com/dragonzords/KT02H20-FLASHER-RE)
- Local: [[ktflash-rust-toolkit-linux-kt02h20-reflash-2026-11-26]], [[kt02h20-jcally-dac-ja11-firmware-flash-protocol]], [[fiio-ja11-peq-match-tin-hifi-c7-hidraw]], [[fiio-ja11-kt02h20-power-and-volume-ceilings-2026-11-16]], [[ktmicro-dsp-dongles-fission-ja11-chu2-same-chip-comparison-and-otg]]
