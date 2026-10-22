---
type: troubleshooting
tags: [android, iqoo, vivo, poweramp, adb, audio-focus, instagram]
created: 2026-10-22
last_verified: 2026-10-22
status: current
---

# Poweramp stutters/pauses when switching apps on iQOO (I2512)

Symptom: music playing in Poweramp behaves "weird" (pauses, restarts) when switching to other apps.

## Diagnosis (adb over wireless debugging)

1. Find the phone. mDNS discovery (`adb mdns services`) returned nothing, so scan the LAN. Phones use randomized (locally administered) MACs, so only the `ip neigh` entries whose first octet has bit 2 set were worth scanning:
   ```bash
   ip neigh | grep -v FAILED
   nmap -Pn -n -p 30000-45000 --open -T4 192.168.50.26   # wireless-debug port is random in 30000-45000
   adb connect 192.168.50.26:33637
   adb devices -l      # model I2512, Android 16, OriginOS 7.0
   ```
2. Rule out the usual vivo suspects (background killing):
   ```bash
   adb shell dumpsys deviceidle whitelist | grep maxmpz   # Poweramp is on the battery whitelist
   adb shell am get-standby-bucket com.maxmpz.audioplayer  # 5 = exempted
   adb shell ps -A | grep maxmpz                           # process alive
   ```
   Poweramp is not being killed, so this is not the OriginOS background-kill issue.
3. Check audio focus history, which is where the cause shows up:
   ```bash
   adb shell dumpsys audio | grep -E "requestAudioFocus|abandonAudioFocus|focus owner"
   adb shell dumpsys media_session     # Poweramp session state=PLAYING
   ```

## Cause

Other apps steal audio focus whenever a video starts, and Poweramp pauses on the loss, then resumes when they release it:

```
08:24:49 requestAudioFocus() com.instagram.android req=4 flags=0x0     # req=4 = GAIN_TRANSIENT_EXCLUSIVE
08:24:49 focus owner: com.maxmpz.audioplayer code: -2 (LOSS_TRANSIENT)  # Poweramp told to pause
08:24:52 abandonAudioFocus() com.instagram.android
08:24:52 focus owner: com.maxmpz.audioplayer code: 1 (GAIN)             # Poweramp resumes
08:24:53 requestAudioFocus() com.maxmpz.audioplayer req=1
```

Instagram requests exclusive transient focus on every reel/video, even auto-played ones (dozens of request/abandon pairs in the log). Tokopedia (`req=2`, transient) and LinkedIn do the same. Poweramp's own focus request uses `PAUSES_ON_DUCKABLE_LOSS`, so it pauses instead of ducking. Each loss also makes Poweramp recreate its `AudioTrack` (new player piids at 08:06), which is the audible glitch.

## Fixes (not applied, user's call)

- Poweramp: Settings > Audio > Audio Focus / "Ignore audio focus loss" (wording varies by build), or switch the loss behavior to duck instead of pause.
- Instagram: Settings > Accessibility > turn off "Autoplay"/mute-by-default; videos then stop grabbing focus until played.
- Per-app: there is no OriginOS toggle to deny audio focus to a single app.

## Second symptom: glitchy sound after lock/unlock

Output goes to a USB DAC (FiiO JadeAudio JA11, `AUDIO_DEVICE_OUT_USB_HEADSET`). `dumpsys media.audio_flinger` for the USB mixer thread (`AudioOut_D`, 48 kHz, 192-frame HAL buffer = 4 ms) shows `FastMixer underruns=9 overruns=120`, `Delayed writes: 109`, timestamp `disc=107`. Poweramp tracks on this thread are repeatedly created/removed and the audio patch is rebuilt (`CFG_EVENT_CREATE_AUDIO_PATCH USB->USB`) on each focus change. A 4 ms buffer has no slack when the CPU is throttled across screen lock/unlock.

```bash
adb shell dumpsys media.audio_flinger | grep -E "Output thread|underruns|Delayed writes|Total writes"
```

Web search found no vivo/iQOO-specific report, but Poweramp's forum has the same pattern on other phones; the developer's standard advice is to raise buffer size/audio thread priority, disable Direct Volume Control, try OpenSL ES vs AudioTrack/Hi-Res output, and check ROM CPU throttling when the screen is off. 
### Result of raising the buffer (2026-10-22)

User raised the buffer size in Poweramp (Settings > Audio > Advanced Tweaks). Effects:

- Poweramp rebuilt its output: a new track at 192 kHz (`dumpsys media.audio_flinger`, 08:31) instead of the 48 kHz / 4 ms `AudioOut_D` mixer path. The old thread's counters (`underruns=9 overruns=120`) stopped changing, so they are stale, not a measurement of the new path.
- The user reports the bigger buffer **helps** with general glitching, but crackling **still happens on lock/unlock**.

Correction: "Audio Thread Priority" is not present in the current build (1031); the advice comes from 2017 forum posts, and a web search found no changelog entry confirming when it was removed. A 2017 Xiaomi report also fixed most lock-screen crackling with a **wakelock** option plus a bigger buffer, so look for a wake-lock setting instead.

Remaining untested ideas, in order: disable Direct Volume Control; look for a wake-lock option; try OpenSL ES vs AudioTrack/Hi-Res output; turn off EQ; sample CPU frequency during screen-off (`adb shell cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq`) and check OriginOS battery/background settings for Poweramp. Next measurement: play, lock/unlock a few times, then re-read `underruns=` for the new output thread.

### Lag on unlock, then resume (2026-10-22)

User: music lags on unlock, then resumes. Lock 08:38:31, unlock 08:39:12 (`logcat -b events | grep screen_toggled`).

- `dumpsys audio` / `media.audio_flinger` show **no** audio event at the unlock instant (no focus change, no re-route, no new underruns). Poweramp stays PLAYING.
- While locked, a Poweramp `USAGE_ASSISTANCE_SONIFICATION` AudioTrack (piid 11407) started/stopped repeatedly and the audio patch was rebuilt on the same device (08:38:50 - 08:39:01). Purpose not identified.
- At the time the active output thread's device was `EARPIECE`, not the JA11 DAC (patch USB -> earpiece at 08:35:45), so the DAC routing needs verifying before blaming the buffer.
- Logcat around the unlock showed no ANR/slow/lmkd lines.

Web: Poweramp forum has the same symptom, mostly over Bluetooth (aptX Adaptive stutter on lock/unlock fixed by SBC; bigger buffer; toggling absolute volume). Other threads: enable Poweramp's **Use Wakelock**, exempt from battery optimizers, and one case fixed by removing fingerprint unlock. A GSMArena comment says dongle DACs crackled then went silent after the iQOO OriginOS 6 update (anecdote). No confirmed iQOO fix found.

References: [Poweramp: stuttering on Bluetooth when locking/unlocking](https://forum.powerampapp.com/topic/25322-music-is-stuttering-on-bluetooth-when-locking-and-unlocking-the-phone/), [Poweramp: music stops when device locked](https://forum.powerampapp.com/topic/10116-music-stops-playing-when-device-locked-possible-solution/), [Spotify community: stuttering when screen is locked](https://community.spotify.com/t5/Android/Music-stuttering-when-Screen-is-locked/m-p/3591102/highlight/true), [GSMArena: iQOO 12 OriginOS 6](https://m.gsmarena.com/iqoo_12_finally_gets_stable_originos_6_update_based_on_android_16-amp-70653.php)

**User finding (2026-10-22): the unlock lag only happens with fingerprint unlock; pattern unlock keeps audio smooth.** This matches the forum report where removing fingerprint unlock fixed lock-related audio problems, so the trigger is the biometric unlock path (fingerprint service/HAL work, sensor/display boost, CPU load), not Poweramp's buffer or focus. Cause not yet identified; next step is capturing logcat (`adb logcat -v time`) during a fingerprint unlock and diffing against a pattern unlock. Workaround: unlock with pattern/PIN.


- [Poweramp forum: crackling sound when lockscreen](https://forum.powerampapp.com/topic/10176-crackling-sound-when-lockscreen/)
- [Poweramp forum: song/sound is breaking up when the screen is locked](https://forum.powerampapp.com/topic/20765-songsound-is-breaking-up-when-the-screen-is-locked/)
- [Poweramp forum: crackling with USB DAC](https://forum.powerampapp.com/topic/9763-crackling-with-usb-dac/)
- [Poweramp forum: crackling during playback](https://forum.powerampapp.com/topic/9882-crackling-during-playback)
