---
type: how-to
tags: [diskos, snowsky-disc, plan, roadmap, review-findings, hot-load, flash, release]
created: 2026-10-29
last_verified: 2026-10-29
status: current
---

# diskOS dev: actionable plan from 2026-10-29

State at writing: `dev` = `e042fef` (pushed to `origin/dev`; `main` untouched at `4cd4a60`). The merged build (session + play admission modules, USB DAC app, round Apps icons, three review fixes) was hot-loaded on the Disc at 15:13; a hot-load lasts until the next reboot, and the Disc has already rebooted once today. Context: [[diskos-ultrareview-dev-to-main-findings-and-first-fixes]], [[diskos-usb-dac-app-stream-rate-pcm-dsd-volume]], [[diskos-session-and-play-admission-modules-parallel-agents]], [[diskos-fork-consolidated-into-dev-branch]].

Working rules that apply to every step: build only from `dev`; hot-load with `~/diskos/diskos-hotload.sh ui/mq_ui` (never the generic deploy script: it does not freeze the `fiio_init.sh` watchdog), only after `uptime` >= 45 s and `reached main loop` in `/usr/data/diskos_boot.log`; tests with `CC=clang`; worktree agents start with `git reset --hard dev`; push `main` only after a flash you are happy with.

## Status at the end of the day (2026-10-29, `dev` = `454b0f7`, pushed)

Done and merged: 0.1 key-SSH awareness; step 2 (adopt a running USB DAC at startup); 3.2 (Storage return saves the pick); 3.3 (unplug fallback retries); 3.4 (autoplay pause gate, corrected so that an UNSET Resume Playback still pauses); 3.5 and 3.6 (settle and theme-reload guard share one predicate); the three broken Python tests; the radio module (candidate 4); the speaker icon (drawn, not a font glyph); the Now Playing back button. Details: [[diskos-parallel-wave-keyssh-restore-switchflow-radio-icon-backbutton]]. Hot-loaded and screenshot-checked: Now Playing back, Apps circles and speaker, Debug Mode key-SSH line.

Still open: everything in section 1 (hardware checks) plus the Key SSH checkbox and the radio toggles on the Disc; 3.1 (held frames) next, then the source-mode extraction (both were held back because they collide with the merged code); section 4 (paused-song capture); section 5 (flash, second `/ultrareview`, then `main`); the older `feat-*` branches are merged into `dev` but their folders under `~/diskos/` were left for you to remove.

## 0. In progress

| # | Task | State | Done when |
|---|------|-------|-----------|
| 0.1 | Debug Mode aware of the key-only SSH on port 2222 (show state in both ON/OFF views, runtime stop/start, truthful `status`, `ssh-off` must not touch it) | agent running in a worktree | merged into `dev`; hot-loaded; screenshot of the Debug Mode screen in each state; stopping and starting works and the UI does not hang |

## 1. Verify on the Disc (needs you and hardware)

| # | Task | First action | Done when |
|---|------|--------------|-----------|
| 1.1 | Charging overlay fix | plug a wall charger, change the theme | no "Charging / Tap to continue" overlay after the relaunch; unplugging does not power off |
| 1.2 | Reconnect after a player restart | restart the player (kill `mq_player`; the watchdog respawns it) while playing, then press play | controls respond within about 2 s; `grep reopening /usr/data/diskos_boot.log` shows the reopen |
| 1.3 | DSD in the USB DAC app | play a DSD file from the computer; `grep "UAC_FORMAT value" /usr/data/fiio/log/fiio_player.log` | the real DSD spelling and rate are known; the parser (prefix `DSD`) and the page match it |
| 1.4 | Other themes | screenshot Apps and USB DAC pages in each theme (`~/diskos/snowsky-shot.sh`) | circles stay round, nothing clipped |

## 2. Fix the USB DAC restart blip (affects every hot-load in that mode)

A fresh `mq_ui` starts with source mode Local while `src_mode=1` is saved, so the cold-boot restore re-sends the USB DAC switch and the host's stream drops for a few seconds. First action: in `ui/main.c` startup, read the real gadget state (`ui_detect_source_mode()`) before `session_restore_arm`, adopt it into the session, and skip the restore when the Player is already there; add scenarios to `ui/tests/session_test.c` ("start while already in USB DAC sends no frames"). Done when a hot-load while a computer is streaming produces no new `UAC_SRATE=0` and no new `usb dac: volume ->` line in the logs. Also covers the relaunch edge cases candidate 1 listed: a relaunch with a stale `usb_audio_on=1` / `src_mode=1`.

## 3. Review findings still open (one worktree agent each, then merge and verify as before)

| # | Finding | Where | First action |
|---|---------|-------|--------------|
| 3.1 | Held frames count as sent: `ipc_send_raw` returns 0 for a frame only held in the line | `ui/ipc.c`; callers `ui/session.c` (local-init), `ui/main.c` (sleep timer), `ui/modes.c` (`out_switch`) | give `ipc_send_raw` a distinct "held" result or a completion callback; callers that retry on failure keep retrying |
| 3.2 | Leaving USB Storage does not save the picked mode and the restart replays the stale `src_mode` | `ui/main.c` `storage_resume_local`, `session_save_source` | save the pick before the restart; test in `session_test` |
| 3.3 | USB DAC unplugged: `usbgone_tick` stops watching once the switch is merely accepted | `ui/modes.c` | keep the watcher until the route reads internal |
| 3.4 | Boot autoplay pause pauses any play in the first 60 s (headset / hardware key) | `ui/main.c` `boot_autoplay_pause_cb`, `session_autoplay_pause_allowed` | only pause the player's own resume autoplay (tie to Resume Playback / the first play state) |
| 3.5 | "Mode didn't switch" toast during the 17-30 s ordered USB DAC exit | `ui/modes.c` `settle_cb`, `ui/main.c` `dac_exit_begin` | make settle wait for `g_dacx` and refresh the picker when the exit lands |
| 3.6 | Theme relaunch guard ignores `g_dacx` and `g_leave` | `ui/modes.c` `modes_output_busy`, `ui/main.c` `ui_theme_reload` | one "source switch in flight" accessor used by 3.5 and 3.6 (do them together) |

Suggested grouping: {3.5, 3.6} together, {3.2, 3.3, 3.4} together (all `modes.c`/`main.c` switch flow), 3.1 alone (touches the `ipc.c` interface). Stale comment to fix with 3.1: `main.c` ~2254 ("self-healed on the next real send").

## 4. Needs a capture session

Paused-song bug: tapping a song while paused re-sends the USB preamble and restarts the song. First action: with the Disc playing, capture the Player-to-UI frames (`a1`, `a2`, `a714` ...) around a pause and a stop to find a reliable paused marker; then do step 2 of the play admission module (`ui/playadmit.h` records what signal is needed). Done when paused on the USB route does not restart the song and an idle drifted Player still gets its preamble.

## 5. Release path (after 1-3 are as you want)

1. Flash the `dev` build (recipe in [[fiio-snowsky-disc-diskos-flash-fedora]]); check the checklist in 1 against the flashed build, not the hot-load.
2. Run `/ultrareview` again on `dev` -> `main` (2 of 3 free runs left); fix what is real.
3. Only then: merge `dev` into `main` and push `main`.

## 6. Later / optional

- Architecture candidates not done: pull the source-mode switch (SD handoff, DAC exit, persisted choice) out of `main.c` (builds on the session module); one radio-intent module for Wi-Fi and Bluetooth (`wifi.c`/`bt.c`).
- A real speaker glyph for the USB DAC tile: regenerate the 28 px icon font with one more `--range` (it currently uses U+F178, an arrow).
- Make key SSH opt-in per image variant (installed for dev images only) if you later decide to; currently it ships everywhere and Debug Mode will show it (0.1).

## 7. Housekeeping

- 20 git worktrees, 9 `worktree-agent-*` branches and the older `feat-*` / `disco-with-fixes` / `stock-plus-disco` branches: check which are merged into `dev` (`git merge-base --is-ancestor <branch> dev`), then remove merged worktrees and delete merged branches.
- `git push -u origin dev` to set the upstream; add `.claude/` to `.gitignore` (or the local exclude) so it stops showing as untracked.
- Three Python tests fail on `dev` before any of this work: `ui/tests/storage_test.py` (stale slice of `main.c`: undeclared `outseq_rc`, `glob_t`), `font_coverage_test.py` (undeclared `ui_font_cjk`), `rmguard_test.py` (looks for `../installer/payload/diskos-rmguard`). Repair or retire them.
- `/ultrareview` free runs used: 1 of 3.
