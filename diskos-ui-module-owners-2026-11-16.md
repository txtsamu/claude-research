---
type: build-log
tags: [diskos, ui, architecture, refactor, c, lvgl, host-tests]
created: 2026-11-16
last_verified: 2026-11-16
status: current
---

# diskOS UI: six concepts, one owner each

Repo `txtsamu/diskos`, branch `main`, base commit `027c24b`, work `45b04f4..9014389`.

The request was the six candidates from an architecture review of the player UI: finish the Working Mode switch, collapse the screen registry, extract Restart and Flash mode, replace the 30-field Player struct with a view, move the Now Playing fan-out, and delete the shallow playstate module.

## What changed

- **Play request owns the position advance.** `playstate.c`, `playstate.h` and `playstate_test.c` are gone. `playreq.c` keeps the same rule (`g_pos`, 1600 ms grace, forward advance only). The `playreq_test` suite still passes.
- **Working Mode switch reports one status.** `srcswitch_status()` returns phase, from/to, landed mode and failure reason. `modes.c` renders it and lost its 500 ms settle timer, the 3.2 s guess and the `ui_detect_source_mode()` call. `srcswitch` now does the settle and the sysfs check through a new `detected_mode` env callback. Three new `srcswitch_test` cases cover land, mismatch and overlay rows.
- **Restart has a module.** `restart.c/h` owns quiesce, reader stop, clock save, SD drain, `sync`, flash arming and reboot behind `restart_env`. `settings.c` keeps only the modal and the table row. Flash arming (`/dev/mem`, `0x10000000 + 0xCC`) moved out of the UI file. New `restart_test` covers drain timeout, sync failure, sync timeout, flash failure, abort and success.
- **Player state is a view plus evidence.** `ipc.h` exposes `player_view_t` and `player_evidence_t`; `ipc_get_view()` / `ipc_get_now()` copy under the IPC mutex; `track_state_t` is private to `ipc.c`. Raw ids, validity flags, tokens and sequence numbers no longer leak to screens. Four dead exports removed (`ipc_player_mode`, `ipc_seed_state`, `ipc_send_cmd_unsafe`, `ipc_send_quiet`).
- **Screens have one registry.** `screenmgr.c` has one `SCREENS[]` table (create, refresh, visible, figure); `screens_init` and `transition` iterate it. `screens.h` dropped from 275 lines / 260 declarations to 108 / 94; screen-owned declarations moved to `screens_ui.h` (163), included by 19 modules. Twenty modules now see only the shared interface.
- **Now Playing has a publisher.** `nowplay.c/h` owns the change rules (sequence, playing, path, title, artist) and the sink fan-out. `main.c` lost `last`, `last_playing`, `np_last_path`, `np_last_title` and `np_last_artist`, and the 29-line inline fan-out. New `nowplay_test` has eight cases.

Docs added: `docs/UI_ARCHITECTURE.md`, plus GLOSSARY terms **Player view**, **Switch status**, **Restart** and **Flash mode**.

An independent read-only review of the six commits found three defects, all fixed in `ec10a22`:

- `theme_kits.c` was missed by my first syntax sweep (it was filtered out with the theme generated files) and lacked `screens_ui.h`; it now includes it and the sweep covers all 102 UI sources.
- The restart confirmation modal stayed on `lv_layer_top()` after a failed restart; `restart_poll_cb` now closes it when the transaction ends.
- `env_restart_kill` killed only the child leader and blocked the LVGL thread for up to 2 s; it now kills the process group and polls 30 x 10 ms, matching the old `kill_and_reap`.

Two coverage notes from the review were also closed: `playreq_test` has the near-wrap position case again, and `nowplay_test` exercises `nowplay_invalidate()` without `force`.

## Gain after a mode switch

The owner reported that Gain fell back to Low after a Working Mode switch. The Player re-initialises the internal
CS43131 DAC on the way back to Local, and only the USB Audio exit path re-sent Gain, DRE and DAC Filter. A switch
through USB DAC or Bluetooth Receiving therefore left the Player on its default Gain. A second problem: the re-send
used `cfg_get_int("audio_gain", 0)`, so an unset key actively forced Low over a Gain the user had set on the Player.

Fix in `98108bb`:

- `srcswitch_send_source()` arms a 2 s `reapply_audio` after any successful Local, USB DAC or Bluetooth Receiving
  sequence. The adapter in `main.c` sends Gain, DRE and DAC Filter only when diskOS has stored a value; an absent key
  leaves the Player alone. The same helper now backs the USB Audio reapply.
- The Local sequence is unchanged and explicit: `0666 6` internal analog, `0642 0` no gadget, `0657 8` Local Player
  work mode, so the Disc's own CS43131 is selected.
- `ui_set_gain` now logs the frame and high/low, and the Local path logs `mode: local playback on the internal DAC`.
- `srcswitch_test` covers the reapply after a direct switch and after returning to Local.

## mipsel toolchain

The pinned musl-cross-make toolchain was missing. It was built on the Fedora host at commit
`227df8b99103f9c59f6570babf892978e293082f` with `ui/toolchain/mcm-config.mak`, installed to
`/opt/mipsel-n2008-musl-cross`, and pinned for this checkout in the ignored `ui/config.mk`. `make -C ui -j32` now
links `mq_ui` for MIPS32r2/FP64/NaN2008 with GCC 11.2.0 and musl 1.2.6.

## Flash result

The latest UI (`ui/mq_ui`, md5 `30c46d1b27cc35eedc8f6c07c0f00008`) was flashed on 2026-11-16 from the V2.57 stock
zip. Start 16:32:15, finish 16:52:15, about 20 minutes as estimated. `usbboot` exit 0, `result: 0x600DF10C [F001]
SUCCESS`, `flash verified OK`. NAND scan found two bad blocks (128, 522); the writer skipped them, capacity 768 blocks
for a 768-block image, no retries. Backup generation `g0020` was committed. The device needs a power-cycle to boot and
install diskOS from `/opt/diskos` on first boot.

`agents/AGENTS.md` now requires a flash request to state the estimated wall-clock finish time before starting and to
repeat the actual time in the result.

## Verification

Host tests:

```
$ make -C ui/tests run
...
./coverart_pipeline_test
PASS (0 failures)
C_EXIT=0

$ make -C ui/tests run-py
...
Ran 5 tests in 0.122s
OK
PY_EXIT=0
```

New test binaries ran inside `run`: `restart_test: ok`, `nowplay_test: ok`, and `srcswitch_test: ok` with the status and audio-reapply cases. The full UI also links:

```
$ make -C ui -j32
artifact: mq_ui
size: 4347300
cc: mipsel-linux-musl-gcc (GCC) 11.2.0
BUILD_EXIT=0

$ file ui/mq_ui
ELF 32-bit LSB executable, MIPS, MIPS32 rel2 version 1 (SYSV), statically linked, stripped
```

UI sources cannot be linked here: `ui/Makefile` needs `mipsel-linux-musl-gcc`, which is not installed. Every application source was instead checked with host gcc in syntax-only mode against the vendored LVGL and FreeType headers, with implicit declarations treated as errors:

```
$ for f in ...; do gcc -fsyntax-only -std=gnu11 -D_GNU_SOURCE \
    -DLV_CONF_INCLUDE_SIMPLE -Werror=implicit-function-declaration \
    -I. -Ithird_party/freetype-2.13.3/include $f; done
SYNTAX_BAD=0
```

`git diff --check 027c24b..HEAD` is clean.

## Gotchas

- The screen registry changes create order from the old hand-written list (weather/lyrics used to be created early, apps/nphub late). Roots are independent and the shown root is moved to the foreground, so z-order is the only visible difference. Not exercised on device here.
- `screens_ui.h` must be included by any module that calls a screen-owned create/open/setter. The compiler finds missing includes only with `-Werror=implicit-function-declaration`; a plain build warns and links.
- `restart_abort()` exists because `lv_timer_create` can fail after `restart_begin` has quiesced the card; the old code refused up front with a child-slot count. The abort kills the clock, unquiesces and toasts.
- The `a607` frame branch in `ipc.c` only fed the dead `ipc_player_mode()`; it is gone. No live consumer read it.
- `comments.md` kept the historical `main.c` entries that mention `playstate_t`; the current-owner prose now points at the play request.

## Not verified

- LVGL rendering, screen transition animations, the on-device flash-mode path and the acoustic Gain result. The mipsel link now passes; the gain fix needs the owner's ear on the Disc.
- The mode-switch status against a real Player: the host test fakes `detected_mode`.

Related: [[diskos-session-and-play-admission-modules-parallel-agents]], [[diskos-shuffle-index-loop-fix-2026-11-16]], [[diskos-hotload-gotchas-test-outputs-usb-storage-reboot]].
