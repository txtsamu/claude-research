---
type: how-to
tags: [diskos, snowsky-disc, architecture, refactor, session, playadmit, outseq, subagents, worktree, host-tests, podman]
created: 2026-10-29
last_verified: 2026-10-29
status: current
---

# diskOS: "Player-state session" and "play admission" modules, built by two parallel agents

Repo `/home/moo/diskos/diskos`, branch `dev` (base `ae5292f`). Follows [[diskos-ui-architecture-review-output-sequencer-design]] (the `outseq` work) and the startup/relaunch bugs in [[diskos-hotload-gotchas-test-outputs-usb-storage-reboot]] sections 5 and 6. Terms are the repo's `GLOSSARY.md` (Player, Source mode, Output route, Player work mode, Output sequence) plus the module/interface/seam/depth vocabulary of the `improve-codebase-architecture` skill.

**Status: merged into `dev` and host-tested; NOT run on the Disc.** No flash, no hot-load. Do that before trusting it (section "What still needs the Disc").

## How the candidates were found

`/improve-codebase-architecture`, scoped to `ui/` (the recent commits cluster in `main.c`, `modes.c`, `screenmgr.c`, `theme_kits.c`, `apps.c`). A read-only Explore agent walked the code; its claims were spot-checked with grep before use (the duplicated gate at `main.c:1657` and `:1720`; `g_source_mode` writes in `main.c`; `radio_on_poll_cb`/`sw_cb` defined in both `wifi.c` and `bt.c`; 13 `lv_timer_create` in `bt.c`). Four candidates came out; the first two were done:

1. **Player-state session** (Strong): "what the Player is on" lived in four places (`modes.c g_route`, seven `main.c` globals, cfg keys `src_mode`/`usb_audio_on`/`spdif`, env vars `DISKOS_RELOAD_ROUTE`/`_SRC`/`DISKOS_THEME_RELOAD`) and five paths re-derived it at startup (`bootusb_tick` 15 s, `localplayer_workmode_cb` 500 ms, `bt_boot_restore`, `boot_autoplay_pause_cb`, `startup_route_reconcile`).
2. **Play admission** (Strong): `outseq.c` was deep, but every play-start caller copied the gate `fw_needs_localplayer_init() && source==0 && !g_route_mac[0] && !g_playing && !play_recent()`.
3. Source-mode switch out of `main.c`, 4. one radio-intent module for Wi-Fi and Bluetooth: not done. The report (HTML, scratchpad) also noted `main.c` has 235 functions and about 172 globals, and that three Python tests read `main.c` as text.

## How the work was run

Two `general-purpose` agents in parallel, each with `isolation: "worktree"`. A worktree agent starts from `main`, not `dev`, so each prompt began with `git reset --hard dev` and a check that `git log --oneline -1` was `ae5292f`. Each prompt also said: no `ssh disc`, no hot-load, no push, stay out of the other agent's functions (candidate 2's module takes the route and source mode as a parameter struct, so it never reads `main.c` globals). Merge-base of both branches was checked to be `ae5292f` before merging.

## What was built

**Candidate 1, `ui/session.c` + `session.h` (no LVGL), branch `worktree-agent-a16492c9e4b0801d1`, 6 commits `bb86b43..b29d600`.** Owns the Output route, the Source mode and the entry path. Interface: `session_route/_set_route`, `session_source_mode/_set_source_mode`, `session_init/_entry/_adopt(gen)/_handoff_export/_handoff_cancel`, `session_autoplay_pause_allowed`, `session_restore_arm/_poll`, `session_startup_route_pending/_settled`, `session_local_init_allowed/_done/_mark/_send(gen)`, `session_saved_source/_saved_usb_audio/_save_*`. The `DISKOS_*` env var names and format are unchanged. Moved out of `main.c`: `g_source_mode`, `g_adopted_gen`, `g_startup_route_checked`, the local-init `done_gen`, the env set/unset in `ui_theme_reload` and the adoption block. Moved out of `modes.c`: the route state and the `bootusb_tick` decision. Kept in `main.c` on purpose: the Bluetooth route (`g_route_mac`, `route_state_*`), `startup_route_reconcile`, the settle logic in `localplayer_workmode_cb`, the 60 s window of `boot_autoplay_pause_cb`. Seams: `ipc_send_cmd` (through `outseq`), `ipc_generation`, `cfg_*`, time passed in as an argument.

**Candidate 2, `ui/playadmit.c` + `playadmit.h`, branch `worktree-agent-ad787ead86b347a59`, commits `0dcadbc`, `f277448`.** `playadmit_start(kind, &situation)` with `kind` = `PLAYADMIT_LIST` or `PLAYADMIT_RESERVED_SLOT`, and a six-int situation struct (`fw_needs_local_init, source_mode, bt_route, output_route, playing, play_recent`). It returns `NONE`, `WORKMODE` or `PREAMBLE`. In `main.c`, `play_situation()` and `play_admit(kind)` are now the only places that read the accessors for play starts. `ui_play_list_ex` and `ui_queue_jump` use `LIST`; `ui_play_playlist`, `ui_play_plan` (type 5) and `ui_play_book` use `RESERVED_SLOT`. `outseq_guard_test.py` gained a check that `outseq_local_preamble` and `outseq_assert_workmode` are called only from `outseq.c` and `playadmit.c`.

## Merge

```bash
cd /home/moo/diskos/diskos            # on dev, clean apart from untracked .claude/
git merge --no-ff -m "Merge Player-state session module (candidate 1)" worktree-agent-a16492c9e4b0801d1   # clean
git merge --no-ff -m "Merge play admission module (candidate 2)"       worktree-agent-ad787ead86b347a59   # 3 conflicts
```

All three conflicts were both-sides-added lines and kept both: `ui/main.c` (`#include "session.h"` plus `"playadmit.h"`), `ui/Makefile` (`APP_SRCS`: `... $(APP)/session.c $(APP)/playadmit.c ...`), `ui/tests/Makefile` (`session_test` and `playadmit_test` rules, the `run:` dependency list and body, `clean:`). Then `git add` the three files and `git commit --no-edit`. Check: `git merge-base --is-ancestor <branch> HEAD` for both branches. (The `git` wrapper on this box hides merge commits from `git log`, so `git log` looked like the merge had not happened; `git cat-file -p HEAD` shows the two parents.)

## Verification that was actually run on the merged tree

```bash
cd ui && podman run --rm --userns=keep-id -v "$PWD:/src:Z" localhost/diskos-ui-builder:latest \
  sh -c 'make clean >/dev/null 2>&1; make -j4 CROSS=$CROSS EXTRA_CFLAGS=-DDISKOS_TEST_OUTPUTS'
strings mq_ui | grep -c 'USB Audio'      # 3
# warnings only in files neither agent touched; none in session.c, playadmit.c, modes.c (touch the three, rebuild, grep)
cd tests && make run CC=clang            # config 7/7, playstate 0 failures, ipc_guard ok, outseq 18 + bt sink, session 18 scenarios,
                                         # playadmit 36 named + 384 cross-product, timekeep ok, tama ok
for t in transport boot_select boot_probe launcher outseq_guard; do CC=clang python3 -I ${t}_test.py; done   # all pass
```

- **Sanitizers:** the Python tests hard-code `-fsanitize=address,undefined`, and this box's gcc has no libasan, so every one of them errors with plain `cc`. Use `CC=clang` (host clang has the runtimes). Also `python3 -I -m unittest <name>` cannot import test modules (`-I` drops the current directory from the path): run `python3 -I <name>.py` or `unittest discover -s .`.
- **Failing before and after (checked on a detached `ae5292f` worktree, same errors):** `storage_test.py` (20 compile errors, e.g. undeclared `outseq_rc` and `glob_t`: it slices `main.c`, and the outseq refactor made the slice need symbols the test does not stub, so it has not covered that code since), `font_coverage_test.py` (undeclared `ui_font_cjk`), `rmguard_test.py` (looks for `../installer/payload/diskos-rmguard`, which only exists in another repo layout). Candidate 1 added two `session_source_mode` stubs to `storage_test.py`, but the test still cannot run, so that edit is unexercised.

## Not done, and why

- **Paused-song bug (step 2 of candidate 2):** tapping a song while paused re-sends the USB preamble (`0666 3`, `0642 5`, `0657 8`), which re-initialises the USB output and restarts the song. Not fixed: `playstate_playing()` is a bool, so paused equals stopped. Skipping the preamble would also skip it for an idle Player that has drifted its route (`ipc_seed_state` sets `have_track=1` at boot, and `ipc.c` clears the track only on an empty-song frame; no stop frame was ever captured), which would bring back the roughly 15 s Bluetooth-PCM hang the preamble prevents. Needs a captured Player stop/pause frame or a reliable state field; recorded in the `playing` comment of `playadmit.h`.
- **Behaviour changes:** none intended. Candidate 2's cross-product test checks every combination against the old gate expressions kept verbatim as oracles.

## Bugs candidate 1 noticed and left alone (it was told to preserve behaviour)

1. A relaunch from the default state (Local, internal DAC) is not adopted, so the 15 s boot restore stays armed. With `usb_audio_on=1` left over from a DAC-missing fallback, a theme change would re-run "Restoring USB Audio" and restart the output.
2. A relaunch adopted on USB Audio with a stale `src_mode=1` passes the restore guards and would switch to USB DAC at 15 s. One-line fix: skip `session_restore_arm` when `session_entry()` is `SESSION_RELAUNCH`.
3. `modes_create` clears cfg `spdif` on first build, which can disagree with a live SPDIF route.

## What still needs the Disc

Build from `dev` only (see [[diskos-fork-consolidated-into-dev-branch]]), then hot-load or flash and check: a theme change on USB Audio keeps the route and sends no frames (log line `theme reload: kept route ...`), a cold boot with `usb_audio_on=1` restores exactly once, Persistent debug still brings Wi-Fi and SSH back, play start from stopped on internal, SPDIF and USB routes still sends the same frames (`fiio_player.log`), Working Mode picker and USB Storage return unchanged.

## References

None external: all from the repo, the existing claude-research notes and the `improve-codebase-architecture` / `codebase-design` skills.
