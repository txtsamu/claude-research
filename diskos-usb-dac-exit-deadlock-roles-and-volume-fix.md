---
type: troubleshooting
tags: [fiio, snowsky-disc, diskos, usb-dac, uac2, deadlock, usb-role, volume, firmware-decompile]
created: 2026-10-22
last_verified: 2026-10-22
status: current
---

# Snowsky Disc USB DAC: exit deadlock, wrong USB roles, quiet volume - findings and fixes

Branch `stock-plus-disco` of the fork (stock diskOS base + Disco's mailbox/spawn/config/crashlog + charging screen + usbhid). Verified on the Disc with a Redmi Note 12 Pro (HyperOS 2 / Android 14) as the host. Companion docs: [[snowsky-disc-usb-dac-uac2-android-and-firmware-decompile]], [[diskos-disc-hotload-watchdog-snowsky-logo-hang]]. Decompiled firmware (private): `txtsamu/snowsky-disc-firmware-decompiled`.

## 1. Quiet DAC mode = per-mode volume slots
The player keeps one saved volume per work mode in `/usr/data/fiio/db/sysconfig.db` (table SYSCONFIG, one row): VOLUME (3), AUDIO_VOLUME_SET (57, USB host audio), BTSINK_VOLUME (63), BT_SRC_VOLUME (64), UAC_VOLUME (65, USB DAC), AIRPLAY_MEM_VOLUME (66). The slot is picked by the 0642 gadget selector (2 = DAC), set asynchronously by the `mode_handle` thread - 0657 alone does not switch it. `0715000C<level>` only writes the ACTIVE slot (no command writes another slot) and is NOT clamped by MAX_VOL; the player sends NO a714 frame on a mode change, so the UI's cached volume is still Local's. The Android phone cannot help: the f_uac2 gadget has no feature unit (only clock-source controls), Android attenuates in software.
Fix (main.c `dac_volume_cb`, ~4.5 s after entering mode 1): send 0715 outright with the user's last DAC level (cfg `dac_volume`, saved from volume frames >8 s after entry) else the Local volume carried over; clamp to max_vol; `ui_set_volume` now clamps too; cfg `dac_match_volume=0` disables. (First attempt compared against st.volume = stale Local volume and silently skipped.)

## 2. "Phone is charging, DAC not connected" = wrong USB power/data roles
Symptom: `udc state=powered` forever, phone only charges. Charger regs showed `REG01=0x26` (OTG boost ON) and `REG08=0xe0` (VBUS_STAT=OTG): the Disc sourced 5 V while being a data *device*; the phone (`dumpsys usb`) was `power_role=sink data_role=device` -> nobody is host. Working state: `REG01=0x16`, `REG08=0x34` (VBUS from the phone), phone `power_role=source data_role=host`, `host_connected=true`, then `udc` goes default -> configured within ~3 s.
Fix that worked: enter USB DAC mode on the Disc FIRST (cable unplugged), then plug the cable into the Disc first and the phone second. (I tried to force it with `i2cset -f -y 2 0x1a 0x01 0x06` (what the player writes on DAC entry); the harness refused the live charger write, so it was not used.) Read-only watcher used: a loop printing `udc state`, `usb_role`, `i2cget -f -y 2 0x1a 0x01/0x08` and the configfs gadget dir every second.

## 3. Exit deadlock (leaving USB DAC with a host attached)
Symptoms: toast "Mode didn't switch", Disc stays in a half state, nothing enumerates, only a reboot recovers. Proof on the live Disc:
```sh
P=$(pidof mq_player | head -1)
for t in /proc/$P/task/*; do [ "$(cat $t/comm)" = mode_handle ] && echo "state=$(cut -d' ' -f3 $t/stat) wchan=$(cat $t/wchan)"; done
# -> state=D wchan=snd_card_free
ls -l /proc/$P/fd | grep snd     # -> 32 -> /dev/snd/pcmC1D0c (deleted)
```
The player's mode thread tears the gadget down (`uac_stop` 0x46dd5c) and blocks in the kernel's `snd_card_free` until every handle on the gadget's sound card is closed; the player's own capture thread still holds `pcmC1D0c` ("capture thread is running! please release first"). Cause (decompiled): `close_pcm_capture_thread` sets capture state 2 and `pthread_join`s with no timeout while the USB uevents (UAC_STATE=STOP / UAC_SRATE=0 -> `reopen_capture_dev`, USB_STATE=DISCONNECTED) overwrite the same state variable from the listener thread, so the stop request is lost. diskOS' old order (0666 first -> closes capture while the host is still there) triggers it; unplugging afterwards did not free it.
Fix (main.c `dac_exit_begin`/`dac_exit_tick`, guard `usb_host_attached()` = UDC state anything but "not attached"; the first version only checked "configured" and missed the `powered` state): send `0642000C0000` FIRST, wait until `/sys/kernel/config/usb_gadget/uac_demo` is gone (measured ~14-17 s with a phone attached, the host flaps configured/suspended meanwhile; timeout 30 s) + 1.5 s margin, then run the normal switch (0666 / 0657). Verified: mode_handle stays in `hrtimer_nanosleep`, gadget gone, Local init, no wedge. cfg `dac_safe_exit=0` restores the old "Unplug the USB cable first" refusal.
Recovery when wedged: `sync; reboot` over ssh (never kill mq_player).

## 4. Other facts worth keeping
- Gadget: `uac2.a` (not uac1), VID 0x2972 PID 0x0158, bDeviceClass 0/0/0, `c_ssize=4` (S32_LE), `c_srate` follows the host (kernel `u_audio_iso_complete` maps first-packet size to 48k/88.2k/96k/176.4k/192k/352.8k/384k, default 44.1k), `p_ssize=2`.
- Android phones probe with ~12 quick set_alt 0/1 toggles, log `UsbACInterface: Unknown Audio Class Interface subtype:0xa` (UAC2 clock source, harmless), then route to `usb_headset`.
- Do NOT `grep` the big `/usr/data/fiio/log/fiio_player.log` on the Disc (OOM killer fired, 59 MB anon): use `tail -n 400 | grep`.
- Charging: the player's `loop_power` thread (FUN_004e2c08, 1 s) re-enables charging with CHARGE_PROTECT on and capacity < 80 (no hysteresis); the plug-event path (`loop_adc_check_thread`) re-inits the charger (ioctl 0x20004d27) when protect is off - any diskOS REG01 write is overwritten on plug.
- Command catalogue notes: `0800` = factory reset (never send), `0621` drop DB tables, `0724` firmware upgrade; the dispatcher runs on the main thread (one command per 10 ms, handlers synchronous) - the likely cause of "Player didn't respond"; `/ui` should be 32 deep (stock) not 10.
