---
type: investigation
tags: [android, apple-music, usb-dac, bit-perfect, redmi-note-12-pro, ruby, mt6877, audioflinger, hi-res, fiio-ja11, adb]
created: 2026-11-09
last_verified: 2026-11-09
status: current
---

# Apple Music stuck at 24-bit/96 kHz on a Redmi Note 12 Pro (ruby): jack vs USB DAC

Question: the phone's owner read that the device can do 32-bit/192 kHz, but Apple Music seemed stuck at 24-bit/96 kHz. Where does the cap come from?

**Answer in short:** nothing was stuck on the phone. (1) The 96 kHz case was just the song's own sample rate (Weeekly, *After School*). (2) A genuine 24/192 song (Coldplay, *Fix You*) plays at 192 kHz through the **USB DAC** end to end. (3) The **3.5 mm jack** path is capped at 48 kHz by the MediaTek audio HAL, so Android resamples 192 kHz down to 48 kHz there. (4) Apple Music never shows 32-bit: that is only Android's internal mixer container.

Device: Redmi Note 12 Pro 5G (`22101316G`, codename `ruby`, MediaTek MT6877), HyperOS 14 / Android 14 (SDK 34), bootloader locked, **not rooted** (adb shell uid 2000). Apple Music 7.0.0. DAC: FiiO JadeAudio JA11 over USB-C.

## Time estimate

About 10 minutes of tool calls in total (estimate, not stopwatch-measured): every step is a sub-second adb call; the only waits were the user switching output (jack, then DAC) between checks.

## Steps in order

### 1. Connect over adb Wireless debugging

`adb connect <PHONE_IP>:<port>` failed at first even though ping worked and the port was open (`nmap -Pn -p 30000-45000 --open <PHONE_IP>` showed it). Cause: the phone's Wireless debugging was not yet paired/authorised for this PC. After the user toggled it, the identical `adb connect` worked. The connect port changes every time Wireless debugging is toggled, so re-scan with nmap if it fails.

Gotcha: `adb kill-server` (tried while debugging the failure) drops every other wireless device too. A second phone (Redmi 10) disappeared and had to be re-added with `adb connect`. Do not kill the server when several devices are attached.

### 2. Read what Android is actually doing (no root needed)

```bash
S=<PHONE_IP>:<port>
adb -s $S shell 'dumpsys media_session | grep -A25 "package=com.apple.android.music" | grep -E "metadata: size|state=PlaybackState"'
adb -s $S shell 'dumpsys audio | grep AudioPlaybackConfiguration | grep started'
adb -s $S shell 'logcat -d -t 2000 | grep "AudioTrack.*audioTrackData" | tail -3'
adb -s $S shell 'dumpsys media.audio_flinger' > af.txt
```

In `af.txt` look at the `Output thread` blocks with `Standby: no`: `Sample rate`, `HAL format`, `Output devices`, and the `Tracks of which N are active` table (`SRate`, `Format`, `G db`, `BitPerfect`). The Apple Music track's `SRate` is what the app delivers; the active thread's `Sample rate` is what reaches the output.

Meaning of codes: `Format 00000005` = `AUDIO_FORMAT_PCM_FLOAT`, `0x3` = `PCM_32_BIT`; `Output devices 0x4000000` = `USB_HEADSET`, `0x8` = `WIRED_HEADPHONE`.

### 3. Results

| Case | Apple Music `AudioTrack` | Active output thread |
|---|---|---|
| USB DAC, Weeekly *After School* | 96000 Hz float | 192000 Hz, PCM_32, `USB_HEADSET` |
| Jack, Coldplay *Fix You* (X&Y) | **192000 Hz** float | **48000 Hz**, PCM_32, `WIRED_HEADPHONE` |
| USB DAC, Coldplay *Fix You* | **192000 Hz** float | **192000 Hz**, PCM_32, `USB_HEADSET` |

- Apple Music hands over the file's native rate, so a 96 kHz stream is a 96 kHz source, not a cap. The Android mixer on USB is already opened at 192 kHz.
- Jack cap: `/vendor/etc/audio_policy_configuration.xml` lists the `Wired Headset` / `primary output` profiles with `samplingRates="44100 48000"` only (PCM_16 and PCM_32). Android resamples everything to 48 kHz for the jack. This is a vendor HAL config on a locked phone, so it cannot be changed without root.
- Android's USB path to the JA11 has no such limit (`USB Headset Out` has no restricted profile; the HAL queries the DAC).
- "32-bit": Apple sends 24-bit content as float; the mixer converts to 32-bit int. Float has a 24-bit mantissa, so 24-bit samples survive the round trip exactly. The audible resolution stays 24-bit, and Apple Music's own UI tops out at 24-bit/192 kHz.

### 4. Which Apple Music tracks are 24/192?

No official or complete list exists. Apple says Hi-Res Lossless is "up to 24-bit/192 kHz"; many catalogue titles are 24/96 or 24/48. Candidates named by users and magazines (not guaranteed on the current catalogue): Coldplay's early albums (confirmed here for *Fix You*), Neil Young and Crazy Horse, CSNY *Deja Vu*, Billy Joel *Piano Man*. Most reliable check: play it and read `SRate` from step 2 (iPhone shows the rate when you tap the lossless badge; the Android app does not show it clearly).

## Software volume / bit-perfect (open, partly tested)

`dumpsys media.audio_flinger` reports `BitPerfect false` and a track gain of about -18 dB at media volume 9/15. That is Android's software volume applied before the DAC, so the samples are scaled.

What was read (without changing volume, since the DAC may drive headphones):
- Media volume range 0-15 (`STREAM_MUSIC`, `usb_headset` was at 9).
- `/vendor/etc/default_volume_tables.xml`, `DEFAULT_MEDIA_VOLUME_CURVE`: points `1,-5800`, `20,-4000`, `60,-1700`, `100,0` (in 1/100 dB). Only index 15 (100 %) is 0 dB, so at max volume the gain stage is unity.
- The USB thread had `0 Effect Chains`, even though `ro.vendor.audio.soundfx.usb=true`.
- Android 14 has an opt-in bit-perfect mixer mode (`AudioMixerAttributes`, `setPreferredMixerAttributes`). `dumpsys media.audio_policy` shows `Preferred mixer audio configuration:` empty, i.e. no app has requested it. Apple Music does not use it, and `cmd audio` has no shell command to set it.

So the practical "bypass" is: set media volume to 15 (0 dB) and control loudness on the DAC/amp. With a single track, 192 kHz source into a 192 kHz mixer (no resampling), unity gain and no effects, the float to int32 path is transparent for 24-bit data. **Tested 2026-11-09 (DAC volume at minimum first, by the user):** `adb shell cmd media_session volume --stream 3 --set 15` printed "will set volume to index=15" but changed nothing (`streamVolume` stayed 2). Volume-up key events work instead: `adb shell input keyevent KEYCODE_VOLUME_UP` in a loop. They stop at index 10 behind the "Raise volume above recommended level?" hearing-safety dialog (`mSafeMediaVolumeIndex=100`); tap OK (`adb shell input tap 768 2105` on this 1080x2400 screen; take a `adb exec-out screencap -p` first) and press up again to reach 15. Result in the audio_flinger track table: `G db` went **-48 (index 2) -> -15 (index 10) -> 0 (index 15)**, the track stayed 192000 Hz float and the USB thread stayed 192000 Hz / PCM_32. `BitPerfect` still reads false because that flag is only set for apps that opted in to Android's bit-perfect mixer mode; the gain stage is nevertheless unity. Loudness is now controlled on the DAC.

Other routes for strict bit-perfect: apps with their own USB driver (Poweramp USB exclusive, USB Audio Player Pro, both installed) bypass Android's mixer and volume, but they cannot play Apple Music streams.

## Could Hi-ResAudio (Magisk module) lift the jack cap? (checked 2026-11-09, not installed)

[adivenxnataly/Hi-ResAudio](https://github.com/adivenxnataly/Hi-ResAudio) (Apache-2.0, last push 2025-06-11, v2.0) rewrites `audio_policy_configuration.xml` / `audio_policy.conf` copies through Magisk so the internal speaker and wired (jack) outputs advertise higher rates and 32-bit; the README says it does **not** apply to Bluetooth/USB. Read via `gh api repos/adivenxnataly/Hi-ResAudio/contents/<file> --jq .content | base64 -d` (`customize.sh`, `copy.sh`, README).

- Gates in `customize.sh`: SDK >= 31 and `ro.soc.manufacturer == Mediatek`. This phone (SDK 34, MT6877) would pass both. (The Redmi 10 on Android 11 failed the first; see the related doc.)
- It targets exactly the cap found above: the jack profile `samplingRates="44100 48000"` (space-separated in this phone's XML, so the module's grep would match, unlike on the Redmi 10).
- **Blocker: it needs root.** This phone is unrooted with a locked bootloader (`ro.boot.flash.locked=1`, verified boot green). Magisk would require unlocking the Xiaomi bootloader first, which wipes the data partition.
- **No benefit for the DAC path**, which already runs at 192 kHz; it also sets `aaudio.mmap_policy=3`, rewrites the primary output flags and deletes speaker compensation filters.
- Unknown whether the MT6877 jack codec/HAL really outputs above 48 kHz once the policy allows it. On the Redmi 10 the equivalent test (192/96 kHz on the jack) cost CPU and sounded wrong, and was reverted (see related doc), and the HAL MMAP path there was a stub.
- Verdict: only worth it for jack-only listening at 96/192 kHz, and only after deciding to unlock the bootloader. Use the USB DAC for 24/192 instead.

## References

- [How do I find 24-bit 192 kHz tracks on Apple? (Apple Community)](https://discussions.apple.com/thread/252881040)
- [Hands-On: Apple Music Lossless and High-Res Lossless (Sound & Vision)](https://www.soundandvision.com/content/hands-apple-music-lossless-and-high-res-lossless)
- [Apple Music high res (Roon community)](https://community.roonlabs.com/t/apple-music-high-res/159869?page=91)
- [Apple Music lossless on Android (9to5Google)](https://9to5google.com/2021/05/14/apple-music-android-lossless-audio-streaming/)
- [Hi-ResAudio Magisk module (adivenxnataly)](https://github.com/adivenxnataly/Hi-ResAudio)
- [Wireless Apple Music Control HiRes and Lossless (hifivision)](https://hifivision.com/goto/post?id=1018347)
- [Apple Classic spielt Titel nur bis 48K/Lossless ab (Apple Community)](https://communities.apple.com/de/thread/256152319)

Related: [android-apple-music-usb-dac-bit-perfect-redmi-10-selene.md](android-apple-music-usb-dac-bit-perfect-redmi-10-selene.md) (same question on the Redmi 10, Android 11).
