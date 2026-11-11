---
type: troubleshooting
tags: [diskos, snowsky-disc, usb-audio, dacvol, volume-keys, input-event, key-codes, x2000_key, hot-load, usb-serial, acm]
created: 2026-11-11
last_verified: 2026-11-11
status: current
---

# diskOS on USB Audio: volume keys dead when Double click = Switch Track, and hold did nothing (fixed), plus pushing a binary over the USB serial shell

Repo `/home/moo/diskos/diskos`, branch `dev` (fast-forwarded to `b70e821`, not pushed to origin). Worktree used: `~/diskos/diskos-dacvolkeys`, branch `fix/dacvol-single-click`. Related docs: [[diskos-usb-dac-exit-deadlock-roles-and-volume-fix]], [[diskos-usb-audio-reverse-engineering-mq-player]], [[diskos-usb-debug-source-menu-serial-no-ethernet-2026-11-10]], [[diskos-hotload-gotchas-test-outputs-usb-storage-reboot]]. In the repo: `docs/USB_AUDIO_VOLUME.md`.

**Result:** single click and hold both change the DAC volume on USB Audio now, double click still skips tracks. Single click and hold were confirmed on the Disc by the user. The double-click part was not tested separately on this build.

## Symptom

Output = USB Audio (external DAC): the volume keys did nothing. Local Playback was fine. The user's Settings > Controls: single click = Adjust Volume (`key_single=1`), double click = Switch Track (`key_double=0`), long press = Adjust Volume (`key_long=1`). After the first fix, a hold still did nothing; only repeated single clicks worked.

## Cause

On USB Audio the `dacvol` module (`ui/dacvol.c`) owns the volume: it writes the DAC's ALSA playback volume and holds the Player at unity (120). The stock Player cannot raise a volume that sits at maximum, so diskOS has to read the keys itself from `/dev/input/event0` (`x2000_key`).

1. `dacvol` gated both its key handler and its "Player volume moved" path on `keys_adjust_volume()`, which in `main.c` required `key_single`, `key_double` **and** `key_long` all to be Adjust Volume. With double click = Switch Track (a common setting) every volume key was ignored. Journal: `dacvol: key code 266 seen (not a volume key)`; mixer unchanged.
2. Hold sends different key codes (262 / 263) that `on_key` never treated as volume keys.

The user's own guess ("I think it's the double press to skip track, check it") was right; the code confirmed it before any hardware test.

## Key codes (device `x2000_key`, `/dev/input/event0`)

| Gesture | Code | How known |
|---|---|---|
| Single click up / down | 251 / 252 | original `dacvol` commit; matches captures |
| Hold up / down | 263 / 262 | labelled captures 2026-11-11 (press value 1, then repeats value 2 about 20 per second, then 0) |
| Double click | 266 / 267 | inferred from captures; which is next/previous is unverified and not needed |

A trailing 251/252 appears 0.3 to 0.5 s after a 266/267, so a double click would otherwise also move the volume one step.

Capture recipe (reads the raw `struct input_event`, 16 bytes on this 32-bit MIPS: `<IIHHi`):

```python
import os, select, struct, subprocess, time
p = subprocess.Popen(["ssh","-o","BatchMode=yes","-tt","disc","cat /dev/input/event0"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
# read 16-byte records, unpack "<IIHHi", print those with type == 1 (EV_KEY): code and value
```

Ask for labelled presses ("hold UP 2 s, wait 3 s, hold DOWN 2 s"). The user's unlabelled first captures only allowed guesses; hold direction was settled by the click-then-hold ordering (251 then 263, 252 then 262) and by the labelled request.

## Fix (commits `1642510`, `b70e821`)

- `ui/dacvol.h`: `DACVOL_KEY_DBL_UP 266`, `DBL_DOWN 267`, `HOLD_DOWN 262`, `HOLD_UP 263`; new env hooks `single_click_volume` and `long_press_volume`.
- `ui/dacvol.c` `on_key`: single click steps the DAC when `key_single` is Adjust Volume; a hold event (value 1 or 2) steps once per event when `key_long` is Adjust Volume; a 266/267 sets `S.last_dbl` and any 251/252 within `DBL_SUPPRESS_MS` (700) is ignored. `keys_adjust_volume` now means single OR long is Adjust Volume and only gates the Player-driven path in `note_player`.
- `ui/main.c`: hooks read `key_single` / `key_long` from `diskos.conf`.
- Tests in `ui/tests/dacvol_test.c` (updated `test_keys_as_track_buttons`; new `test_single_click_volume_with_double_click_as_track`, `test_hold_repeats_volume`).
- The mixer worker (`ui/dacvol_sys.c`) keeps only the latest requested value, so about 20 hold events a second do not queue up `amixer` runs.

Hold speed: one level per repeat event, about 20 levels a second on the 0 to 120 scale, so a full sweep takes about 6 s. Not tuned; the user accepted it.

## Commands

```bash
cd ~/diskos/diskos-dacvolkeys/ui/tests && CC=clang make run && CC=clang make run-py     # all PASS, run-py rc=0
cd ~/diskos/diskos-dacvolkeys/ui && podman run --rm --userns=keep-id -v "$PWD:/src:Z" localhost/diskos-ui-builder:latest sh -c 'make CROSS=$CROSS EXTRA_CFLAGS=-DDISKOS_TEST_OUTPUTS'
flock /tmp/diskos-disc.lock ~/diskos/diskos-hotload.sh ./mq_ui          # needs ssh to the Disc
ssh disc 'grep dacvol /usr/data/diskos_journal.log | tail'              # look for "dacvol: attach card1 ..."
cd /home/moo/diskos/diskos && git merge --ff-only fix/dacvol-single-click
```

A hot-load vanishes on reboot: the flashed Disc keeps the old `dacvol` until it is reflashed with a build from `dev`.

## Getting a build onto the Disc when Wi-Fi is off (USB serial)

The Disc was plugged into the PC by USB-C with USB Debug on: it showed as `0525:a4a7 diskOS USB Debug` and `/dev/ttyACM0` gave a root shell, but `wlan0` was DOWN (no ssh). The hot-load script only knows ssh. Findings:

- A status command over the serial shell works: `python3 -I serial_cmd.py 'uptime; ip -4 addr'` (script in `~/sessions/2026-11-10-flash-merged-dev/`, writes the command plus a newline and reads for N seconds).
- Pushing the 4.3 MB binary as base64 heredoc blocks of 24 KB with a size check after each block works (first block arrived intact) but ran at about 7.5 KB/s (measured: 1.0 MB in 133 s), so about 9.5 minutes in total. The slowness is the text path (base64 plus per-block waits), not the USB link. Over USB the Disc only has serial, no Ethernet (see the USB Debug doc), so ssh-speed transfer is not possible that way.
- A raw-mode attempt (`stty raw -echo; head -c N > file`, then write the bytes) was started but not verified: the script timed out waiting for its READY marker, and the shell was left stuck inside `head -c`, swallowing every later command with echo off. Do not retry that without a way to recover (the recovery would be to feed the remaining bytes as zeros).
- In the end the user switched Wi-Fi on from the Disc's settings and the normal ssh hot-load took a few seconds. When Wi-Fi is available, use it.

Gotchas hit:

- `pkill -f "serial_cmd.py"` inside a bash command that itself contains that text kills your own shell (exit 144). Use the `[c]md` bracket trick.
- `python3 script | head -n 0` kills the script with SIGPIPE after its first print; it had already pushed one test block to `/usr/data/mq_ui.probe` (removed).
- A USB DAC cannot be tested while the USB-C port is plugged into the PC for USB Debug; the DAC needs the port. Use Wi-Fi ssh for the Disc side.

## Not checked

- Double click skipping tracks on the flashed/hot-loaded build was not checked separately after the hold change (the double-click code path was not touched, and a test covers it).
- Flashing: `dev` has not been flashed since these commits.

## Time estimate

Measured or timed in this session where noted, otherwise my estimate for repeating it:

| Step | Time |
|---|---|
| Find the cause in the code (the user had already named it) | about 2 min |
| Edit, add tests, host test run (C plus Python) | about 3 min |
| Cross build in the podman builder | about 1 min (estimate) |
| Hot-load over ssh | about 10 s (not timed precisely) |
| Key capture (labelled, 25 s) | 25 s (measured) |
| Hold handling: edit, tests, build, hot-load | about 6 min |
| Pushing the binary over serial (base64) | about 9.5 min (extrapolated from 133 s per MB) |

Total for the whole thing if Wi-Fi is on and the key codes are already known: about 10 minutes. Most of the real time in this session went on waiting for the Disc to come back and on the serial detour.

## References

No external sources were used; everything came from the repo, the Disc and live captures.
