---
type: investigation
tags: [android, apple-music, usb-dac, bit-perfect, magisk, redmi-10, selene, mediatek, audioflinger, android11]
created: 2026-11-05
last_verified: 2026-11-05
status: current
---

# Apple Music on a rooted Android 11 phone: can it reach a USB DAC bit-perfect?

Question: the phone (rooted, adb attached) should play Apple Music through a USB DAC at hi-res / bit-perfect. Outcome: **no Magisk module is documented that does this on Android 11**; the real routes are Android 14+ with a bit-perfect-capable audio HAL, or an app with its own USB driver (which cannot play Apple Music). Nothing was changed on the phone; no DAC was plugged in yet.

## Time estimate

About 10 minutes of research (estimate, not timed). Nothing was flashed or installed.

## Device state (read over adb, 2026-11-05)

```bash
adb devices -l
adb shell 'getprop ro.product.model; getprop ro.build.version.release; getprop ro.build.version.sdk; getprop ro.board.platform'
adb shell 'su -c id; su -c "magisk -v"'
adb shell 'pm list packages | grep -i -E "apple|music|magisk"'
adb shell 'su -c "cat /proc/asound/cards; ls /sys/bus/usb/devices; ls /data/adb/modules"'
adb shell 'su -c "cat /vendor/etc/usb_audio_policy_configuration.xml"'
```

| Item | Value |
|---|---|
| Device | Xiaomi `21121119SG`, codename `selene` (Redmi 10 2022), MT6768 |
| Android | 11 (SDK 30), build `AL5186-selene-build-20211216190244` |
| Root | Magisk 30.7, `su` works (uid 0) |
| Magisk modules | `LowRAMFlagJos`, `NLSound`, `magisk-swapspace`, `playintegrityfix` |
| Apple Music | not installed |
| USB DAC | none attached (only `card0` mt6768-mt6358; USB bus has just the root hub) |
| `ro.vendor.audio.soundfx.usb` | `true` (effects are applied on USB output) |
| `ro.audio.usb.period_us` | 5000 |
| `/vendor/etc/usb_audio_policy_configuration.xml` | `halVersion="2.0"` (HIDL); `usb_device output` has only `AUDIO_OUTPUT_FLAG_FAST`; no direct and no `AUDIO_OUTPUT_FLAG_BIT_PERFECT` port |

## Findings

1. **Android's system path resamples.** The mixer converts USB output to 48 kHz unless the device is on the Android 14 bit-perfect path. Android 14 added `setPreferredMixerAttributes` / bit-perfect mixer behaviour; the vendor must add `AUDIO_OUTPUT_FLAG_BIT_PERFECT` to a mix port in `usb_audio_policy_configuration.xml`, and the doc says the attribute is supported only with the AIDL Audio HAL.
2. **This phone is Android 11 with a HIDL 2.0 USB HAL**, so the Android 14 route is not available as-is. The same-looking config on a Redmi Note 12 Pro (Android 14, MIUI) already failed to offer bit-perfect, see [bitchord-android-usb-exclusive-mode-uac-driver.md](bitchord-android-usb-exclusive-mode-uac-driver.md); so upgrading Android alone is not a guarantee either, the HAL has to expose the flag.
3. **Apple Music for Android has no private USB driver.** Players like UAPP / Poweramp `usbx` / BitChord get bit-perfect by claiming the DAC through usbfs; they cannot play Apple Music's DRM streams. Reports about Apple Music on Android 14+ are conflicting: a 2025 secondhand Zhihu/Reddit claim says it uses the Android 14 API; older threads (Android 13, late 2024) say it resamples 44.1 to 48 kHz. Not verified by me.
4. **The "sample-rate unlocker" modules solve a different problem.** `usb-samplerate-unlocker` (yzyhk904) patches `std_sample_rates[]` in `/vendor/lib{,64}/libalsautils.so` to lift the 96 kHz cap (default 192 kHz, `full` 384, `max` 768 which may stutter). Its page says nothing about bit-perfect, Apple Music or MediaTek, and tested only LineageOS 10/11 and ArrowOS 11/12. Whether it changes the 48 kHz mixer resampling on this stock MIUI build is **unverified** (my inference: it would not, because the mixer rate is a policy matter, not the libalsautils rate table).
5. **`audio-jitter-silencer`** (same author) disables adaptive battery/connectivity and Wi-Fi suspend features and merges a Doze whitelist; claims lower jitter, no bit-perfect claim, no measurements.
6. **Apple Music root detection** is reported to be a simple root-file check in `/system/bin/` (smartworld.it), solved there with MagiskHide, which no longer exists in Magisk 30.x. Use DenyList / Shamiko-style hiding if the app refuses to start. `playintegrityfix` is already installed.
7. **`NLSound` is active** and is a global audio-tuning module; it edits audio policy and effects, which works against bit-perfect. Disable it (touch `/data/adb/modules/NLSound/disable`, reboot) before any DAC test. Not done.

## Dead ends / not found

- No source found for a Magisk module that adds `AUDIO_OUTPUT_FLAG_BIT_PERFECT` or a direct USB output to an Android 11 HIDL HAL.
- The custom-ROM search returned only `spes` (Redmi Note 11) builds, which do not apply to `selene`; no Android 14 ROM for `selene` was confirmed.

## Suggested next steps (not run)

1. Install Apple Music, plug the DAC, then measure what actually happens instead of trusting claims:
   ```bash
   adb shell 'su -c "dumpsys media.audio_flinger | grep -i -A6 -E \"usb|Output thread\""'
   adb shell 'su -c "cat /proc/asound/card1/stream0"'   # rate/format while a 96 kHz or 192 kHz track plays
   ```
   Also watch the DAC's own sample-rate LED. 48 kHz everywhere means the mixer is resampling.
2. Disable `NLSound` first, set system volume to max, system sound effects off.
3. If it stays at 48 kHz: either try the unlocker module as a controlled experiment (back up first; `/data/adb/modules/<name>/disable` removes it), or move to a ROM whose USB HAL declares the bit-perfect flag, or use a bit-perfect player for local files (BitChord fork, UAPP) and accept that Apple Music stays on the Android mixer.

## References

- [USB Samplerate Unlocker (yzyhk904)](https://github.com/yzyhk904/usb-samplerate-unlocker)
- [audio jitter silencer (yzyhk904)](https://github.com/yzyhk904/audio-jitter-silencer)
- [Preferred mixer attributes on USB devices (AOSP)](https://source.android.com/docs/core/audio/preferred-mixer-attr?hl=en)
- [想听Apple Music无损,该怎么入门? (Zhihu)](https://www.zhihu.com/tardis/jm/ans/2027866405748385690)
- [HiFiVision: Apple Music resampling on Android 13](https://hifivision.com/goto/post?id=1048373)
- [r/AppleMusic mirror: Apple Music on Android](https://cal1.lr.ggtyler.dev/r/AppleMusic/comments/1g74ejp/apple_music_on_android)
- [Head-Fi UAPP thread](https://www.head-fi.org/threads/usb-audio-player-pro-uapp-24-and-32-bit-playback-ubiquitous-usb-audio-support-for-android.704065/post-17717934)
- [SlashGear: apps that play hi-res audio on Android](https://www.slashgear.com/1662737/apps-android-high-resolution-audio-full-quality)
- [Poweramp forum: forced 48 kHz Android resample](https://forum.powerampapp.com/topic/22229-forced-48-khz-android-resample-and-deep_buffer-enforced-flag-on-hi-res-output-log/)
- [smartworld.it: Apple Music and root](https://www.smartworld.it/news/apple-music-root.html)
