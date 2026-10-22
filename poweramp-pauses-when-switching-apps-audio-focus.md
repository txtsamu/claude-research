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

Remaining untested ideas, in order: disable Direct Volume Control; raise audio thread priority; try OpenSL ES vs AudioTrack/Hi-Res output; turn off EQ; sample CPU frequency during screen-off (`adb shell cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq`) and check OriginOS battery/background settings for Poweramp. Next measurement: play, lock/unlock a few times, then re-read `underruns=` for the new output thread.

## References

- [Poweramp forum: crackling sound when lockscreen](https://forum.powerampapp.com/topic/10176-crackling-sound-when-lockscreen/)
- [Poweramp forum: song/sound is breaking up when the screen is locked](https://forum.powerampapp.com/topic/20765-songsound-is-breaking-up-when-the-screen-is-locked/)
- [Poweramp forum: crackling with USB DAC](https://forum.powerampapp.com/topic/9763-crackling-with-usb-dac/)
- [Poweramp forum: crackling during playback](https://forum.powerampapp.com/topic/9882-crackling-during-playback)
