---
type: how-to
tags: [diskos, snowsky-disc, working-mode, srcswitch, usb-dac, bluetooth-receiving, usb-storage, usb-debug, usb-audio, source-switch]
created: 2026-11-11
last_verified: 2026-11-11
status: current
---

# diskOS: switching between non-Local Working Modes goes through Local Playback by itself

Repo `/home/moo/diskos/diskos`, branch `dev`, merge commit `c964e99` (agent commit `29075c4` on `feat/auto-via-local`, base `b70e821`). Not pushed, not flashed; hot-loaded and tried by the user on a Disc. Related: [[diskos-srcswitch-source-mode-switch-extraction]], [[diskos-usb-debug-source-menu-serial-no-ethernet-2026-11-10]], [[diskos-usb-audio-volume-keys-double-click-and-hold-2026-11-11]], [[diskos-hotload-gotchas-test-outputs-usb-storage-reboot]]. In the repo: `comments.md` ("Working Mode transitions" table), `docs/TOUR.md`.

**Request:** "when I switch between working mode I need to switch to Local Playback first, do it automatically." The user confirmed all four of these failed: USB DAC to Bluetooth or USB Storage; Bluetooth Receiving to anything; USB Storage to anything; the USB Audio row from a non-Local mode. Later they added: USB Debug then USB Audio. After the last hot-load the user said "it works now".

## What was wrong

`ui/srcswitch.c` `source_switch` only hopped through Local (`via_local`) for two cases (route already USB Audio, or source 1 to 3) and for USB Debug. Everything else sent the source change straight to the Player, or hit `admit_check(ADMIT_OUTPUT_SWITCH)` which answers `Return to local playback first` whenever the source is not Local (the USB Audio row, `outroute_pick`).

## What changed

- `needs_local(mode)`: true when the target is not Local, not the current mode, and the current source is DAC (1) or Bluetooth (2) or the route is USB Audio. Those go through `via_local` (Local, wait at least 3 s, then the target). Toasts: `Leaving USB DAC...`, `Leaving Bluetooth Receiving...`, then `Switching to <mode>`.
- The USB Audio row is now `SRCSWITCH_MODE_USB_AUDIO` (5) in `ui_set_source_mode`, so `modes.c` lost its special case and shares the pending/settle path. It goes via Local first, and only then `outroute_pick(OUT_USB)`.
- USB Storage (`sd_host_owned()`) to anything: `storage_leave(mode)` writes a one-shot config key `src_pending` (1 DAC, 2 BT, 4 USB Debug, 5 USB Audio) and calls `sd_return_begin(0)`. Storage always returns to Local first and the UI restarts (existing behaviour). The new process reads and clears the key in `modes_output_boot_restore` (`srcswitch_init` runs before `cfg_load`, so it cannot read it earlier). A 500 ms timer enters the target once 15 s have passed, `ipc_is_ready()` is true, nothing else is switching and the source is Local; it gives up after 120 s with `Couldn't continue the mode switch - pick it again`. Known limit: a UI restart for another reason inside the 15 s window loses the target.
- `leave_tick` no longer gives up or continues while `sd_switch_pending()`, an output switch, a DAC exit or a USB Debug stop is in progress (the 10 s abandon still fires otherwise).
- `source_switch` refuses with `Switching...` while a hop or pending target is waiting.
- Local to X, X to Local and USB Audio route to Local were left alone.

## How it was done

The agent worked in its own worktree, `git worktree add -b feat/auto-via-local ../diskos-autolocal dev` (the Agent tool's `isolation: "worktree"` failed because the session's primary directory was not a git repo, so the worktree was made by hand and the agent was told to work only there). Verification: `srcswitch_test` went from 41 to 64 scenarios (every case above, including a simulated restart for storage), `cd ui/tests && CC=clang make run && CC=clang make run-py` all pass, cross-build ok, then I read the diff, merged both branches into `dev` and re-ran tests and the build on the merged tree.

```bash
cd /home/moo/diskos/diskos && git merge --ff-only feat/maxvol-buttons
git merge --no-edit -m "Merge feat/auto-via-local: ..." feat/auto-via-local
cd ui/tests && CC=clang make run && CC=clang make run-py
cd .. && podman run --rm --userns=keep-id -v "$PWD:/src:Z" localhost/diskos-ui-builder:latest sh -c 'make CROSS=$CROSS EXTRA_CFLAGS=-DDISKOS_TEST_OUTPUTS'
flock /tmp/diskos-disc.lock ~/diskos/diskos-hotload.sh ui/mq_ui
```

## Not verified

- USB Storage to another mode (with the restart and the 15 s pending timer) was not run on a Disc; only host-simulated. The user confirmed the USB Debug to USB Audio case, not each of the others one by one.
- The case where the Player is still settling after the hop to Local (`admit_settling`, nine seconds) can refuse the final `outroute_pick`; the code then drops the target instead of retrying. Not seen on the Disc.

## Time estimate

| Step | Time |
|---|---|
| Agent: code, 23 new tests, docs, commit | about 10 min (measured: 608 s) |
| My review of the diff, merge, tests and cross-build on the merged tree | about 4 min |
| Hot-load | about 10 s |

## References

No external sources were used.
