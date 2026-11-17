---
type: investigation
tags: [diskos, snowsky-disc, boot, logs, dmesg, fat, sdcard, vfat, power-off, ssh, troubleshooting]
created: 2026-11-17
last_verified: 2026-11-17
status: current
---

# Disc boot log error check: previous session and current boot (2026-11-17)

Request: "check my diskos logs from before boot and current check for errors, look in claude-research on how to do it". Repo `/home/moo/diskos/diskos`, branch `main`, `3726ebc`, clean. The Disc was reachable at `192.168.50.29:2222` (key SSH, `Host disc` in `~/.ssh/config`), same address as the 11-10 note.

## Procedure

From [[diskos-boot-starting-state-and-boot-net-errors-2026-11-10]]: read the `/usr/data` logs over key SSH. There is no `sftp-server` on the Disc, so `scp` fails and every file has to come over `ssh ... cat`:

```bash
for f in diskos_boot.log diskos_journal.log diskos_rmguard.log coldplug.log; do
  ssh disc "cat /usr/data/$f" > "$f"
done
ssh disc 'cat /usr/data/fiio/log/fiio_player.log' > fiio_player.log
ssh disc 'dmesg' > dmesg.txt
```

`fiio_player.log` contains NUL bytes, so `grep` needs `-a` or it reports "binary file matches".

`diskos_boot.log` has no timestamps and is appended across boots, so segments are split by the cold-boot markers `chargemode: charger at boot` and `check product is , start wifi config` (the latter only appears when `/usr/bin/wifi_up.sh` runs at boot). Current boot = line 3566 to end (UI start 17:19, wifi config at 17:20). Everything before that is the previous session or older.

Boot clock note: S97 and the journal ran with an RTC value about 7 h ahead (`Wed Nov 18 00:19` for a real `Tue Nov 17 17:19`), then the UI corrected it (`clock: 1794910776 ok`). So boot-time timestamps in `diskos_install.log` and `diskos_journal.log` for this boot are 7 h ahead. This is the known timekeep behaviour, not a fault.

## Current boot (17:19, up 5 min at inspection)

Healthy: `mq_player` pid 1151 and `mq_ui` pid 1122 alive, both POSIX queues `QSIZE:0` (no command backlog), 51.9 MiB free on `/usr/data`, SD mounted vfat at `/tmp/sdcard`, running binary md5 `ceb84837af9264fde610f279646b1952` matching `/usr/data/mq_ui` (the flashed 11-16 USB DAC build). `S97` logged `already installed + verified -> repaired +x/symlink, booting diskOS`, so the flashed UI survived verification.

| Source | Message | Count | Verdict |
|---|---|---|---|
| boot log | `ls: /etc/product_version/*/: No such file or directory` | 1 | known stock `wifi_up.sh` bug (11-10 note), harmless |
| boot log | `Failed to kill daemon: No such file or directory` | 2 | known `avahi-autoipd -k` in `default.script`, harmless |
| player | `player_interface.c: work mode NULL` | 2 | normal before `work mode=LOCALPLAYER` at 17:19:46 |
| player | `ota_update.c: get_ota_server_version fail` | 2 | expected: FiiO phone-home block maps the OTA host to 127.0.0.1 |
| dmesg | `exFAT-fs ... failed to mount! (-22)` | 4 | coldplug probes exFAT first, card is vfat, then mounts correctly |
| dmesg | `FAT-fs: Volume was not properly unmounted. Some data may be corrupt. Please run fsck.` | 2 | **new class**, see below |
| dmesg | `blk_update_request: I/O error, dev mtdblock_bbt_ro2/ro4/ro7` | 9 | known read-only vendor partitions, harmless |
| dmesg | `[dhd] ... failed -23`, `CFG80211-ERROR` | many | Wi-Fi chip bring-up chatter, known; `wlan0` came up and got the lease |

No timezone race this boot: unlike the 11-10 baseline, `set_local_time.c: get timezone failed` and `util.c: read route buf fail` did not fire, and `udhcpc` got `192.168.50.29` immediately.

`process_failed.txt` has no new entries; the last line is still `Mon Nov 16 17:27:32 mq_player Restarting`.

## Previous session (boot before the 17:19 one)

It ended on the idle power-off path, not a crash: `diskos_journal.log` shows `idle power-off: timer fired, no charger input` at `u=2589`, and the next journal record is the current boot. Boot log for that session contains only the same two known-benign lines.

Player log for that session adds:

- `playlist server is running` x3, `playlist_server.c: curlist_source ... not support folder jump!` x14: player state churn, known.
- `mount failed with exit code 255, retry use ntfs to mount` x1: known coldplug fallback.
- `[USB_DAC] init failed: -2` x1 at `04:36:14`: one-off USB DAC init failure (ENOENT). Three such lines exist in the whole file (11-16 18:52, 11-16 22:00, 11-17 04:36), each followed by a healthy `EVENT_USB_DAC_FORMAT`. Consistent with a plug/unplug race, not a stuck state.

`dmesg` keeps only the current boot, and `diskos_dmesg.log` stores short tails taken at UI start (`u=7`), before the SD mount at `u=9.3`, so the previous boot's FAT message cannot be compared directly.

## The one real finding: the vfat card is never cleanly unmounted

`FAT-fs (mmcblk0p1): Volume was not properly unmounted` fires on both mount passes of the current boot (9.37 s and 14.47 s). Cause is in the code, not the card:

- `ui/power.c:85` `power_shutdown_begin()` runs `quiesce_begin`, then `sync`, then sends `0806000C0001` to the MCU, which cuts power.
- `ui/sdio.c:138` `sd_quiesce_begin()` calls `card_close()`.
- `ui/sdio.c:55` `card_close()` only clears `g_allowed` and `g_sd_writable`. Nothing in `sdio.c` calls `umount()` at all.

So the kernel never unmounts `/tmp/sdcard`; the MCU removes power while the filesystem is still mounted, and the FAT clean flag stays dirty. The `sync` before the handoff does flush file data, so this is not an automatic data-loss bug, but it is a real "unclean filesystem" every power-off, and the card will keep warning until something clears the flag (a mount plus clean unmount, or `fsck.vfat`).

A fix would be one `umount("/tmp/sdcard")` (with `umount2(..., MNT_DETACH)` fallback, the pattern already used at `ui/main.c:1481`) between the sync success and the MCU handoff in `power.c`. Implemented the same day, together with the stock player's release path: see [[diskos-sd-clean-unmount-and-fsdetect-2026-11-17]] (`15797a0`).

## Not verified

- Whether the previous boot showed the same FAT warning. Only the current boot's full `dmesg` is retained.
- Whether any actual data was lost on the card. The read-only check (`fsck.vfat -n`) was not run because the card was mounted; the shutdown `sync` makes loss unlikely.
- The exact reason the clock starts 7 h ahead in the RTC. Only observed, matching the existing timekeep note.
- The `dhd -23` Wi-Fi errors were not compared against a stock firmware boot on this device.

## References

- [[diskos-boot-starting-state-and-boot-net-errors-2026-11-10]]
- [[fiio-snowsky-disc-diskos-flash-fedora]]
- [[diskos-persistent-clock-timekeep]]
- [[diskos-usb-audio-normal-build-hotload-2026-11-16]]
