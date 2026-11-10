---
type: investigation
tags: [diskos, snowsky-disc, usb-gadget, configfs, acm, serial, ecm, rndis, usb-debug, source-menu, dwc2, hot-load]
created: 2026-11-10
last_verified: 2026-11-10
status: current
---

# diskOS "USB Debug" row in the Source menu: serial shell over the USB cable, and why USB Ethernet is impossible on this kernel

Repo `/home/moo/diskos/diskos`, work in the worktree `/home/moo/diskos/diskos-usbdebug`, branch `feat/usb-debug-source` (base `0f3c5a5` = `dev` at the time; `dev` has since moved to `53f6108`). Request: "add feature to debug via USB, add it in source menu", with one gadget carrying a serial shell **and** a USB Ethernet link so `ssh` works over the cable. Companion docs: [[diskos-srcswitch-source-mode-switch-extraction]], [[diskos-usb-dac-exit-deadlock-roles-and-volume-fix]], [[diskos-usb-audio-reverse-engineering-mq-player]], [[diskos-persistent-debug-checkboxes]], [[diskos-hotload-gotchas-test-outputs-usb-storage-reboot]], [[diskos-disc-hotload-watchdog-snowsky-logo-hang]], [[snowsky-disc-usb-dac-uac2-android-and-firmware-decompile]]. In the repo: `docs/USB_DEBUG.md` (the design, kept with the code).

**Result: the serial half is built and works on the Disc with a Linux PC attached; the Ethernet half is impossible without a new kernel and was not faked.**

## Time estimate

Measured from the device clock and tool output in the continuing session (the earlier agent's part, which only wrote the first `diskos-debug.sh` draft, is not counted): about 1 h 10 min wall clock in total, of which waits were: podman cross build 15.7 s (full, `-j4`), `make run` about 26 s, `make run-py` about 20 s, root unit tests 18 s, one hot-load about 15 s plus 9-10 s for the UI to come up, `usb-on` 2.2 s on the Disc (0.14 s `usb-off`), PC enumeration under 2 s. Nothing here is a human-speed figure.

## 1. What the kernel can do (read-only, `ssh disc`)

```sh
zcat /proc/config.gz                      # No such file: the kernel has no config.gz
ls /lib/modules                           # No such file; lsmod shows only bcmdhd/soc_*/utils; modules live in /module_driver
grep configfs /proc/filesystems           # nodev configfs   (but NOT mounted: ls /sys/kernel/config is empty)
dmesg | grep -i -E 'dwc2|gadget|udc'      # dwc2 13500000.otg_new: bound driver configfs-gadget ; android_work: sent uevent USB_STATE=...
grep -E 'usb_func$' /proc/kallsyms        # acmusb_func gserusb_func obexusb_func mass_storageusb_func ffsusb_func uac1usb_func uac2usb_func hidusb_func mtpusb_func ptpusb_func  (exactly 10)
grep -i -E 'ecm|rndis|ncm|gether|eem_' /proc/kallsyms   # only strcasecmp-type false hits
for p in tun_chr_open ppp_register_channel ppp_input slip_open; do grep -c " $p" /proc/kallsyms; done   # 0 0 0 0 ; ls /dev/net: No such file
which pppd slattach                       # none (busybox has udhcpd/udhcpc/ip/ifconfig, dnsmasq exists, none of it matters without a netdev)
```

The decisive test is the kernel's own function registry, through configfs on a scratch gadget (nothing bound, removed again; script in the session scratchpad, run over `ssh disc 'sh -s'`):

```sh
mount -t configfs none /sys/kernel/config; mkdir /sys/kernel/config/usb_gadget/zz_probe
for f in acm.0 gser.0 mass_storage.0 uac2.a hid.0 ffs.x obex.0 mtp.0 ecm.0 rndis.0 ncm.0 eem.0 geth.0 subset.0 midi.0 loopback.0 uvc.0 printer.0; do
  mkdir /sys/kernel/config/usb_gadget/zz_probe/functions/$f && echo "OK $f" && rmdir ...; done
rmdir /sys/kernel/config/usb_gadget/zz_probe; umount /sys/kernel/config
```

Result: `acm.0 gser.0 mass_storage.0 uac2.a hid.0 ffs.x obex.0 mtp.0` OK; `ecm.0 rndis.0 ncm.0 eem.0 geth.0 subset.0 midi.0 loopback.0 SourceSink.0 uvc.0 printer.0` all `No such file or directory`. So ECM, RNDIS, NCM, EEM are absent and cannot be loaded. The two ways around it are closed as well: no TUN (a FunctionFS userspace Ethernet function needs one) and no PPP/SLIP (an IP link over the ACM port needs one). **What would be needed:** a kernel with `CONFIG_USB_CONFIGFS_ECM` (+ `u_ether`) or `CONFIG_USB_CONFIGFS_RNDIS` (and `CONFIG_TUN` for a userspace route), or matching out-of-tree modules for the vendor 4.4.94 tree - i.e. a kernel flash. The vendor kernel source/build tree is not in the repo, so it was not attempted.

## 2. How the stock player owns the gadget (decompile, `~/diskos/firmware-decompiled`)

All gadgets are plain configfs, built by the Player itself (`part002_004586cc.c`): `FUN_0046d240` (UAC: `mount -t configfs none /sys/kernel/config`, `mkdir usb_gadget/uac_demo`, `uac2.a`, VID 0x2972 PID 0x0158), `FUN_0046dec0` (storage: `storage_demo`, `mass_storage.0`, `lun.0/file=/dev/mmcblk0`, VID 0525 PID a4a5), `FUN_0046e510` (`adb_demo`, FunctionFS, no callers). Stopping (`FUN_0046dd5c`, `FUN_0046e454`) opens `UDC` for write, removes links/functions/config/strings/gadget with `rmdir` and runs `umount /sys/kernel/config`. That is why configfs is normally not mounted. The mode thread `FUN_004e5af4` (`loop_mode_handle_thread`, 100 ms poll) acts **only when the `0642` selector value changes**: on a change it stops the old gadget, writes `device` (or `host` for selector 5) to `/sys/class/usb_role/13500000.otg_new-role-switch/role` and builds the new one (`sleep(1)` after the role write). Selector 0 builds nothing; `0642 0` while already 0 is a no-op. The kernel emits `android_work: sent uevent USB_STATE=CONNECTED/CONFIGURED/DISCONNECTED` for any configfs gadget and the Player logs them (`EVENT_USB_STATE_*`) but does nothing harmful with them in Local.

Also found: the flashed Disc is the **public** variant and has no `S99usbserial` in `/etc/init.d` (`/etc/diskos_manifest`: `VARIANT=public`); the installer copies `S99usbserial` only for `--variant dev` (`diskos_installer/imagebuild.py`). `/usr/project/diskos-debug.sh` on the flashed image is older than the repo (no `key-off`), so the new verbs need a flash.

## 3. Design

USB Debug is an **overlay on Local**, not a Source mode: the Player stays at selector 0 / Local work mode, the UI sends **no** Player frame, nothing is saved (`src_mode`) and nothing is restored at boot. diskOS owns the UDC only while the row is on:

| Mode | Owner | Gadget |
|---|---|---|
| Local | nobody | none |
| USB DAC / USB Storage | Player | `uac_demo` / `storage_demo` |
| USB Audio | Player | none (host role) |
| USB Debug | diskOS (`diskos-debug.sh usb-on`) | `diskos_dbg`: one `acm.0`, VID:PID 0525:a4a7, class 02 |

Enter: refuse if a stock gadget exists; go via Local first (existing `via_local`) when the source is not Local, the USB Audio route is on or the card is exported; run `usb-on` detached (45 s limit); the UI trusts the UDC attribute, not the exit code. Leave: `usb-off` detached (shell, empty write to `UDC`, remove directories), +1 s margin, then the normal `source_switch`; for Local nothing is sent. Failure: a failed start cleans up and toasts; a failed stop keeps the state ON, abandons the pending switch and sends nothing, so the Player never changes the selector with our gadget bound. The USB Audio route (host role) is refused while USB Debug is on (guard in `outroute_pick`, hook `usb_debug_active`). A UI restart adopts a bound gadget; an outside `usb-on`/`usb-off` is noticed within a second.

Dev image boot hook `S99usbserial`: the old 2 s loop that re-bound `serial_demo` made the stock gadgets unable to bind at all on a dev image (and would fight every switch). It is now one bounded `usb-on` at boot (3 tries, none after exit 2), after which the UI owns the port.

## 4. Steps taken, in order

```sh
cd /home/moo/diskos/diskos-usbdebug && git status && git diff            # the earlier agent's draft: usb-on built TWO ACMs (acm.1 reserved for ssh, never used)
# reviewed critically: dropped acm.1/ttyGS1, the ROOTHOME edits to key-on/key-off (not needed), the serial_demo refusal; kept the env-var test seams
tests/test_usbdbg_script.py   # new: runs usb-on/usb-off/usb-status against a fake configfs/UDC/role tree with PATH shims (rmdir, mount, umount, fuser, sleep)
python3 -m unittest tests.test_usbdbg_script          # 23 tests; also mutation-checked (changed idVendor in the script, the test failed)
# UI: ui/usbdbg.c/.h (no LVGL, env struct), srcswitch.c (dbg_enter, dbg_leave_begin, dbg_exit_tick), modes.c (row 4, USB Audio row 4 -> 5), outroute.c (guard), main.c (env), Makefile
cd ui/tests && CC=clang make run && CC=clang make run-py     # srcswitch_test: 23 new scenarios; storage_test.py updated for the new link
cd ui && python3 tools/generate_i18n.py                       # after adding 17 rows to i18n/strings.tsv (translations for all 10 languages)
cd ui && podman run --rm --userns=keep-id -v "$PWD:/src:Z" localhost/diskos-ui-builder:latest sh -c 'make -j4 CROSS=$CROSS EXTRA_CFLAGS=-DDISKOS_TEST_OUTPUTS'
```

Device tests (every sequence wrapped in `flock /tmp/diskos-disc.lock`; the Disc has no sftp, so files go over `ssh disc 'cat > file' < local`):

```sh
ssh disc 'cat > /usr/data/diskos-debug.sh.test-20261110 && chmod 755 ...' < payload/diskos-debug.sh   # a new file, no device file overwritten
ssh disc 'mount -o bind /usr/data/diskos-debug.sh.test-20261110 /usr/project/diskos-debug.sh'        # runtime overlay; umount restores the flashed script (md5 4efefbac...)
~/diskos/diskos-hotload.sh ui/mq_ui                      # after: uptime >= 45 s and "reached main loop" in /usr/data/diskos_boot.log
sh /usr/project/diskos-debug.sh usb-on                   # on shell=on  (2.2 s)
python3 hostserial.py                                    # PC side: wait for /dev/ttyACM0, raw 115200 termios, send 'echo HOSTMARK_$((6*7)); uname -a; id'
sh /usr/project/diskos-debug.sh usb-off                  # off (0.14 s)
```

Results on the Disc (public image, V2.57, Linux 4.4.94) with its USB port cabled to this Fedora PC: PC kernel log `usb 1-4: New USB device found, idVendor=0525, idProduct=a4a7 ... Product: diskOS USB Debug`, `cdc_acm 1-4:1.0: ttyACM0`; the shell answered `HOSTMARK_42`, `uname`, `uid=0(root)`; `usb-off` left no gadget directory, no `ttyGS0`, no stray process, configfs unmounted, UDC `not attached`. From the picker with real taps: row selected with a check mark, sub-label "Open /dev/ttyACM0 on the PC", panel "On the PC: / picocom -b 115200 /dev/ttyACM0 / Root shell, no password"; the USB Audio row refused with "Leave USB Debug first"; Local Playback showed "Leaving USB Debug..." and cleared the mark; boot log lines `usb debug: on (host connected)`, `leaving, then mode 0`, `gadget gone, continuing the switch to mode 0`. A UI relaunch with a gadget bound logged `gadget already bound at start, adopted (host connected)`; `usb-on` from SSH logged `adopted a gadget that was started from outside` and `usb-off` logged `the gadget was removed from outside`.

## 5. Dead ends and incidents (read before touching the shared Disc by touch)

- **Blind taps are dangerous.** A touch script assumed the picker was scrolled so that USB Debug sat at y=250; on a freshly opened picker that row is USB Storage, so the tap exported the card to the PC (`sda 59.5G File-Stor Gadget`, not mounted by udisks). Leaving USB Storage is **by design a full Disc restart** ([[diskos-hotload-gotchas-test-outputs-usb-storage-reboot]] section 2), so the Disc rebooted (`uptime` 0 min) and every hot-loaded build, including another agent's, was replaced by the flashed UI. Another swipe changed the brightness slider (22 vs 14; restored by dragging it back) and a tap toggled the Key SSH checkbox on the Debug Mode page ("did not stop": the flashed script has no `key-off`, so nothing changed). Mitigation that worked: gate every tap on a screenshot comparison (`gate.py`: PIL crop of the target row vs a reference image, abort when the difference is above 8), and do not run touch tests while another agent also drives the screen. The log also shows taps from the other agent interleaved with mine: the lock only serialises scripts, not the screen.
- Several of my first tests were wrong, not the code: `ps | grep ttyGS` counted the ssh shell's own command line; a log check at boot looked at a UI build that predated the feature.
- A race seen once: while the Player was building `storage_demo` (after the accidental tap), `usb-on` saw no stock gadget yet, built ours and failed to bind (`err: could not bind`, UDC `EBUSY`), then cleaned up. In the real UI flow the stock gadget is checked after the source is Local, so the window does not exist; the role file is no longer written back on `usb-off` for exactly this reason.
- Why not restore the role: the Player leaves `device` after every mode, and a write-back of `none` could race a Player already switching.

## 6. Host-side recipe (for the user)

```sh
ssh disc ...                                        # or: just use the Disc: Quick Settings > source > USB Debug
ls /dev/ttyACM*                                     # appears 1-2 s after the row says "Open /dev/ttyACM0 on the PC"
picocom -b 115200 /dev/ttyACM0                      # or screen / tio ; the user needs the dialout group; Windows: the new COM port in PuTTY (Serial)
lsusb | grep 0525:a4a7                              # "Linux-USB Serial Gadget (CDC ACM mode)", product "diskOS USB Debug"
```

## 7. Not verified

A flashed image (the script was bind-mounted for the test), a cold boot, a dev-image boot hook, USB DAC / USB Storage / USB Audio entered after USB Debug (host tests only; the first unmodified USB Storage round trip happened by accident and worked, including the restart), audio playing while the gadget goes up and down (no track queued on the Disc), macOS/Windows hosts, a charger-only cable. The public-image decision (the row exists in public builds, passwordless root shell while on) is the maintainer's to confirm: `SECURITY.md`/`INSTALL.md` were updated for it; gating on `VARIANT=dev` is a one-line change.

## References

None external: everything came from the live Disc, the firmware decompile, the repo and the earlier write-ups linked above.
