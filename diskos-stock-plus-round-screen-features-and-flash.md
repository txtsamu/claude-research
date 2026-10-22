---
type: how-to
tags: [fiio, snowsky-disc, diskos, lvgl, round-display, ui, flash, usbboot, ghidra, security]
created: 2026-10-23
last_verified: 2026-10-23
status: current
---

# diskOS stock-plus-disco: round-screen fixes, new features, and flashing it

Fork `txtsamu/diskos`, branch **`stock-plus-disco`** (stock diskOS base + fixes + a few Disco system ports); flashed 2026-10-22 20:48 (`0x600DF10C [F001] SUCCESS`, UI sha256 `441507ed…`, commit `cea2ca9`). The Disco-based experiment (Halo/Stone themes ported onto Disco 2.5.9) is branch `disco-with-fixes`. Related: [[diskos-usb-dac-exit-deadlock-roles-and-volume-fix]], [[diskos-disc-hotload-watchdog-snowsky-logo-hang]].

## Round glass geometry (360x360 framebuffer, round panel)
Visible only where `(x-180)^2+(y-180)^2 <= 180^2`; chord width at row y = `2*sqrt(180^2-(y-180)^2)` (339 px at dy=60, 268 at dy=120, 226 at dy=140, 221 at y=322). Practical safe radius for text/controls ~166.
Audit method: overlay script (darken outside r180, draw r180 + r166 rings) on live screenshots; measure per-screen rects from the code. Findings and fixes (all constants, no per-frame work on this GPU-less renderer): list viewport copy-pasted on ~12 screens (x30..330, y70..322, rows 268 wide) -> shared `ui/ui_round.h` (viewport y72..340 so the bezel clips instead of a flat cut at 322, `pad_bottom 44` so the last row clears); terminal Home buttons y276 -> y262 (corners r178.5 -> 164); Stone pill raised; keyboard rows y184/222/260/298 -> 178/214/250/286; Now Playing transport +-52, 56 px touch targets; confirm cards 268x180; QS brightness slider w200 y>=52. Research (Wear OS / Pebble / LVGL scroll examples) says centre-focus lists, stepped-opacity fades and a progress arc are the next UX steps (not done: they cost per-frame work).
**Left-edge white line:** every screen root had a permanent 1 px left border (white @10%, `anim_panel_shadow` in anim.c) meant only as the slide's leading edge; on the real glass it showed. Now `anim_panel_hairline(o,on)`: on while sliding, off at rest. Detect with: mean brightness of PNG column 0 vs column 1.

## Features added
- **Hold the back arrow = Home** (ui.c `back_hold_home`): no Home button existed. LVGL still sends CLICKED after a long press, so a filter registered before the real handler swallows it (`lv_event_stop_processing`).
- **Power off:** Settings > System row + opt-in Quick Settings tile `qs_t_poweroff`, confirm card, then `power_shutdown_request()` (SD-safe).
- **Command guard** (ipc.c `ipc_frame_is_dangerous`): refuses `0800` (factory reset), `0621` (drop DB tables), `0724`/`0722` v1=2 (firmware upgrade / OTA download), `0720` start; `ipc_send_cmd_unsafe` is the only bypass; host test `ui/tests/ipc_guard_test.c`.
- **Block FiiO update checks** (phonehome.c, Settings > System, cfg `block_fiio_checks`): the player's `network_detect_` thread wgets `discpick.fiio.net/ota_patch_user.json` and `fiio-bluetooth.fiio.net/<product>/version.txt` after Wi-Fi connects (also release notes, `ipinfo.io`, `worldtimeapi.org`, NTP which stay). /etc/hosts is read-only squashfs and there is no iptables/nft, so a private copy in tmpfs is bind-mounted over /etc/hosts mapping those two hosts to 127.0.0.1/::1 (same bind-mount pattern as /etc/shadow). Verified: `ping discpick.fiio.net` -> 127.0.0.1, OTA files stay 0 bytes, "get_ota_server_version fail" logged, no firmware prompt, clock fine.
- **Disco system ports:** player-command mailbox (ordered outbound queue, silent re-sync), `CFG_MAX` 256->512, posix_spawn helper, LVGL assert -> abort, `/ui` mqueue 32 deep.

## What the player exposes (no runtime switch in V2.57)
mq_player serves unauthenticated **FiiO Link** (TCP 12100 + UDP multicast beacon; the FiiO Control phone app, `com.fiio.control`, uses it) and a Mongoose **HTTP server on TCP 12103** (library browse, cover art, playlist edit, `build_log_zip` log export). Both start on "network up" (`FUN_004e57f0`) and stop on "network down"; no sysconfig column, IPC opcode or stock-UI toggle exists. AirPlay/DLNA/QPlay/Roon are only separate work modes (5/6/7) diskOS never enters. Only mitigation: Wi-Fi off. Sources: [FiiO Link first look](https://porta-fi.com/fiio-link-a-first-look/), [FiiO: how to use FiiO Link](https://fiio.com/newsinfo/908691.html).

## Build and flash recipe (the stock-plus worktree)
```sh
cd ~/diskos/diskos-stock-plus
# once: usbboot binary (the release tarball ships it) + venv
tar xzf ~/diskos/diskos-installer-linux-x86_64.tar.gz -C vendor/linux-x86_64 --strip-components=3 diskos-installer/vendor/linux-x86_64/usbboot diskos-installer/vendor/linux-x86_64/usbboot.manifest
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt     # pycryptodome + pyusb
# UI (must keep -DDISKOS_TEST_OUTPUTS or the USB Audio row/IEM buttons disappear)
podman run --rm -v "$PWD/ui:/src:Z" --userns=keep-id -u "$(id -u):$(id -g)" localhost/diskos-ui-builder sh -c 'make -j4 CROSS=$CROSS EXTRA_CFLAGS=-DDISKOS_TEST_OUTPUTS'
# image only (stops at E110 "no device in mask-ROM mode"):
echo n | ./diskos-installer install --firmware ~/Downloads/SNOWSKY_DISC_update_20260909_v257.zip --variant public --ui ui/mq_ui --no-ota
# verify: unsquashfs -cat ~/.local/share/diskos-installer/build/out.squashfs etc/diskos_manifest  == sha256 ui/mq_ui
# flash: power off, hold Vol-Down, plug USB (lsusb: a108:eaef), then the same command with -y
```
Timing: upload ~118 s, then a **fixed 18 min writer wait** (`DISKOS_FLASH_WAIT`), total ~20 min; do not unplug. After `flash verified OK` the Disc stays in USB boot until power is cut (unplug + hold power). First boot runs `S97diskos_install`. Settings in /usr/data survive.
Hot-load without flashing: `~/diskos/diskos-hotload.sh [mq_ui]` (freezes the `fiio_init.sh` watchdog); `THEME=<preset>` sets `theme_preset`.

## Gotchas found
- A stray `dis.py` in the scratchpad shadowed Python's stdlib `dis` (PIL import crash): run helper scripts with `python3 -I` from another directory.
- Screenshots (`snowsky-shot.sh`) only read page 0 of `/dev/fb0`; they fail while `cat /sys/class/graphics/fb0/pan` is `0,360`.
- `tinj hold <x> <y> <ms>` (tools/tinj.c) for long presses; `tinj tap` only holds ~220 ms.
- Never recursive-grep `/usr/data` on the Disc (named pipes block forever) or the big `fiio_player.log` (OOM).
