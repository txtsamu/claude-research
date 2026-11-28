---
type: build-log
tags: [diskos, snowsky-disc, flash, mask-rom, installer, dev, mq_ui, command-spawn, boot-splash]
created: 2026-11-28
last_verified: 2026-11-28
status: current
---

# Flash the `dev` checkpoint `82ffa18` onto the Disc

Repo: `txtsamu/diskos`, branch `dev`, flashed commit `82ffa18` (the post-merge regression fix). The flash used the
verified local binary, not a release asset. This note records the exact run and what was checked.

## Time estimate

Measured from the log timestamps:

| Step | Time | Kind |
|---|---|---|
| Preflight (`doctor`, `lsusb`) | about 10 s | estimate |
| Image build inside `install` | 2 s (`20:16:45` to `20:16:47`) | measured |
| Mask-ROM write and verify | 20 m 08 s (`20:16:47` to `20:36:55`) | measured |
| Total command | 20 m 10 s (`20:16:45` to `20:36:55`) | measured |

The estimate given before starting was "about 20 minutes, SUCCESS around 20:37". The actual `SUCCESS` line was
`20:36:55`. First boot to a usable UI is about 7 minutes, but that was not measured in this run.

## Why this image

`dev` at `82ffa18` fixes eight regressions from the module consolidation and had already passed the clean host suite and
the cross build. The binary was built from a clean tree at `20:12`:

```
md5    21c3f99ca03d054b72a3a5526555fce7
sha256 84725ec323a6720decb984bbd8d41c7cbcc6666cea2e09b0ef68cdd37423e747
size   5528880
```

A docs-only commit (`2f705ac`, `CHANGELOG.md` and `docs/UI_ARCHITECTURE.md`) followed the flash and did not change the
binary.

## Preflight

The Disc was already in mask-ROM mode:

```console
$ lsusb | grep -i "a108:eaef"
Bus 001 Device 015: ID a108:eaef Ingenic Semiconductor Co.,Ltd Ingenic USB BOOT DEVICE

$ ./diskos-installer doctor
20:16:32 version    : 1.2.1
20:16:32 host       : linux-x86_64 (Fedora Linux 43 (Workstation Edition)) (supported)
✓   usbboot, mksquashfs, unsquashfs, SPL and DRAM blobs present
✓ device: 1 in mask-ROM mode
✓ device: can be opened by this user (/dev/bus/usb/001/015)
20:16:32 diskOS installed via this tool: yes (variant=public, at 2026-11-28T10:15:12Z)
20:16:32 saved bone-stock image (for restore): yes
```

`doctor` reports `payload/mq_ui` as the default UI, which is stale. The flash must pass `--ui` explicitly.

## The flash

```sh
cd /home/moo/projects/diskos/diskos
./diskos-installer install \
  --firmware /home/moo/Downloads/Archived/SNOWSKY_DISC_update_20260909_v257.zip \
  --ui ui/mq_ui \
  --variant public -y \
  2>&1 | tee /tmp/opencode/flash-dev-82ffa18.log
```

The run was started in the background and left alone until the notification. Key lines:

```console
20:16:45 OTA dir: main_os/ota_v257
20:16:46 stock rootfs matches the pinned known-good V257 image (sha256 verified)
20:16:47 ✓ image built: .../diskos_public.bin (100663296 bytes) md5=04d80ed4a854157f81e109f36f40a37b
20:16:47 OTA updates: ON (key sha256 e19993de778056b8...)
20:16:47 stock image staged as backup g0028, pending the base check
20:16:48 base required on the Disc: V2.57 (recovery 18)
20:36:55 usbboot exit=0
20:36:55 scan: bad-blocks-found=2 list=[128, 522]
20:36:55 writer capacity: 768 blocks (image needs 768)
20:36:55 write: skipped=2 retried=0 worst=0
20:36:55 result: 0x600DF10C [F001] SUCCESS
20:36:55 ✓ flash verified OK
20:36:55 backup g0028: committed
```

The two bad blocks are the same ones earlier flashes skipped, with zero retries.

## Verify the written image

Do not trust the log alone. Read the built squashfs:

```sh
B=~/.local/share/diskos-installer/build/diskos_public.bin
unsquashfs -cat "$B" opt/diskos/mq_ui | md5sum
unsquashfs -cat "$B" etc/diskos_manifest
```

```console
21c3f99ca03d054b72a3a5526555fce7  -
SHA256=84725ec323a6720decb984bbd8d41c7cbcc6666cea2e09b0ef68cdd37423e747
SIZE=5528880
ARCH=mips-le
VARIANT=public
BUILT=2026-11-28T13:16:46Z
```

Both match `ui/mq_ui` and its manifest, so the image carries the exact checkpoint binary.

## Gotchas

- The bundled `payload/mq_ui` is not the build under test. Always pass `--ui <path>`, and check the baked
  `opt/diskos/mq_ui` md5 afterwards.
- The device does not reboot after a mask-ROM write. It stays in mask ROM until it is unplugged and powered on.
- The installer builds the image and writes it in one command. There is no separate "build only" step unless you answer
  `n` at the confirmation without `-y`.
- `-y` is only safe once the firmware, variant and UI path are verified. It skips the confirmation that repeats the
  OTA state and the consequence.
- If a flash result is unknown, keep power and USB connected for at least 25 minutes before recovery. That rule did not
  apply here (`SUCCESS` and `✓ flash verified OK`).

## Not verified

- Post-boot checks were not done when this note was written. Still to confirm: `/opt/diskos/mq_ui`, `/usr/data/mq_ui`
  and `/proc/<pid>/exe` all at `21c3f99c`, the `S97: installed verified` line in `/usr/data/diskos_install.log`, and the
  first-boot panel behavior (no Home frame before the splash, no splash stutter).
- Real Wi-Fi lease behavior, `wpa_cli -a` delivery, gesture feel and the book rollback still need the running device.

## References

No external web sources were used. Everything came from the repo and earlier notes:

- `docs/INSTALL.md` and `docs/DEV_WORKFLOW.md` (installer commands and the `--ui` override).
- `agents/AGENTS.md` (flash finish-time rule and the mask-ROM safety rules).
- Related notes: [[diskos-architecture-review-seven-findings-2026-11-28]],
  [[diskos-flash-build-7-2026-11-19]], [[diskos-wifisup-extract-2026-11-28]].
