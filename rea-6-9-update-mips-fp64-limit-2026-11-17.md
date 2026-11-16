---
type: investigation
tags: [rea, rea-agents, ghidra, mips, fp64, nan2008, node, diskos, snowsky-disc, reverse-engineering, firmware-decompiled]
created: 2026-11-17
last_verified: 2026-11-17
status: current
---

# REA 6.9.0 update: local Node 24 pin, and why its Ghidra lane refuses the Disc's MIPS FP64 binaries

Request: "check latest rea version and update it check if we can reverse engineer more from the firmware using rea". The firmware in question is the FiiO Snowsky Disc V2.57 rootfs, decompiled at `/home/moo/diskos/firmware-decompiled` (private repo `txtsamu/snowsky-disc-firmware-decompiled`, single commit `f7a9137`). diskOS repo was at `/home/moo/diskos/diskos`, branch `main`, `3726ebc`, clean.

## Outcome

REA is updated and its Ghidra provider is healthy. It still cannot open the Disc's userland binaries, and the refusal is deliberate, not a misconfiguration: the lane admits MIPS32r2 o32 only with 32-bit CPR1 (double-precision or FPXX) or soft-float, while the Disc is `CPR1 size: 64`, `FP ABI: Hard float (32-bit CPU, 64-bit FPU)`, plus `EF_MIPS_NAN2008`. The decompiler gain is zero.

## Update

`npm view rea-agents version` returned `6.9.0`; installed was `6.8.0`.

REA 6.9.0 declares `engines.node = ^22.23.4 || ^24.22.1 || >=26.12.1`, and 6.8.0 ran on the same floor. Fedora 43 carries `nodejs 22.22.2-2.fc43` only, and the new binary refuses to start:

```
REA requires Node.js 22.x (>=22.23.4), 24.x (>=24.22.1), 26.12.1+; this process runs Node.js 22.22.2. Install a supported release, then retry.
```

So Node v24.22.3 Krypton went into `/home/moo/.local/node24`, tarball checked against `SHASUMS256.txt` (`node-v24.22.3-linux-x64.tar.xz: OK`), and REA was installed with that npm (`npm 11.19.1`) into the same `~/.local` prefix the project's own installer uses on Linux:

```
PATH=/home/moo/.local/node24/bin:$PATH npm install -g --prefix "$HOME/.local" --allow-scripts=frida rea-agents@6.9.0
```

System Node stays 22.22.2. `~/.local/bin/rea` and `~/.local/bin/rea-agents` are now small wrappers instead of npm symlinks:

```sh
#!/bin/sh
# REA 6.9.0 needs Node >= 24.22.1; pin the local Node 24 so the system Node 22 is untouched.
exec /home/moo/.local/node24/bin/node /home/moo/.local/lib/node_modules/rea-agents/scripts/rea.mjs "$@"
```

`~/.bashrc` gained line 76: `export GHIDRA_INSTALL_DIR=/var/tmp/moo-ghidra/ghidra_12.1.4_PUBLIC`.

`rea doctor` now reports `node 24.22.3 healthy`, `ghidra 12.1.4 healthy`, `ghidra-headless` and `ghidra-native_decompiler` healthy, `ghidra-java 25.0.4.1`. Overall `healthy: false` remains because Hopper, IDA, JADX, Kuna and every client registration are absent. None of those are needed for the Ghidra lane.

## Why the Disc binaries are refused

```
$ rea analyze /home/moo/diskos/re/mq_ui_stock_257 --provider ghidra
architecture_unsupported: EF_MIPS_NAN2008 requires separate verification of NaN encoding semantics in this Ghidra lane.
```

The admission code is `dist/ghidra/GhidraMipsProfile.js`. It walks the declared ABI record and ends at:

```
This Ghidra MIPS lane admits double-precision or FPXX ABI declarations with 32-bit CPR1, or soft-float without CPR1; single-float, FP64 and unspecified modes need separate verification.
```

The target headers, from `readelf -A`:

```
Flags: 0x70001405, noreorder, cpic, nan2008, o32, mips32r2
ISA: MIPS32r2   GPR size: 32   CPR1 size: 64   CPR2 size: 0
FP ABI: Hard float (32-bit CPU, 64-bit FPU)   FLAGS 1: 00000001
```

Clearing `EF_MIPS_NAN2008` in a scratch copy (`e_flags` `0x70001405 -> 0x70001005` at ELF offset 36) only moves the refusal to the CPR1/FP64 rule. `REA_GHIDRA_LANGUAGE_ID=MIPS:LE:32:fp64` with `REA_GHIDRA_COMPILER_SPEC_ID=mips32le_fp64` does not bypass either; it is honored for loading, but admission runs first and the pinned lane language cannot be combined with an override.

The lane itself works: `rea analyze /usr/bin/ls --provider ghidra` completed and returned evidence with `upstream_analysis_profile.provider.version 12.1.4`. The problem is the MIPS profile, not the install.

This matters because `~/diskos/firmware-decompiled` exists precisely because stock Ghidra MIPS languages mishandle odd FP registers. The pipeline used a custom `MIPS:LE:32:fp64` variant, built from `mips32le.slaspec` with `FREGSIZE 8`, and documented that the stock 32-bit-FPR language "truncates ~100 functions per large binary". REA pins `MIPS:LE:32:default` for its admitted MIPS lanes, so even a metadata-forged admission would decompile worse than the existing output.

## What REA can still do here

Without an engine, the static inspectors work and return canonical Evidence:

- `rea inspect-native-exports` on `mq_ui_stock_257`: provider `rea-native-exports`, architecture `mips`, sha256 `f9b40d82...`.
- `rea inspect-elf-notes` and `rea inspect-byte-entropy`: same binary, provider `rea-elf-notes` / `byte-entropy`.

Everything heavier needs a caller-supplied tool REA will not install:

- `inspect-binary-layout` wants `REA_PWNTOOLS_PYTHON` with pwntools 4.15.0, pyelftools 0.33, Unicorn 2.1.2.
- `inspect-firmware-regions` wants `REA_BINWALK_COMMAND`.
- `execute-rizin-command` and `debug-with-rizin` want `REA_RIZIN_COMMAND`; rizin is not installed on this host.

## Gotcha: the entry script is a symlink

`~/.local/bin/rea` was a symlink into `scripts/rea.mjs`. Writing a wrapper with `cat > ~/.local/bin/rea` followed the symlink and replaced the package entry script, after which `rea --version` failed with a `SyntaxError` on the shell line. Fixed by deleting both bin links and reinstalling `rea-agents@6.9.0`, then creating the wrappers after `rm` of the symlink. Never redirect into a path that is still a symlink; `rm` first.

## What would actually add coverage

Not REA. The decompiled repo's own numbers point at the real gaps: 27 of 411 ELFs decompiled, 734 of 53,223 kernel symbols, recovery OS v18 never processed, bootloader absent from the OTA zip, 3 `wl` failures that only a different decompiler could reach.

## Not verified

- Whether upstream REA would admit FP64 MIPS with a verification flag; no such knob exists in 6.9.0.
- Whether forging the ABI record into the recordless lane is worth it. Predicted to be worse, not tested.
- The rizin path for the 3 `wl` failures, since rizin and rz-ghidra are not installed.
- `rea setup` client registrations were not run; only the analysis provider was configured, by environment variable.

## References

- [[diskos-usb-audio-normal-build-hotload-2026-11-16]]
- [[snowsky-disc-usb-dac-uac2-android-and-firmware-decompile]]
- [[diskos-usb-debug-source-menu-serial-no-ethernet-2026-11-10]]
- [[diskos-rust-rewrite-feasibility-2026-11-17]]
