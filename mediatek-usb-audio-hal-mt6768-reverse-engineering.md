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

## Patch applied: 192k first (2026-11-05)

Installed as a systemless Magisk module `mtk-usb-rate-order`; the stock `/vendor` files are untouched. Active only after a reboot (not rebooted yet when this was written, so **not yet verified live**).

```bash
S=~/sessions/2026-11-05-mtk-usb-hal-re
python3 -I $S/scripts/patch_rates.py $S/bins/libalsautils64.so $S/module/mtk-usb-rate-order/system/vendor/lib64/libalsautils.so   # offset 0x17ac
python3 -I $S/scripts/patch_rates.py $S/bins/libalsautils32.so $S/module/mtk-usb-rate-order/system/vendor/lib/libalsautils.so     # offset 0x13fc
# module.prop id=mtk-usb-rate-order; install:
adb push $S/module/mtk-usb-rate-order /sdcard/ && adb shell 'su -c "cp -r /sdcard/mtk-usb-rate-order /data/adb/modules/ && chown -R root:root /data/adb/modules/mtk-usb-rate-order && chcon -R u:object_r:vendor_file:s0 /data/adb/modules/mtk-usb-rate-order/system"'
```

- The script requires the original 13-entry table to occur exactly once, then rewrites it to `192000, 176400, 96000, 88200, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000` (same file length). Done for both `lib64` and `lib`.
- Stock hashes (sha256): lib64 `e1e54345dca3c1961a64cf6bcb4ed26532e455a975563816eedae923a6ba1d2a`, lib `94084a46797dd85cd8d71484e5c4cb3da955ef06226335d2036dd7e3cb524ffc`; originals are in `~/sessions/2026-11-05-mtk-usb-hal-re/backups/`. Patched lib64: `3c3faa32...3723`. No other module touches `libalsautils` (NLSound only ships `system/vendor/etc`).
- Side effect: "default" and "highest" rate for any USB device (including USB headset mics) now become 192 kHz if the device accepts it, since the library returns the first accepted entry.
- Verify after reboot: `adb shell 'su -c "sha256sum /vendor/lib64/libalsautils.so"'` should show `3c3faa32...`; with a DAC, `adb logcat -s modules.usbaudio.audio_hal` and `cat /proc/asound/card1/stream0`.
- Undo: `adb shell 'su -c "touch /data/adb/modules/mtk-usb-rate-order/disable"'` and reboot (or delete the module folder; Magisk safe mode also disables modules if boot fails).

## Live check with a DAC (2026-11-05, after the reboot)

Wireless adb: `adb connect 192.168.50.18:5555` was refused (Android 11 wireless debugging uses a random port); `nmap -p 30000-49999,5555 --open 192.168.50.18` found `45481`, then `adb connect 192.168.50.18:45481`.

- **Patch is live:** `sha256sum` of `/vendor/lib64/libalsautils.so` = `3c3faa32...3723` and `/vendor/lib/libalsautils.so` = `a4abb6a9...ffac3` after reboot; the live 64-bit table reads `192000, 176400, 96000, 88200, 48000, 44100, ...`; `audioserver` up, no crash lines.
- **DAC:** FiiO JadeAudio JA11, USB `2972:0102`, 480 Mbps high-speed, UAC2 (`/sys/bus/usb/devices/1-1`). From `dmesg | grep "usb 1-1"`: iface 1 alt 1 = 16-bit at 44.1/48/88.2/96/176.4/192 kHz; alt 3 = 32-bit at 192 kHz.
- **Evidence the system path now opens at 192 kHz / 32-bit:** `dmesg` shows thread `writer` (tid 7387, which `/proc/7387/exe` confirms belongs to `/vendor/bin/hw/android.hardware.audio.service.mediatek`, the audio HAL) starting the playback endpoint 1.3 s after the DAC enumerated: `iface=1:3 format = 32bit rate = 192000`, `frames_per_period=960` (960 frames at 192 kHz = 5 ms = `ro.audio.usb.period_us`). That fits the new default (first valid entry = 192000, highest PCM format = 32-bit). I have no pre-patch baseline for the same DAC, so this is consistent with the patch, not proof of it.
- **Not testable at that moment:** Poweramp (`com.maxmpz.audioplayer`, "external proxy" player, state started) was playing and holds interfaces 1.0/1.1 through `usbfs` (its own USB driver), so no ALSA card exists (`/proc/asound/cards` shows only `card0`) and `/proc/asound/card*/stream0` cannot be read. The `USB_AUD` HAL log lines were not in logcat (buffer rolled or filtered).
- To test the Android mixer path, stop Poweramp's USB-exclusive output (or play from a normal AudioTrack app, e.g. Apple Music), then read `cat /proc/asound/card1/stream0` and `dmesg | grep "usb 1-1"`.

- **Test files:** six synthetic 24-bit FLACs (44.1, 48, 88.2, 96, 176.4, 192 kHz, 30 s, soft chord, ultrasonic marker on 88.2k+) were generated with `~/sessions/2026-11-05-hires-test-files/scripts/make_tones.sh` and pushed to the phone's `/sdcard/Music/HiResTest/`. Real free hi-res sources found: 2L Test Bench is offline; Real HD-Audio demo files need an email request; the Internet Archive copy of the Open Goldberg Variations has only MP3/Ogg.

## 384 kHz table swap (module v2.0, 2026-11-05)

The stock loop is fixed at 13 slots, so 384000/352800 can only be added by dropping two entries. Chosen: drop `12000` and `11025` (keep `8000` for telephony). New table, applied to both `lib64` (offset `0x17ac`) and `lib` (`0x13fc`) from the **stock** copies in `backups/`:

```
384000, 352800, 192000, 176400, 96000, 88200, 48000, 44100, 32000, 24000, 22050, 16000, 8000
```

```bash
python3 -I $S/scripts/patch_rates.py $S/backups/libalsautils64.so.orig $M/system/vendor/lib64/libalsautils.so 384
python3 -I $S/scripts/patch_rates.py $S/backups/libalsautils32.so.orig $M/system/vendor/lib/libalsautils.so 384
# module.prop -> version=v2.0; push over /data/adb/modules/mtk-usb-rate-order, chown root, chcon vendor_file, adb reboot
```

- Verified after reboot: sha256 lib64 `6260de7e...497e`, lib `3ece3104...e197`; live lib64 table reads the 13 values above; `audioserver` up (pid 723).
- v1.0 (192k-first, keeps all 13 stock rates) is saved in `backups/module-192-v1.0/`.
- `profile_get_sample_rate_strs` builds the rate list in a 224-byte stack buffer, so six-digit rates fit.
- Wireless debugging port changes on every reboot: rescan with `nmap -p 30000-49999,5555 --open 192.168.50.18` (this time `45221`).
- **Not tested with the DAC yet:** after this reboot the Type-C controller reported nothing attached (`typec_mode=0`, no `1-1` in `/sys/bus/usb/devices`), so the DAC needs to be re-plugged. Expectation, unverified: the HAL probes 384000/352800 against the DAC, but AudioFlinger's mixer (to my recollection capped at 192 kHz) may still resample.

## References

- [usb-samplerate-unlocker (yzyhk904)](https://github.com/yzyhk904/usb-samplerate-unlocker): origin of the `std_sample_rates[]` / `libalsautils` patch
- [HiFi SRC Bypass (lizi600jin)](https://github.com/lizi600jin/hifi-src-bypass): reorders the same 13-entry table
- [Ghidra](https://github.com/NationalSecurityAgency/ghidra) 12.1.4 headless analyzer (local install)
