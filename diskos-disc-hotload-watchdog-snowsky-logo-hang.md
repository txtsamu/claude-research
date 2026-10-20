---
type: troubleshooting
tags: [fiio, snowsky-disc, diskos, disco, hot-load, watchdog, fiio_init, ssh]
created: 2026-10-20
last_verified: 2026-10-20
status: current
---

# Disc: hot-loading mq_ui sometimes hangs at the Snowsky logo (fiio_init.sh watchdog)

## Symptom
Hot-loading a new `mq_ui` over SSH (kill `mq_ui`, relaunch ours) intermittently left the Disc stuck mid-way on the
Snowsky boot logo, Wi-Fi/SSH dropped, and after a power cycle the flashed UI was back. The UI log
(`/usr/data/diskos_boot.log`) said `diskos: another test UI owns the display, or instance lock unavailable`.
The first hot-load of a session worked; later ones did not.

## Root cause (two interacting races)
`/usr/project/fiio_init.sh` ends in a watchdog loop (polls every 5 s):
`if ! pgrep -x mq_ui; then ... killall -9 mq_player mq_ui udhcpc wpa_supplicant wget bluetoothd ...; backlight off; mq_ui & ; mq_player & fi`.
Any 5-s poll that lands while no `mq_ui` is alive therefore kills the player, Wi-Fi and the backlight and restarts the
*stock/flashed* UI and player = the logo animation, interrupted by our next launch.
1. Relaunching immediately after `killall -9 mq_ui` can lose `flock()` on `/tmp/diskos-ui.lock` to the dying process
   (`ui_instance_acquire`, exit code 75) -> no UI alive -> watchdog fires.
2. Adding a `sleep 2` between kill and relaunch (to dodge 1) opens a 2-s window = ~40 % chance the watchdog polls inside it.

Evidence: `/usr/data/fiio/log/process_failed.txt` got `mq_ui Restarting` lines at 17:42:27, 17:42:38, 17:44:20 = the
failed hot-loads (nothing for the first, lucky one).

## Fix: freeze the watchdog during the swap
SIGSTOP the watchdog shell, swap, retry the launch until the lock is free, SIGCONT it (trap on exit so it always resumes;
if our UI never stays up, resuming lets it restore the flashed UI as the fallback). Never touch `mq_player`.
Script: `~/diskos/diskos-hotload.sh [mq_ui]`. Core of it (runs on the device via `ssh disc 'sh -s'`):

```sh
WD=$(pgrep -f /usr/project/fiio_init.sh | head -1)      # NOT from the ssh command line: pgrep -f would match that too
trap 'kill -CONT $WD 2>/dev/null' EXIT INT TERM
kill -STOP $WD
touch /tmp/.diskos_radios_reset
mv -f /usr/data/mq_ui.new /usr/data/mq_ui
killall -9 mq_ui
# retry: sleep 1; setsid /usr/data/mq_ui </dev/null >>/usr/data/diskos_boot.log 2>&1 & sleep 4; check readlink /proc/$p/exe == /usr/data/mq_ui
```
Stage first with an md5 check (`cat > /usr/data/mq_ui.new ... md5sum`). Verified: first attempt, no new
`process_failed.txt` line, `mq_player` pid unchanged, load ~0.3.

## Related gotchas found the same day
- A reboot makes `S97diskos_install` verify `/usr/data/mq_ui` against the baked SHA/size and restore the flashed build,
  so any hot-loaded build disappears on reboot (by design).
- Disco's process shows in `ps` as `{exe} mq_ui` (comm `exe`); `pgrep -x mq_ui` and `pidof mq_ui` still match it.
- Screenshots: `snowsky-shot.sh` reads `/dev/fb0` at the visible page, but a read at yoffset 360 returns 0 bytes
  (only page 0 is readable). It works when `cat /sys/class/graphics/fb0/pan` is `0,0`; right after a fresh start it is.
- `theme_preset` in `/usr/data/diskos.conf` persists across hot-loads; Stone (6) from the old fork looks broken under
  Disco's changed shared code (title overflows its pill); Halo (0) is the restored original look. Backup of the old
  config: `/usr/data/diskos.conf.stone-backup`.
