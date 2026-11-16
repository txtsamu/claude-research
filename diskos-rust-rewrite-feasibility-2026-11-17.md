---
type: investigation
tags: [diskos, rust, mips, mipsel, ingenic-x2000, lvgl, cross-compile, unbrick, stock-firmware]
created: 2026-11-17
last_verified: 2026-11-17
status: current
---

# diskOS Rust rewrite feasibility, stock firmware status, and recovery path

Repo: `/home/moo/diskos/diskos`, branch `main`, HEAD `3726ebc` ("USB Audio: show the external DAC row in the normal build").

Question: can diskOS be rewritten in Rust, will it run on the FiiO Snowsky Disc, and how do we recover if an experimental build breaks boot?

## Verdict

Rust itself works on this device. A statically linked, hard-float, NaN2008, MIPS32r2 musl binary built with a custom target JSON runs under QEMU. The toolchain is solved.

A full UI rewrite is a different question. The blocker is not rustc, it is LVGL 9.2.2. No usable Rust binding for LVGL 9.x exists, so a rewrite would mean owning a custom FFI layer over the vendored C library plus porting 38,019 lines of app C, 192,337 lines of generated font tables, and the C-side framebuffer, evdev, ioctl, and mqueue code.

Best risk-adjusted path: Rust sidecar processes first, then a Rust installer CLI, then one Rust UI screen. Do not start with a full rewrite.

## Session log

1. Read the current codebase: `ui/` is 102 app C files plus vendored LVGL 9.2.2, FreeType 2.13.3, SQLite and generated fonts, built static with the mipsel hard-float musl toolchain. The installer is ~8k lines of Python. Host tools are small C programs.
2. Checked the host: Fedora 43 x86_64, no rustc installed. Installed a throwaway nightly under `/tmp/opencode` with `rust-src`; no repo files were touched.
3. Reproduced the stock-target failure with a tiny C object: soft-float and nan=legacy objects are rejected by the device's hard-float, NaN2008 CRT.
4. Dumped the built-in `mipsel-unknown-linux-musl` target spec, changed the float features to `+fpxx,+nooddspreg,+nan2008`, set the cross linker, and built `std` with `-Zbuild-std`.
5. Fixed absolute CRT paths and the `-lunwind` request by aliasing `libgcc_eh.a` to `libunwind.a`.
6. Produced a 530,072-byte static MIPS32r2 hard-float binary and ran it under `qemu-mipsel-static`; it printed `hello mips 3.00`.
7. Spawned a research subagent for prior art, LVGL bindings, the unwinder issue, and the unbrick path. Its findings are folded into this note.
8. Verified the stock firmware copies and hashes after the user asked whether they still exist. All three `stock.bin` generations are identical; the official V2.57 ZIP and decrypted rootfs are also present.

## Toolchain findings

Host: Fedora 43 x86_64. The repo had no Rust installed. A throwaway rustup nightly (`1.102.0-nightly`) in `/tmp/opencode` was used; nothing in the repo was modified.

Target ABI from `ui/README.md` and the existing binary: Ingenic X2000, MIPS32r2 little-endian, hard float, FP64, NaN2008, static musl, GCC 11.2.0 cross toolchain at `/opt/mipsel-n2008-musl-cross` (musl 1.2.6).

Rust's official `mipsel-unknown-linux-musl` is Tier 3 and its spec says `+mips32r2,+soft-float`. It cannot link against this toolchain:

```text
ld: m_t.o: linking -mnan=legacy module with previous -mnan=2008 modules
ld: warning: m_t uses -mhard-float (set by crt1.o), m_t.o uses -msoft-float
ld: failed to merge target specific data of file m_t.o
```

A custom target JSON fixed it. Key fields:

```json
"features": "+mips32r2,+fpxx,+nooddspreg,+nan2008",
"linker": "/opt/mipsel-n2008-musl-cross/bin/mipsel-linux-musl-gcc",
"panic-strategy": "abort",
"llvm-abiname": "o32"
```

Two extra fixes were needed:

1. Absolute CRT paths in `pre-link-objects-fallback` and `post-link-objects-fallback`. Rust passes bare `crt1.o` with `-nostartfiles`, and GCC does not find them by name.
2. `-lunwind`. Rust `std` has an unconditional `unwind` dependency and, for static musl, emits `#[link(name = "unwind", kind = "static")]`. The toolchain has no `libunwind.a`, and `-nodefaultlibs` suppresses GCC's implicit `-lgcc_eh`. A copy of `libgcc_eh.a` named `libunwind.a` in a `-L` directory satisfies it. `libgcc_eh.a` provides `_Unwind_Backtrace`, `_Unwind_GetIP`, and the rest.

Build command shape:

```sh
cargo build --release -Zjson-target-spec -Zbuild-std=std,panic_abort \
  --target mipsel-diskos.json
```

Result:

```text
ELF 32-bit LSB executable, MIPS, MIPS32 rel2, statically linked, stripped
530,072 bytes
Tag_GNU_MIPS_ABI_FP: Hard float (32-bit CPU, 64-bit FPU)
ISA: MIPS32r2
Flags: 0x70001407, noreorder, pic, cpic, nan2008, o32, mips32r2
```

The same ABI flags as `ui/mq_ui`. Executed under `qemu-mipsel-static`:

```text
hello mips 3.00
exit=0
```

PoC files: `/tmp/opencode/rustpoc/mipsel-diskos.json`, `hello.rs`. QEMU was unpacked from Fedora `qemu-user-static-mips` into `/tmp/opencode/qemu` to avoid a root install.

## Rewrite scope

| Target | Feasibility | Main blocker |
|---|---|---|
| Host installer, Python to Rust | High | Windows WinUSB driver step, GUI packaging |
| On-device Rust sidecar (indexer, art cache, scrobble, network) | High | None material |
| Full UI in Rust + LVGL 9.2.2 | Low to medium | No LVGL 9 Rust binding; custom FFI needed |
| Full UI in Rust without LVGL | Low | Rebuilding a widget toolkit, fonts, themes, animations |
| Rust audio engine replacing `mq_player` | Low to medium | DAC ioctls, MCU protocol, streaming stacks, not Rust |

Findings from research:

- `lvgl` / `lvgl-sys` on crates.io is 0.6.2, published 2023-04-02, vendoring LVGL 8.3.5. No 9.x release.
- The repo's `lvgl-master` branch is also pre-9.0. Its submodule points at a 2023-05-08 commit. Widget coverage is small (arc, bar, keyboard, label, meter).
- `bindgen` cross-compiles to MIPS only with an explicit sysroot. Tested: `clang -target mipsel-unknown-linux-musl --sysroot=/opt/mipsel-n2008-musl-cross/mipsel-linux-musl -E t.c` succeeds; without the sysroot it picks host glibc headers and fails.
- No public example found of Rust + LVGL on MIPS, and none of Rust on X2000/XBurst. HelixScreen (C++, LVGL 9 on Ingenic X2000E, static musl, hard float) is the closest proof that the UI class works on the SoC family, not that Rust bindings work.
- FreeType and SQLite already cross-compile cleanly. Keep them in C behind thin `extern "C"` shims.
- Official caveat: Rust on MIPS inverts signaling NaN bit patterns (rustc book, issue #68925). Low practical impact but worth knowing for animation or DSP math.

Recommended order:

1. One real Rust sidecar binary on device (library indexer or artwork cache).
2. Rust installer CLI that reuses `mksquashfs`, `usbboot`, and the pinned blobs. Port `basegate.py` and its tests first.
3. One Rust full-screen UI process, coordinated through the existing boot selector.
4. Full rewrite only after the first three are boring.

The go/no-go test for a Rust UI is mqueue IPC: `mq_open` / `mq_send` / `mq_receive` against the stock `mq_player`. If that round-trips from Rust, the rest is ordinary work. The framebuffer and evdev steps are next.

## Stock firmware status

Verified present on 2026-11-17:

| What | Path | SHA-256 |
|---|---|---|
| Committed stock NAND image (current gen `g0021`) | `~/.local/share/diskos-installer/stock/g0021/stock.bin` | `e75d85bddb7b9fe304dfe334058693fb522a93cb1048ddfb5417f136f204eae0` |
| Earlier generations, byte-identical | `.../stock/g0019/stock.bin`, `.../stock/g0020/stock.bin` | same |
| Official FiiO V2.57 OTA ZIP | `~/Downloads/SNOWSKY_DISC_update_20260909_v257.zip` | `2bfad000609440bcbf492468e9e5f8f3d5e0bade797323431a15b5755688bfcf` |
| Decrypted stock rootfs | `~/.local/share/diskos-installer/build/stock_rootfs.squashfs` | `111e4dd7ee3d7ff91ba7e61181690be7ffd22bd1bbd13ad513f5f015ffb302ae` |

`stock/current.json` selects `g0021`. `stock.json` records base `v257-r18` / "V2.57 (recovery 18)", image size 100,663,296 bytes, status `committed`. The 80,596,361-byte rootfs hash matches the `.0000.111e4dd7...` chunk name inside the V2.57 ZIP.

The flash note at [[fiio-snowsky-disc-diskos-flash-fedora]] still says `stock/g0001/`. That generation was pruned; the image hash is the same and has rotated to `g0019` through `g0021`.

## Unbrick path

Verified from `flash/my_write6.c`: diskOS writes only mtd2 rootfs, blocks 80 through 848 (768 blocks, 96 MiB). It does not write mtd0 uboot, mtd1 kernel, mtd3 kernel2, mtd4 rootfs2, mtd5 ota, mtd6 mac, or mtd7 userdata. The partition offsets line up with `docs/HARDWARE.md` (2 MB + 8 MB = block 80). `rootfs2` is not an A/B fallback slot, per `agents/AGENTS.md`.

Recovery ladder, safest first:

0. Unknown flash result: leave the Disc powered and connected for at least 25 minutes. Do not retry or disconnect. The writer may still be running.
1. Bad experimental `mq_ui`, OS still boots: hold Volume Up at power-on. `payload/S96diskos_select` XORs the GPIO state with `boot_default_stock`, so Volume Up boots the other UI. If the binary crashes, the `fiio_init.sh` watchdog respawns stock `/usr/bin/mq_ui`. If the binary is not manifest-approved, `payload/S97diskos_install` moves it to `/usr/data/mq_ui.rejected` and stock runs.
2. UI dead, OS alive: use Debug Mode SSH, key-only Dropbear on port 2222, or the USB ACM gadget `0525:a4a7` on `/dev/ttyGS0`. Replace or delete `/usr/data/mq_ui`, then relaunch with `setsid`.
3. Standard reflash: power off, hold Volume Down, connect USB. Screen stays black. Device enumerates as `a108:eaef`. Run `./diskos-installer restore-stock`.
4. No usable saved backup: `./diskos-installer restore-stock --firmware ~/Downloads/SNOWSKY_DISC_update_20260909_v257.zip`. The installer rebuilds stock and checks the device's kernel/recovery base before writing. Never substitute a different firmware version.
5. Mask-ROM will not enumerate: check `udev/70-diskos-maskrom.rules`, remove other Ingenic devices, use a direct data cable, and do a full power-off first (`F204`).
6. Bootloader-level damage: only possible if something other than diskOS wrote mtd0. There is no documented Disc-specific public procedure. Generic X2000 cloner material (ballaswag/ingenic-usbboot, thingino cloner) is not validated for this DRAM and partition layout. Treat as "get help", not "follow a guide".

`ingenic-flash-tool` on PyPI does not list X2000 support. FiiO's own local update requires a booting OS, so it is not a recovery path for a corrupt rootfs.

## What was not verified

- No Rust binary was run on the physical Disc, only under QEMU user emulation.
- Kernel 4.4 compatibility for `getrandom`, `statx`, and other std paths is untested.
- RSS and startup cost of a Rust std binary on the 117.5 MiB device is unmeasured.
- mqueue IPC, framebuffer mmap, evdev MT-B touch, and the LVGL FFI shim were not attempted.
- The recovery procedure is assembled from repo documentation and code constants. It was not executed on hardware during this session.
- Generic Ingenic cloner tools on this exact device are unverified and potentially unsafe.

## Related

- [[fiio-snowsky-disc-diskos-flash-fedora]]
- [[diskos-stock-plus-round-screen-features-and-flash]]
- [[diskos-disc-hotload-watchdog-snowsky-logo-hang]]
- [[ingenic-x2000-swb-reboot-to-usb-boot]]
- [[snowsky-disc-usb-dac-uac2-android-and-firmware-decompile]]
- [[diskos-build-diskos-bin-image-locally]]
