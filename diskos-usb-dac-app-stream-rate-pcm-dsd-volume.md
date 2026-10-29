---
type: how-to
tags: [diskos, snowsky-disc, usb-dac, uac2, uevent, netlink, alsa, apps, lvgl]
created: 2026-10-29
last_verified: 2026-10-29
status: current
---

# diskOS "USB DAC" app: stream rate (kHz), PCM or DSD, and volume

Repo `/home/moo/diskos/diskos`, branch `dev`, commit "USB DAC app: stream rate, PCM or DSD and volume, from the Apps page" (on top of the session/play-admission merge, see [[diskos-session-and-play-admission-modules-parallel-agents]]). Request: when USB DAC mode is active, show the sample rate in kHz, PCM or DSD, and the volume, as an app (an Apps tile, like Pet).

**Status: hot-loaded onto the Disc and working (PCM streams); DSD still unverified.** Hot-loaded 2026-10-29 14:28 with `~/diskos/diskos-hotload.sh ui/mq_ui` (see below); a hot-load lasts until the next reboot, so it is not flashed yet.

## Where the numbers come from (read-only checks on the Disc, nothing sent to the Player)

The UI did not parse any rate frame (`aa1b` "UAC sample-rate change" is in `docs/RE_CATALOGUE.md` but nothing in `ui/ipc.c` handles it). With the Disc in USB DAC mode and a computer playing to it:

```bash
ssh disc 'cat /proc/asound/cards'          # card 1 = FIIOUAC2Gadget (the gadget's sound card; id file: /proc/asound/card1/id)
ssh disc 'cat /proc/asound/card1/pcm0c/sub0/hw_params'
#   format: S32_LE  channels: 2  rate: 48000 (48000/1)    <- capture side = what the host sends; "closed" when idle
ssh disc 'cat /proc/asound/card1/pcm0c/sub0/status'       # state: RUNNING
ssh disc 'tail -n 400 /usr/data/fiio/log/fiio_player.log | grep -E "UAC_|dac_control"'
#   uevent_listener.c: UAC_SRATE ==== UAC_SRATE=48000   ...   UAC_FORMAT value: PCM
#   (on host stop: UAC_SRATE=0 and UAC_FORMAT value: UNKNOW [sic])
#   dac_control.c: bits_per_sample=32 sample_rate=2 is_dsd=0
ssh disc 'cat /sys/kernel/config/usb_gadget/uac_demo/functions/uac2.a/c_srate'   # 48000: the advertised config, NOT the live rate
```

So the Player itself learns rate and PCM/DSD from **kernel uevents** `UAC_SRATE=<hz>` and `UAC_FORMAT=<PCM|...>`. Nothing in sysfs holds the PCM/DSD verdict, so the UI listens to the same uevents itself. ALSA `hw_params` is the fallback for the rate when the UI started after the stream (a uevent is only sent on change). Bit depth was left out on purpose: `S32_LE` is the container, not the real depth.

## What was built

- `ui/dacinfo.c` + `dacinfo.h` (no LVGL). `dacinfo_init()` opens a `NETLINK_KOBJECT_UEVENT` socket (group 1, non-blocking, only messages from `nl_pid == 0`); `dacinfo_get()` drains it, folds `UAC_SRATE` / `UAC_FORMAT` into the state (`UAC_SRATE=0` clears the format) and falls back to ALSA when no uevent has been seen. Pure parsers: `dacinfo_parse_uevent`, `dacinfo_parse_hwparams`, `dacinfo_format_rate` ("48 kHz", "44.1 kHz", "176.4 kHz", "2.82 MHz").
- `ui/dac_ui.c`: `SCR_DAC` page (`dac_create/_open/_visible`): rate in the accent colour, a PCM/DSD pill, `Volume N` with a bar (0..`VOL_MAX`, from `ipc_get_state`). One 500 ms `lv_timer`, only while the page is on show (screenmgr calls `dac_visible`). Outside USB DAC mode (`ui_get_source_mode() != 1`) it says "USB DAC mode is off" with a Working Mode button; in the mode with no host playing it says "Waiting for the computer or phone to play" and still shows the volume.
- Wiring (same places as Pet): `screens.h` (`SCR_DAC`, declarations), `screenmgr.c` (figure number 36, root, create, visible hooks), `apps.c` tile "USB DAC", `main.c` deep link `mq_ui dac`, `ui/Makefile` sources.
- Tests: `ui/tests/dacinfo_test.c` (rule `dacinfo_test`, in `make run`): PCM and DSD streams, stop clears the format, rate-only update keeps the format, unrelated uevents ignored, garbage and an unterminated key, `hw_params` text captured from the Disc, rate wording.

## Bug the sanitizer caught in my first version

The first parser called `strtol` on the value inside the message buffer. A kernel uevent is not NUL-terminated at the end, and the netlink receive buffer is uninitialised, so a `UAC_SRATE=48000` as the last entry would be read past the buffer. ASan reported it in the "key at the very end" test case. Fix: `entry_value()` copies the value into a bounded, terminated local buffer before `strtol` / `strncmp`.

## Gotchas hit

- `make check-theme` (part of the link) is a plain text grep: a **comment** that contains the font symbol name `font_icons_28` fails the build ("use a font role (TF(...)) instead"). Word comments without it.
- The 28 px icon font (`font_icons_28.c`) only has U+F004, F079, F074, F08A, F178, F013, F15B, F185, F202, F186: no speaker or audio glyph. The tile uses U+F178 (long arrow) as a stand-in; a proper icon needs the font regenerated with another `--range`.
- The `git`/`make`/`grep` wrappers on this box (RTK) truncate output ("... (13 lines truncated)"), even when redirected to a file; counts from `grep -c` came out as 0 for lines that were there. Use `rtk proxy make run CC=clang > file` and count in Python. Python/host tests need `CC=clang` here (see the earlier note about sanitizers).

## Hot-load and what was verified on the Disc

The first attempt used the generic `tools/diskos-deploy.sh` (key-SSH copy) and was stopped: it does not freeze the `fiio_init.sh` watchdog, which is what causes the Snowsky-logo hang ([[diskos-disc-hotload-watchdog-snowsky-logo-hang]]). The documented way is the watchdog-safe script:

```bash
cd ~/diskos/diskos && ~/diskos/diskos-hotload.sh ui/mq_ui      # stages + md5-checks, SIGSTOPs the watchdog, swaps, retries the launch, SIGCONTs
#   >> staged 5c006126...   ok=1 attempts=1   (mq_player pid unchanged)
ssh disc 'tail -n 3 /usr/data/fiio/log/process_failed.txt'     # no new "mq_ui Restarting" line
~/diskos/snowsky-shot.sh out.png                               # screenshot (read-only); shots in ~/sessions/2026-10-29-diskos-dac-app/shots/
```

Seen on the real panel (Terminal theme, header `~/usb_dac`): while a computer streamed, the page showed **96 kHz / PCM / Volume 35** with the bar at about 29 percent. The host changed from 44.1 to 96 kHz at 14:28:57 (`UAC_SRATE=96000` in `fiio_player.log`, ALSA `rate: 96000`) and the page followed within a second, so the netlink listener receives the kernel `UAC_*` uevents inside the UI process, and the layout fits the round glass. When the stream was momentarily down it showed "Waiting for the computer or phone to play" with the volume.

Side effect seen (not caused by this feature): a fresh `mq_ui` started while already in USB DAC mode begins with source mode Local and `src_mode=1` saved, so the cold-boot restore re-sends the switch to USB DAC (log: `usb dac: volume -> 35 (your last USB DAC level)`, then `UAC_SRATE=44100` again). The host's stream dips for a few seconds after every hot-load or relaunch that is not a theme reload. Candidate 1's notes (see [[diskos-session-and-play-admission-modules-parallel-agents]]) already list the related relaunch edge cases; fix would be to detect the real gadget state at startup before arming the restore.

## Apps page: round icons and the clipped first row (same day, from the user: "the apps page looks weird, use a circle for the icon")

Screenshot first (`~/diskos/snowsky-shot.sh`, read-only) showed two things on the Terminal theme: square outlined tiles, and the top border of the first row cut off. Causes, both in `ui/apps.c`:

1. The tile was a clickable object holding a glyph label, which the theme kit classifies as `KIT_ICON_BUTTON` and restyles into its own boxed button (Terminal: a square outline), whatever radius the code set. Fix: a transparent clickable cell (`kit_keep`) holding a circular chip (`LV_RADIUS_CIRCLE`, `SURFACE_RAISED` fill, 2 px `BORDER_STRONG`, also `kit_keep`, not clickable so the touch goes to the cell), glyph centred in the chip, caption under it, and `transform_scale` 240/256 on the pressed state instead of a colour swap. `kit_keep` makes the kit pass skip that object (not its children).
2. `lv_obj_set_flex_align(g_list, CENTER, START, CENTER)`: the last argument (track alignment) centred the rows vertically; with 2 rows of 118 px, the 10 px gap and the 44 px bottom pad (290 px) in a 266 px viewport, the content overflowed about 12 px at both ends and hid the top of the first row. Fix: track alignment `START`.

Hot-loaded twice with `~/diskos/diskos-hotload.sh ui/mq_ui` (no new `process_failed.txt` line); screenshots `apps-page-before.png`, `apps-circles-v2.png` in `~/sessions/2026-10-29-diskos-dac-app/shots/`. Only the Terminal theme was looked at; other themes are untested. Each hot-load while in USB DAC mode again re-sent the mode switch (see the side effect above), so the host's stream dipped each time.

## Still not verified

1. The **DSD spelling** of `UAC_FORMAT` and the rate the gadget reports for DSD: only `PCM` and `UNKNOW` appear in the logs. The parser matches the prefix `DSD`; DSD over USB is normally DoP (a PCM carrier at 176.4 kHz or higher), so the page may show a PCM-looking rate with "DSD". Play a DSD file from the host and read `fiio_player.log` for `UAC_FORMAT value:`.
2. After a hot-load while a stream is running and no new uevent has arrived, the format reads "-" until the next change (the rate still shows, from ALSA). Not seen in practice because of the restore re-switch above.
3. The tile icon is a stand-in arrow; not looked at in the Apps grid.
4. Other themes (only Terminal was seen).

## References

None external: all from device logs, `docs/RE_CATALOGUE.md` and the repo.
