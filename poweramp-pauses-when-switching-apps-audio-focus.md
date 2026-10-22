---
type: troubleshooting
tags: [android, iqoo, vivo, poweramp, adb, audio-focus, usb-dac, fingerprint, instagram]
created: 2026-10-22
last_verified: 2026-10-22
status: current
---

# Poweramp pauses on app switch, lags on fingerprint unlock (iQOO I2512)

Device: iQOO I2512, Android 16, OriginOS 7.0, Poweramp build-1031, output to a FiiO JadeAudio JA11 USB DAC.

Two separate symptoms:

1. Music pauses/glitches when switching to other apps. **Cause confirmed:** other apps grab audio focus.
2. Music crackles/lags around screen lock/unlock. **Partly narrowed down:** the bigger Poweramp buffer helps, and the unlock lag only happens with **fingerprint** unlock, not pattern. Root cause not found.

## Diagnosis (adb over wireless debugging)

1. Find the phone. mDNS discovery (`adb mdns services`) returned nothing, so scan the LAN. Phones use randomized (locally administered) MACs, so only `ip neigh` entries with such MACs were worth scanning:
   ```bash
   ip neigh | grep -v FAILED
   nmap -Pn -n -p 30000-45000 --open -T4 192.168.50.26   # wireless-debug port is random in 30000-45000
   adb connect 192.168.50.26:33637
   adb devices -l      # model I2512
   ```
2. Rule out the usual vivo suspects (background killing):
   ```bash
   adb shell dumpsys deviceidle whitelist | grep maxmpz    # Poweramp is on the battery whitelist
   adb shell am get-standby-bucket com.maxmpz.audioplayer  # 5 = exempted
   adb shell ps -A | grep maxmpz                           # process alive
   ```
   Poweramp is not being killed, so this is not the OriginOS background-kill issue.
3. Check audio focus history, which is where symptom 1 shows up:
   ```bash
   adb shell dumpsys audio | grep -E "requestAudioFocus|abandonAudioFocus|focus owner"
   adb shell dumpsys media_session     # Poweramp session state=PLAYING
   ```

## Symptom 1: pauses when switching apps

Other apps steal audio focus whenever a video starts, and Poweramp pauses on the loss, then resumes when they release it:

```
08:24:49 requestAudioFocus() com.instagram.android req=4 flags=0x0     # req=4 = GAIN_TRANSIENT_EXCLUSIVE
08:24:49 focus owner: com.maxmpz.audioplayer code: -2 (LOSS_TRANSIENT)  # Poweramp told to pause
08:24:52 abandonAudioFocus() com.instagram.android
08:24:52 focus owner: com.maxmpz.audioplayer code: 1 (GAIN)             # Poweramp resumes
08:24:53 requestAudioFocus() com.maxmpz.audioplayer req=1
```

Instagram requests exclusive transient focus on every reel/video, even auto-played ones (dozens of request/abandon pairs in the log). Tokopedia (`req=2`, transient) and LinkedIn do the same. Poweramp's own focus request uses `PAUSES_ON_DUCKABLE_LOSS`, so it pauses instead of ducking. Each loss also makes Poweramp recreate its `AudioTrack` (new player piids at 08:06), which is the audible glitch.

Fixes (not applied, user's call):

- Poweramp: look for an audio focus option (wording varies by build) so it ducks instead of pausing.
- Instagram: Settings > Accessibility > turn off autoplay; videos then stop grabbing focus until played.
- There is no OriginOS toggle to deny audio focus to a single app.

## Symptom 2: crackling / lag around lock and unlock

### Initial state

`dumpsys media.audio_flinger` for the USB mixer thread (`AudioOut_D`, 48 kHz, 192-frame HAL buffer = 4 ms) showed `FastMixer underruns=9 overruns=120`, `Delayed writes: 109`, timestamp `disc=107`, with Poweramp tracks repeatedly created/removed and the audio patch rebuilt (`CFG_EVENT_CREATE_AUDIO_PATCH USB->USB`). A 4 ms buffer has no slack when the CPU is throttled across screen lock/unlock.

```bash
adb shell dumpsys media.audio_flinger | grep -E "Output thread|underruns|Delayed writes|Total writes"
```

### Raising the buffer (helps)

User raised the buffer size in Poweramp (Settings > Audio > Advanced Tweaks).

- Poweramp rebuilt its output: a new track at 192 kHz (08:31) instead of the 48 kHz / 4 ms `AudioOut_D` path. The old thread's counters stopped changing, so they are stale, not a measurement of the new path.
- User reports the bigger buffer **helps** general glitching, but crackling **still happens on lock/unlock**.
- "Audio Thread Priority" (advice from 2017 forum posts) does **not** exist in build 1031; no changelog found saying when it was removed.

### Lag on unlock, then resume

Test: lock 08:38:31, unlock 08:39:12 (`adb logcat -b events | grep screen_toggled`).

- `dumpsys audio` / `media.audio_flinger` show **no** audio event at the unlock instant (no focus change, no re-route, no new underruns). Poweramp stays PLAYING.
- While locked, a Poweramp `USAGE_ASSISTANCE_SONIFICATION` AudioTrack (piid 11407) started/stopped repeatedly and the audio patch was rebuilt on the same device (08:38:50 - 08:39:01). Purpose not identified.
- The active output thread's device was `EARPIECE`, not the JA11 DAC (patch USB -> earpiece at 08:35:45), so DAC routing needs verifying before blaming the buffer.
- Logcat around the unlock showed no ANR/slow/lmkd lines.
- An earlier 1-2 second lock test showed no new underruns (1689 writes, delayed writes unchanged at 290); too short to be conclusive.

### Fingerprint vs pattern (user finding)

The unlock lag **only happens with fingerprint unlock; pattern unlock keeps audio smooth.** So the trigger is the biometric unlock path, not Poweramp's buffer or focus. Workaround: unlock with pattern/PIN.

Cause not identified. Plausible but unverified: fingerprint auth causes a CPU/power/display burst or fingerprint-HAL activity that briefly disturbs the audio thread or the USB path. Sensor type on this iQOO was not checked. Next step: capture `adb logcat -v time` during one fingerprint unlock and one pattern unlock with music playing through the DAC, and diff USB, audio re-routing, CPU frequency (`cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq`) and fingerprint service activity.

### Untested ideas

Poweramp **Use Wakelock** option (fixed most lock-screen crackling on a 2017 Xiaomi report together with a bigger buffer), disable Direct Volume Control, OpenSL ES vs AudioTrack/Hi-Res output, EQ off, OriginOS battery/background settings for Poweramp, unplug/replug the DAC.

## Web research summary

- Poweramp forum has the same lock/unlock symptom mostly over Bluetooth (aptX Adaptive stutter fixed by SBC; bigger buffer; absolute volume toggle), and crackling on lock screen fixed by wakelock plus a bigger buffer.
- Fingerprint precedent: one Poweramp user on a Samsung (Android 6) whose music stopped after lock until the saved fingerprint was deleted and pattern unlock used; an old iOS 7 Touch ID music-skip thread.
- A GSMArena comment says dongle DACs crackled then went silent after the iQOO OriginOS 6 update (anecdote).
- Three searches found **no confirmed mechanism and no vivo/iQOO report** tying fingerprint unlock to audio lag.

## References

- [Poweramp forum: crackling sound when lockscreen](https://forum.powerampapp.com/topic/10176-crackling-sound-when-lockscreen/)
- [Poweramp forum: song/sound is breaking up when the screen is locked](https://forum.powerampapp.com/topic/20765-songsound-is-breaking-up-when-the-screen-is-locked/)
- [Poweramp forum: crackling with USB DAC](https://forum.powerampapp.com/topic/9763-crackling-with-usb-dac/)
- [Poweramp forum: crackling during playback](https://forum.powerampapp.com/topic/9882-crackling-during-playback)
- [Poweramp forum: stuttering on Bluetooth when locking/unlocking](https://forum.powerampapp.com/topic/25322-music-is-stuttering-on-bluetooth-when-locking-and-unlocking-the-phone/)
- [Poweramp forum: music stops when device locked (fingerprint may interfere)](https://forum.powerampapp.com/topic/10116-music-stops-playing-when-device-locked-possible-solution/)
- [Spotify community: stuttering when screen is locked](https://community.spotify.com/t5/Android/Music-stuttering-when-Screen-is-locked/m-p/3591102/highlight/true)
- [GSMArena: iQOO 12 OriginOS 6 update](https://m.gsmarena.com/iqoo_12_finally_gets_stable_originos_6_update_based_on_android_16-amp-70653.php)
- [iMore: music skips after Touch ID unlock (iOS 7)](https://forums.imore.com/iphone-5s/273113-music-skips-stutters-after-unlocking-device-using-touch-id-ios-7-0-4-a.html)
