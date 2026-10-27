---
type: troubleshooting
tags: [diskos, snowsky-disc, hot-load, usb-audio, test-outputs, usb-storage, reboot, podman, ssh]
created: 2026-10-27
last_verified: 2026-10-27
status: current
---

# diskOS hot-loading gotchas: missing USB Audio row, "random" reboot, wrong base build

Three surprises from one session of building and hot-loading `mq_ui` onto the Disc. Companion docs: [[diskos-fork-consolidated-into-dev-branch]], [[diskos-persistent-debug-checkboxes]], [[fiio-snowsky-disc-diskos-flash-fedora]].

## 1. "USB Audio mode is gone"

Cause: the USB Audio picker row and the Settings SPDIF toggle exist only in builds made with `-DDISKOS_TEST_OUTPUTS` (`ui/modes.c`: the `MODES[]` entry and `ROW_USB_AUDIO` are `#ifdef`'d). A plain `make` build has no such row. Fix: rebuild with the flag. Changing `EXTRA_CFLAGS` does not rebuild untouched objects, so `make clean` first:

```bash
cd ~/diskos/diskos/ui
podman run --rm --userns=keep-id -v "$PWD:/src:Z" localhost/diskos-ui-builder:latest \
  sh -c 'make clean >/dev/null 2>&1; make -j4 CROSS=$CROSS EXTRA_CFLAGS=-DDISKOS_TEST_OUTPUTS'
strings mq_ui | grep -c 'USB Audio'        # > 0 means the row is compiled in
```

No Docker on this box; the builder image `localhost/diskos-ui-builder` already existed under podman (full rebuild about 35 s, incremental a few seconds).

## 2. "The Disc restarted by itself"

Not a crash. Leaving USB Storage mode ends in `storage_resume_local()` (`ui/main.c`), which toasts "Restarting to reload the card..." and calls `settings_restart_now()`, because `mq_player` keeps a file open on the unmounted card and the next play would hang. Evidence found: `/usr/data/diskos_boot.log` ending with `storage: local mount confirmed; SD readers and artwork cache resumed`, then a second `=== diskos main start`; `uptime` 0 min; no panic/segv/watchdog line in `tail -n 300 /usr/data/fiio/log/fiio_player.log | grep -iE ...` (never grep the whole 59 MB log, see [[diskos-usb-dac-exit-deadlock-roles-and-volume-fix]]). Consequence: the reboot also drops any hot-loaded `mq_ui` (the flashed one returns), so redeploy afterwards.

## 3. Hot-load deploys over key SSH (no Debug Mode password)

`tools/diskos-deploy.sh` wants `DISKOS_IP`/`DISKOS_PW` and password SSH on port 22. The Disc also runs key-only SSH on port 2222 (`Host disc`, 192.168.50.57, see the flash doc), so a scratch copy of the script was used with three edits (`IP=disc`, drop the `SSHPASS` export, `SSH=(ssh -o ConnectTimeout=8)`, `root@$IP` -> `$IP`); the md5 check, swap and the "never kill mq_player" logic are unchanged:

```bash
sed -e 's|^IP=.*|IP=disc|' -e 's|^export SSHPASS=.*||' -e 's|^SSH=(.*|SSH=(ssh -o ConnectTimeout=8)|' \
    -e 's|root@\$IP|$IP|g' tools/diskos-deploy.sh > /tmp/deploy-key.sh
bash /tmp/deploy-key.sh ui/mq_ui            # ">> deployed OK: /usr/data/mq_ui running; mq_player alive"
ssh disc 'md5sum /usr/data/mq_ui'           # must equal md5sum ui/mq_ui
```

## 4. The wrong-base trap

Hot-loading a build from the wrong branch silently replaces the flashed UI. The flashed `mq_ui` was `stock-plus-disco` (device md5 `8a107281...`, `/usr/data/mq_ui` dated 2026-10-22 20:23); builds from `fix/usb-dac-workmode` lacked the Oct 22 fixes (slide-hairline `3d9d2a3`, USB DAC volume and ordered exit, round glass, power off, command guard, mailbox port). Before deploying, check what the device runs and what you built from:

```bash
ssh disc 'md5sum /usr/data/mq_ui; ls -l /usr/data/mq_ui /usr/data/mq_ui.fork-backup'
git -C ~/diskos/diskos branch --show-current && git -C ~/diskos/diskos log --oneline -3
```

Resolution and the single-branch rule: [[diskos-fork-consolidated-into-dev-branch]].

## 5. Theme change in USB Audio mode: music paused, then USB Audio and the song restart

Symptom (user): on the USB Audio route, changing the theme pauses the player; pressing play then restarts USB Audio and the song. A theme change re-execs the UI (`ui_theme_reload`, `main.c`), keeping the player running. Three separate causes, found by reading `diskos_boot.log`, `fiio_player.log` and the code:

```bash
ssh disc 'tail -40 /usr/data/diskos_boot.log'                       # "diskos main start argc=2" (the relaunch), "boot: paused the player's resume autoplay", NO "theme reload: kept route"
ssh disc 'tail -n 600 /usr/data/fiio/log/fiio_player.log | grep -E "PAUSE|START|set out device|USB_HOST|NO_WORK_MODE"'
#   [PAUSE] ... 2 s later "set out device USB_HOST!" + "[audio_track_stop] NO_WORK_MODE" + new "[START]"  = the UI re-sent 0666 3 before the play
```

1. **The route was never kept.** The adoption of `DISKOS_RELOAD_ROUTE/SRC` sat in the main loop's `ipc_take_reconnected()` branch. That flag (`ipc.c`: `g_reconnected = 1`) is set only when `/ui` is re-attached after a player restart, and `ipc_generation()` only moves then too; a plain relaunch has generation 0 and never gets the event. So the new UI believed the route was internal. (Commit `270c7b4` had this untested; it said so.)
2. **Saved-preference restore re-ran the switch.** `modes_output_boot_restore` -> `bootusb_tick` (`modes.c`) re-selects USB Audio 15 s after any UI start when `usb_audio_on=1` and the route is not USB: pause, `0666 3`, `0642 5`: the player closes and reopens its output and restarts the song. With the route adopted the tick sees `OUT_USB` and stops.
3. **Autoplay pause ran again.** `boot_autoplay_pause_cb` ("Resume Playback: keep the restored song, paused", pauses if playing and no transport command was sent yet) is meant for cold boot but also ran in the relaunched process.

Fix (dev, `ui/main.c`): adopt route and source mode at startup (log `theme reload: kept route 2, source mode 0 (gen 0)`), and skip the autoplay-pause timer when `DISKOS_THEME_RELOAD` is set. Tested on the Disc without touching the screen by emulating the relaunch:

```bash
ssh disc 'killall -9 mq_ui; DISKOS_THEME_RELOAD=1 DISKOS_RELOAD_ROUTE=2 DISKOS_RELOAD_SRC=0 setsid /usr/data/mq_ui home </dev/null >/usr/data/diskos_boot.log 2>&1 &'
# after 30 s: log has "kept route 2", no "paused the player's resume autoplay", no "Restoring USB Audio";
# the player log has no "set out device USB_HOST" or output re-init after the relaunch
```

Not fixed (pre-existing, same frames as before the refactor): tapping a song while paused or stopped sends the local-play preamble (`outseq_local_preamble`: `0666 3`, `0642 5`, `0657 8` on the USB route) because the UI treats "not playing" as "stopped", which re-initialises the USB output and restarts that song. Not tested with a real theme change on the screen.

## Not diagnosed

"No sound on USB DAC mode" was reported while running the wrong-base build; the frames sent for that mode were identical to the pre-refactor code (checked by diff), and the user's next message turned out to be about the USB Audio row. After moving to `dev` it was not re-tested, so whether the missing Oct 22 USB DAC volume fix explains it is unknown.
