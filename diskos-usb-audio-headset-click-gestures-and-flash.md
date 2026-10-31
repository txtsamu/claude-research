---
type: how-to
tags: [diskos, snowsky-disc, usb-audio, usbhid, headset, ja11, click-gestures, subagents, flash, usbboot]
created: 2026-10-31
last_verified: 2026-10-31
status: current
---

# diskOS: headset click gestures for USB Audio (1 = play/pause, 2 = next, 3 = previous), and flashing `dev`

Request: "for USB Audio i want headset button control more specific, like double click to next and triple click for previous". Fork `txtsamu/diskos`, branch `dev`, commit `4f28beb`; flashed to the Disc the same day. Companion docs: [[diskos-usb-audio-reverse-engineering-mq-player]], [[fiio-snowsky-disc-diskos-flash-fedora]], [[diskos-stock-plus-round-screen-features-and-flash]].

**Status: flashed and verified (`0x600DF10C [F001] SUCCESS`), but the gestures are NOT yet tried on the JA11.** Which key code the JA11's button sends is unverified until a press shows in the `usbhid:` log.

## Time estimate

Measured this session unless marked (est.). Total from "build" to "flash verified": about 21 min wall-clock, of which 20 min is the flash.

| Step | Time |
|---|---|
| Host tests (`make -C ui/tests run CC=clang`) | seconds (est.) |
| Cross-build `ui/mq_ui` in podman (`make clean` + `-j4`) | about 1 min (est.; finished before the next poll) |
| Build the image with `echo n \|` (stops before flashing) | under 5 s (09:44:03 to 09:44:04) |
| Flash: upload | about 2 min (the previous flash's log shows 124,954 ms for the 96 MiB image) |
| Flash: fixed writer wait (`DISKOS_FLASH_WAIT`) | 18 min (1080 s) |
| Flash total | 20 min 7 s measured (09:44:17 to 10:04:24); my up-front guess of 10:05-10:08 was about 1-3 min late |
| First boot after power-cycle | not measured |

## How the existing support was found (and a wrong turn)

The question was whether USB Audio already handled headset buttons. A first grep said no, and that answer was wrong: the match was buried under output from the font data files (`ui/font_*.c` contain hex like `0xe0`), and `head -30` cut it off. Always exclude `font_*` and `lvgl` from a repo-wide grep:

```bash
cd ~/diskos/diskos
git log --all --oneline -i -E --grep='usb audio|usb host|headset|hid|button|media key' | head
git show --stat f911eb8        # "USB Audio: drive playback/volume from the attached IEM's media buttons (usbhid)"
cat -n ui/usbhid.c
grep -n "usbhid" ui/main.c ui/Makefile     # main.c:2456 calls usbhid_poll(bl_state == 0)
```

What `ui/usbhid.c` did before this work: while the output route is USB (`modes_output_route() == OUT_USB`) it opens every `/dev/input/eventN` whose sysfs path contains `/usb` (never event0 = the Disc's keys, event1 = touch), read-only, and maps `KEY_PLAYPAUSE`/`KEY_PLAYCD`/`KEY_PAUSECD` to play/pause, `KEY_NEXTSONG` to next, `KEY_PREVIOUSSONG` to previous, `KEY_VOLUMEUP/DOWN` to volume +-2, one action per press, 150 ms debounce. A one-button dongle sends only the play/pause key, so it could only play/pause.

## The change

- `ui/clicks.{c,h}`: a pure click counter. `clicks_press(c, now)` counts a click and returns 3 at once on the third; `clicks_poll(c, now)` returns the pending 1 or 2 once `CLICKS_WINDOW_MS` (350) has passed since the last click (window measured from the last click, wraparound-safe).
- `ui/usbhid.c`: play/pause keys go through the counter (1 = play/pause, 2 = next, 3 = previous); dedicated next/previous/volume keys still act at once. The play/pause key's debounce is 40 ms (`CLICK_DEBOUNCE_MS`) because 150 ms would swallow a fast triple click. The counter is reset when the route leaves USB or the charge screen / keyboard is up. The window and the actions are fixed, not settings.
- `ui/Makefile` (+`clicks.c`), `ui/tests/Makefile` and `ui/tests/clicks_test.c` (10 cases: 349/350 ms boundary, window from last click, triple resolves at once, fourth click starts a new sequence, reset, wraparound, NULL).
- Docs: `CHANGELOG.md`, `docs/TOUR.md`, `docs/HARDWARE.md`, `GLOSSARY.md` (term "Click gestures"), and the design notes in `comments.md` under `ui/usbhid.c` (the repo has a no-comments-in-source rule, so explanations go there).

Done in parallel: one subagent (own worktree) wrote `clicks.{c,h}` and `clicks_test.c` from a fixed interface while the parent wired `usbhid.c`, the Makefile and the notes. The worktree started at the `dev` tip and its files were copied over by hand; the parent re-ran the tests in the main tree and removed the worktree and its branch.

```bash
make -C ui/tests clicks_test CC=clang && ui/tests/clicks_test        # PASS (0 failures)
make -C ui/tests run CC=clang                                        # exit 0 (C tests only)
cd ui && clang -fsyntax-only -Wall -Wextra -std=gnu11 -D_GNU_SOURCE -DLV_CONF_INCLUDE_SIMPLE -I. -Ilvgl -Ilvgl/src usbhid.c   # exit 0
```

Host tests need `CC=clang` here (the box's gcc has no libasan). `ui/tests/playadmit_test` is an untracked leftover binary, not part of this work.

## Build and flash `dev`

Preconditions checked first: `./diskos-installer doctor` all green (usbboot, system `mksquashfs`/`unsquashfs`, LZO check, one device in mask-ROM that the user can open); firmware ZIP `~/Downloads/SNOWSKY_DISC_update_20260909_v257.zip`; podman image `localhost/diskos-ui-builder`; `.venv` with pycryptodome + pyusb.

Is the Disc in flash mode? `lsusb | grep -i ingenic` must show `a108:eaef Ingenic USB BOOT DEVICE` (normal mode is `2972:0158 FiiO SNOWSKY DISC`). If not: power off, hold Vol Down, plug in USB.

```bash
cd ~/diskos/diskos && git log --oneline -1                  # confirm dev
# 1. UI, keeping -DDISKOS_TEST_OUTPUTS or the USB Audio row disappears
podman run --rm --userns=keep-id --security-opt label=disable -v "$PWD/ui:/src" -w /src localhost/diskos-ui-builder:latest \
  sh -c 'make clean >/dev/null 2>&1; make -j4 CROSS=$CROSS EXTRA_CFLAGS=-DDISKOS_TEST_OUTPUTS'
strings ui/mq_ui | grep -E "double click|triple click"       # the new code is in the binary
# 2. image only: answer n at the confirmation, nothing is written
echo n | ./diskos-installer install --firmware ~/Downloads/SNOWSKY_DISC_update_20260909_v257.zip --variant public --ui ui/mq_ui --no-ota
# 3. the image's baked hash must equal the binary's
sha256sum ui/mq_ui
unsquashfs -cat ~/.local/share/diskos-installer/build/out.squashfs etc/diskos_manifest | head -1   # SHA256=...
# 4. flash (about 20 min; keep the cable in and the host awake)
./diskos-installer install --firmware ~/Downloads/SNOWSKY_DISC_update_20260909_v257.zip --variant public --ui ui/mq_ui --no-ota -y
```

Gotchas hit: `./diskos-installer` is a `sh` wrapper, not a Python file: running it with `.venv/bin/python` gives `SyntaxError` on `HERE=$(...)`; run it directly. The built UI here was sha256 `57449e49d7ef...` (4,301,500 bytes, `mipsel-linux-musl-gcc 11.2.0`). Result: `scan: bad-blocks-found=2 list=[128, 522]`, `write: skipped=2 retried=0`, `0x600DF10C [F001] SUCCESS`, backup `g0013` committed.

## After the flash (not done yet)

1. The Disc stays in USB boot until power is cut: unplug, hold power to boot. First boot runs `S97diskos_install`; if the UI hash does not verify, the stock UI runs (fail-closed).
2. Settings > Audio > Working Mode > USB Audio (shown because of `-DDISKOS_TEST_OUTPUTS`), plug in the JA11, click its button once / twice / three times.
3. Over key-SSH on the Disc, `usbhid:` lines go to the UI's stderr: `usbhid: opened eventN "<name>"` then `usbhid: eventN key C -> play/pause|next (double click)|previous (triple click)`. If the button does nothing, the log shows which node opened and whether any key arrives; a vendor HID code would need adding to `usbhid.c`.
4. If it works, push `dev` to `main` only when the user says they are happy with the flash (`git merge-base --is-ancestor origin/main dev` first).

Recovery if anything goes wrong: `RECOVERY.txt` (wait 25 minutes after a hung mask-ROM run, then power off, hold Vol Down, reconnect), or `./diskos-installer restore-stock`.

## References

- Repo docs: `agents/AGENTS.md`, `RECOVERY.txt`, `docs/HARDWARE.md` (input devices: event0 `x2000_key`, event1 `cst816t`), `comments.md` (`ui/usbhid.c`).
- Earlier commits: `f911eb8` and `c484550` (the `usbhid` module), `4f28beb` (this change).
