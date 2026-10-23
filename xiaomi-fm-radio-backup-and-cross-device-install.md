---
type: how-to
tags: [android, xiaomi, redmi, miui, hyperos, fm-radio, adb, wireless-debugging, apk-backup, mediatek, mt6635]
created: 2026-10-23
last_verified: 2026-10-23
status: current
---

# Back up Xiaomi FM radio apps from a Redmi 10 and install them on a Redmi Note 12 Pro 5G

Source phone: Redmi 10 (`selene`, MIUI 12.5, Android 11) over USB. Target: Redmi Note 12 Pro 5G
(`ruby`, `22101316G`, HyperOS 2.0 `OS2.0.17.0.UMOIDXM`, Android 14) over wireless ADB. The target phone had
**no FM apps at all** (nothing in `pm list packages -u`), so the radio was missing, not just disabled.

## 1. What the FM stack consists of

| Package | Role | Where |
|---|---|---|
| `com.miui.fm` 1.0.486 | "Mi Radio" UI (`com.miui.fmradio.FmRadioActivity`) | `/data/app/MIRadioGlobal/MIRadioGlobal.apk` (user-updatable app) |
| `com.miui.fmservice` 11 | FM backend service + permission screen | `/system/system_ext/app/FM/FM.apk` (system app) |
| `com.android.fmradio` 2.0 | AOSP/MTK FM Radio app | `/system/system_ext/priv-app/FMRadio/FMRadio.apk` (system priv-app) |

`pm path <pkg>` gives each path; `dumpsys package <pkg>` gives version and the SYSTEM flag.

## 2. Backup (source phone, USB, root available)

```bash
D=~/phone-backup/redmi10-fm-radio; mkdir -p $D && cd $D
adb pull /data/app/MIRadioGlobal/MIRadioGlobal.apk com.miui.fm_1.0.486.apk
adb pull /system/system_ext/priv-app/FMRadio/FMRadio.apk com.android.fmradio_2.0.apk
adb pull /system/system_ext/app/FM/FM.apk com.miui.fmservice_11.apk
# app data (presets/settings) via root; exec-out keeps the tar stream binary-clean
for p in com.miui.fm com.android.fmradio com.miui.fmservice; do
  adb exec-out "su -c 'tar -C /data/data -cf - $p 2>/dev/null'" > data_$p.tar
done
sha256sum *.apk *.tar > SHA256SUMS
```

Note: `adb pull` of `/system/...` APKs works without root. `/data/data` needs `su`.

## 3. Connect to the target over wireless debugging

mDNS found nothing (`adb mdns services` empty), so the port was found by scanning the phone's IP:

```bash
nmap -p 30000-49999 --open -T4 192.168.50.3      # -> 38123/tcp open
adb connect 192.168.50.3:38123                    # worked: PC was already paired earlier
adb devices -l                                    # now two devices; always use -s from here on
```

The wireless-debugging port changes every time the toggle is switched, so re-scan if `connect` is refused.

## 4. Check the target has FM hardware before installing

```bash
N=192.168.50.3:38123
adb -s $N shell ls /dev | grep -iE "fm|radio"                 # fm, radio
adb -s $N shell getprop | grep -iE "fm_chipid"                # persist.vendor.connsys.fm_chipid = mt6635
adb -s $N shell pm list packages -u | grep -iE "fm|radio"     # empty: no FM apps present
```

The MT6635 connsys combo chip has the FM tuner. FM also needs **wired headphones plugged in** as the antenna.

## 5. Install, and the missing-service trap

```bash
adb -s $N install ~/phone-backup/redmi10-fm-radio/com.miui.fm_1.0.486.apk     # Success
adb -s $N shell monkey -p com.miui.fm -c android.intent.category.LAUNCHER 1
```

Mi Radio opened but logged, repeatedly:

```
ActivityManager: Unable to start service Intent { act=com.miui.fm.intent.action.START_FM_SERVICE
  pkg=com.miui.fmservice } U=0: not found
```

The UI is only a front end; it needs `com.miui.fmservice`, which is a system app absent on this ROM. Installing the
backed-up system APK as an ordinary app **worked** (Xiaomi platform-signed packages are accepted across their
devices):

```bash
adb -s $N install ~/phone-backup/redmi10-fm-radio/com.miui.fmservice_11.apk   # Success
adb -s $N shell am force-stop com.miui.fm
adb -s $N shell monkey -p com.miui.fm -c android.intent.category.LAUNCHER 1
adb -s $N shell ps -A | grep miui.fm     # com.miui.fmservice:remote and com.miui.fm both running
```

Afterwards a `com.miui.fmservice/.../PermissionActivity` task appeared: the first-run permission screen, which
must be accepted on the phone.

## 6. Result: software works, but the tuner receives nothing

User report: "tuning does not work". The app sat on `87.5` with a "Tuning..." toast and an empty dial. Debug steps, in order:

```bash
adb -s $N shell ls -lZ /dev/fm                     # crw-rw---- media media u:object_r:fm_device:s0 (exists)
adb -s $N shell dumpsys audio | grep -A3 "Connected devices"   # type:0x4 (headset) connected: antenna present
adb -s $N shell input keyevent KEYCODE_WAKEUP      # uiautomator dump failed ("null root node") with screen off
adb -s $N exec-out screencap -p > fm.png           # screenshot: found seek buttons (scale 1.2 vs displayed image)
adb -s $N logcat -c; adb -s $N shell input tap 792 2114      # seek-forward button
adb -s $N logcat -d | grep -E "FMLIB|Fm:s-|AudioALSAFM"
```

What the log showed:
- `Fm:s-FmLocalService: onFmTurnedOn`, `AudioALSAFMController: setFmVolume()`: the service and the audio HAL FM path are up.
- `FMLIB_CORE: seek start freq 8750 band_channel_no=[206] ... band[8750 - 10800]`, then **all 205 steps logged `freq=XXXX-----1`**
  (no other result code appeared even once), ending `FMLIB_JNI: seek, [freq=8750] [ret=0]`: it wrapped to the start with no station.
- `FMR_tune ... [ret=0]`, `isRDSsupport [support=1]`; `FMR_read_rds_data ... [ret=-1013]` every 500 ms (no RDS data).
- No crashes, no FM-related `avc: denied`. (The `mcd_data_file` denial is unrelated.)

Reading: every driver call succeeds (chip MT6635 answers, `/dev/fm` works), but the tuner sees zero channels across the
whole 87.5-108.0 MHz band. That points to **no usable RF at the chip**: the headphone-cable antenna is not routed to the
FM input on this board, or the FM front end is unpopulated. The official Note 12 Pro 5G firmware ships with no FM app
either, which supports that. This is an inference from the log, not confirmed on the board.

Discriminating test (not yet done): plug the same headphones into the Redmi 10 (FM works there with `com.miui.fm`).
If it finds stations, the cable and location are fine and the Note 12 Pro lacks the antenna path.
Other things that cost nothing to try: a different wired headset (4-pole TRRS vs 3-pole), plugging it in fully, moving
near a window. Stations are broadcast on 87.5-108.0 only; the app's band is fixed at that range.

## 7. Installing the third package (`com.android.fmradio`) did not help; all three removed

User suggested installing the remaining system package. Done:

```bash
adb -s $N install ~/phone-backup/redmi10-fm-radio/com.android.fmradio_2.0.apk     # Success
adb -s $N shell pm grant com.android.fmradio android.permission.RECORD_AUDIO
adb -s $N shell pm grant com.android.fmradio android.permission.POST_NOTIFICATIONS
adb -s $N shell am force-stop com.miui.fm; adb -s $N shell am force-stop com.miui.fmservice   # free /dev/fm
adb -s $N shell am start -n com.android.fmradio/.FmMainActivity     # it has NO launcher icon; resolve-activity said "No activity found"
```

`dumpsys package com.android.fmradio` shows `FmMainActivity`, `FmEmActivity` (MTK engineering mode), `FmService`, `FmProvider`.
Tapping its play button auto-scanned in **four passes** (per-step codes `-----1` .. `-----4`, ~74/126/126/79 steps) and ended with
`FMLIB_CORE: scan stop!!! tune ret=0`. The screen then showed 100.1 MHz, which I wrongly took as a found station; the
"Radio Stations" list said **"No stations found"**. The one thing that went wrong in my process: my `KEYCODE_BACK` came while that scan
was still running, so I cannot be sure the last pass ran to the end. A clean rerun was started but the user stopped the session and asked for removal.
`content query --uri content://com.android.fmradio/station` fails (`provider not exported`).

Conclusion unchanged: the FM chip and driver work, but no station was found by either app. Most likely cause is still the antenna path,
unconfirmed. The Redmi 10 headphone cross-test from section 6 was never run.

Removed at the user's request ("its not working"):

```bash
for p in com.miui.fm com.miui.fmservice com.android.fmradio; do adb -s $N uninstall $p; done   # all Success
adb -s $N shell pm list packages -u | grep -iE "fmradio|miui\.fm|fmservice"                    # empty
```

The APK + data backups of all three remain in `~/phone-backup/redmi10-fm-radio/`.

## 8. Not verified

Actual tuning/audio was **not** tested over ADB: it needs wired headphones and the permission prompt accepted on
the phone. `com.android.fmradio` was backed up but not installed (the Mi Radio + fmservice pair covers it).
Both packages are now ordinary user-installed apps on the target, so they would not survive a factory reset, and the
`avc: denied` for `mcd_data_file` / `DynamicFPS ... Permission denied` lines in logcat are cosmetic.

Revert: `adb -s $N uninstall com.miui.fm; adb -s $N uninstall com.miui.fmservice`.
