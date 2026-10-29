---
type: how-to
tags: [diskos, snowsky-disc, architecture, refactor, srcswitch, source-mode, usb-storage, usb-dac, host-tests, podman, hot-load]
created: 2026-10-29
last_verified: 2026-10-29
status: current
---

# diskOS: source-mode switch (candidate 3) moved out of `main.c` into `ui/srcswitch.c`

Repo `/home/moo/diskos/diskos`, branch `dev`, commit `6369094` (pushed to `origin/dev`; `main` untouched). Candidate 3 of the architecture review ([[diskos-session-and-play-admission-modules-parallel-agents]] lists candidates 1 and 2; candidate 4 is the radio module in [[diskos-parallel-wave-keyssh-restore-switchflow-radio-icon-backbutton]]). Done in one session, inline (one sequential refactor, no parallel agents).

**Status: host-tested (all green), built with the pinned mipsel toolchain, hot-loaded on the Disc and it starts and adopts a running USB DAC. NOT yet exercised: a USB Storage round trip and a USB DAC exit with a computer attached (section "Still needs the Disc").**

## What moved and how it is wired

`main.c` 4176 -> 3893 lines. `ui/srcswitch.c` (356 lines) + `srcswitch.h` own: the SD handoff phase machine and its crash-safe marker (`/tmp/.diskos_sd_export_intent`, phases D/E/H/R), the SD admission gate (`g_sd_writable`, `g_sd_writers`, `g_sd_hold`, `g_launch_verdict`, quiesce), `storage_media_local`, the ordered USB DAC exit (`0642 0` first, wait for the `uac_demo` gadget to go, +1.5 s, then the real switch), the volume carry, and `ui_set_source_mode` with its transition table.

- No LVGL. Everything touching the system comes in through `struct srcswitch_env` (15 hooks: `now`, `media_mounted`, `exported_to_host`, `host_confirmed`, `host_attached`, `dac_gadget_present`, `player_guarded`, `playing`, `scan_active`, `scan_if_library_empty`, `art_cancel`, `card_returned`, `restart`, `toast`, `set_volume`). `main.c` keeps the sysfs readers (`coldplug_mounted`, `sd_exported_to_host`, `storage_host_confirmed`, `usb_host_attached`, `storage_player_guarded`) and passes them in: that is the "sdio and gadget sysfs paths" seam from the review.
- Three LVGL timers (storage tick, DAC-exit poll, one-shot volume carry) became one `srcswitch_tick()` on the existing 100 ms timer (`srcswitch_tick_cb` in `main.c`).
- Names other files use are unchanged (`ui_set_source_mode`, `ui_source_switch_pending/failed`, `ui_dac_exit_pending`, `ui_local_playback_allowed`, `sd_write_begin/end`, `ui_sd_quiesce_*`); `screens.h` now `#include`s `srcswitch.h` instead of declaring them.
- New accessors for what `main.c` still touches: `srcswitch_set_launch_verdict`, `srcswitch_hold/_held`, `srcswitch_revoke` (verdict 0 + hold + writable 0 + `sd_io_hold` + phase UNKNOWN, called from `sd_features_gate_cb` before `scanner_abort`/`art_kill_all`), `srcswitch_restart_deadline`, `srcswitch_sd_writable`, `srcswitch_mode_mutex` (the coldplug thread's mount lock), `srcswitch_dac_level_settled`.
- One behaviour difference: two switches into USB DAC within 4.5 s now leave one pending volume set, not two.
- Deleted the dead `usb_host_configured()` (the only `-Wunused-function` warning in `main.c`; the old `storage_test.py` even carried `-Wno-unused-function` for it).

## Steps, in order

1. Baseline first: `make -C ui/tests run CC=clang` and the eight Python tests (`CC=clang python3 -I ui/tests/<name>_test.py`) were all green on `dev` (the three that failed last week were already repaired).
2. Extracted mechanically so nothing is retyped: `sed -n '626,969p' main.c` into a scratch file, deleted the ranges that stay in `main.c` (`storage_player_guarded`, `usb_host_*`, the `settings_restart_now` prototype), then scripted the substitutions (`lv_tick_get()` -> `now_ms()`, `ui_toast(` -> `E->toast(`, `g_playing` -> `E->playing()`, ...). Python `assert s.count(old) == 1` on every replacement so a missed or double match fails loudly.
3. Host syntax check without the device toolchain: `clang -std=gnu11 -D_GNU_SOURCE -DLV_CONF_INCLUDE_SIMPLE -I. -I.. -Ithird_party/freetype-2.13.3/include -Wall -Wextra -fsyntax-only main.c srcswitch.c modes.c bt.c settings.c power.c` (found one real error: `settings_restart_now` used before its prototype).
4. `tests/storage_test.py` rewritten: instead of slicing `main.c` between anchors it defines the env table and `#include "srcswitch.c"` in the test TU (white-box on purpose: some cases set the phase the way a UI restart leaves it). `session_*` and `modes_*` are non-static stubs because `srcswitch.c` includes their headers. `SD_EXPORT_MARKER` is `#ifndef`-guarded so the test points it at a temp dir. The old stub of `storage_media_local` is gone: the test now exercises the real predicate, including the launch-verdict gate (that stub being stale is what once let a pending-verdict gap pass review). The 11 old cases pass unchanged; 5 new ones: leaving USB DAC waits for the gadget then switches; a gadget that never goes away ends the exit (30 s) without switching; the Local volume is carried once after 4.5 s; no carry if USB DAC is left earlier; the restart after a USB Storage return fires once.
5. `ui/Makefile` `APP_SRCS` gets `$(APP)/srcswitch.c`.
6. Device build (the `diskos-ui-builder` image already exists under podman; no Docker here):
   ```
   cd ~/diskos/diskos/ui && podman run --rm --userns=keep-id -v "$PWD:/src:Z" localhost/diskos-ui-builder:latest
   ```
   Dead ends: the README's `docker run ... -u $(id -u):$(id -g) -v $PWD:/src` prints "mount the ui/ source at /src" under rootless podman on Fedora; adding only `:z` then fails with `Fatal error: can't create /src/main.o: Permission denied`; `--userns=keep-id` is what makes the `.o` files writable. Result: `ui/mq_ui` 4301272 bytes, md5 `2dca1f6a351183a9303b298d5691abdd`, GCC 11.2.0 musl. Default flags, so no USB Audio/SPDIF rows (those need `-DDISKOS_TEST_OUTPUTS`). Careful when grepping the build log: the link line is one enormous line; filter with `cut -c1-200`.
7. Hot-load, per [[diskos-disc-hotload-watchdog-snowsky-logo-hang]]: precheck `ssh disc 'cat /proc/uptime; grep -c "reached main loop" /usr/data/diskos_boot.log'` (up 2088 s, 8 boots in the log), then `~/diskos/diskos-hotload.sh ui/mq_ui` -> `ok=1 attempts=1`, `mq_player` pid unchanged, no new line in `/usr/data/fiio/log/process_failed.txt`. Boot log of the new process: `startup: Player already in USB DAC mode - adopted, no restore (gen 0)` then `reached main loop`.

## Still needs the Disc

- USB Storage round trip: switch to USB Storage, see the computer mount it, switch back; the UI must restart itself (`storage_resume_local` -> `settings_restart_now`), the picked Working Mode must survive, and `/tmp/.diskos_sd_export_intent` must be gone afterwards.
- USB DAC exit with a computer attached: expect `usb dac: leaving with a host attached: 0642 0 first, then mode N`, then `gadget gone, continuing the switch` within ~17-30 s, no `usb dac: exit timed out`.
- USB DAC volume carry after a switch into USB DAC (`usb dac: volume -> N` about 4.5 s after the switch).
- Unchanged and still open: the paused-song bug (play admission only records why a paused Player gets the preamble). `modes.c` and `bt.c` still call `ui_route_bt` / `ui_player_settling` in `main.c`; only the source-switch half of the `modes.c <-> main.c` loop is gone.
