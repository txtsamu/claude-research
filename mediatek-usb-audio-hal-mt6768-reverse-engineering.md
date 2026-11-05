---
type: investigation
tags: [android, mediatek, mt6768, usb-audio, usb-dac, audio-hal, ghidra, reverse-engineering, libalsautils, aurisys, selene, bit-perfect]
created: 2026-11-05
last_verified: 2026-11-05
status: current
---

# Reverse engineering MediaTek's USB audio HAL (`audio.usb.mt6768.so`, Redmi 10 `selene`)

Follow-up to [android-apple-music-usb-dac-bit-perfect-redmi-10-selene.md](android-apple-music-usb-dac-bit-perfect-redmi-10-selene.md). Goal: find where a USB DAC's sample rate is capped on this MediaTek phone (Android 11, stock MIUI, MT6768), since no public write-up of the MediaTek USB HAL exists. Everything here is static analysis of binaries copied off the phone; **nothing was changed on the phone** and **no DAC was attached**, so the behaviour is read from code, not measured.

## Time estimate

About 25 minutes total (estimate): pulling files 1 min, Ghidra import + decompile of both libraries 14 s (measured, `time` output), the rest was reading decompiled code.

## Files analysed (copied with root, kept in `~/sessions/2026-11-05-mtk-usb-hal-re/bins/`)

| File on phone | Size | Role |
|---|---|---|
| `/vendor/lib64/hw/audio.usb.mt6768.so` | 73 KB | MediaTek USB audio HAL (`modules.usbaudio.audio_hal`) |
| `/vendor/lib64/libalsautils.so` | 20 KB | AOSP `alsa_device_profile` code (probes the DAC) |
| `/vendor/lib64/hw/audio.primary.mt6768.so` | 2.1 MB | MTK primary HAL; exports `createMTKAudioUSBPlaybackHandler` / `...USBProvider` (Aurisys) |
| `/vendor/etc/audio_param/USBDevice_AudioParam.xml` (+`_ParamUnitDesc.xml`) | 1 KB | per-USB-device parameters |

## Steps (in order)

```bash
S=~/sessions/2026-11-05-mtk-usb-hal-re; mkdir -p $S/{bins,scripts,out,proj}
# copy via su (adb pull cannot read /vendor directly), then remove the temp copy
adb shell 'su -c "cp /vendor/lib64/hw/audio.usb.mt6768.so /sdcard/h.so"'; adb pull /sdcard/h.so $S/bins/audio.usb.mt6768.so; adb shell rm /sdcard/h.so
# same for libalsautils.so, audio.primary.mt6768.so, USBDevice_*.xml

export JAVA_HOME=~/.local/jdks/jdk-21*   # Ghidra 12.1.4 needs JDK 21
A=~/tools/ghidra_12.1.4_PUBLIC/support/analyzeHeadless
$A $S/proj hal -import $S/bins/audio.usb.mt6768.so -import $S/bins/libalsautils64.so
# scripts/DecompileAll.java (kept in the session dir): decompiles every function to one text file
$A $S/proj hal -process audio.usb.mt6768.so -noanalysis -scriptPath $S/scripts -postScript DecompileAll.java $S/out/usbhal.c
$A $S/proj hal -process libalsautils64.so  -noanalysis -scriptPath $S/scripts -postScript DecompileAll.java $S/out/alsautils.c
```

Gotcha: running `-import` twice with one `-postScript` output path makes the second program overwrite the first; use `-process <file>` per binary with its own output file.

## Findings

1. **The parameter XML is not the cap.** `USBDevice_AudioParam.xml` only maps USB VID:PID (SABRENT, Logitech H540, FiiO E18, Microsoft LX-3000, LeTV, Baseus B51, JBL Reflect Aware C) to `playback_latency_us` / `capture_latency_us` (default 1500 µs). This disproves my earlier guess that the policy rate lived there.
2. **`libalsautils.so` is stock AOSP `alsa_device_profile`.** The standard rate table (`std_sample_rates[]`, 13 entries, at vaddr `0x1017ac`, file offset `0x17ac` in lib64) is, in this order: `96000, 88200, 192000, 176400, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000`. `profile_read_device_info` walks that table; for each rate inside the DAC's PCM min/max (`pcm_params_get_min/max(params, 6)`) it does `pcm_open` + `pcm_is_ready`, and keeps the ones that succeed **in table order** (max 13).
3. **Where the "96 kHz limiter" comes from.** `profile_get_default_sample_rate` and `profile_get_highest_sample_rate` both return `sample_rates[0]`, i.e. the *first valid entry in table order*, not the numerically highest. Because 96000 comes first, a DAC that supports 96 kHz gets 96000 as both "default" and "highest" even if it also supports 176.4/192 kHz. The library itself does support 176.4 and 192 kHz (they are probed and kept); this ordering is what yzyhk904's unlocker and `hifi-src-bypass` fix by reordering the table. So on this phone the table is not missing 192 kHz; it is just ordered 96 kHz first.
4. **HAL output path** (`android::adev_open_output_stream`, `0x107a38`): after `profile_read_device_info`, if the requested rate is 0 it uses `profile_get_default_sample_rate` (so 96 kHz first); if the requested rate is valid per the probed list it is used as is (log `[USB_AUD] 2. usb out proxy_config.rate`); if not valid it falls back to the default (log `3.`). Output `sup_sampling_rates` returns the real probed list (`rates_list_device`); only the capture side returns MTK's fixed 13-rate list (same order, at `0x105da0`).
5. **No hard-coded 96/192 kHz limit in the output path.** Searching the decompiled HAL for 96000/192000/48000 constants found none. The only rate threshold is `rate >> 8 < 0x177` (below about 95.5 kHz) and it is in `adev_open_input_stream` (capture, "UL enh"), irrelevant to playback.
6. **MediaTek processing may sit in the playback path.** `start_output_stream` does `dlsym("createMTKAudioUSBPlaybackHandler")` from `audio.primary.mt6768.so` (Aurisys) and routes playback through that handler; if it is absent, it falls back to a plain `proxy_open`. Both symbols exist in `audio.primary.mt6768.so`, so on this phone playback most likely goes through the Aurisys handler. Whether Aurisys alters music samples (gain, resampling, DSP) was not determined. It is the main unknown for bit-perfect.
7. **Tunables:** properties `vendor.audio.usb.out.period_us`, `vendor.audio.usb.out.period_count` (and `in.`); `ro.audio.usb.period_us` is 5000 on the phone. These set buffering/latency only.

## What this means

- The 96 kHz cap on MediaTek is a table-ordering quirk in `libalsautils`, not a missing capability, so a one-line style patch (reorder the 13 `uint32` entries so 192000 and 176400 come first, 52 bytes, same length) is the plausible fix, as `hifi-src-bypass` does on other SoCs; it was not applied or tested here.
- It would still not make Apple Music bit-perfect: AudioFlinger's mixer rate and Apple Music's own volume/DSP are separate, and the Aurisys handler is unverified (finding 6).
- Not done: a runtime test. With a DAC attached the useful measurements are `adb logcat -s modules.usbaudio.audio_hal` (look for `adev_open_output_stream, config.rate=` and `usb out proxy_config.rate`) and `cat /proc/asound/card1/stream0`.

## References

- [usb-samplerate-unlocker (yzyhk904)](https://github.com/yzyhk904/usb-samplerate-unlocker): origin of the `std_sample_rates[]` / `libalsautils` patch
- [HiFi SRC Bypass (lizi600jin)](https://github.com/lizi600jin/hifi-src-bypass): reorders the same 13-entry table
- [Ghidra](https://github.com/NationalSecurityAgency/ghidra) 12.1.4 headless analyzer (local install)
