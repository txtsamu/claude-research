---
type: investigation
tags: [ingenic, x2000, x1600, usb-boot, mask-rom, swb, boot-rom, fiio, snowsky-disc, diskos, flashing, spi-nand]
created: 2026-10-19
last_verified: 2026-10-19
status: current
---

# Ingenic X2000: reboot into USB boot (flash mode) from software — "SWB"

Goal: put the FiiO Snowsky Disc (Ingenic X2000) into its boot-ROM USB boot mode (`a108:eaef Ingenic USB BOOT DEVICE`, what the diskOS installer flashes through) **without** holding Vol-Down at power-on, so diskOS can offer "Restart to Flash Mode".

## Result

- **Entering USB boot from software works on the Disc.** Over root SSH:
  ```sh
  devmem 0x100000cc 32 0x42575302   # readback 0x42575302
  reboot
  ```
  → the PC enumerated `a108:eaef Ingenic USB BOOT DEVICE` **5 s** later, no button.
- **Flashing from that state fails with the stock diskOS writer**: the install started 18:38:20 from the SWB-entered state returned `18:58:27 base gate: 0xDEAD000A (the NAND was not in its power-on state ...) ✗ [E320] Nothing was written`. Nothing was written; the Disc kept its build.

### Ways to restore the NAND power-on state that were ruled out (2026-10-19)
| Approach | Result |
|---|---|
| SPI-NAND RESET (`0xFF`) | Already issued by the writer right before the gate (`nand_reset()`, `flash/my_write6.c:436`) — on GD5F2GM7 it does not restore the block-protect bits. (GigaDevice text "reset returns to power-on defaults" is from the GD5F1GQ5 part and its `66h`+`99h` reset.) |
| Kernel MTD lock before reboot | FiiO's 4.4 SFC-NAND driver implements no lock ops: `flash_lock -i /dev/mtdN 0 1` → `error 122 (Operation not supported)` on mtd0..7; `flash_lock -l /dev/mtd5 0 1` and `flash_unlock` → same. |
| Full power cycle | Restores the NAND but also clears CPM_SLPC → normal boot. |

Remaining option: make the writer accept the unlocked chip only when the boot ROM was entered deliberately via SWB (the V2.57 base-partition hash check still runs) — requires rebuilding `my_write6_dram.bin` and updating `WRITER_SHA256` in `diskos_installer/flasher.py`. Until then, flashing needs a power-off + Vol-Down.

## How the magic value was found

1. Generic searches ("Ingenic X2000 reboot into usb boot", "X1000 boot_sel reboot", Rockbox jztool) only document button combos; Rockbox's jztool README says USB boot "must be entered manually". thingino's wiki mentions forcing USB boot from a running system only by damaging the bootloader.
2. Lead: CatPlay firmware (Carlinkit car dongles, **Ingenic X1600**) — issue #21 shows their device reaching `a108:eaef` via `reboot2recovery.py`. Source:
   ```bash
   gh api 'repos/catplay-labs/catplay-firmware/contents/meta-carlinkit-mini/recipes-bsp/carlinkit-mini-flasher/files/reboot2recovery.py' --jq .content | base64 -d
   ```
   Their payload (delivered via an HTTP command-injection on the dongle; irrelevant when you already have root):
   ```
   devmem 0x100000cc 32 0x42575302; echo wdt > /proc/jz/reset/reset
   ```
3. GitHub code search for the register:
   ```bash
   for q in '42575302' '0x100000cc' 'jz/reset/reset' '100000cc devmem'; do
     gh api -X GET search/code -f q="$q" --jq '.items[] | .repository.full_name+"  "+.path'; done
   ```
   found two vendor scripts:
   - `dawmlight/vendor_ingenic` → `smartpen/rootfs-overlay/usr/bin/softburn` — board `smartpen_x2000_mmc`, `"board": "x2000"` in its `config.json`:
     ```sh
     # enter SWB software boot, usb boot.
     devmem 0x100000cc 32 0x42575302
     reboot
     ```
   - `SudoMaker/buildroot-loshark` → `user-overlay/usr/sbin/reboot-bootloader`: `devmem 0x100000cc 32 0x6275726e` (ASCII "burn"; same register, likely an older-generation variant).
4. Decoding: `0x42575302` little-endian = bytes `02 'S' 'W' 'B'` → **SWB = software boot**, mode byte `0x02` = USB boot. In the X2000 U-Boot headers shipped with diskOS (`spl-src/uboot-xburst-lpddr3-src.tar.gz`, `arch/mips/include/asm/arch-x2000/cpm.h`) offset `0xCC` of the CPM block (`0x10000000`) is `CPM_SLPC`; nothing in U-Boot uses it → read by the boot ROM. (U-Boot's own `common/boot_mode.c` uses a different scratch register, `CPM_CPSPR` `0x34`, with recovery/fastboot signatures — bootloader-level, not boot-ROM USB boot.)

## Open question: can the installer flash after a software entry?

diskOS's NAND writer (`flash/my_write6.c:442`) refuses unless the SPI-NAND (GD5F2GM7) is in its power-on state:
```c
if((b0 & 0x10u) == 0u || (a0 & 0x3Au) != 0x38u) return (dbg[G_RESULT] = 0xDEAD000Au), 0;   /* power-cycle and retry */
```
(`B0` bit 4 = ECC enabled; `A0` BP2..BP0 = 111 = every block write-protected.) Linux's NAND driver unprotects the chip; a SoC reset doesn't power-cycle the NAND. Seen today: a **second** flash in the same mask-ROM session (no power-off after the first) failed with
```
base gate: 0xDEAD000A (the NAND was not in its power-on state (ECC off or already unlocked)); Disc base seen: unknown
✗ [E320] Nothing was written.
```
The same check decides whether "Restart to Flash Mode" is usable for flashing. Test in progress (install started 18:38:20 from the SWB-entered state).

Idea if it fails: lock all MTD blocks from Linux (MEMLOCK ioctl / `flash_lock`) right before the SWB reboot so `A0` returns to `0x38`, instead of changing the writer.

## diskOS implementation (fork `txtsamu/diskos`, commit `f345950`)

Settings → System → **Restart to Flash Mode** (confirm modal). Reuses the Restart button's drain + `sync` + RTC-save path; right before `reboot(RB_AUTOBOOT)` it maps `/dev/mem` at `0x10000000`, writes `0x42575302` to `+0xCC` and verifies the readback (`swb_arm()` in `ui/settings.c`). Cancel / failure clears the flag so a later plain restart (e.g. the post-USB-Storage restart) can never land in flash mode. If the ROM ignored the value the Disc would just restart; Vol-Down remains the fallback.

## References

- [catplay-labs/catplay-firmware — reboot2recovery.py](https://github.com/catplay-labs/catplay-firmware/blob/master/meta-carlinkit-mini/recipes-bsp/carlinkit-mini-flasher/files/reboot2recovery.py)
- [catplay-firmware issue #21 — Ingenic USB BOOT DEVICE a108:eaef on X1600](https://github.com/catplay-labs/catplay-firmware/issues/21)
- [dawmlight/vendor_ingenic — smartpen softburn (X2000)](https://github.com/dawmlight/vendor_ingenic/blob/master/smartpen/rootfs-overlay/usr/bin/softburn) and [config.json](https://github.com/dawmlight/vendor_ingenic/blob/master/smartpen/config.json)
- [SudoMaker/buildroot-loshark — reboot-bootloader](https://github.com/SudoMaker/buildroot-loshark/blob/master/user-overlay/usr/sbin/reboot-bootloader)
- [ballaswag/ingenic-usbboot (X2000E, Creality K1)](https://github.com/ballaswag/ingenic-usbboot)
- [thingino wiki — USB Boot Mode](https://github.com/themactep/thingino-firmware/wiki/USB-Boot-Mode), [Ingenic USB Cloner](https://github.com/themactep/thingino-firmware/wiki/Ingenic-USB-Cloner)
- [Rockbox jztool README (X1000 USB boot)](https://git.lenord.me/len0rd/rockbox/raw/commit/0faf978c3dec53f62c0b1624e883e9ee03b9c788/rbutil/jztool/README.md)
