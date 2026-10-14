---
type: how-to
tags: [android, bitchord, usb-dac, bit-perfect, uac, usbfs, media3, exoplayer, audio, redmi, mediatek, android-sdk, adb]
created: 2026-10-14
last_verified: 2026-10-14
status: current
---

# BitChord: USB exclusive mode (bit-perfect + built-in USB DAC driver)

Added a "USB exclusive mode" to the BitChord Android music app (Kotlin, Media3 1.11) so a USB DAC/DSP plays without Android's mixer, like Poweramp's `usbx` output or UAPP. The work is on branch `usb-exclusive-mode` of the fork https://github.com/txtsamu/BitChord (upstream: kushagrasinghx/BitChord), commit `8006f342`.

Test hardware: Redmi Note 12 Pro (`ruby`, model 22101316G, MediaTek MT6877, Android 14 / API 34, MIUI) + **Celest Sol** USB-C dongle DAC (VID 14663 / PID 15208, UAC1, full-speed).

## Outcome

- Two tiers, picked per phone:
  1. **Android 14 official bit-perfect** (`AudioManager.setPreferredMixerAttributes` + `MIXER_BEHAVIOR_BIT_PERFECT`). Falls back to a **native-rate** tier (same API, `MIXER_BEHAVIOR_DEFAULT`) when the HAL has no bit-perfect port.
  2. **Built-in UAPP-style driver**: USB host permission popup → claim the DAC away from `snd-usb-audio` → isochronous streaming over usbfs from native code. Used when Android can't do bit-perfect.
- Verified on device: driver claims Celest Sol, streams **24-bit / 48 kHz (alt 2)**, 96 kHz source resampled to 48 kHz in-app; phone volume keys drive the DAC's **hardware feature-unit volume** (-60..0 dB) through a remote-volume media session.

## Key findings (why the design is what it is)

1. **This Redmi cannot do Android's bit-perfect USB.** Its `/vendor/etc/usb_audio_policy_configuration.xml` is `halVersion="2.0"` (HIDL) and `usb_device output` has only `AUDIO_OUTPUT_FLAG_FAST`, no `AUDIO_OUTPUT_FLAG_BIT_PERFECT`. Confirmed at runtime: `getSupportedMixerAttributes()` returned 20 configs, all `behavior=0` (DEFAULT), only 44.1 / 48 kHz.
2. **The Celest Sol itself only does 44.1 / 48 kHz** (Poweramp's log: `srs=0x30 count=2 srs= 44100 48000`, `prepare selected alt=2 ... fmt=s24`). So a 96 kHz file is resampled by every app, Poweramp included. The exclusive-mode gain on this DAC is no system mixer, no Android volume processing, and no notification sounds, not higher rates.
3. **Media3 1.11 `DefaultAudioSink` only opens 16-bit or Float32 AudioTracks** (`ToInt16PcmAudioProcessor` vs `ToFloatPcmAudioProcessor`; `shouldUseFloatOutput = enableFloatOutput && isEncodingHighResolutionPcm`). A 24-bit int track is only possible below the sink, through the `AudioOutputProvider` / `AudioOutput` seam (`DefaultAudioSink.Builder.setAudioOutputProvider`). That seam is where both the 24-bit narrowing and the whole direct-USB output plug in.
4. **The popup in UAPP/Poweramp is the USB host permission dialog** (`UsbManager.requestPermission`). It only appears when the app drives the DAC itself. The Android-API tier has no popup.
5. **Volume keys stop working** once the driver claims the DAC: Android no longer has a USB audio device, so media volume moves the speaker. Fix: the session `ForwardingPlayer` reports `DeviceInfo.PLAYBACK_TYPE_REMOTE` (max 30) plus the device-volume commands while the driver holds the DAC. This is the same trick the app already used for Cast. `dumpsys media_session` then shows `volumeType=REMOTE, controlType=ABSOLUTE, max=30`.
6. **The app lagged** on the debug build. Thread CPU showed `RenderThread` and the Mali GPU driver dominating (Compose UI), not playback. The repo's `benchmark` build type (R8, non-debuggable, debug-signed, package `com.dev.bitchord.benchmark`) is much smoother.

## Architecture (files in the BitChord repo)

| File | Role |
|---|---|
| `playback/audio/usb/UsbBitPerfect.kt` | Android-API tier: query `getSupportedMixerAttributes`, choose a format, `setPreferredMixerAttributes` only when the AudioTrack actually opens (so a pre-buffered next track can't cut the current tail), listener for another app taking over |
| `playback/audio/usb/BitPerfectAudioOutputProvider.kt` | `ForwardingAudioOutputProvider`: (a) direct-USB output when the driver holds the DAC; (b) opens AudioTrack as packed 24 / 32-bit and narrows Float32 on `write()` (exact for 16/24-bit sources) |
| `playback/audio/usb/UacDescriptors.kt` | Parses raw UAC1/UAC2 descriptors: Type I alts (subslot, bits, rates), iso OUT endpoint + sync type + feedback ep, UAC2 clock sources, feature units (volume/mute) |
| `playback/audio/usb/UsbDirectDriver.kt` | Permission flow, `claimInterface(force=true)` for the AC and AS interfaces, alt selection, sample-rate SET_CUR (UAC1: endpoint request `0x22`; UAC2: clock source `0x21`), UAC2 RANGE, hardware volume, release + kernel reattach |
| `cpp/usb/usb_iso_stream.cpp` (`libbitchord_usb.so`) | usbfs `USBDEVFS_SUBMITURB` iso URBs (6 × 8 ms), SPSC ring buffer, silence when paused/starved, feedback endpoint for async DACs, `USBDEVFS_GET_SPEED`, `USBDEVFS_CONNECT` to hand the interface back |
| `playback/audio/usb/UsbDirectAudioOutput.kt` | Media3 `AudioOutput`: Float32/s16 → DAC subslot (2/3/4 bytes), mono→stereo, software gain only when there's no HW volume, position from frames the DAC consumed |
| `playback/audio/usb/SincResampler.kt` | Kaiser-windowed sinc (24 zero-crossings, β=9, 512 phases) for rates the DAC lacks |
| `PlaybackService.kt` | Wiring: sink encoding choice, float sink enable, DSP bypass, `SessionPlayer` remote volume, settings observers |
| `CrossfadeController.kt` | Crossfade/Automix disabled while exclusive (no volume ramps, one stream) |

## Steps / commands (in order)

### 1. Clone and inspect
```bash
cd ~/Music && git clone https://github.com/kushagrasinghx/BitChord && cd BitChord
grep -rn "AudioSink\|AudioTrack" --include=*.kt app/src/main/java | head   # existing PrecisionAudioSink, stub usb/DirectAudioOutput.kt
```

### 2. Toolchain without sudo (Fedora 43 only had JDK 25; Gradle 8.11.1 / AGP 8.10.1 need ≤21)
```bash
mkdir -p ~/.local/jdks ~/Android/Sdk/cmdline-tools
cd ~/.local/jdks && curl -sL -o jdk21.tgz "https://api.adoptium.net/v3/binary/latest/21/ga/linux/x64/jdk/hotspot/normal/eclipse" && tar xzf jdk21.tgz && rm jdk21.tgz
cd ~/Android/Sdk/cmdline-tools && curl -sL -o clt.zip https://dl.google.com/android/repository/commandlinetools-linux-13114758_latest.zip && unzip -q clt.zip && mv cmdline-tools latest && rm clt.zip
export JAVA_HOME=~/.local/jdks/jdk-21.0.12.1+1 ANDROID_HOME=~/Android/Sdk
yes | sdkmanager --sdk_root=$ANDROID_HOME --licenses
sdkmanager --sdk_root=$ANDROID_HOME "platforms;android-37.0" "build-tools;36.0.0" "platform-tools" "ndk;27.0.12077973" "cmake;3.22.1"
echo "sdk.dir=$HOME/Android/Sdk" > ~/Music/BitChord/local.properties
```
**Gotcha:** `compileSdk = 37` but the SDK manager only has `platforms;android-37.0` (no `android-37`). AGP 8.10 then fails with `Failed to find target with hash string 'android-37'`. A symlink doesn't help, because AGP reads `package.xml`. Working fix: copy the platform and patch its metadata:
```bash
cd ~/Android/Sdk/platforms && cp -a android-37.0 android-37
sed -i 's/platforms;android-37.0/platforms;android-37/; s/<api-level>37.0</<api-level>37</' android-37/package.xml
sed -i 's/AndroidVersion.ApiLevel=37.0/AndroidVersion.ApiLevel=37/' android-37/source.properties
```

### 3. Research: is the phone capable?
```bash
adb shell getprop ro.build.version.sdk          # 34
adb shell cat /vendor/etc/usb_audio_policy_configuration.xml   # halVersion 2.0, no BIT_PERFECT flag
adb shell dumpsys usb | sed -n '/host_manager/,/]/p'           # interfaces/alts/endpoints of the DAC
adb shell dumpsys media.audio_flinger | grep -E "Output thread|Sample rate|HAL format|Output devices"
```
`/sys/bus/usb/devices/*/descriptors` is permission-denied on MIUI without root. The app logs its parsed descriptors instead.

### 4. Build, test, install
```bash
cd ~/Music/BitChord
./gradlew :app:testDevDebugUnitTest --tests '*.usb.*'      # 17 tests
./gradlew :app:testDevDebugUnitTest --tests 'com.music.bitchord.playback.*' --tests 'com.music.bitchord.AudioPipelineTest'   # 204 pass
# Optimized build. Lint-vital fails on an UPSTREAM issue (zh-Hant strings with no default: lyrics_original_title*), skip it locally:
./gradlew :app:assembleDevBenchmark -x lintVitalAnalyzeDevBenchmark -x lintVitalReportDevBenchmark -x lintVitalDevBenchmark
adb install -r app/build/outputs/apk/dev/benchmark/app-dev-arm64-v8a-benchmark.apk
```
MIUI: `INSTALL_FAILED_USER_RESTRICTED` until **Developer options → Install via USB** is on. Every install then needs a tap on the phone's confirmation prompt, including over Wi-Fi adb.

### 5. Wi-Fi adb so the phone's USB port can hold the DAC
```bash
IP=$(adb shell ip -f inet addr show wlan0 | awk '/inet /{print $2}' | cut -d/ -f1)
adb tcpip 5555 && adb connect $IP:5555     # 192.168.50.3 here
adb -s $IP:5555 logcat -v time -s UsbDirectDriver:* UsbDirectAudioOutput:* UsbIsoStream:* UsbBitPerfect:*
adb -s $IP:5555 shell dumpsys media_session | grep -A14 bitchord | grep volumeType
```

### 6. Reference: what Poweramp's driver does (for comparison)
```bash
adb logcat -d --pid=$(adb shell pidof com.maxmpz.audioplayer) | grep -i -E "usbx|USB lock"
# PSRouterUsbExclusiveLock: USB lock ENGAGED name=Celest Sol path=/dev/bus/usb/001/002
# usbxoutput.c: prepare selected alt=2 ch=2 sr=48000 ... fmt=s24 ... srs= 44100 48000
```
Poweramp holds the DAC while it plays, so stop it before BitChord can claim the DAC.

### 7. Expected BitChord log on success
```
UsbDirectDriver: hardware volume: unit 2 channels=[1, 2] range -60.0..0.0 dB mute=0
UsbDirectDriver: opened Celest Sol: Celest Sol · UAC1 · 16/24-bit · 44.1/48 kHz
UsbIsoStream: stream started ep=0x02 maxPacket=288 pps=1000 frameBytes=6 rate=48000 fb=0x00
UsbDirectAudioOutput: output 96000 Hz float x2 → DAC 48000 Hz 24-bit x2 (resampled)
```

### 8. Commit and push
```bash
git checkout -b usb-exclusive-mode && git add ... && git commit
gh repo fork kushagrasinghx/BitChord --remote --remote-name fork --clone=false   # created fork but did NOT add the remote
git remote add fork https://github.com/txtsamu/BitChord.git && git push -u fork usb-exclusive-mode
```

## Dead ends / ruled out

- **AAudio exclusive mode:** USB on Android has no MMAP path, so it silently becomes SHARED (the repo's own `AAudioEvaluation.kt` documents this).
- **Android bit-perfect on this phone:** HAL lacks it (above). The native-rate tier works but still mixes notifications and applies system volume.
- **Symlinking `android-37` → `android-37.0`:** AGP still rejects it. The copy + metadata patch is needed.
- **Reading sysfs descriptors:** permission denied on MIUI.

## Known limitations / follow-ups

- **Untested on hardware:** UAC2 high-speed DACs and async feedback endpoints are implemented but untested. The Celest Sol is UAC1 adaptive.
- **Unplug mid-song** throws a non-recoverable write error, so playback stops instead of blasting from the speaker.
- **No DSD/DoP, and >2-channel streams** fall back to the system path, which means the speaker while the driver holds the DAC.
- **Resampler CPU:** Kotlin, not optimized. A polyphase table for 2:1 ratios or a C++ port would cut CPU several-fold.
- **Volume persistence:** the driver holds the DAC for as long as the setting is on and the service is alive. Software-volume step is in memory only.
- **Upstream lint bug:** the zh-Hant `lyrics_original_title*` strings break `lintVital` on release builds.

## References

- [Android Developers – Improve audio playback (preferred mixer attributes / BIT_PERFECT)](https://developer.android.com/media/platform/improve-audio-playback)
- [AOSP – Preferred mixer attributes on USB devices](https://source.android.com/docs/core/audio/preferred-mixer-attr)
- [Media3 1.11.0 DefaultAudioSink.java](https://github.com/androidx/media/blob/1.11.0/libraries/exoplayer/src/main/java/androidx/media3/exoplayer/audio/DefaultAudioSink.java)
- [Media3 1.11.0 AudioOutputProvider.java](https://github.com/androidx/media/blob/1.11.0/libraries/exoplayer/src/main/java/androidx/media3/exoplayer/audio/AudioOutputProvider.java)
- [Media3 1.11.0 AudioTrackAudioOutputProvider.java](https://github.com/androidx/media/blob/1.11.0/libraries/exoplayer/src/main/java/androidx/media3/exoplayer/audio/AudioTrackAudioOutputProvider.java)
- [Media3 1.11.0 AudioOutput.java](https://github.com/androidx/media/blob/1.11.0/libraries/exoplayer/src/main/java/androidx/media3/exoplayer/audio/AudioOutput.java)
- [Adoptium API (Temurin 21 download)](https://api.adoptium.net/)
- [Android SDK command-line tools](https://developer.android.com/studio#command-line-tools-only)
