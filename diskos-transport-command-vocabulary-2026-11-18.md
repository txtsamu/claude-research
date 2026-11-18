---
type: build-log
tags: [diskos, ui, transport, refactor, c, host-tests]
created: 2026-11-18
last_verified: 2026-11-18
status: current
---

# diskOS UI: transport commands get a named vocabulary

Repo `txtsamu/diskos`, branch `arch/transport` (worktree `~/.local/share/opencode/worktree/c6e21f/arch-transport`), base `e6bc3da`, work `a5f5ce2` (local only, not pushed). Parallel agents held the card/storage, settings-sender and idle-machine branches; this one touched none of their files.

The request: the three transport frames (play/pause, next, previous) were known by raw hex in six places - `ui/ipc.h:62` defined only `PLAYER_CMD_PLAYPAUSE "0201000C0000"`, `ui/usbhid.c:22-23` privately redefined `CMD_NEXT`/`CMD_PREVIOUS`, `ui/transport.c:30-32` classified by `strcmp` against the literals inside `ui_transport_command`, and `ui/ui.c:1446-1448` + `ui/quicksettings.c:280-282` passed frame strings through LVGL button user data so the classification could recognise them later. Give the commands a named identity with zero behavior change: the frames sent to the Player must stay byte-identical in every path.

## Time estimate

About 55 minutes end to end (measured from worktree start to the green `make check`). Reading the six call sites, ADRs 0001/0002, the guard test and comments.md conventions took roughly half of it; the edits themselves are small; the full host suite (`make run` then `make check`) takes about 1.5 minutes per pass on this workstation, and I ran the pair three times (after the edits, after comments.md, before the commit).

## What changed

- **`ui/transport.h` owns the vocabulary.** New `ui_transport_cmd_t`: `UI_TRANSPORT_NONE = 0`, `UI_TRANSPORT_PLAYPAUSE`, `UI_TRANSPORT_NEXT`, `UI_TRANSPORT_PREV` (values 1..3 coincide with the click counts and the wire suffixes, but nothing depends on that - both mappings are explicit switches). `ui_transport_command` takes the named command. `ui_transport_click_command(int clicks)` is a static inline in the header mapping 1/2/3 to play-pause/next/previous and everything else to NONE - inline so `clicks_test` can pin the gesture rule without linking `transport.c`'s ~20 process fakes (the `ipc.h:54` `ipc_display_title` inline is the header-inline precedent).
- **`ui/transport.c` maps names to frames.** A private `transport_frame()` switch returns `PLAYER_CMD_PLAYPAUSE` (still `ipc.h`'s single spelling) for the toggle and the two next/prev literals, which now live in this one function and nowhere else in the UI sources. The old `strcmp` classification, `if(!cmd)`, and `is_next/is_prev` flags became `frame == NULL`, `cmd == UI_TRANSPORT_PLAYPAUSE`, and one `cmd == UI_TRANSPORT_NEXT` comparison in the book-seek branch. `<string.h>` left with the `strcmp`s (`<stddef.h>` came in for `NULL`).
- **Callers name commands.** `ui/ui.c:434` `transport_cb` and `:485` `make_clickable` carry the enum through LVGL user data via `(intptr_t` casts - the exact idiom `quicksettings.c` already uses for tile ids (`:140`, `:224`); `ui.c:1446-1448` pass `UI_TRANSPORT_PREV/PLAYPAUSE/NEXT`. `ui/quicksettings.c:255` `cmd_cb` guards with `if(!c)` (NONE is 0, same truthiness as the old NULL check) and `build_transport` passes the names. `ui/usbhid.c` dropped its two private defines; `send_clicks` goes through `ui_transport_click_command`, and `KEY_NEXTSONG`/`KEY_PREVIOUSSONG` name `UI_TRANSPORT_NEXT/PREV`. `ui/home.c:240` sends the named toggle.
- **`ui_transport_action` stays in `theme_kit.c`** but now switches on the enum instead of `strcmp`ing hex. It did not move into `transport.c`: it calls `lv_snprintf`, and `transport.c`/`transport.h` is the deliberate No-LVGL seam module (comments.md, `ui/transport.h` banner). Moving it would force a hand-written `lv_snprintf` prototype in `transport.h` that must exactly match LVGL's, or a behavior-risky switch to stdio `snprintf`. `theme_kit.h` includes `transport.h` for the type.
- **`ui_seek_to` stayed in `admit.c`** (the secondary cleanup was offered "only if it stays mechanical"). It is entangled: `tests/admit_test.c:188-197` tests it directly against the real admission rules and `admit_test` links only `admit.c` plus bootstate/outroute/outseq/session/playreq (`tests/Makefile:37-38`) - moving the function to `transport.c` would break that link, and pulling `transport.c` into `admit_test` drags in the whole UI/scanner/SD stub set. `tests/transport_test.c:34` also fakes `ui_seek_to` to observe seeks, so the move would rewrite two test harnesses, not just callers. Grep found the other callers: `ui/books.c:205`, `ui/ui.c:401`, `ui/transport.c:42`, and three `main.c` env-table references (`.seek_to` at `main.c:463/581/939`); `screens.h:80` is a second, duplicate declaration (screens.h already includes transport.h).
- **Tests cover the mapping.** `tests/transport_test.c` fakes now capture the frame: every command call uses the name, and assertions pin the exact bytes - `PLAYER_CMD_PLAYPAUSE` straight from `ipc.h`, `"0201000C0001"`, `"0201000C0002"` - plus the `UI_TRANSPORT_NONE` refusal (`== -1`, nothing sent). All existing assertions survive with the same meaning (hint reconciliation, no optimistic success on IPC failure, no commands during USB ownership, bounded book seeks, scan admission). `tests/clicks_test.c` gained `test_click_command`: 0 -> NONE, 1 -> PLAYPAUSE, 2 -> NEXT, 3 -> PREV, `CLICKS_MAX` is the third click, past the cap is no command. `clicks.c` itself is untouched. The `clicks_test` build rule gained `../transport.h` as a prerequisite; nothing else in `tests/Makefile` changed.
- **The guard tightened itself.** `tests/outseq_guard_test.py:40` exempted `theme_kit.c` from the "play/pause spelled once" check only because `ui_transport_action` used to hold the literal. With the enum mapping that reason is gone, so the exemption is removed - `0201000C0000` now lives in `ipc.h` alone among `ui/*.ch` (the checked-in MIPS binary `payload/mq_ui` still embeds all three frames as data; it was not rebuilt or touched).
- **comments.md** updated for every meaningfully changed file: new entries at `transport_frame`, the `transport.h` vocabulary and click mapping, `usbhid.c` `send_clicks`, `ui.c` `make_clickable`, `quicksettings.c` `build_transport`, `theme_kit.c` `ui_transport_action`, the `transport_test` frame capture, a new `ui/tests/clicks_test.c` section, and the rewritten outseq-guard note; index counts and a new clicks_test row added.

## Usage grep before moving anything

`PLAYER_CMD_PLAYPAUSE`: definition `ui/ipc.h:62`; transport classification `ui/transport.c:32`; callers `ui/usbhid.c:76`, `ui/ui.c:1447`, `ui/quicksettings.c:281`, `ui/home.c:240`; unrelated raw `ipc_send_cmd` users that keep it `ui/main.c:716,930`, `ui/outroute.c:226,376,402,406`, `ui/sdio.c:258`, `ui/srcswitch.c:317,323`; tests `tests/transport_test.c`, `tests/sdio_test.c:22`, `tests/outroute_test.c:21`, `tests/admit_test.c:53`, and `tests/outseq_guard_test.py:45-46` (which asserts the define stays in `ipc.h` - it does).

`"0201000C0001"`: `ui/usbhid.c:22`, `ui/ui.c:1448`, `ui/quicksettings.c:282`, `ui/transport.c:30`, `ui/theme_kit.c:78`, `tests/transport_test.c`. `"0201000C0002"`: same set at `ui/usbhid.c:23`, `ui/ui.c:1446`, `ui/quicksettings.c:280`, `ui/transport.c:31`, `ui/theme_kit.c:77`, `tests/transport_test.c:67`. Plus the binary `payload/mq_ui`. After the change, `grep "0201000C000[012]" ui/*.c ui/*.h` matches exactly two files: `ui/ipc.h:62` and `ui/transport.c:29-30`.

## Verification

Host gates from `ui/tests`, both required before the commit:

```text
$ make run   (exit 0)
--- transport ---
./transport_test
PASS instant feedback, rapid repeated taps, reconciliation and tick wrap
PASS no optimistic success on IPC failure and no commands during USB ownership
PASS bounded book seeks, failed seek preserves resume, successful music skip clears it
PASS honest scan admission, busy/error feedback and the started toast
--- clicks ---
./clicks_test
PASS (0 failures)
--- coverart ---
./coverart_test
PASS (0 failures)
./coverart_pipeline_test
PASS (0 failures)

$ make check   (exit 0)
--- outseq_guard (python) ---
.....
----------------------------------------------------------------------
Ran 5 tests in 0.057s

OK
--- rmguard (python) ---
.....
----------------------------------------------------------------------
Ran 5 tests in 0.127s

OK
```

The six device-side files are not host-built, so each got a host `cc -fsyntax-only -std=gnu11 -D_GNU_SOURCE -DLV_CONF_INCLUDE_SIMPLE -I. -Wall -Wextra` pass (`ui.c`, `quicksettings.c`, `theme_kit.c`, `home.c`, `usbhid.c`, `transport.c`), plus a sweep over the wider `theme_kit.h` includers since `theme_kit.h` now pulls in `transport.h` (`apps.c`, `books.c`, `bt.c`, `chargemode.c`, `controls.c`, `library.c`, `settings.c`, `saver.c`, `theme_kits.c`, `theme_validate.c`, `theme_store.c`, `main.c`, `modes.c`): zero errors. The only warning seen (`ui.c:1745` misleading-indentation) is pre-existing untouched code and only appears because the sweep adds `-Wextra`, which the device Makefile does not use.

Identity audit, path by path: toggle sends `PLAYER_CMD_PLAYPAUSE` bytes from `ipc.h` either way; next/prev send the same two literals, previously spelled at the call sites and now spelled once in `transport_frame`; `usbhid` log lines unchanged (`"play/pause"`, `"next (double click)"`, `"previous (triple click)"`, `"next"`, `"previous"`); `ui_transport_action` labels unchanged (`pp`/`next`/`prev`/`cmd`); the book-seek branch clamps exactly as before; NULL/garbage refusal became NONE -> `transport_frame` returns NULL -> -1.

## Gotchas

- The enum starts at 1 on purpose: a NULL LVGL user data casts to 0 = `UI_TRANSPORT_NONE`, preserving the old `if(!cmd) return -1` / `if(!c) return` behavior at the transport_cb and cmd_cb boundaries. Making PLAYPAUSE 0 would have turned missing user data into a play/pause.
- `ui/tests/transport_test.c` had a local `int sent = commands;` counter, so the new capture buffer is named `sent_frame` to avoid shadowing it.
- The podman mipsel cross-build is deliberately not run on refactor branches, so the device link is verified by the host syntax sweep only.

## Not verified

- The mipsel link and on-device behavior: no cross-build, no device touch (by instruction). The checked-in `payload/mq_ui` binary is now one refactor behind `ui/`; whoever next builds for a flash should expect `src_md5` to change.
- LVGL click wiring (`transport_cb`, `cmd_cb`, `tp_btn`) is compile-verified only; the host tests cannot drive LVGL event delivery.

## References

None - every finding above came from reading the repo tree (`agents/AGENTS.md`, `GLOSSARY.md` "Click gestures", `docs/adr/0001`/`0002`, `comments.md` sections for the files touched). No web sources contributed.

Related: [[diskos-ui-module-owners-2026-11-16]], [[diskos-session-and-play-admission-modules-parallel-agents]], [[diskos-usb-audio-volume-keys-double-click-and-hold-2026-11-11]], [[diskos-sd-clean-unmount-and-fsdetect-2026-11-17]].
