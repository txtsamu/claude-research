---
type: investigation
tags: [diskos, snowsky-disc, ultrareview, code-review, ipc, installer, chargemode, session, subagents, worktree]
created: 2026-10-29
last_verified: 2026-10-29
status: current
---

# diskOS: ultrareview of dev -> main, and the first three fixes

Repo `/home/moo/diskos/diskos`. `/ultrareview` (cloud, free run 1 of 3) was launched for `dev` -> `main` after the session/play-admission merges ([[diskos-session-and-play-admission-modules-parallel-agents]]) and the USB DAC app ([[diskos-usb-dac-app-stream-rate-pcm-dsd-volume]]). Scope reported: 92 files, +5156/-1716, i.e. all of `dev` against `main`, so most findings are about older fork work, not that day's changes. Findings are claims from a reviewer: each agent below read the code before acting.

## Provenance check

Nothing from the day's refactors touched `ui/ipc.c`, `payload/` or `diskos_installer/` (`git diff --stat ae5292f HEAD` for those paths was empty). For the findings near files that were changed (local-init marking, `src_mode` saving, the autoplay pause), the same logic is already in `ae5292f`. So none of the ten is a regression from that day; all are in earlier dev work.

## The ten findings

Fixed in this round (3):

1. **Windows installer cannot build images.** `diskos_installer/imagebuild.py:1278` calls `bundle.data("S98diskos_sshkey")` (required) for every variant, but the file was in none of the packaging inventories, so a frozen build (PyInstaller spec bundles exactly `build/verify_git_blobs.py PAYLOAD`) would raise `PreflightError` E102. **Right.** Fix: add it to `build/verify_git_blobs.py` (`PAYLOAD`), `build/stage-release.sh` (`REQ_PAYLOAD`), `tests/test_windows_release_inventory.py` (`PAYLOAD`, compared as an exact set) and the `doctor` check in `diskos_installer/__main__.py`. Branch `worktree-agent-a66c5e47381cfd6ee`, commit `eb6e097`. Not reproduced with a real frozen/Windows build.
2. **Dead /player queue after a player restart.** The old sender closed `g_tx` after EAGAIN ran out (the "H1" case); the new ordered outbound line kept the fd, so after the stock player unlinks and recreates `/player` every frame queued behind the stuck head frame until `ipc_health_check` (30 s tick) noticed. **Right.** Fix in `ui/ipc.c`: a per-frame stall clock `s0`; `tx_stall_reopen()` true after `TX_REOPEN_MS` 2000; in `tx_drain_locked`, when the head frame is stuck on EAGAIN that long, close `g_tx`, retry the same frame at once (`tx_open` reopens the current `/player`), restart the stall clock. 2 s is far above the brief wait and normal drain, well below the 6 s hold (so the frame still gets its retry) and the 30 s health tick. New host test `ui/tests/ipc_tx_test.c` (extracts the sender from `ipc.c` with sed, fake `mq_open/mq_send/mq_close`): ordered delivery on the new queue, no reopen under 2 s, one reopen per window on a busy queue, hold expiry still fails, ENOENT waits; it fails (10 FAIL lines) with the reopen disabled. The close is under `g_txmu` like the existing closes. Commit `3f68945`. The comment at `main.c` ~2254 ("self-healed on the next real send") is still stale.
3. **Charging overlay after a theme change.** `chargemode_boot()` ran once per mq_ui process; a theme change re-execs the UI, so on a wall charger the "Charging / Tap to continue" overlay returned, and pulling the charger within about 3 s powered the Disc off. **Right** (the review's other two `execv` lines are not relaunches: one hands off to the stock UI, one is an argv fix-up before `session_init`). Fix: `session_chargemode_boot_allowed()` in `ui/session.c` (true only for `SESSION_COLD_BOOT`), used at the `main.c` call site; `chargemode_tick()` still runs. Two new `session_test` scenarios. A crash respawn, a hot-load or a real power-on cannot be told apart (no handoff env), so those still show the overlay. Commit `0729330`.

Merged into `dev` as three `--no-ff` merges (no conflicts): `826cd93`, `ce99102`, `e042fef`.

Not fixed yet (7):

4. **Key-only root SSH on port 2222 is invisible to Debug Mode, on every image variant** (`payload/S98diskos_sshkey`; `diskos-debug.sh` `ssh_running`/`ssh_off` match only `dropbearmulti`, the key daemon runs as `dropbear`). Debug Mode shows SSH off and Disable leaves it running. **Owner's decision**: install it for dev images only / opt-in, or make Debug Mode see and stop it. Not touched.
5. **Held frames count as sent.** `ipc_send_raw` returns 0 for a frame only held in the line (and it may be dropped after `TX_HOLD_MS`); callers that read 0 as delivered lose their retry: `session_local_init_send` (marks the generation initialised), the sleep timer (disarms), `out_switch`. Needs a distinct "held" result or a completion callback. (Sites: `ui/session.c`, `ui/main.c`, `ui/modes.c`.)
6. **Leaving USB Storage never saves the picked mode** and `storage_resume_local()` then restarts, so the boot restore replays the stale `src_mode`.
7. **USB DAC unplugged while routed to it:** `usbgone_tick` deletes its watcher once `out_switch(OUT_INTERNAL)` is merely accepted; if the async switch later aborts the route stays on a silent USB_HOST_NULL sink.
8. **Autoplay pause** (`boot_autoplay_pause_cb`) pauses ANY playback in the first 60 s after a cold boot unless the UI sent a transport frame, including a play started with a headset or hardware key.
9. **Ordered USB DAC exit:** the picker's `settle_cb` judges the switch after 3.2 s, but the exit takes 17-30 s, so it toasts "Mode didn't switch" and never refreshes.
10. **Theme relaunch guard** `modes_output_busy()` ignores `g_dacx` (ordered exit, up to 30 s) and `g_leave`, so a theme change in that window execs away the continuation and hands off a half-left source mode.

## How it was run

Three `general-purpose` agents in parallel, each in its own worktree (`isolation: "worktree"`), told to `git reset --hard dev` first (a worktree agent starts from `main`) and to confirm `8167365`. `git reset --hard dev` inside a worktree only moves that worktree's own branch; it never touches `dev`. Each prompt said: treat the review text as a claim and read the code first, no Disc access, no push, stay in your own files, no attribution lines. Reports were checked against the branches (merge-base, diff, tests re-run) before merging.

## Verification on the merged tree

```bash
cd ui/tests && rtk proxy make run CC=clang > out.txt 2>&1     # rc=0; config 7/7, playstate 0 failures, ipc_guard, ipc_tx ok, outseq 18, session (20 scenarios), playadmit 36+384, dacinfo, timekeep, tama
for t in transport boot_select boot_probe launcher outseq_guard; do CC=clang python3 -I ${t}_test.py; done    # all pass
cd ../../tests && PYTHONPATH=/home/moo/diskos/diskos python3 -m unittest test_windows_release_inventory test_git_blobs test_stage_release   # 44 tests OK, 8 skipped
cd ../ui && podman run --rm --userns=keep-id -v "$PWD:/src:Z" localhost/diskos-ui-builder:latest sh -c 'make -j4 CROSS=$CROSS EXTRA_CFLAGS=-DDISKOS_TEST_OUTPUTS'   # mq_ui built; only old warnings
```

Gotchas: the installer tests need the repo root on the import path (`python3 -I` drops it; plain `python3 -m unittest` from `tests/` lacks it too: use `PYTHONPATH`); `test_windows_cli` has one pre-existing error (missing `RECOVERY.txt` in a staging test); the RTK wrapper refused some `git add`/`commit` calls inside agent worktrees (use `/usr/bin/git`) and hides merge commits from `git log`.

## Not verified

Hot-loaded onto the Disc 2026-10-29 15:13 with `~/diskos/diskos-hotload.sh ui/mq_ui` (md5 `77661757...`, `ok=1 attempts=1`, no new `process_failed.txt` entry). The Disc had rebooted a minute earlier (which drops any hot-load), so the script was run only after `uptime` >= 45 s and `reached main loop` appeared in `diskos_boot.log`. Seen afterwards: Local mode, a track playing, Now Playing drawn correctly (screenshot `merged-build-running.png`), 0 `ipc: /player full ... reopening` lines (expected: no player restart happened). A hot-load lasts until the next reboot; the flashed build is still the old one.

Still NOT exercised on the Disc: the charging-overlay fix (needs a wall charger plus a theme change) and the dead-queue reopen (needs a real player restart; look for `ipc: /player full for ...ms, reopening` in `/usr/data/diskos_boot.log`). No frozen Windows build was run. `dev` was pushed to `origin/dev` (`e042fef`), `main` untouched; `dev` has no upstream configured (`git push -u origin dev` would set it).

## References

None external: the ultrareview output was the source; every claim was checked against the repo.
