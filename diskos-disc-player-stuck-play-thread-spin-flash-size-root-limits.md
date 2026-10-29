---
type: troubleshooting
tags: [diskos, snowsky-disc, mq_player, play_thread, ipc, ssh, flash, mtd, root, squashfs]
created: 2026-10-29
last_verified: 2026-10-29
status: current
---

# Disc: local playback stopped responding (play_thread at 100%), flash size, and what root can do

Companion docs: [[fiio-snowsky-disc-diskos-flash-fedora]] (key-only SSH, flash), [[diskos-persistent-debug-checkboxes]], [[diskos-disc-hotload-watchdog-snowsky-logo-hang]]. Cause of the spin is **not known**; the player was recovered with a reboot. Everything below was read-only until that reboot.

## 1. "Check how big the flash is" and why the PC saw no device

On the Fedora PC `lsblk` and `lsusb` showed nothing Snowsky-like (only NVMe, a Bluetooth dongle, receivers). The Disc was not in USB storage mode: it was running normally on Wi-Fi at `192.168.50.57`, so there was nothing to enumerate. Read it over the key-only SSH instead (`Host disc`, port 2222):

```bash
ssh disc 'cat /proc/mtd; df -h /usr/data /tmp/sdcard'
# mtd0 uboot 2 MB, mtd1 kernel 8, mtd2 rootfs 128, mtd3 kernel2 8, mtd4 rootfs2 25, mtd5 ota 1, mtd6 mac 1, mtd7 userdata 83  => 256 MB NAND
# /usr/data: ubifs, 67.6 MB, 52.6 MB free.  /tmp/sdcard (/dev/mmcblk0p1, vfat): 59.5 GB, 34 GB free
```

## 2. Symptom and diagnosis

Symptom: the UI no longer controlled local playback; `diskos_boot.log` was full of `ipc: player busy, '0201000C0001' waits (N in line)` and `ipc_send_cmd '...' failed: Resource temporarily unavailable` (play, pause, work mode, output setup all affected).

```bash
ssh disc 'uptime; pgrep -x mq_ui; pgrep -x mq_player; md5sum /usr/data/mq_ui; cat /etc/diskos_manifest'
# UI = the flashed build (size 4291844 = manifest SIZE), uptime 2 min. Not a stale hot-load.
ssh disc 'tail -n 300 /usr/data/fiio/log/fiio_player.log | grep -iE "error|fail|PAUSE|START|set out device|NO_WORK_MODE"'
# last player line was [PAUSE]:exit ... work_mode=LOCALPLAYER, then nothing: the player logged no more commands
ssh disc 'P=$(pgrep -x mq_player); for t in /proc/$P/task/*; do echo "$(cat $t/comm) $(grep State $t/status | cut -f2) $(cat $t/wchan)"; done'
# every thread sleeping (futex / nanosleep / recv) EXCEPT play_thread: State R, wchan 0
ssh disc 'P=$(pgrep -x mq_player); T=<play_thread tid>; a=$(awk "{print \$14+\$15}" /proc/$P/task/$T/stat); sleep 3; b=$(awk "{print \$14+\$15}" /proc/$P/task/$T/stat); echo $((b-a))'
# 301 clock ticks in 3 s = 100% of one core, while the player was paused
```

Open file at the time: `Danilla/Telisik (2014)/03 - Senja Di Ambang Pilu.flac` (`ls -l /proc/$P/fd | grep sdcard`). Config had `audio_filter=4`, `work_mode=1`, `src_mode=0`, no hot-load. `mq_recv_thread` was waiting on a futex, so UI commands were queued or dropped (EAGAIN), which explains the "busy" lines. Ruled out: wrong or hot-loaded build (size and manifest match), Wi-Fi (RSSI -47 dBm, `wpa_state=COMPLETED`; the `online_lyric` curl timeout and OTA check failures are unrelated and normal with `block_fiio_checks=1`), SD card (mounted rw, 34 GB free).

Unknown: whether the FLAC, the pause, or `audio_filter=4` triggers the spin. `/proc/<pid>/task/<tid>/stack` was empty (no kernel stack) and there is no strace on the device.

## 3. Recovery

```bash
ssh disc 'cp /usr/data/fiio/log/fiio_player.log /usr/data/fiio/log/fiio_player.stuck.log; sync; reboot'
# SSH back in ~20 s; play_thread then used 1 tick per 3 s, UI answered taps, a track started, no "player busy" lines
```

The copy was confirmed afterwards (`-rw------- 407364 bytes, 4487 lines`, last lines are `audio_track_stop` from the shutdown at 13:43:47, so it holds the stuck period plus the stop). The reboot restores the flashed UI (same as before). If it hangs again: do not reboot first; sample the thread (which tid, how many ticks) and keep `fiio_player.stuck.log`, then compare with that first copy on the device. Try the same track, and pause it, to see whether it reproduces.

## 4. "Do we have full root access via debug?"

Yes for the shell, no for the system image:

```bash
ssh disc 'id; mount | grep -E " / | /usr/data "; touch /etc/.rwtest; /usr/project/diskos-debug.sh status; cat /proc/cmdline'
# uid=0(root) groups=root,wheel; key-only SSH (port 2222) logs in as root; Debug status SSH=on SERIAL=off KEYSSH=on
# /  = squashfs (ro); touch /etc/.rwtest -> "Read-only file system"; kernel cmdline has "ro rootfstype=squashfs"
# /usr/data = ubifs rw,sync. /dev/mem and /dev/mtd0..7 exist.
```

Practical limits: only `/usr/data`, `/tmp` and running processes can be changed live. `S97diskos_install` restores `/usr/data/mq_ui` to the baked hash on boot, and the `fiio_init.sh` watchdog restarts the stock UI and player when `mq_ui` is not running. Changing `/etc` or the rootfs needs a reflash (or a remount I did not try; do not do it on the live flash without a backup).

## References

None external: all from device logs and the earlier claude-research notes.
