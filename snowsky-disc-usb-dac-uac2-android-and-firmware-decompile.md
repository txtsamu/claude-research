---
type: investigation
tags: [fiio, snowsky-disc, usb-dac, uac2, android, ghidra, reverse-engineering, firmware, configfs]
created: 2026-10-22
last_verified: 2026-10-22
status: current
---

# Snowsky Disc: USB DAC mode (UAC2 gadget) vs Android, and the full firmware decompile

## What the Disc does in USB DAC mode (read from the live Disc + the stock player)
Live read-only checks (`ssh disc`, key auth, port 2222) with USB DAC mode on and an Android phone attached:
```sh
cat /sys/class/udc/*/state                       # configured / suspended / not attached
cat /sys/class/usb_role/*/role                   # device in DAC mode
G=/sys/kernel/config/usb_gadget/uac_demo; cat $G/idVendor $G/idProduct $G/bDeviceClass; ls $G/functions
for f in $G/functions/*/*; do [ -f $f ] && echo "$f=$(cat $f)"; done
cat /proc/asound/cards; cat /proc/asound/card1/pcm0c/sub0/status /proc/asound/card1/pcm0c/sub0/hw_params
dmesg | grep -i -E "dwc2|gadget|uac|afunc_set_alt|otg|role"
```
Findings:
- The gadget is **UAC2** (`uac2.a`), not UAC1 (the player has a dead uac1.a branch, `uac_start(mode, srate)` at 0x46d240 is always called as `(2, 0xac44)`). Gadget `uac_demo`: VID 0x2972 PID 0x0158 "FiiO"/"SNOWSKY DISC", bcdUSB 0x200, **bDeviceClass 0/0/0** (no IAD composite class), config c.1 bmAttributes 0x80 MaxPower 50, `c_chmask=3 c_ssize=4` (S32_LE capture), `c_srate` 44100 written but the live value follows the host (48000), `p_chmask=3 p_ssize=2 p_srate=48000`, ALSA card `FIIOUAC2Gadget`.
- Entering DAC mode: `0642 2` -> player sets `usb_role` to device, charger OTG off (`/dev/sgm41513` ioctl 0x20004928), builds the gadget, binds UDC `13500000.otg_new`. `0657 1` = USB DAC work mode (our fix e07dfee: 8 was the silent bug).
- The Disc has a **separate saved volume per work mode** (sysconfig: VOLUME=53 local, BTSINK_VOLUME=60, UAC_VOLUME=27 of 120). Android sees no hardware volume control on the gadget and attenuates in software, so DAC mode starts quiet: raise the Disc volume key in DAC mode and the phone's media volume.
- On a Redmi Note 12 Pro (HyperOS 2.0 / Android 14) DAC mode **worked**: the phone enumerated it (`dumpsys usb` shows vid 10610 pid 344 = 0x2972/0x0158, interface class uac2), probed it with ~12 quick set_alt 0/1 toggles (Android probing rates), then streamed 48 kHz S32_LE (`udc state: configured`, `pcm0c RUNNING`, BAIC playback started). Android logs `UsbACInterface: Unknown Audio Class Interface subtype:0xa` (UAC2 clock-source descriptor) - harmless.
- Phone side commands used: `adb connect <ip>:<wireless-debugging-port>` (find the port with `nmap -Pn -p 30000-49999 --open <ip>`; works without pairing if the PC key was paired before), then `dumpsys usb`, `dumpsys audio | grep -i usb`, `logcat -d | grep -i -E "UsbAlsa|AudioALSAPlaybackHandlerUsb|UsbACInterface"`.
- Untested hypotheses for phones that do NOT work (changes would be made on the live gadget: `echo "" > UDC`, edit, `echo 13500000.otg_new > UDC`; never while a host is `configured` and leaving the mode - `close_pcm_capture_thread` deadlock): (A) `bDeviceClass 0xEF / bDeviceSubClass 0x02 / bDeviceProtocol 0x01`; (B) `c_ssize=2` + `p_chmask=0` (player capture code assumes S32_LE, needs checking); (C) bmAttributes 0xC0, MaxPower 2. Android's documented host support is "a subset of UAC1" (AOSP) and UAC2 behaviour varies by vendor.

## Full decompile of the stock firmware (V2.57)
Private repo: `txtsamu/snowsky-disc-firmware-decompiled` (decompiled pseudo-C only; no binaries/firmware inside). Local copy `~/diskos/firmware-decompiled`.
- Inputs: stock rootfs `~/.local/share/diskos-installer/build/stock_rootfs.squashfs` (the installer decrypts the OTA chunks with `_openssl_aes_decrypt`, key in `diskos_installer/imagebuild.py`); kernel = the `xImage.*.enc` chunks decrypted the same way: U-Boot legacy uImage Linux-4.4.94, MIPS, zboot stub + gzip, vmlinux ~9.9 MB at 0x80010000.
- Userland: 411 unique ELFs -> TIER1 13 / TIER2 14 decompiled (mq_player 6825 functions, mq_ui 6289, bsa_server, libroon, libfiio_decoder, bluetoothd, soc_*.ko, ...), TIER3 384 third-party inventoried only. Ghidra 12.1.4 headless. **Needs language `MIPS:LE:32:fp64`** (a locally compiled sleigh variant with 64-bit FPRs): the stock `MIPS:LE:32:default` cannot decode `ldc1/sdc1/*.d` on odd FP registers used by this XBurst2 toolchain and truncated ~100 functions per large binary. Also a post-script (`FindFuncs.java`) creates functions at `addiu sp` prologues that no function covers: stock analysis missed ~25% of pointer-only functions (mq_player `.text` coverage 59% -> 96%). Scripts: `/var/tmp/moo-ghidra/scripts`, runner `run_one.sh`.
- Kernel: `vmlinux-to-elf` (pip, in a venv) recovers 53k kallsyms symbols and an ELF; symbols verified against the live Disc `/proc/kallsyms` (52,687 of 52,698 shared names identical). 734 vendor-specific functions (f_uac2/u_audio/afunc_*, SGM41513, AW35615, CS43131, CW221x, Ingenic X2000 glue, otg/role) decompiled. The vendor debug prints ('pengweizhong') come from `configfs_composite_bind` (0x80422d70), which Ghidra has no xref for: found by scanning lui/addiu pairs.
- Gaps: stripped binaries (mostly `FUN_xxxx` names, guessed types); PLT stubs not decompiled; physical key drivers not in the kernel selection; loadable modules loaded as relocatable ELF.

## References
- [FiiO: USB DAC function on the DISC](https://fiio.com/newsinfo/1111810.html)
- [AOSP: USB digital audio](https://source.android.com/docs/core/audio/usb)
- [f_uac2 validation patch discussion](https://lkml.iu.edu/hypermail/linux/kernel/2105.1/01712.html)
- [Mobile Audiophile: Snowsky Disc review](https://mobileaudiophile.com/daps/snowsky-disc-review-fiios-retro-mini-touchscreen-dap/)
- [Headfonia: FiiO Snowsky Disc review](https://www.headfonia.com/fiio-snowsky-disc-review/2/)
- [Ghidra releases](https://github.com/NationalSecurityAgency/ghidra/releases)
