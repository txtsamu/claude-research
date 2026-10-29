---
type: how-to
tags: [diskos, snowsky-disc, subagents, worktree, debug-mode, key-ssh, session, radio, nowplaying, hot-load, tinj, screenshots]
created: 2026-10-29
last_verified: 2026-10-29
status: current
---

# diskOS: seven parallel agents (Debug key SSH, restore, switch flow, radio, icon, tests, Now Playing back button)

Follows [[diskos-dev-next-steps-plan-2026-10-29]] and [[diskos-ultrareview-dev-to-main-findings-and-first-fixes]]. `dev` went from `e042fef` to `454b0f7`, pushed to `origin/dev`; `main` untouched at `4cd4a60`. The combined build (`mq_ui` md5 `dcf27e0e...`, About row "1.2.1 (dcf27e0e)") was hot-loaded on the Disc and checked by screenshot.

## What was run

Seven `general-purpose` agents in parallel, each `isolation: "worktree"` and told to `git reset --hard dev` first (a worktree agent starts from `main`) and confirm the commit. Common rules in every brief: no Disc access, no push or merge, no attribution lines, stay inside your own files (the groups were chosen so that `main.c`/`modes.c`/`session.c` edits were in distinct functions), tests with `CC=clang`, do not edit CHANGELOG/docs (except the Debug agent), report merge-base and `git diff --stat`. Not done in parallel on purpose: held-frame return values (`ipc_send_raw`, read by the restore and switch-flow code) and pulling the source-mode switch out of `main.c` (collides with both); both wait for this wave to be merged.

| Agent | Result | Branch tip |
|---|---|---|
| Debug Mode key SSH | `diskos-debug.sh key-off` (reverse of `key-on`, idempotent), truthful `status`, Debug screen shows and toggles "Key SSH :2222" | `a659fc9` |
| Startup restore | adopt a running USB DAC at startup (no re-switch), save the pick when leaving USB Storage, gate the boot autoplay pause | `afcafae` |
| USB DAC switch flow | picker settle waits for the ordered exit, theme-reload guard shares one "switch in flight" predicate, unplug fallback retries (3 tries) | `c9a9648` |
| Radio module | `radio.c/.h`: shared bring-up watch, one off teardown per radio, used by `wifi.c` and `bt.c` | `52d3c90` |
| Test repair | `storage_test`, `font_coverage_test`, `rmguard_test` fixed (test files only) | `4ab3d1f` |
| Speaker icon | no `lv_font_conv` on the box, so the USB DAC tile draws a speaker with LVGL primitives | `0fa8ce6` |
| Now Playing back button | `<` chevron built through the shared header code, per-theme placement | `4f42d55` |

Merged one at a time with `/usr/bin/git merge --no-ff` (the RTK `git` wrapper hides merge commits from `git log` and refuses some worktree commands). Only one conflict: `ui/tests/Makefile` (the Debug and radio agents each added a test rule, run dependency, run body and clean entry: keep both). After each merge the Python tests and the host suite were re-run.

## Things the review of the reports caught (read the diff, do not trust the report)

1. **Boot autoplay pause treated an unset Resume Playback as Off.** `main.c` sends `0684` to the Player only when cfg `memory_play` is set (`mp >= 0`); with it unset the Player keeps its own setting. On this Disc `memory_play` is absent from `diskos.conf` and the boot log still shows `boot: paused the player's resume autoplay`, so the Player does autoplay at boot. "Unset = Off" would have stopped the pause and made the Disc start playing at every boot. Fix (commit `dcadf1d`): `session_autoplay_pause_allowed()` is true for a cold boot when the value is not an explicit 0; call it with `cfg_get_int("memory_play", -1)`; test updated (unset keeps the pause, explicit 0 skips it, 2 keeps it).
2. **`storage_test` broke after the switch-flow merge**: the test compiles a slice of `main.c`, which now calls `modes_dac_exit_done`, a symbol the harness did not define. Added the stub in `ui/tests/storage_test.py` (commit `875800c`). Expect this whenever `main.c` gains a call into another module.
3. **My own test marker was wrong**, not the test: `keyssh_test` prints `keyssh_test ok`, I had searched for `keyssh_test: ok`.
4. Device facts the Debug agent could only assume were checked read-only over key SSH: busybox has `awk`, `pgrep`, `umount`; `/proc/net/tcp6` does NOT exist (the new `key_up` skips missing files); the new listener check finds the daemon on 2222; `pgrep -f "/usr/data/sshd/dropbear -s"` matches the daemon and the per-connection children (so `key-off` from a key-SSH session ends that session).
5. Radio module: unguarded `lv_timer_del(g_radio_timer)` in the new disarm is safe only if nothing else clears the timer; checked every use of the radio, scanwait and bootrestore timers in `wifi.c`/`bt.c`: all go through arm/disarm.

## Verification on the final `dev` (all run by me)

```bash
cd ui/tests && rtk proxy make run CC=clang > out.txt 2>&1     # rc=0, 0 FAIL: config 7/7, playstate, ipc_guard, ipc_tx, outseq 18, session 27 scenarios, playadmit 36+384, dacinfo, keyssh, radio, timekeep, tama
for t in transport boot_select boot_probe launcher outseq_guard storage font_coverage rmguard; do CC=clang python3 -I ${t}_test.py; done   # all 8 PASS (3 of them failed on dev before today)
cd ../../tests && PYTHONPATH=/home/moo/diskos/diskos python3 -m unittest test_windows_release_inventory test_git_blobs test_stage_release   # 44 OK, 8 skipped
cd ../ui && podman run --rm --userns=keep-id -v "$PWD:/src:Z" localhost/diskos-ui-builder:latest sh -c 'make clean >/dev/null 2>&1; make -j4 CROSS=$CROSS EXTRA_CFLAGS=-DDISKOS_TEST_OUTPUTS'   # mq_ui 4300676 bytes, only old warnings
~/diskos/diskos-hotload.sh ui/mq_ui                            # ok=1 attempts=1, no new process_failed.txt entry
```

## Driving the Disc's screen over key SSH (how the screenshots were taken)

`/usr/data/tinj` is on the device: `ssh disc '/usr/data/tinj tap X Y'` and `'/usr/data/tinj swipe X1 Y1 X2 Y2'` (screen coordinates 0..359, upright, as in `~/diskos/snowsky-shot.sh` screenshots; no password needed over key SSH). Pull-down from the top edge is `swipe 180 4 180 220`. Lists keep scrolling for about a second after a swipe, so wait 2 s before the screenshot or you capture a mid-scroll frame (the first Debug Mode search was thrown off by this). Right after a hot-load the framebuffer still shows the OLD UI's last frame for a moment (an Apps page with clipped circles was the old process, not a bug): wait about 8 s. Screenshots are in `~/sessions/2026-10-29-diskos-dac-app/shots/` (`final-*.png`); the Debug Mode one shows the current temporary SSH password, so do not publish it.

Seen on the real panel (Terminal theme): Now Playing has the `<` chevron at the left edge and tapping it at (14,179) returned Home (log `TAP x=14 y=179`); the Apps page shows three complete circles with the drawn speaker for USB DAC; the Debug Mode screen shows "Key SSH :2222  ON (keys only)" with its checkbox and the line "Disable does not stop it. Back at boot." above the Disable button, fitting inside the glass (tight under the two-line red warning); System > About shows the build id.

## Not verified

- The Key SSH checkbox itself (stopping it from a key-SSH session ends the connection used to drive the screen; try it by hand, the checkbox turns it back on).
- The charging-overlay and dead-queue fixes (need a charger and a real player restart), Wi-Fi and Bluetooth toggles after the radio refactor (list: Wi-Fi on/off from the screen and the quick tile, Bluetooth on/off including off mid bring-up, reboot with `bt_on` on and off), the other themes, the Now Playing back button placement in the ring themes (only the ring-hidden Terminal theme was seen), a hot-load while in Bluetooth Receiving (not gadget-visible, so the restore can still re-send the switch), and a hot-load while in USB DAC mode with a computer streaming (the adopt logic reads the gadget at startup; not exercised in this session).
- DSD wording, a frozen Windows build.

## Next (still open from the plan)

Held-frame return values (`ipc_send_raw`), then the source-mode switch extraction from `main.c`; the paused-song capture; flash and a second `/ultrareview` before touching `main`. Worktrees of the finished agents were removed (all merged); older `feat-*` branches (merged into `dev`, with working folders under `~/diskos/`) were left alone.
