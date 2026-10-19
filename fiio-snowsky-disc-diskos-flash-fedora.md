---
type: how-to
tags: [fiio, snowsky-disc, diskos, dap, ingenic, x2000, mask-rom, flashing, squashfs, udev, fedora]
created: 2026-10-19
last_verified: 2026-10-19
status: current
---

# Flashing diskOS onto a FiiO Snowsky Disc from Fedora 43

Installed [diskOS](https://github.com/b0hemia/diskos) **v1.2.1** (Public variant) onto a FiiO Snowsky Disc DAP running stock firmware **V2.57**, from the Fedora 43 desktop, using the CLI installer. Flash succeeded and verified (`result: 0x600DF10C [F001] SUCCESS`).

One real snag: the **bundled `mksquashfs` in the v1.2.1 Linux release crashes with SIGFPE** on this host, failing the installer's LZO self-check (E104). Fix was to move the bundled squashfs tools aside so the installer falls back to Fedora's system `squashfs-tools`.

## Prerequisites

- Official, unmodified FiiO firmware ZIP matching the version currently on the Disc. Supported bases: V2.09, V2.28, V2.40, V2.57. Used: `~/Downloads/SNOWSKY_DISC_update_20260909_v257.zip` (V2.57).
  - The on-device writer refuses to write (nothing touched) if the Disc's kernel/recovery doesn't match the selected firmware.
- Python ≥ 3.8 (had 3.14.7), `libusb1`, `squashfs-tools` (Fedora's 4.6.1 has LZO). `python3-tkinter` only needed for the GUI — skipped, used CLI.
- Good USB cable, ~20 min uninterrupted, host must not sleep (the installer uses `systemd-inhibit` itself).

## Steps

### 1. Put the Disc in mask-ROM (flash) mode

Power off, hold **Volume Down**, plug in USB. Screen stays black. Check:

```bash
lsusb | grep -i ingenic
# Bus 001 Device 015: ID a108:eaef Ingenic Semiconductor Co.,Ltd Ingenic USB BOOT DEVICE
```

### 2. Download + verify the installer

```bash
mkdir -p ~/diskos && cd ~/diskos
gh release download v1.2.1 -R b0hemia/diskos -p 'diskos-installer-linux-x86_64.tar.gz' -p SHA256SUMS
cat SHA256SUMS; sha256sum diskos-installer-linux-x86_64.tar.gz
# linux tarball: d4e0a37a01061235810a0ff817868faacbf692ccd67a4588c868d4b91267bca9 (matched)
tar xzf diskos-installer-linux-x86_64.tar.gz
cd diskos-installer
```

(`grep linux SHA256SUMS | sha256sum -c -` reported "no properly formatted checksum lines" — that was the rtk output-filter hook mangling the pipe, not a bad file; compared manually instead.)

### 3. Setup (no sudo)

```bash
./install.sh            # creates .venv, installs pyusb + pycryptodome
./diskos-installer doctor
```

Doctor reported two failures:

```
✗   squashfs LZO pack/extract check: FAILED - [E104] ... using '.../vendor/linux-x86_64/mksquashfs'
✗ device: this user cannot open it (/dev/bus/usb/001/015) - USB permissions
```

### 4. Fix E104 — bundled mksquashfs crashes

Reproduced the installer's exact check by hand:

```bash
S=$SCRATCH/sq; mkdir -p $S/src
head -c 300000 /dev/zero | tr '\0' 'a' > $S/src/p.bin
vendor/linux-x86_64/mksquashfs $S/src $S/p.sqfs -comp lzo -b 131072 -no-xattrs -all-root -noappend -processors 1
# ... 100% ... Floating point exception (core dumped)   rc=136
```

Same command with Fedora's `/usr/sbin/mksquashfs` + `unsquashfs` → rc=0, round-trip bytes identical. Not disk space (`/tmp` had 31G free).

`diskos_installer/bundle.py:native()` prefers a vendored tool if the file *exists* (even if broken), and only falls back to the system copy on PATH for squashfs tools when the vendored file is **absent**. So:

```bash
cd vendor/linux-x86_64
mv mksquashfs mksquashfs.broken
mv unsquashfs unsquashfs.broken   # keep both tools from the same (system) version
```

Doctor then showed `mksquashfs: /usr/bin/mksquashfs (system)` and `squashfs LZO pack/extract check: OK`.

### 5. Fix USB permissions — udev rule

```bash
sudo cp udev/70-diskos-maskrom.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Rule content: `SUBSYSTEM=="usb", ATTR{idVendor}=="a108", ATTR{idProduct}=="eaef", MODE="0660", TAG+="uaccess"`. No replug was needed — `getfacl /dev/bus/usb/001/015` showed `user:moo:rw-` right after the trigger. Doctor now all green.

### 6. Flash

```bash
./diskos-installer install \
  --firmware ~/Downloads/SNOWSKY_DISC_update_20260909_v257.zip \
  --variant public -y > flash.log 2>&1
```

Sequence in the log:

1. Extract stock rootfs (`stock_rootfs.squashfs`, 80,596,992 bytes).
2. Build `diskos_public.bin` (100,663,296 bytes = 96 MiB, 768 NAND blocks).
3. Stage the stock rootfs as backup `g0001` (committed only after the base check passes).
4. Mask-ROM flash: start 12:02:45, `usbboot exit=0` at 12:22:52 (~20 min).

Result:

```
scan: bad-blocks-found=2 list=[128, 522]
writer capacity: 768 blocks (image needs 768)
write: skipped=2 retried=0 worst=0
result: 0x600DF10C [F001] SUCCESS
✓ flash verified OK
backup g0001: committed
✓ diskOS flashed and verified. Power-cycle the device to boot it.
```

The 2 bad blocks are normal factory NAND bad blocks; the writer skips them.

Then: unplug, power on — diskOS installs itself on first boot.

## Why the flash takes ~20 minutes (and shows no real progress)

From `diskos_installer/flasher.py`: `usbboot` uploads the SPL + writer (`my_write6_dram.bin`) + image into the Disc's DRAM, starts the writer, then **waits a fixed `FLASH_WAIT` = 1080 s (18 min)** and only then reads a DONE marker back. There is no early-completion polling — the "Xm30s elapsed" lines are just a host-side timer. The writer itself hashes the ~96 MiB image and ~25 MiB of base partitions (firmware-base gate), then scans/erases/programs/verifies 768 blocks. Hard ceiling is the wait + 15 min (E303 if exceeded). If an outcome is ever unknown (E301–E303, E310, E321): leave the Disc powered + connected ≥25 min, don't retry, follow `RECOVERY.txt`.

## Backups / restore

- Saved stock rootfs: `~/.local/share/diskos-installer/stock/g0001/` — keep a copy of it.
- State: `~/.local/share/diskos-installer/state.json` (`phase: flash-verified`, `variant: public`).
- Use stock UI without reflashing: **Settings > System > Default UI > Stock**; hold **Volume Up** at power-on to boot the other UI once.
- Full removal: `./diskos-installer restore-stock` (or `restore-stock --firmware <zip>` if the saved backup is damaged).
- Updates 1.2.x: app-only OTA via **Settings > System > Update diskOS**; some fixes need a full reflash.

## Notes

- Never run the installer with `sudo` — it keeps per-user state under `~/.local/share/diskos-installer`.
- Don't redistribute generated `diskos_*.bin` images (contain FiiO's rootfs).
- Installer location on fedora: `~/diskos/diskos-installer` (bundled squashfs tools renamed `*.broken` there).

## References

- [b0hemia/diskos — README](https://github.com/b0hemia/diskos)
- [diskos docs/INSTALL.md — Linux packages, udev rule, error codes](https://github.com/b0hemia/diskos/blob/main/docs/INSTALL.md)
- [diskos release v1.2.1](https://github.com/b0hemia/diskos/releases/tag/v1.2.1)
