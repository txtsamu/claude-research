---
type: investigation
tags: [android, apple-music, audioflinger, bitrate, lossless, hi-res, redmi-note-12-pro, ruby, adb, dumpsys, bit-perfect]
created: 2026-11-26
last_verified: 2026-11-26
status: current
---

# Is Apple Music on Android playing the right bitrate? (Redmi Note 12 Pro 5G, adb)

Question: the phone is attached over adb, Apple Music is playing. Is the app decoding and feeding the **correct native sample rate** (lossless / hi-res), or is it falling back to AAC 256 and/or resampling internally?

Answer, measured: **the app is correct, the phone's output path is not.** Apple Music opens an `AudioTrack` at the source rate (44100 Hz for a CD-rate track, 192000 Hz for a 24/192 track, same app version, same session), but every track lands in a 48 kHz `MIXER` thread (`AudioOut_15`, HAL `PCM_32_BIT`, `AUDIO_DEVICE_OUT_WIRED_HEADPHONE`), so 192 kHz is resampled down to 48 kHz before the internal DAC. `BitPerfect` is `false` on the track row.

## Time estimate

About 10 minutes of hands-on work, plus two passive waits that are measured here: 45 s and 90 s of network sampling, and 3 x 4 s audio_flinger polls. Roughly 1 of those 10 minutes went to fighting a flapping USB cable (see Gotchas).

## Device state

```bash
adb devices -l
adb shell 'getprop ro.product.model; getprop ro.build.version.release; getprop ro.build.version.sdk'
adb shell 'dumpsys package com.apple.android.music | grep -E "versionName|versionCode"'
adb shell 'pm list packages -U | grep apple'
```

| Item | Value |
|---|---|
| Device | `22101316G`, codename `ruby` (Redmi Note 12 Pro 5G), MTK |
| Android | 14 (SDK 34), MIUI/HyperOS |
| Apple Music | `com.apple.android.music` 7.0.3 (versionCode 1626), uid **10953** |
| Playback | Apple Music PID 31742, MEDIA_SESSION `PLAYING` |
| Output | 3.5 mm jack, `AUDIO_DEVICE_OUT_WIRED_HEADPHONE` |
| Root | none (`su` not present), so `/proc/<pid>/maps` and app data are unreadable |

Track under test: Surfaces, *Sunday Best* / "Where the Light Is" (album is badged **Hi-Res Lossless** and **Dolby Atmos** in the app). The same song was first seen at 44.1 kHz, then at 192 kHz after the quality setting was raised, which makes it a clean before/after on one file.

## The commands that actually answer the question

```bash
# what does the app hand to AudioFlinger right now
adb shell 'dumpsys media.audio_flinger' | awk '/^Output thread/{th=$0} /Tracks of which/{print th; getline; getline; print "   "$0}'

# full dump, keep it for the thread header (sample rate, HAL format, device)
adb shell 'dumpsys media.audio_flinger' > flinger.txt

# what the app claims to be playing
adb shell 'dumpsys media_session' | grep -A15 com.apple.android.music
```

Track-row columns are, in order: `Type Id Active Client(PID) Session PortId S Flags Format ChnMask SRate ST Usg CT Gdb LdB RdB VSdB Server FrmCnt FrmRdy F Underruns Flushed BitPerfect Latency`.

## Evidence

### 44.1 kHz state (10:10), same song

```
Output thread ..., name AudioOut_15, tid 1821, type 0 (MIXER):
  Sample rate: 48000 Hz
  HAL format: 0x3 (AUDIO_FORMAT_PCM_32_BIT)
  Output devices: 0x8 (AUDIO_DEVICE_OUT_WIRED_HEADPHONE)
  1 Tracks of which 1 are active
           2278    yes  31742   10129    2329 A  0x000 00000005 00000003  44100  3   1  0  -19 ...  false  354.44
```

### 192 kHz state (10:12, held for three 4 s polls)

```
           2281    yes  31742   10081    2332 A  0x000 00000005 00000003 192000  3   1  0  -23 ...  false  397.74
           2281    yes  31742   10081    2332 A  0x000 00000005 00000003 192000  ...  false  396.98
           2281    yes  31742   10081    2332 A  0x000 00000005 00000003 192000  ...  false  397.27
```

Field readout:

| Field | Value | Meaning |
|---|---|---|
| `Client` | 31742 | matches `pidof com.apple.android.music`, so the track is Apple Music's, not a system sound |
| `Format` | `00000005` | `AUDIO_FORMAT_PCM_FLOAT` (0x3 is `PCM_32_BIT`, 0x5 is float, 0x6 is `PCM_24_BIT_PACKED`) |
| `SRate` | `44100` then `192000` | the app follows the source rate, no fixed internal resample |
| `Chn mask` | `00000003` | stereo |
| `F Underruns` | `0` | not glitching |
| `BitPerfect` | `false` | the framework flags this track as non-bit-perfect |

### Where the 192 kHz actually goes

The only active output thread is a 48 kHz `MIXER` (`AudioOut_15`) on the wired headphone device. AudioFlinger resamples any track whose rate differs from the mixer thread rate, so 192 kHz is converted to 48 kHz before the HAL. There is no direct/offload thread at 192 kHz for it to escape to; the 96 kHz threads in the dump are historical/standby (they belonged to a USB headset that was unplugged earlier).

HAL format on the output is `PCM_32_BIT`, so 24-bit depth survives the trip, the sample rate does not.

## Ruling out "it's just AAC 256"

AAC in Apple Music tops out at 44.1/48 kHz, so a 192000 Hz `AudioTrack` cannot be an AAC decode. It proves the hi-res lossless tier is active and the app is not downsampling, at least on the client side.

Network volume is useless for confirming this on a downloaded song: wifi `rx_bytes` measured **120,747 B in 90 s (1.3 KB/s)** on the 44.1 k track and **61,091 B in 45 s (~10 kbps)** on the 192 k one. Both were offline files, so the stream bitrate is not observable from traffic. If you need to measure an online stream, read `/proc/net/dev` (`wlan0` rx) before and after a 60-90 s window; per-uid numbers are not available without root.

Also ruled out: `dumpsys media.codec` on this build prints `Can't find service: media.codec`, and `dumpsys media.metrics` holds **zero** `mime=audio` records for uid 10953 (only `video/hevc` for the animated artwork), so Apple Music decodes audio in its own native stack rather than through Java `MediaCodec`. There is no codec-name trail to read; the sample rate on the AudioTrack is the strongest available signal.

## Verdict

| Layer | Rate | Correct? |
|---|---|---|
| Apple's stream / app decode | 192 kHz (44.1 kHz on the other track) | yes, native rate |
| App's `AudioTrack` | 192000 Hz, float, stereo | yes |
| AudioFlinger mixer thread (3.5 mm) | 48000 Hz | resampled |
| 3.5 mm DAC | 48 kHz, 32-bit | not the source rate |
| AudioFlinger mixer thread (JA11 USB) | 96000 Hz | resampled |
| JA11 DAC | 96 kHz, 32-bit | the HAL ceiling, not the source rate |

So "is it playing the correct bitrate" splits in two: the app is delivering the right stream at the right rate; the phone then resamples it, 4:1 on the jack and 2:1 over USB. The JA11 does not buy native 192 kHz on this phone, because Android caps the dongle at 96 kHz; and true bit-perfect would need `AUDIO_OUTPUT_FLAG_BIT_PERFECT`, which stock MIUI did not expose on the sibling Redmi 10 test either (see [[android-apple-music-usb-dac-bit-perfect-redmi-10-selene]]).

## With a USB DAC attached (FiiO JadeAudio JA11, same session)

Plugging the dongle in changes the ceiling, not the behaviour. The app keeps requesting the source rate; Android now opens a 96 kHz output thread for the USB device instead of the 48 kHz jack thread.

```
Output thread ..., name AudioOut_1A5, tid 6098, type 0 (MIXER):
  Sample rate: 96000 Hz
  HAL frame count: 4096
  HAL format: 0x3 (AUDIO_FORMAT_PCM_32_BIT)
  HAL buffer size: 32768 bytes
  Output devices: 0x4000000 (AUDIO_DEVICE_OUT_USB_HEADSET)
  Timestamp stats: ... localSR(95999.8, ...)
  2 Tracks of which 1 are active
           2289    yes  31742   10081    2343 A  0x000 00000005 00000003 192000 ... false  381.52
```

- Same 24/192 track, same app: `AudioTrack` **192000 Hz** -> mixer thread **96000 Hz** -> DAC. The resample is now 2:1 instead of the jack's 4:1.
- `localSR(95999.8)` in the timestamp stats is the HAL clock measured at ~96 kHz, so the 96 kHz is real and steady, not just a declared rate.
- `BitPerfect` is still `false`, and there is no bit-perfect port anywhere in the policy: the USB routes are `Mix; Sink: "USB Headset Out"` fed by `primary output`, `deep_buffer`, `fast`, `hifi_playback` (a MIUI mix port with `AUDIO_OUTPUT_FLAG_NONE`), so it is a normal mixer, not a direct path.

Why 96 kHz and not 192: the phone's USB audio HAL advertises this dongle with a hard ceiling of **44100, 48000, 88200, 96000** in `dumpsys media.audio_policy`, even though the JA11 is sold as 384 kHz/32-bit. `dumpsys usb` identifies it as `FIIO / JadeAudio JA11`, port `USB Headset Out`, `card=1;device=0`.

Rate fidelity spot-checks while switching tracks with the DAC attached (all `Client 31742`):

| Track | AudioTrack rate | Format | Note |
|---|---|---|---|
| Dua Lipa, "Break My Heart" | 48000 | PCM float | a genuine 48 k master, the app did not force 48 k |
| SHE IS SUMMER, "CALL ME IN YOUR SUMMER" | 44100 | **PCM 16-bit** | 16-bit content, 44.1 k passed through untouched |
| Surfaces, "Where the Light Is" | 192000 | PCM float | hi-res, capped to 96 k by the USB HAL |

So the app is rate-faithful on both outputs; the loss happens in the phone's HAL.

## Gotchas

- **The USB cable kept dropping.** Kernel log: `usb 1-4: USB disconnect` then `device descriptor read/64, error -110` on a loop, every few seconds. `adb devices` would show the device, then lose it mid-command. Workaround that made the session usable: `adb tcpip 5555` then `adb connect <phone-ip>:5555`, and run everything against `192.168.50.3:5555`. Wireless debugging was already enabled on the phone.
- **`/sys/class/net/wlan0/statistics/rx_bytes` is permission denied for the shell user** on this build. `/proc/net/dev` is readable and carries the same rx counter.
- **`dumpsys netstats detail` is useless for minute-scale measurement**: buckets are `bucketDuration=7200` (2 h).
- **No root**: `su` absent, `/proc/31742/maps` denied, so the app's loaded decoder libs can't be listed and its settings XML can't be read. The quality setting was confirmed indirectly (the 44.1 -> 192 switch) and by the in-app album badges.
- **Apple Music is a Media3/media-session app but not a MediaCodec audio client**, so all the usual "grep logcat for `c2.*alac.decoder`" recipes give nothing on this app.

## What was not verified

- Bit depth. The track is `PCM_FLOAT`; float cannot tell 16 from 24 bit. 192 kHz only exists in Apple's lossless tier (which is 24-bit), so 24/192 is the safe inference, not a direct read.
- Whether the 44.1 kHz track was ALAC 16/44.1 or AAC 256. Same song at 44.1 kHz before the setting change, but with no codec trail and an offline file, both look identical to `audio_flinger`.
- The resampler quality. Android's mixer resampler is not bit-perfect, but how audible the 192 -> 48 conversion is was not measured, and no listening test was done.

## References

- [About lossless audio in Apple Music (Apple Support, updated 2026-11-12)](https://support.apple.com/en-us/HT212183) — Android section confirms lossless is supported with a wired connection and that rates above 48 kHz may need an external DAC.
- [AOSP `audio-base.h` format enum](https://android.googlesource.com/platform/system/media/+/refs/heads/main/audio/include/system/audio-base.h) — `AUDIO_FORMAT_PCM_FLOAT = 0x5`, `AUDIO_FORMAT_PCM_32_BIT = 0x3`.

Related: [[android-apple-music-usb-dac-bit-perfect-redmi-10-selene]], [[redmi-note-12-pro-hyperos-duplicate-storage-folders-2026-11-19]], [[bitchord-android-usb-exclusive-mode-uac-driver]].
