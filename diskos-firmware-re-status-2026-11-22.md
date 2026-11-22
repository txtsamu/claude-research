---
type: investigation
tags: [diskos, snowsky-disc, fiio, ghidra, reverse-engineering, firmware-decompiled, mips, fp64, rea, jumptable, toolchain]
created: 2026-11-22
last_verified: 2026-11-22
status: current
---

# diskOS firmware reverse engineering: state, the `/var/tmp` toolchain loss, and the rebuilt lane

Request: "check claude-research and status of reverse engineer of diskos firmware", then "find on internet so the failures can be fix", then "fix A".

Short answer: the reverse-engineering output is complete for its declared scope and pushed. The environment that produced it was destroyed along with `/var/tmp`, and the pipeline scripts were never committed. The lane has been rebuilt on a durable install and the three remaining decompiler failures are fixed. What is still missing is the two pipeline scripts.

Related: [[snowsky-disc-usb-dac-uac2-android-and-firmware-decompile]], [[diskos-usb-audio-reverse-engineering-mq-player]], [[rea-6-9-update-mips-fp64-limit-2026-11-17]], [[diskos-sd-clean-unmount-and-fsdetect-2026-11-17]], [[fiio-snowsky-disc-diskos-flash-fedora]].

## What the RE produced (intact)

Private repo `txtsamu/snowsky-disc-firmware-decompiled`, local copy `~/diskos/firmware-decompiled`.

- Commits `f7a9137` (initial decompile) and `76f354c` (decompiler patch plus the three recovered `wl` functions), working tree clean, local HEAD identical to `origin/master`, visibility `private`, 81 MB.
- `MANIFEST.md`: all 411 unique ELFs (415 paths) with tier, sha256, NEEDED libs and the tier reason. TIER1 13 and TIER2 14 decompiled, TIER3 385 inventory only.
- 34,960 userland functions across 27 binaries, plus 734 kernel vendor functions in `decomp/kernel/src/` (8 files: `usb_audio_00.c`, `usb_otg_00.c`, `gadget_glue_00.c`, `cs43131_00.c`, `sgm41513_00.c`, `aw35615_00.c`, `ingenic_00.c`, `misc_00.c`).
- 0 decompilation failures. The last three, in `wl`, were fixed on 2026-11-22 (see below).
- `rootfs-tree.txt` (complete listing with per-file sha256), `fw-text/` (FiiO's own shell scripts, `etc/init.d`, `etc/ota_bin`, `usr/project/config`, `module_driver/*.sh`).
- Kernel symbol recovery validated against the live device: 52,687 of 52,698 names at identical addresses.

Documented gaps, from the repo's own `README.md` "Known gaps": stripped binaries so names are `FUN_`/`DAT_` and types guessed, limited C++/vtable resolution, heuristic function discovery (about 96 percent `.text` coverage on `mq_player`), PLT stubs replaced by import placeholders, kernel and bootloader outside the repo, TIER3 not decompiled.

## Where the output is actually used

- USB Audio work mode and the `mq_player` capture-thread deadlock, [[diskos-usb-audio-reverse-engineering-mq-player]].
- USB DAC UAC2 gadget layout and the role-switch sequence, [[snowsky-disc-usb-dac-uac2-android-and-firmware-decompile]].
- The USB debug gadget design, `docs/USB_DEBUG.md`.
- SD card clean unmount and fsdetect, [[diskos-sd-clean-unmount-and-fsdetect-2026-11-17]].
- `docs/adr/0001-working-mode-switches-go-via-local.md` cites the decompile, including its own gap ("the Player's storage selector is not fully decompiled").

## What broke, and what it looks like now

`/var/tmp/moo-ghidra/` was the whole pipeline and `/var/tmp` is not durable. State found on 2026-11-22, and after the rebuild:

| path | found | now |
|---|---|---|
| `/var/tmp/moo-ghidra/ghidra_12.1.4_PUBLIC` | 436 files against 5,219 in `~/tools/ghidra_12.1.4_PUBLIC`; `support/analyzeHeadless` and `support/sleigh` absent | superseded, `GHIDRA_INSTALL_DIR` points at `~/tools` |
| `.../Processors/MIPS/data/languages/` | only `mips.ldefs` and `MIPS.opinion` | restored on `~/tools`, plus the fp64 variant |
| `/var/tmp/moo-ghidra/scripts` | empty | still empty, scripts not rewritten |
| `/var/tmp/moo-ghidra/kernel` | empty (`vmlinux.elf`, `kernel.raw` gone) | still empty, re-extract needed |
| `/var/tmp/moo-ghidra/kproj/kern.rep` | empty (0 files) | still empty |

Proof of the original breakage, run 2026-11-22:

```
$ /var/tmp/moo-ghidra/ghidra_12.1.4_PUBLIC/support/analyzeHeadless
timeout: failed to run command '.../support/analyzeHeadless': No such file or directory

$ /home/moo/tools/ghidra_12.1.4_PUBLIC/support/analyzeHeadless /tmp/opencode/langtest p1 \
    -import /home/moo/diskos/re/mq_player_257 -processor MIPS:LE:32:fp64 -noanalysis
Exception in thread "main" ghidra.util.exception.InvalidInputException: Unsupported language: MIPS:LE:32:fp64
```

The second command used the *intact* install at `~/tools` and still failed, because the fp64 language variant had only ever been registered in the `/var/tmp` copy. The same install with `-processor MIPS:LE:32:default` imported `mq_player_257` fine, so the base MIPS lane was healthy and only the fp64 variant was missing.

`rea doctor` still reports `ghidra healthy` because it only checks that the directory exists. It does not notice a missing headless launcher or missing processor languages.

## Why REA does not rescue this

REA 6.9.0 refuses these binaries by design: `architecture_unsupported: EF_MIPS_NAN2008`, and clearing that flag only moves the refusal to the CPR1/FP64 rule. `REA_GHIDRA_LANGUAGE_ID=MIPS:LE:32:fp64` is honored for loading but admission runs first. Only the static inspectors work (`inspect-native-exports`, `inspect-elf-notes`, `inspect-byte-entropy`). Details in [[rea-6-9-update-mips-fp64-limit-2026-11-17]].

## The 3 `wl` failures: cause and fix

The three failures were not a general decompiler bug. All three aborted with `Low-level Error: Backward normalization not implemented`, from one place:

```
Ghidra/Features/Decompiler/src/decompile/cpp/jumptable.cc:1815
JumpBasic2::findUnnormalized()
```

`JumpBasic2` is the second jump-table model: it handles a switch whose variable passes a two-path guard and joins in a MULTIEQUAL. `findUnnormalized` walks backward from the unnormalized variable and throws when neither MULTIEQUAL input is the normalized variable. The exception escapes `DecompInterface` and the whole function is lost, not just the table.

All three are the same dispatch shape, confirmed by disassembling `wl` from the rootfs:

```
4f8b80: lbu  v0,-32(v0)
4f8b8c: sll  v0,v0,0x2
4f8b90: addu v0,v0,a0        # a0 = 0x5bb040
4f8b98: lw   v0,0(v0)
4f8ba8: jr   v0
```

A byte index into an absolute-address table, minus 32. The table at `0x5bb040` holds 224 entries, 40 distinct destinations in `0x4f8884` to `0x4fb4e8`, all inside the function. `0x4fa368` and `0x533db0` use the same `lbu` / `sll` / `addu` / `lw` / `jr` sequence with their own tables.

Upstream status: nothing. The only hit is an unanswered discussion, [NationalSecurityAgency/ghidra#5945](https://github.com/NationalSecurityAgency/ghidra/discussions/5945) (Nov 2023, 0 replies). No issue, no PR. The most recent commit touching `jumptable.cc` is 2026-10-26 (`GP-7423 Add findCbranch to checkCommonCbranch`), unrelated.

### Fix A: patch and rebuild the decompiler (chosen)

Replace the throw with the basic-model fallback:

```cpp
  else
    JumpBasic::findUnnormalized(maxaddsub,maxleftright,maxext);
```

The base method re-reads `normalvn` from `pathMeld.getVarnode(varnodeIndex)` and sets `switchvn = normalvn`, so the identity mapping is safe; only the label reverse-emulation degrades.

Build, in `Ghidra/Features/Decompiler/src/decompile/cpp` of the install:

```
make ghidra_opt
cp ghidra_opt ../../../../os/linux_x86_64/decompile
```

`make install_ghidraopt` also exists but copies to `$(GHIDRA_BIN)`, the `ghidra.bin` layout, absent from a release install, so copy manually.

### Fix B: jump-table override, no rebuild (not used)

`JumpBasicOverride` bypasses `JumpBasic2` entirely. `JumpTable.writeOverride(Function)` writes the override as `switch` / `case_N` label symbols in the function's `override` namespace, `HighFunction` re-reads it on load, and the decompiler receives it in the function XML. A script per failing switch, with the destination list taken from the table above, is enough. Per-binary and per-switch, so Fix A was preferred.

## Fix A applied

Installed in `~/tools/ghidra_12.1.4_PUBLIC`:

1. `GHIDRA_INSTALL_DIR` in `~/.bashrc:76` repointed from the stripped `/var/tmp` copy to `~/tools/ghidra_12.1.4_PUBLIC`.
2. `jumptable.cc` patched as above; original kept as `jumptable.cc.orig`, original binary as `os/linux_x86_64/decompile.orig`.
3. `make -j$(nproc) ghidra_opt` (0 errors), `ghidra_opt` copied over `os/linux_x86_64/decompile`. The string "Backward normalization" is gone from the new binary.
4. fp64 language restored: `mips32le_fp64.slaspec` (stock `mips32le.slaspec` with `FREGSIZE "8"`), compiled with `support/sleigh`, `mips32le_fp64.cspec` copied from `mips32_fp64.cspec`, and the `MIPS:LE:32:fp64` block re-added to `mips.ldefs`.

Result on `wl` (`0x4f81b0`, `0x4fa368`, `0x533db0`), same project settings, before and after:

```
original binary:  3 x completed=false, "Low-level Error: Backward normalization not implemented"
patched binary:   3 x completed=true, switch recovered with case labels
```

The output carries two warnings, `Sanity check requires truncation of jumptable` and `Could not find normalized switch variable to match jumptable` (jumptable.cc:2772), and the switch expression stays a raw byte index rather than a folded one. That is the expected degradation.

No x86 regression: 20 of 20 functions decompiled from `/usr/bin/ls` with the patched binary.

The three functions are in the repo (`part003_004d1b38.c`, `part004_00522800.c`), `failed.txt` and the counts say 0 failures, and the patch is committed as `patches/jumptable-backward-normalization-fallback.patch` (commit `76f354c`).

## Still missing

- `FindFuncs.java` and `ExportAll.java`. Without them a binary cannot be re-exported end to end. Their behaviour is described in the repo `README.md` "Method" section: create functions at `addiu sp,sp,-N` prologues not covered by an existing function (optional o32 PIC `lui/addiu/addu gp` preamble), re-run analysis, then decompile every function with 8/6 parallel `DecompInterface`s at a 90 s per-function timeout.
- The kernel artefacts. Re-extract needs the archived ZIP: decrypt the `xImage.*.enc` chunks with `_openssl_aes_decrypt` from `diskos_installer/imagebuild.py` (password `fo123`), `tail -c +65` to drop the uImage header, then `vmlinux-to-elf` from a venv.
- The discovery shortfall. `FindFuncs` is heuristic and misses pointer-only leaf functions; `mq_player` sits at about 96 percent `.text` coverage.

Surviving inputs, for whoever does that work: `~/Downloads/Archived/SNOWSKY_DISC_update_20260909_v257.zip` (sha256 `2bfad000609440bcbf492468e9e5f8f3d5e0bade797323431a15b5755688bfcf`), `~/.local/share/diskos-installer/build/stock_rootfs.squashfs` (sha256 `111e4dd7ee3d7ff91ba7e61181690be7ffd22bd1bbd13ad513f5f015ffb302ae`), `~/diskos/re/mq_player_257` (md5 `ff7beab94287f586d6faa2b51924c901`), `~/diskos/re/mq_ui_stock_257` (md5 `8795cf93b17867d8b119c1ee34c72249`).

## Time estimate

Measured on 2026-11-22, from file timestamps: patch applied 12:38:37, `ghidra_opt` built 12:39, fp64 `.sla` compiled 12:39. About 2 minutes of wall clock for the whole lane restore including the language rebuild, with `-j$(nproc)`. The three-function verification run took about 90 seconds, most of it the 2 MB `wl` analysis. A full kernel re-extract and re-decompile was not measured; the original run recorded roughly 30 minutes.

## Not verified

- Whether `~/tools/ghidra_12.1.4_PUBLIC` is byte-identical to the Ghidra zip the repo README hashes (`ddac49f9...`); it was not re-hashed.
- Whether `mips32_fp64.cspec`, now also copied to `mips32le_fp64.cspec`, is the same file the original pipeline used.
- Whether `kern.rep` being empty means the project DB was deleted or was never persisted.
- Only the three `wl` functions were re-decompiled. The other 34,957 userland outputs were not re-validated against the patched lane, and the patch is global, so a re-export is the real regression test.

## References

- [NationalSecurityAgency/ghidra discussion #5945, "Low-level Error: Backward normalization not implemented"](https://github.com/NationalSecurityAgency/ghidra/discussions/5945)
- [jumptable.cc on master](https://github.com/NationalSecurityAgency/ghidra/blob/master/Ghidra/Features/Decompiler/src/decompile/cpp/jumptable.cc)
- [JumpTable.java, writeOverride](https://github.com/NationalSecurityAgency/ghidra/blob/master/Ghidra/Framework/SoftwareModeling/src/main/java/ghidra/program/model/pcode/JumpTable.java)
- [HighFunction.java, override namespace read](https://github.com/NationalSecurityAgency/ghidra/blob/master/Ghidra/Framework/SoftwareModeling/src/main/java/ghidra/program/model/pcode/HighFunction.java)

Everything else came from the local repo, the local Ghidra installs and the notes linked above.
