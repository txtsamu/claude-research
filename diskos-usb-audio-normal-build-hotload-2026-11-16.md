---
type: build-log
tags: [diskos, snowsky-disc, fiio, usb-audio, usb-dac, external-dac, uac, hotload, mipsel, lvgl, working-mode, screenshot]
created: 2026-11-16
last_verified: 2026-11-16
status: current
---

# diskOS: USB Audio (external USB DAC) hot-loaded as a normal build row

Request: "can we implement that feature to our build? i think its the same USB Audio feature because it makes my device use external USB DAC output", then "hot load latest fix to my device".

Repo `/home/moo/diskos/diskos`, branch `main`, commit `3726ebc` ("USB Audio: show the external DAC row in the normal build"), working tree clean. Binary `ui/mq_ui`, md5 `ceb84837af9264fde610f279646b1952`, size 4,349,816, built with `mipsel-linux-musl-gcc (GCC) 11.2.0` from `/opt/mipsel-n2008-musl-cross`.

## What changed in the source

The external DAC output already existed behind `-DDISKOS_TEST_OUTPUTS` (`OUT_USB` in `outroute.c`/`outseq.c`, the `SRCSWITCH_MODE_USB_AUDIO` picker row in `modes.c`). `3726ebc` makes it the normal build:

- `ui/modes.c`: the USB Audio row is compiled unconditionally. It is hidden with `LV_OBJ_FLAG_HIDDEN` and refused with a toast ("USB Audio needs firmware 2.40 or 2.57") when `fw_has_usb_audio()` is false.
- `ui/fwcaps.c` / `ui/fwcaps.h`: new `fw_has_usb_audio()`, true for `fw_os_ver()` 240 and 257, the same gate as `fw_needs_direct_sd_mount()`.
- The local (git-ignored) `ui/config.mk` no longer passes `-DDISKOS_TEST_OUTPUTS`, so a plain `make` yields the normal build. The Settings SPDIF Output row stays test-only.
- `docs/TOUR.md`, `CHANGELOG.md`, `agents/AGENTS.md`, `comments.md` updated to match.

Design note: the row keeps the existing output-route implementation (`outroute` + `outseq`, `OUT_USB`), not upstream PR #16's source-mode-4 design. That PR (`IniGisah:feat/v1.2-usb-dac-output`) is still open and CONFLICTING on `b0hemia/diskos`; `zmd22/diskos-disco` 3.6.1 exposes the same capability but only under its Zune theme and installs over stock V2.57.

## Hot-load

The Disc was unreachable for a while (`192.168.50.29:2222` "No route to host", nmap found no `2222` on `192.168.50.0/24`, no `a108:eaef` on USB). It came back on Wi-Fi at 17:41.

```
$ date '+%H:%M:%S'; bash /tmp/opencode/deploy-key.sh ui/mq_ui; date '+%H:%M:%S'
17:41:16
>> local mq_ui md5=ceb84837af9264fde610f279646b1952 -> disc
>> deployed OK: /usr/data/mq_ui running; mq_player alive
DEPLOY_EXIT=0
17:41:20
```

Before the deploy the device ran the flashed UI (`/usr/data/mq_ui` md5 `30c46d1b27cc35eedc8f6c07c0f00008`). After it:

```
MD5=ceb84837af9264fde610f279646b1952
EXE=/usr/data/mq_ui
PLAYER=1150
USBAUDIO_ROWS=5
SPDIF_ROWS=0
FW=4.4.94
```

`grep -ac "USB Audio" /usr/data/mq_ui` = 5, `grep -ac "SPDIF Output"` = 0, which matches the normal build. The noisiest line in `/usr/data/diskos_boot.log` is `Failed to kill daemon: No such file or directory`, the pre-existing BusyBox `killall` complaint, not a crash.

## Proving the row without a finger on the glass

Two tricks made this quick and repeatable:

1. `mq_ui` takes a start screen as its first argument (`main.c` maps `home`, `workmode`, `quick`, `settings`, ...), so relaunching into the picker beats blind swipes:
   ```
   ssh disc 'killall -9 mq_ui; setsid /usr/data/mq_ui workmode </dev/null >>/usr/data/diskos_boot.log 2>&1 &'
   ```
2. Screenshot via `dd if=/dev/fb0 bs=518400 count=1`, `Image.frombuffer("RGBA",(360,360),raw,"raw","BGRA").rotate(180)`, after confirming `/sys/class/graphics/fb0/pan` prints `0,0`. See [[diskos-screenshots-over-key-ssh-and-terminal-home-layout]].

The picker showed, top to bottom: **Local Playback**, **USB Audio / "Play to an external USB DAC"**, **USB DAC / "Be a DAC for a phone or PC"**, **Bluetooth Receiving**, with no SPDIF row. On relaunch the saved route was still `OUT_USB`, so the app restored it and showed the "Switching to USB audio output" toast.

To return the route to the internal DAC, the `tap` tool from `/home/moo/sessions/2026-10-29-apps-settings-scroll/` was copied to `/tmp/tap` (the Disc has no `sftp-server`, so `cat > /tmp/tap < tap`). The panel is rotated 180, so raw coordinates are `(x, 360 - y)`; tapping screen `(180, 97)` is `/tmp/tap 180 263 120`. After that the checkmark sat on Local Playback and the toast cleared. Relaunching with no argument brought back the normal Home screen (17:42, Wi-Fi up, 92% battery, "Not Playing"). See [[diskos-apps-page-scrolls-up-when-settings-tile-pressed]] for the touch-injection details.

## Gotchas

- Every manual relaunch can race the `fiio_init.sh` watchdog, which may respawn stock `/usr/bin/mq_ui`. Poll for a PID whose `/proc/<pid>/exe` is `/usr/data/mq_ui`, then kill only instances whose exe is exactly `/usr/bin/mq_ui`. Never kill `mq_player`; that hard-reboots the MCU.
- The hot-load is temporary. A reboot, or leaving USB Storage, makes `S97diskos_install` restore the flashed build, so USB Audio disappears again. See [[diskos-hotload-gotchas-test-outputs-usb-storage-reboot]].
- Leaving the route on `OUT_USB` with no DAC attached means silent output. Return to Local Playback when no DAC is plugged in.
- The USB Audio row is now independent of `-DDISKOS_TEST_OUTPUTS`. Do not tell the user the row needs a test build any more. SPDIF still does.

## Not verified

- Actual playback through a real external USB DAC on this normal build (the row, the route and the switch toast were checked; audio out was not).
- Behaviour after a reboot or after leaving USB Storage, which revert to the flashed build.
- Upstream PR #16's netlink `a60a` unplug/replug latching against this procfs-based route, which still may differ.
- Permanence. Keeping the row across reboots still needs a flash of the same binary (~20 min mask-ROM write), see [[fiio-snowsky-disc-diskos-flash-fedora]].

## References

- [[diskos-usb-audio-headset-click-gestures-and-flash]]
- [[diskos-usb-audio-reverse-engineering-mq-player]]
- [[diskos-ui-module-owners-2026-11-16]]
- [[snowsky-disc-quieter-after-usb-audio-cs43131-reinit-gain-reset-2026-11-11]]
