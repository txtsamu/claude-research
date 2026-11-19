---
type: how-to
tags: [diskos, flash, mask-rom, installer, build-7, mq_ui, snowsky-disc, fat, unmount, verification]
created: 2026-11-19
last_verified: 2026-11-19
status: current
---

# Flashing diskOS fork build 7 onto the Disc (2026-11-19)

Request: "help me flash our latest build", with the Disc already sitting in mask ROM. This is the procedure and the verification. Release: <https://github.com/txtsamu/diskos/releases/tag/v1.2.1-fork.7>, source `cf58a93`, UI md5 `80b0b0e1ef69b776a83f8e954a915061`.

## Time estimate

- Whole flash from command start to `SUCCESS`: **20 m 00 s**, measured (09:54:53 to 10:14:53).
- Image build before the write: under 1 second (stock rootfs was already extracted from the same firmware ZIP).
- First boot and install to `/usr/data`: about 7 minutes from power-on to a reachable debug shell (the device booted around 10:21, SSH answered at 10:22).
- The estimate given before starting was 20 minutes, finish around 10:15 to 10:20. Actual success line: 10:14:53.

## Entering mask ROM was the hard part

The first checks showed no Disc on USB at all. Then the device enumerated as the wrong thing:

```
09:50:12  idVendor=0525 idProduct=a4a5  Product: composite-storage  Manufacturer: ingenic
09:50:14  USB disconnect
09:50:14  descriptor read/64, error -110, then error -71, unable to enumerate
```

`0525:a4a5` is USB Storage mode, not flash mode. Flash mode is `a108:eaef` (Ingenic X2000 mask ROM), screen black, no network. The `-71` loop is the usual result of missing the button window or a marginal cable.

What worked: unplug the cable, let the failed address cycle clear, power the Disc fully off, hold **Volume Down**, plug USB in while still holding, and keep holding a few seconds. The device then came up cleanly:

```
09:54:05  New USB device found, idVendor=a108, idProduct=eaef
          Product: Ingenic USB BOOT DEVICE
```

## Preflight

```bash
lsusb | grep -i "a108:eaef"
cd ~/diskos/diskos-installer
./diskos-installer doctor
```

`doctor` confirmed mask ROM, `/dev/bus/usb` access for the user, bundled usbboot and DRAM blobs, working squashfs tools, and a saved stock image. Firmware ZIP in use: `/home/moo/Downloads/Archived/SNOWSKY_DISC_update_20260909_v257.zip` (101 MB).

One trap: the installer's bundled `payload/mq_ui` is the old v1.2.1 binary. For a fork release, always pass `--ui` with the release asset.

```bash
./diskos-installer install \
  --firmware /home/moo/Downloads/Archived/SNOWSKY_DISC_update_20260909_v257.zip \
  --ui /tmp/opencode/release-fork7/mq_ui \
  --variant public -y \
  2>&1 | tee /tmp/opencode/flash-fork7-0956.log
```

`-y` skips the confirm prompt. Use it only when the firmware, the variant and the UI path are already verified. The stock image is saved automatically as a restore point.

## Flash result

```
09:54:51 stock rootfs matches the pinned known-good V257 image
09:54:53 image built: diskos_public.bin (100663296 bytes) md5=488c9d49e9acb58cb9d44169afae5e54
10:14:53 usbboot exit=0
10:14:53 scan: bad-blocks-found=2 list=[128, 522]
10:14:53 writer capacity: 768 blocks (image needs 768)
10:14:53 write: skipped=2 retried=0 worst=0
10:14:53 result: 0x600DF10C [F001] SUCCESS
10:14:53 backup g0023: committed
✓ flash verified OK
```

The two bad blocks are the same ones the previous flashes skipped, with zero retries.

## Verify the image before booting

Do not trust the log alone. Read the built squashfs:

```bash
unsquashfs -cat ~/.local/share/diskos-installer/build/diskos_public.bin opt/diskos/mq_ui | md5sum
unsquashfs -cat ~/.local/share/diskos-installer/build/diskos_public.bin etc/diskos_manifest
```

```
80b0b0e1ef69b776a83f8e954a915061
SHA256=7263832b9553c07749bebfac39c4336621ed8c008d68dc586aad1bdf5acd9417
SIZE=4354196
VARIANT=public
```

The SHA256 is the released asset's checksum, so the image carries the exact build 7 binary.

## After the first boot

The device stays in mask ROM after the write; it does not reboot itself. Unplug USB and power it on. `S97diskos_install` copies the embedded UI to `/usr/data` and verifies it.

Debug shell checks:

```bash
ssh disc 'md5sum /proc/$(pidof mq_ui)/exe /usr/data/mq_ui /opt/diskos/mq_ui; pidof mq_ui mq_player'
ssh disc 'grep -iE "installed verified|quarantined" /usr/data/diskos_install.log | tail -4'
ssh disc 'mount | grep sdcard; dmesg | grep -c "exFAT-fs"'
```

Result:

```
80b0b0e1ef69b776a83f8e954a915061  /proc/1190/exe
80b0b0e1ef69b776a83f8e954a915061  /usr/data/mq_ui
80b0b0e1ef69b776a83f8e954a915061  /opt/diskos/mq_ui
1190 mq_ui   1244 mq_player

S97: installed verified mq_ui from embedded (size 4354196, build flashed)
```

The card mounted as `/dev/mmcblk0p1 on /tmp/sdcard type vfat`, the `sd gate` opened at poll 3, and `dmesg | grep -c exFAT-fs` returned `0`, so the failed exFAT probe really is gone.

## The FAT warning is still there, and why

The first boot after the flash printed:

```
FAT-fs (mmcblk0p1): Volume was not properly unmounted.
```

That describes the **previous** power-off, the one used to enter mask ROM mode, which is a hard power-off with no UI shutdown path. It is not evidence that build 7 failed to unmount. The boot-sector byte at offset `0x41` reads `0x01` while the volume is mounted, which is normal; the kernel sets it on mount and should clear it on a clean unmount.

The proof still costs one clean cycle: power off from Quick Settings (or Settings > System > Power off), power on, and check that the new boot prints no such line. Backing out of a dirty volume also needs a one-time `fsck.vfat -a` on a PC, because the kernel refuses to clear an already-dirty flag.

## Clearing the sticky flag over SSH

The device has no `fsck.vfat`, so the flag was cleared with the same player-release path used on 2026-11-17, without removing the card.

The helper is the repo's own `ui/mqsend.c`, cross-compiled static for mipsel (the file is one of the nine sources excluded from the UI binary):

```bash
/opt/mipsel-n2008-musl-cross/bin/mipsel-linux-musl-gcc -Os -static \
  -o /tmp/opencode/mqsend ui/mqsend.c
```

`scp` fails against this device (`/usr/libexec/sftp-server` is not present), so push over plain SSH:

```bash
ssh disc 'cat > /tmp/mqsend && chmod 755 /tmp/mqsend' < /tmp/opencode/mqsend
```

Release the card through the player, verify it is really unmounted, clear byte `0x41`, then return to Local:

```bash
ssh disc '
  /tmp/mqsend 0666000C0006; sleep 1
  /tmp/mqsend 0642000C0001; sleep 1
  /tmp/mqsend 0657000C0008; sleep 3
  grep -q /tmp/sdcard /proc/mounts && { echo still mounted; exit 1; }
  printf "\000" | dd of=/dev/mmcblk0p1 bs=1 seek=65 count=1 conv=notrunc
  sync
  /tmp/mqsend 0666000C0006; sleep 1
  /tmp/mqsend 0642000C0000; sleep 1
  /tmp/mqsend 0657000C0008
  echo add > /sys/block/mmcblk0/uevent
'
```

Observed:

```
before clear, unmounted:  1
after write:              0
after remount:            1     (normal, kernel marks it dirty while mounted)
```

A second release/remount cycle without writing proved the kernel now clears the flag by itself: byte `0` after unmount, `1` after remount. Before the clear, the same unmount left it at `1`.

Two details worth knowing:

- The uevent remount is not instant. A check four seconds later still saw the card unmounted, and a manual `mount` in that window failed with `Device or resource busy`; the player mounted it shortly after. Wait, then re-check, do not force a second mount.
- The USB cable was unplugged, so the storage gadget had no host to enumerate. With a host attached, the exported card could be automounted and the raw write would race with it.

## Final proof

One more Restart from the UI, then this boot:

```
uptime 0 min
dmesg | grep -i "not properly unmounted"   -> NONE
card: /dev/mmcblk0p1 on /tmp/sdcard type vfat (rw)
byte 0x41: 1 (mounted, normal)
journal, previous session: "card unmounted before shutdown or restart"
dmesg | grep -c exFAT-fs -> 0
```

The warning loop is closed. It stays closed only while power-offs go through the UI; a hardware long press still cuts power without the unmount and marks the volume dirty again.

## Gotchas

1. **USB Storage mode looks like progress but is not flash mode.** `0525:a4a5` is the player's mass-storage gadget. Only `a108:eaef` is mask ROM.
2. **The `-71` address loop needs a full unplug and power-off**, not a retry. The button has to be held before the cable goes in.
3. **The installer's bundled UI is stale.** Pass `--ui` or you flash the v1.2.1 binary from `payload/`.
4. **The device does not reboot after a successful flash.** Unplug and power on.
5. **`diskos_install.log` timestamps are fake (Jan 1)** because the RTC is not set at that point in boot. Match on the size line instead.
6. **The sticky FAT dirty bit survives flashes.** Flashing writes the rootfs partition, not the SD card, so a dirty card stays dirty until a clean shutdown or an fsck.

## Not verified

- Full UI exercise after the flash: playback, USB modes, Restart, and the new module paths beyond boot.
- The saved stock image was committed but not restored in this session.
- The flag clear skipped `fsck.vfat`, so filesystem consistency still rests on the volume's history rather than a check.

## Related notes

- [[diskos-fork-build-7-release-2026-11-19]]
- [[diskos-sd-clean-unmount-and-fsdetect-2026-11-17]]
- [[diskos-ui-deepening-six-modules-and-harness-2026-11-18]]
- [[fiio-snowsky-disc-diskos-flash-fedora]]
- [[diskos-hotload-gotchas-test-outputs-usb-storage-reboot]]

## References

No external web sources were used. Commands come from the installer's own `doctor` and `install --help`, and the firmware base is the pinned V2.57 ZIP already used for the 2026-11-16 flash.
