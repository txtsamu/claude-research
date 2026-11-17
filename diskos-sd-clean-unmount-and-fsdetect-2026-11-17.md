---
type: build-log
tags: [diskos, snowsky-disc, sdcard, vfat, fat, power-off, restart, unmount, mount, fsck, mq_player, decompiled, tests]
created: 2026-11-17
last_verified: 2026-11-17
status: current
---

# Disc: clean SD unmount at power-off/restart, and no more failed exFAT probe (2026-11-17)

Request: "okay fix all of that problem and try fixing the known issues too", after [[diskos-boot-log-error-check-2026-11-17]]. Repo `/home/moo/diskos/diskos`, `main`, started at `3726ebc`.

Landed on `main` and pushed to `origin` (`txtsamu/diskos`):

```
15797a0 Power: cover the player's five unmount attempts before the handoff
fd9c96e Merge clean SD unmount before power-off and restart
ac80b79 Merge SD filesystem detection
4ff4b27 Power: unmount the SD card before power-off and restart
05c4569 SD: detect the filesystem before mounting
```

## Fix 1: unmount /tmp/sdcard before the MCU cuts power, and before reboot

Cause of the `FAT-fs (mmcblk0p1): Volume was not properly unmounted` warning: neither shutdown path ever called `umount`. `power_shutdown_tick` went quiesce -> `sync` -> frame `0806000C0001` to the MCU, and `restart_tick` went quiesce -> `sync` -> `reboot(RB_AUTOBOOT)`. The kernel never cleared the FAT clean bit.

The stock player keeps the last track open even when idle (`pid=1151 comm=mq_player fd=17 -> /tmp/sdcard/Music/.../10 - HEART BEAT.flac`), so a plain `umount` returns EBUSY. The fix therefore uses the stock player's own USB Storage release path.

Code:
- `ui/power.h:40` new optional op `int (*unmount_card)(void *ctx)`; called at `ui/power.c:115` on the PW_SYNC success branch, immediately before the power frame.
- `ui/restart.h:23` new optional `int (*unmount_card)(void)`; called at `ui/restart.c:89` after the sync child exits 0, before `flash_arm`/`reboot`.
- `ui/main.c:501` `env_unmount_card()`: try `umount("/tmp/sdcard")`; EINVAL/ENOENT means not mounted; on EBUSY send `srcswitch_send_source(SRCSWITCH_MODE_USB_STORAGE)` (frame `0642000C0001`, the same path as the USB Storage screen) and retry `umount` 40 times at 100 ms; finally `umount2(MNT_DETACH)`; every outcome goes to `bootlog_event`. A failed unmount never aborts the shutdown or restart.

Why the player release works with no USB host attached, from the decompiled stock player (private repo `~/diskos/firmware-decompiled`, `decomp/mq_player`), `process/player/snowsky_disc/src/all_mode_control.c` `loop_mode_handle_thread`, storage entry:

```
sync();
iVar5 = FUN_004c473c(1);                       // unmount /dev/mmcblk0*
if ((iVar5 == 0) && (iVar5 = FUN_004c47dc("/tmp/sdcard"), iVar5 == 0)) {
    echo device > /sys/class/usb_role/13500000.otg_new-role-switch/role;
    sleep(1);
    FUN_0046dec0();                            // start storage_demo gadget
} else { ... "TF card unmount failed (ret=%d), refuse to enter storage mode" }
```

`FUN_004c2fd4` (`util/src/mount_storage_dev.c` `unmount_point`) scans `/proc/mounts` for any device path containing `/dev/mmcblk0`, then runs `sync; usleep(200000); umount <mountpoint>` up to 5 times. No host presence is checked, so the unmount is unconditional and clears the FAT clean flag. The 40 retries in `env_unmount_card` cover the player's worst case of five 0.4 s attempts.

## Why the first hardware run still warned: the dirty bit is sticky

The flashed build ran the clean unmount (journal: `card busy errno=16(Resource busy), asking the player to release it` then `card unmounted after player release in 1 tries`) and the next boot still printed `Volume was not properly unmounted`. Root cause, from the kernel source (`fs/fat/inode.c`):

- The flag is **not** in the FAT table. It is bit 0 (`FAT_STATE_DIRTY`) of the boot-sector byte at offset **0x41** on FAT32 (`fat32.state`, `BS_Reserved1`), offset 0x25 on FAT16.
- `fat_set_state()` is called with `set=1` on mount and `set=0` on unmount, but the first thing it does is:

```
/* do not change state if fs was dirty */
if (sbi->dirty) {
    if (set)
        fat_msg(sb, KERN_WARNING, "Volume was not properly unmounted...");
    return;
}
```

So a volume that is already marked dirty stays dirty forever: every mount warns, every unmount returns early. The card read `0x41 = 01` while mounted, i.e. permanently dirty. The unmount code was correct, but it could not clear a bit the kernel refuses to touch.

Proof that it is the card, not the kernel being broken: a scratch FAT16 and FAT32 image mounted on both the Disc and this Fedora host showed the same behaviour (the byte is untouched for an already-dirty volume). And after the bit was cleared once, the Disc's next mount set it to `01` again and the card stayed usable.

One-time clear actually performed over SSH, without removing the card:

```
/tmp/mqsend /player 0666000C0006 0642000C0001 0657000C0008   # player unmounts the card for USB Storage
# /tmp/sdcard gone from /proc/mounts
printf '\000' | dd of=/dev/mmcblk0p1 bs=1 seek=65 count=1 conv=notrunc
sync
/tmp/mqsend /player 0666000C0006 0642000C0000 0657000C0008   # back to local
echo add > /sys/block/mmcblk0/uevent                          # player remounts
```

Result: byte `00` after the clear, then `01` after the remount (normal for a mounted volume), card readable, player alive. The `mqsend` helper is `/tmp/opencode/mqsend.c`, cross-compiled with `/opt/mipsel-n2008-musl-cross`.

The correct alternative, which also checks the filesystem, is `sudo fsck.vfat -a /dev/sdX` on a PC with the card removed. Clearing the bit without a check assumes the volume is consistent, which is what the card's history suggests but was not proven.

Commit `e6bc3da` adds a block-device `fsync` after the unmount (`ui/main.c` `card_flush()`), because the stock shutdown ends in `system("poweroff -f")` in the player (`FUN_004e6f0c`), which does not sync or unmount anything before the MCU cuts power.

## Fix 2: detect the filesystem before mounting (no failed exFAT probe)

`ui/main.c` used to call `sd_mount_utf8("exfat")` first and `"vfat"` second, so every boot logged four `exFAT-fs ... failed to mount! (-22)` dmesg lines (twice per boot, because the mount happens twice).

- New `ui/sdfs.c` `sdfs_detect(dev)`: reads sector 0; `"EXFAT   "` at offset 3 -> `"exfat"`; `0x55AA` at 510 plus a `FAT` label at 54/82 or a plausible BPB (bytes-per-sector 512/1024/2048/4096, sectors-per-cluster a power of two 1..128, nonzero reserved sectors) -> `"vfat"`; anything else -> `NULL` (caller keeps the old exfat-then-vfat order).
- `ui/main.c:1498` uses the result to order the two mount attempts. All existing behaviour (export re-check, log strings, failure log) is preserved.
- `ui/Makefile` adds `$(APP)/sdfs.c`.

Verified against the real card boot sector over SSH (`dd if=/dev/mmcblk0p1 bs=512 count=1`): offset 3 `mkfs.fat`, offset 11 `00 02` (512), offset 13 `0x40` (64), offset 14 `0x0040`, offset 54 `FAT32   `, 510 `55 aa`. So detection returns `vfat` and the exFAT probe is skipped on this card.

## Tests and build

New/updated host tests, all passing:

```
$ cd ui/tests && ./power_test && ./restart_test && ./sdfs_test
power_test: ok
restart_test: ok
sdfs_test: OK
```

`power_test` asserts the order sync -> unmount -> power frame, that a failing unmount still sends the frame, that a failed sync never calls unmount, and that a missing op still works. `restart_test` asserts `UR` (unmount then reboot) and `UFR` for flash mode. `sdfs_test` covers exFAT, FAT32, FAT16 with label, garbage, signature-only, label-without-signature and a missing file. The full `make run` completed with exit 0, and the merged tree built with the pinned builder with zero compiler warnings:

```
$ cd ui && podman run --rm --userns=keep-id -v "$PWD:/src:Z" localhost/diskos-ui-builder:latest
artifact: mq_ui
md5: 24d88617ef5bc7b01d6611b886e2e7e3
size: 4349824
cc: mipsel-linux-musl-gcc (GCC) 11.2.0
```

Binary kept at `/home/moo/diskos/diskos/ui/mq_ui` (the build also leaves `mq_ui.debug`).

## Known issues that were evaluated and left alone

| Issue | Owner | Why not changed |
|---|---|---|
| `ls: /etc/product_version/*/: No such file or directory` | stock `/usr/bin/wifi_up.sh` | `/` is squashfs ro and the directory holds `version.in`, not a product subdir. A bind mount would hide `version.in`, which `ui/fwcaps.c:14` reads; an overlay over `/etc` would hide `init.d` and `/etc/localtime` and void the installer's rootfs-byte checks. One harmless `ls` line per boot. |
| `Failed to kill daemon: No such file or directory` | stock `/usr/share/udhcpc/default.script` | `avahi-autoipd -k` with no daemon running. Silencing it would need a wrapper over a ro-rootfs binary, or `2>/dev/null` on the whole sourced script (`ui/wifi.c:76`), which would also hide the useful `udhcpc: lease of ... obtained` lines. |
| `work mode NULL`, `playlist server is running`, `mount failed 255, retry ntfs`, `[USB_DAC] init failed: -2` | stock `mq_player` | Player internals; diskOS does not control the player's init order or its NTFS retry. |
| `ota_update ... get_ota_server_version fail` | stock player + diskOS phone-home block | Intentional: the block maps the FiiO OTA hosts to 127.0.0.1. Removing the block would restore phone-home. |
| `mtdblock_bbt_ro2/4/7` I/O errors, `[dhd] ... -23` | kernel / vendor Wi-Fi driver | Read-only vendor partitions and BCM43438 bring-up chatter. |
| Boot logs 7 h ahead until the UI starts | pre-diskOS RTC load | Kernel reads the local-time RTC as UTC, so S97 logs `Wed Nov 18 00:19` for a real 17:19. The UI repairs it with `hwclock -s` at `ui/main.c:1701`, then `timekeep_boot()`. A payload-side guard in `S97diskos_install` would fix the S97 timestamps but needs a reflash to take effect, and can copy a garbage RTC if it ever hangs; not worth it for log cosmetics. |
| `weather: no usable data (resp='')` | diskOS `ui/weather.c` | The fetch runs at UI start before the Wi-Fi lease and retries with 20 s backoff (`weather_poll`). The device was unreachable at the end of the session, so the retry could not be confirmed live. |

## Device run and the flash image

The Disc was powered on at 19:43 and the pre-fix baseline was captured: the fresh boot still showed the two `Volume was not properly unmounted` lines, as expected (they describe the previous power-off, which used the old build).

Hot-loaded at 19:44 with `~/diskos/diskos-hotload.sh /home/moo/diskos/diskos/ui/mq_ui`:

```
>> staged 24d88617ef5bc7b01d6611b886e2e7e3
ok=1 attempts=1
24d88617ef5bc7b01d6611b886e2e7e3  /proc/1538/exe
```

The card stayed mounted, the player was up, and the relaunch logged `boot: player ready after 606 ms`.

A power-off was deliberately NOT done: S97 verifies `/usr/data/mq_ui` against the baked manifest on every boot, so the 8-byte-larger hot-load would be quarantined and the flashed (old) build restored. The hot-load is temporary by construction.

Persistent image built and validated instead (installer stopped at E110 because no device was in mask-ROM mode):

```
cd ~/diskos/diskos-installer
./diskos-installer install \
  --firmware ~/Downloads/SNOWSKY_DISC_update_20260909_v257.zip \
  --ui /home/moo/diskos/diskos/ui/mq_ui --variant public

✓ image built: ~/.local/share/diskos-installer/build/diskos_public.bin
  100663296 bytes md5=750cfef369f07d3669a74919b9a52809
```

Verified inside the built squashfs: `/opt/diskos/mq_ui` sha256 `96c426442550c1aaea152a61d9f536c586930c4bd3075f28fe67737c37cef2c6`, identical to the built UI, and `/etc/diskos_manifest` records `SIZE=4349824` with that same SHA256.

## Not verified

- After the sticky bit was cleared, the final proof is one more power-off from Quick Settings and a power-on: the clean unmount should clear `0x41` and the next boot should print no `Volume was not properly unmounted`. That run had not happened when this note was written.
- The 4 s maximum block during shutdown is not measured; the UI shows "Shutting down..." during it.
- Clearing the bit without `fsck.vfat` assumes the volume was consistent. No fsck was run on the card.
- A hardware long-press power-off bypasses `power_shutdown_request()` entirely, so it will mark the volume dirty again and the warning returns until the next fsck or bit clear. diskOS has no boot-time repair for that case.

## References

- [[diskos-boot-log-error-check-2026-11-17]]
- [[diskos-boot-starting-state-and-boot-net-errors-2026-11-10]]
- [[diskos-persistent-clock-timekeep]]
- [[fiio-snowsky-disc-diskos-flash-fedora]]
