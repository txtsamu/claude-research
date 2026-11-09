---
type: investigation
tags: [android, redmi-10, selene, mt6768, magisk, usb-dac, otg, dap, poweramp, miui, adb]
created: 2026-11-09
last_verified: 2026-11-09
status: current
---

# Redmi 10 (selene): making USB DAC dongles more compatible, and turning it into a DAP

Goal: the rooted phone should detect DAC dongles more reliably and behave like a dedicated audio player (DAP). This session was a read-only audit over adb plus two web-research passes. **Nothing was changed on the phone and no DAC was attached**, so DAC behaviour below is read from the device configuration, not measured. Earlier work on the same phone: [android-apple-music-usb-dac-bit-perfect-redmi-10-selene.md](android-apple-music-usb-dac-bit-perfect-redmi-10-selene.md), [mediatek-usb-audio-hal-mt6768-reverse-engineering.md](mediatek-usb-audio-hal-mt6768-reverse-engineering.md), [redmi-10-magisk-root-swap-zram-and-modules.md](redmi-10-magisk-root-swap-zram-and-modules.md).

## Time estimate

About 10 minutes wall clock (estimate from tool timings: adb probes a few seconds each, the two web-research agents ran 2.1 and 2.8 minutes in parallel, measured by the agent runtime). Applying the recommended steps would take about 5 minutes plus one reboot.

## Device state read over adb (2026-11-09)

```bash
adb devices -l
adb shell 'getprop ro.product.model; getprop ro.build.version.release; getprop ro.miui.ui.version.name; getprop ro.boot.verifiedbootstate'
adb shell 'su -c "magisk -v; ls /data/adb/modules"'
adb shell 'su -c "cat /vendor/etc/usb_audio_policy_configuration.xml"'
adb shell 'su -c "ls /sys/class/power_supply/usb; cat /sys/class/power_supply/usb/typec_mode"'
adb shell 'su -c "for f in /sys/module/usb20_host/parameters/*; do echo \$f=\$(cat \$f); done"'
adb shell 'su -c "dmesg | grep -iE \"otg|bq2589x\" | tail"'
adb shell 'su -c "dumpsys usb | head -60; dumpsys audio | grep -iE \"safe|absolute\""'
```

| Item | Value |
|---|---|
| Device | `21121119SG` (`selene`), MT6768, MIUI 12.5.7 (`V12.5.7.0.RKUIDXM`), Android 11, kernel 4.14.186-perf |
| Root | Magisk 31.1, `su` works from adb shell. Boot-state props read `ro.boot.verifiedbootstate=green`, `ro.boot.flash.locked=1` today, whereas [redmi-10-magisk-root-swap-zram-and-modules.md](redmi-10-magisk-root-swap-zram-and-modules.md) recorded orange / `flash.locked=0` on 2026-10-23. Cause not investigated (possibly props spoofed by a module); confirm with `fastboot oem device-info` / `fastboot getvar unlocked` before any flashing |
| Modules | `mtk-usb-rate-order` v1.1 (192k-first table, md5 of the mounted lib64 equals the module copy), `playintegrityfix` v18, `magisk-swapspace` v2.4. `NLSound`, `LowRAMFlagJos`, `encore` are gone |
| Apps | Poweramp `build-1031-bundle-play` (installed 2026-10-21); `com.miui.audioeffect` still present; no Xposed/LSPosed |
| USB audio policy | HIDL `halVersion="2.0"`, `usb_device output` has only `AUDIO_OUTPUT_FLAG_FAST`; no direct / bit-perfect port |
| OTG supply | external charger IC `bq2589x`; dmesg shows `bq2589x_set_boost_ilmt: otg curr = 1800000` (1.8 A boost limit), so supply is not the limiting factor |
| Type-C | `dumpsys usb`: `supported_modes=dual`, `can_change_mode=false`; `usb20_host` params: `typec_control=1`, `vbus_control=0`, `vbus_force_on=0`; `mt_usb/musb-hdrc/cmode=1` |
| OTG props | `persist.vendor.otg_control=true`; `init.mt6768.usb.rc` has `on property:vendor.set.vbus.onoff=*` -> writes `/sys/module/usb20_host/parameters/vbus_force_on 1`. Nothing in `/vendor/etc/init` reads `otg_control`, so what consumes it is unknown |
| Settings keys | `settings list global/secure/system | grep -iE "otg|usb"` shows only `usb_mass_storage_enabled`, `volume_music_usb_headset=6`; no MIUI OTG auto-off key present while no OTG device is connected |
| Safe volume | `mSafeMediaVolumeState=SAFE_MEDIA_VOLUME_ACTIVE`, `mSafeUsbMediaVolumeIndex=140`, `mSafeUsbMediaVolumeDbfs=-15.0` (caps loudness on USB outputs unless acknowledged/disabled) |
| Poweramp battery state | standby bucket 5 (exempt), `RUN_ANY_IN_BACKGROUND: allow`, `WAKE_LOCK: allow`. Requests `SET_VOLUME_KEY_LONG_PRESS_LISTENER` but it is **not granted** (permission is defined by package `android`, i.e. privileged/signature class) |
| Charge control nodes | `/sys/class/power_supply/battery/{charging_enabled,input_suspend,hiz_enable,charge_control_limit,reverse_limit}` exist; `/proc/mtk_battery_cmd/{current_cmd,en_power_path,en_safety_timer}` exist (these are the switches ACC probes) |
| CPU | `schedutil` on both clusters; governors available: ondemand userspace powersave performance schedutil |
| USB now | no DAC attached; `/proc/asound/cards` shows only `card0` |

## Findings

### A. DAC detection / compatibility

1. **No Magisk module aimed at DAC detection, disconnects, UAC1/UAC2 handling or DAC hardware volume exists for MTK/Android 11** (search of GitHub / Magisk repos / XDA by the research agent; Head-Fi and the Poweramp forum blocked fetches, so those are snippet-level only). The phone already enumerated a UAC2 FiiO JA11 fine ([earlier doc](mediatek-usb-audio-hal-mt6768-reverse-engineering.md)), so basic detection works.
2. **Candidate modules, none verified on this ROM:**
   - `audio-misc-settings` (yzyhk904): 100 volume steps, effects framework off, CSD (safe-volume) off, USB HAL transfer period tweak, `vendor.audio.adm.buffering.ms=2`. Tested Android 10-16 Qualcomm and MTK on LineageOS/crDroid/phh GSI, **not stock MIUI**. Maybe: only the safe-volume/CSD and 100-step parts are relevant to a DAP. It edits props and soundfx, so it may clash with `ro.vendor.audio.soundfx.usb=true`.
   - `USB_SampleRate_Changer` (yzyhk904): root scripts that generate an audio policy and reload audioserver, with `--bypass-offload`; mentions an MTK 96 kHz lock. Read the script first; it overlaps my `mtk-usb-rate-order` patch.
   - Skip: `Audio Compatibility Patch` (nothing documents a DAC benefit), `Hi-ResAudio` (adivenxnataly: Android 12+, speaker/wired only, explicitly not USB).
   - Already judged poor fits earlier: usb-samplerate-unlocker, audio-jitter-silencer, BitPerfect-DAC, hifi-src-bypass.
3. **MIUI-specific anecdotes (Poweramp forum snippets):** MIUI misreports a DAC as "Other Output Devices" (diagnostic: Poweramp Settings > Audio > Advanced Tweaks > Audio Outputs Detection Log); MIUI's "Hi-Fi" toggle under Sound > Headset must be on or output is forced to 16-bit/48 kHz (check whether this Redmi has it); a second direct-USB app (USB Audio Player Pro) can block Poweramp's hi-res output; Poweramp DVC can make hi-res USB output very quiet (try "no DVC"). Dongle anecdotes: Cx31993 (JCally JM6E, "CX Pro") not recognised on a Redmi 10C, FiiO KA3 does not bypass Android's resampler, Apple dongle low volume (snd-usb-audio has no quirk for its broken volume control).
4. **Hardware (DAC) volume:** no module. AOSP only has hardware master volume via the AIDL USB HAL (Android 14+); not available on this HIDL 2.0 HAL. Poweramp's USB Exclusive mode does control the DAC's own volume itself, which is the practical route here.

### B. OTG / host mode

5. **MIUI's OTG auto-off (about 10 minutes idle)** is documented by Xiaomi support pages (Settings > Additional settings > OTG); one page says the switch was removed on many models from MIUI 11. No settings key or root override is documented for MIUI. The only analogue is OnePlus' `settings put global oneplus_otg_auto_disable 0`. This phone showed no OTG key while nothing was attached, so the key has to be discovered: diff `settings list global|secure|system` (before/after) with a dongle plugged in and the toggle flipped.
6. **MTK sysfs knobs that exist on this phone but are undocumented elsewhere:** `/sys/module/usb20_host/parameters/vbus_force_on` (forces VBUS on in host mode; only written by an init trigger on `vendor.set.vbus.onoff`), `typec_control`, `vbus_control`. Untested: writing them is the first thing to try if a power-hungry dongle fails to power up. No online source documents these for Helio 4.14.
7. **Charging while a DAC is attached (pass-through):** nothing found online. The phone has `input_suspend`, `hiz_enable`, `charging_enabled` nodes that a charge-limiting tool can use, but whether the bq2589x can charge and source OTG at once was not tested.

### C. DAP setup

8. **Keep the player alive on MIUI** (dontkillmyapp.com): lock the app in Recents; Security > Permissions > Auto-start on; Security > Battery > App Battery Saver > app > No restriction; "Keep running after screen off". On the device Poweramp already has bucket 5 + RUN_ANY_IN_BACKGROUND allow, so the remaining steps are autostart and the recents lock (not checked over adb).
9. **Volume-key long-press for next/prev with the screen off:** Poweramp has the feature but needs `SET_VOLUME_KEY_LONG_PRESS_LISTENER`, which is not granted here. Whether root `pm grant` works for a permission defined by `android` (privileged/signature) was **not tried**. Alternatives from community reports: Key Mapper / Button Mapper (reported to work screen-off when rooted), or the Xposed module `Hepolise/VolumeKeyTrackControlModule` (needs LSPosed; README lists only a OnePlus 13 on Android 16 as tested).
10. **Auto-open Poweramp on DAC connect:** no Poweramp setting. Root options are reported but unverified on Android 11: preset the default activity for the USB device in `/data/system/users/0/` (the `usb_device_manager.xml` / `usb_permissions` style files; on this phone `/data/misc/usb/` does not exist and `/data/system/users/0/` has no usb file yet, so it only appears after one "always" approval).
11. **Bit-perfect checklist (Poweramp official + 2023 forum guide):** use USB Exclusive; "Perfect Bit Perfect" skips EQ/DSP/software volume/fades; ReplayGain counts as DSP, so off; fades/crossfade off; match Hi-Res output rate to the track; allowed-rate logic is exact rate, else next higher, then next lower; only one app may hold the DAC. Bit-perfect and EQ are mutually exclusive in Poweramp's definition.
12. **Battery:** ACC (VR-25/acc) is the only charge-limit candidate; its README lists MTK switches `/proc/mtk_battery_cmd/current_cmd` and `en_power_path`, both present here. Not tested on selene; run `acc -s s::` to list working switches. Airplane mode (Wi-Fi/BT off) is the repeated Head-Fi advice against GSM buzz into a USB DAC. No documented CPU-governor/frequency cap for MT6768 to reduce DAC noise (searched, nothing).
13. **Android 14+ ROM is not worth it for this goal.** No official LineageOS selene build found; only an unofficial /e/OS 4.3 (probably Android 13) post of 2026-08-31 and a 2022 KangOS (Android 11) build. Android 14's bit-perfect mixer needs the AIDL audio HAL and a vendor-declared `AUDIO_OUTPUT_FLAG_BIT_PERFECT` port; this phone's vendor is Android 11 HIDL, and Poweramp USB Exclusive does not use the framework mixer anyway. Latest stock is MIUI 14 (Android 13).

## Dead ends / not found

- No Magisk module for DAC detection or UAC1/UAC2 fixes; no MIUI OTG-timeout key or root fix; no documented MTK 4.14 host-mode / typec switch; no CPU-governor noise fix; no `cmd deviceidle` evidence for MIUI's own killer.
- `forum.powerampapp.com` and `head-fi.org` returned 403/bot wall to fetch; their items are from search snippets and should be re-read in a browser before relying on them.
- `/proc/asound/*` is unreadable as the adb shell user (needs `su`); `/sys/kernel/debug` is absent.

## Suggested next steps (not run; need a go-ahead for anything that changes the phone)

1. Plug the DAC, then measure: `adb shell 'su -c "cat /proc/asound/cards; cat /proc/asound/card1/stream0"'` during playback, and diff `settings list global|secure|system` around the OTG toggle (also reveals the key behind the 10-minute auto-off).
2. Poweramp: USB Exclusive, hardware volume, Perfect Bit Perfect; check Advanced Tweaks > Audio Outputs Detection Log if the DAC is misdetected; lock in Recents, autostart on, No restriction.
3. Try `pm grant com.maxmpz.audioplayer android.permission.SET_VOLUME_KEY_LONG_PRESS_LISTENER` as root (reversible with `pm revoke`).
4. Safe-volume limit: either accept the -15 dBFS USB cap or test `audio-misc-settings` (back up first; undo with `touch /data/adb/modules/<id>/disable` + reboot).
5. If a dongle will not power up: test `echo 1 > /sys/module/usb20_host/parameters/vbus_force_on` with it attached (reverts at reboot).

## References

- [dontkillmyapp: Xiaomi](https://dontkillmyapp.com/xiaomi)
- [Poweramp features / USB Exclusive](https://powerampapp.com/)
- [AOSP: preferred mixer attributes (bit-perfect)](https://source.android.com/docs/core/audio/preferred-mixer-attr)
- [audio-misc-settings (Magisk-Modules-Alt-Repo)](https://github.com/Magisk-Modules-Alt-Repo/audio-misc-settings)
- [USB_SampleRate_Changer (yzyhk904)](https://github.com/yzyhk904/USB_SampleRate_Changer)
- [usb-samplerate-unlocker (Alt-Repo)](https://github.com/Magisk-Modules-Alt-Repo/usb-samplerate-unlocker)
- [Audio Compatibility Patch (acp mirror)](https://github.com/httpsgithu/acp)
- [Audio Compatibility Patch, XDA thread](https://forum.xda-developers.com/t/audio-compatibility-patch-formerly-universal-deep_buffer-remover-mmtex.3577067/post-85200875)
- [Hi-ResAudio (adivenxnataly)](https://github.com/adivenxnataly/Hi-ResAudio)
- [XDA: always-on OTG on OxygenOS (`oneplus_otg_auto_disable`)](https://www.xda-developers.com/enable-always-on-otg-oxygenos/)
- Xiaomi support, OTG: [KA-613065](https://www.mi.com/ph/support/faq/details/KA-613065/), [KA-509270](https://www.mi.com/global/support/faq/details/KA-509270/), [KA-07213](https://www.mi.com/sg/support/article/KA-07213)
- [VR-25/acc](https://github.com/VR-25/acc)
- [Hepolise/VolumeKeyTrackControlModule](https://github.com/Hepolise/VolumeKeyTrackControlModule)
- [Old phone as a DAP write-up (Niagara launcher, ADB debloat)](https://esli-blog.pages.dev/posts/transform-old-smartphone-in-a-digital-audio-player-dap)
- [/e/OS community: Redmi 10 Prime selene](https://community.e.foundation/t/redmi-10-prime-selene/82511)
- [SourceForge: redmi-10-selene](https://sourceforge.net/projects/redmi-10-selene/)
- [LineageOS issue 6189: alioth DAC/OTG (no fix)](https://gitlab.com/LineageOS/issues/android/-/issues/6189)
- Snippet-only (fetch blocked): Poweramp forum topics [26255](https://forum.powerampapp.com/topic/26255-detection-of-external-usb-dac/), [18517](https://forum.powerampapp.com/topic/18517-bitrate-16bit48khz-only-what-to-do/), [25630](https://forum.powerampapp.com/topic/25630-very-low-volume-with-dcv-turned-on-with-hi-res-output-usb-dac-even-at-default-settings/), [17082](https://forum.powerampapp.com/topic/17082-hardware-volume-from-usb-dac/), [26720](https://forum.powerampapp.com/topic/26720-long-press-of-the-volume-buttons-does-not-work-when-the-screen-is-off-miui-14-android-13), [26532](https://forum.powerampapp.com/topic/26532-need-some-help-or-guide-for-using-bit-perfect-playback/); Head-Fi [Cx Pro on Xiaomi](https://www.head-fi.org/threads/cx-pro-conexant-cx31993-not-working-on-xiaomi-devices.966347/), [KA3 thread](https://www.head-fi.org/threads/ka3-ka13-fiio-x-jadeaudio-usb-dac-dongle.960238/page-36), [repurposing an old phone](https://www.head-fi.org/threads/repurposing-an-old-android-phone-as-a-dedicated-source.970842/)
