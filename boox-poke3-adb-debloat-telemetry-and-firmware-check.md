---
type: how-to
tags: [boox, onyx, poke3, android10, e-ink, adb, debloat, telemetry, firmware, koreader, play-books]
created: 2026-10-28
last_verified: 2026-10-28
status: current
---

# Onyx Boox Poke3: adb debloat, telemetry check and firmware check

Debloated an Onyx Boox Poke3 (Android 10, firmware 3.5) over adb with reversible `pm disable-user`, checked what telemetry is likely active, and checked for a firmware update. Google Play Books and the Play Store were deliberately kept, so the whole Play services stack stays enabled.

## Summary

- Device: `Poke3`, Android 10, firmware **3.5** (build `2023-12-12_23-45_3.5_4687b1901`, incremental `12699`), security patch 2023-02-01. No telephony (`ro.radio.noril=yes`, no `android.hardware.telephony` feature), Wi-Fi only.
- Device was already clean: 8 user-installed apps, 132 system packages. One package was already disabled (`com.onyx.android.production.test`).
- Disabled 37 packages with `pm disable-user --user 0` (all reversible), uninstalled Librera. Launcher `com.onyx/.StartupActivity` still resolves after the changes.
- Telemetry: probably active on the Google side (Play services logging services running); Boox side unverified. Could not read the Google "Usage & diagnostics" toggle over adb.
- Firmware 3.5 is the newest Poke3 firmware found online (May 2024 MobileRead post). Nothing newer found; the device's own Firmware Update screen is the only authoritative check.

## Steps

### 1. Confirm adb and snapshot packages (before changing anything)

USB debugging enabled on the device, then:

```bash
adb devices -l
adb shell getprop ro.product.model          # Poke3
adb shell getprop ro.build.version.release  # 10
mkdir -p ~/sessions/2026-10-28-boox-poke3-debloat && cd ~/sessions/2026-10-28-boox-poke3-debloat
adb shell pm list packages -f -3 > third-party.txt   # user-installed
adb shell pm list packages -f -s > system.txt        # system
adb shell pm list packages -d    > disabled.txt      # already disabled
adb shell pm list users          > users.txt         # single user 0
```

Third-party apps present: KOReader, Moon+ Reader Pro, Librera (`com.foobnix.pro.pdf.reader`), F-Droid, a file manager, Syncthing, Google Play Books, an Al-Quran app.

### 2. Tiered candidate list

Tier 1 (safe, no downside): `com.onyx.igetshop`, `com.onyx.mail`, `com.onyx.easytransfer`, `com.android.email`, `com.android.quicksearchbox`, `com.android.protips`, `com.android.dreams.basic`, `com.android.dreams.phototable`, `com.android.htmlviewer`, `com.android.bookmarkprovider`, `com.android.wallpaper.livepicker`, `com.android.wallpaperbackup`, `com.android.dynsystem`, `com.android.providers.calendar`, `com.google.android.syncadapters.calendar`, `com.google.android.syncadapters.contacts`, `com.android.cellbroadcastreceiver`, `com.android.smspush`.

Tier 2 (safe if the feature is unused): `com.onyx.appmarket`, `com.onyx.android.ksync` (Boox Cloud), `com.onyx.dict`, `com.onyx.calculator`, the four `com.simplemobiletools.*` apps, `org.chromium.chrome`, `com.android.bips`, `com.android.printspooler`, `com.android.printservice.recommendation`, `com.qualcomm.wfd.service` (Miracast), `com.dsi.ant.server`, `com.android.companiondevicemanager`, `com.android.hotspot2`.

Tier 3 (Google/cellular): `org.codeaurora.ims`, `vendor.qti.iwlan`, `com.google.android.gms.setup`, `com.google.android.partnersetup`.

Never touched: `com.onyx` (launcher + core, per-app e-ink tuning, navball), `com.onyx.kreader`, `com.onyx.kime`, `com.onyx.latinime`, `com.onyx.floatingbutton`, `com.onyx.android.onyxotaservice` (OTA), `systemui`, `settings`, `documentsui`, `packageinstaller`, `permissioncontroller`, `providers.*` (except calendar), `google.android.webview`, `com.qualcomm.*`, `com.qti.service.colorservice` (e-ink refresh), `navbar` overlays.

Kept because Play Books depends on them: `com.android.vending`, `com.google.android.gms`, `com.google.android.gsf`, plus `com.google.android.apps.books` and `com.google.android.tts` (TTS kept in case of read-aloud).

### 3. Apply with a rollback script

Use `pm disable-user --user 0`, not `pm uninstall --user 0`: disabling is undone with `pm enable`, uninstalling a Boox system app is not easily undone.

```bash
adb shell pm uninstall com.foobnix.pro.pdf.reader      # Librera, user app, fully removed

echo '#!/bin/bash' > rollback.sh
for p in $(cat tier1.txt); do
  adb shell pm disable-user --user 0 "$p" </dev/null
  echo "adb shell pm enable $p" >> rollback.sh
done
# repeat with tier2-3.txt; tier1.txt had com.onyx.easytransfer removed at the user's request
```

**Gotcha:** the first attempt used `while read p; do adb shell ... ; done < tier1.txt` and only the first package was processed, because `adb shell` reads stdin and swallowed the rest of the file. Use `for p in $(cat file)` plus `</dev/null` on every `adb shell`, or `adb shell -n`.

Verification:

```bash
adb shell pm list packages -d | wc -l                 # 38 (37 new + the already-disabled production.test)
adb shell cmd package resolve-activity --brief \
  -c android.intent.category.HOME -a android.intent.action.MAIN   # com.onyx/.StartupActivity
adb shell pm list packages -e | grep -E 'vending|gms$|gsf|apps.books|webview|tts'
```

Rollback: `bash rollback.sh` re-enables everything disabled. Librera is the only irreversible change (reinstall from F-Droid/Play).

### 4. Telemetry check (what adb can and cannot see)

```bash
for ns in global secure system; do adb shell settings list $ns | grep -iE 'usage|analytic|diagnos|report|crash|upload|stats|ad_id|limit_ad|location_mode'; done
adb shell dumpsys activity services | grep ServiceRecord | grep -iE 'onyx|gms'
adb shell dumpsys account | grep 'Account {'
```

Findings:

- Google account signed in; Play services running with logging services alive: `clearcut` (analytics log store, with `DEFlatFileLogStore` on disk), `GmsCoreStatsService`, `tron.CollectionService`.
- `upload_apk_enable=1` (Play Protect uploads unknown APKs). Ad ID not restricted. `activity_starts_logging_enabled=1` and `netstats_enabled=1` are local only. `location_mode=0`, `network_recommendations_enabled=0`, `wifi_scan_always_enabled=0`, crash dropbox disabled.
- Boox: `com.onyx.android.ksync` (Boox Cloud) was running as a service. `com.onyx`, `ksync`, `kreader` hold `BATTERY_STATS` and `PACKAGE_USAGE_STATS`. No analytics SDK names found in package info, but `dumpsys` does not list embedded SDKs, so **that is not conclusive**. `/proc/net/tcp` snapshot showed no established connections at that moment (also inconclusive); `run-as` is blocked (apps not debuggable).
- Not readable over adb: Google Settings → Usage & diagnostics toggle (do it by hand).
- Not done (suggested): Private DNS filtering (`adb shell settings put global private_dns_mode hostname` + `private_dns_specifier <host>`), or a day of DNS query logging on a filtering resolver to see which domains Boox apps contact.

### 5. Firmware check

```bash
for p in ro.build.display.id ro.build.version.security_patch ro.build.date ro.build.fingerprint ro.build.version.incremental; do echo "$p=$(adb shell getprop $p)"; done
# find the firmware-update activity and open it on the device
adb shell dumpsys package com.onyx | grep -iE 'firmware'
adb shell am start -n com.onyx/.common.setting.ui.SettingFirmwareUpdateContainerActivity
```

The activity is `com.onyx/.common.setting.ui.SettingFirmwareUpdateContainerActivity`; it opened successfully and was in the foreground. The "Check for updates" tap was left to the user. `com.onyx.android.onyxotaservice` was deliberately left enabled; whether the update check still works with `ksync` and `appmarket` disabled was **not verified**. If the check fails, re-enable them: `adb shell pm enable com.onyx.android.ksync com.onyx.appmarket`.

Online: Onyx said in 2022 the Poke3 stays on Android 10 but keeps getting firmware. Manual updates are delivered as `update.upx` copied to `/sdcard/update.upx` with the device offline, then the Firmware settings screen (per the MobileRead thread); the official site pages are stale.

### 6. Optimization notes gathered

Sourced:
- Long-press an app in the Boox launcher for per-app e-ink settings (refresh mode, refresh frequency, contrast, colour).
- Frequent full refresh removes ghosting at the cost of a flash and slightly more battery; A2 mode is fast but ghosts after extended scrolling.
- One Poke3 owner fixed an app by changing its dpi and disabling contrast support.
- Boox "freezing" of apps hides them from third-party launchers until turned off in the Boox launcher.

From general knowledge, not sourced by this session: A2/Fast for menus, Normal/HD for reading; set Android window/transition/animator scales to 0 (2 GB RAM device); keep light/Bluetooth/Wi-Fi off when unused.

Launcher: no e-ink-tested alternative found. Recommendation was to keep `com.onyx` (it owns the per-app e-ink tuning, refresh controls and navball). If trying a minimal launcher, Olauncher from F-Droid, and switch back with `adb shell cmd package set-home-activity com.onyx/.StartupActivity` (untested here).

Play Books on e-ink: weak (animations, little refresh control). KOReader / Moon+ are better for local epubs and Syncthing syncs files without Google. Kept installed because the user still uses it.

## Open items

- Result of the on-device "Check for updates" was not reported.
- Boox network telemetry not measured; Private DNS filtering and Usage & diagnostics toggle not applied.
- Session files (package dumps, tier lists, `rollback.sh`): `~/sessions/2026-10-28-boox-poke3-debloat/`.

## References

- [Boox Leaf review (per-app e-ink options)](https://myereader.substack.com/p/onyx-boox-leaf-review-the-tinkerers)
- [Seeing faint background text is normal (ghosting / full refresh)](https://blog.the-ebook-reader.com/2019/10/28/seeing-faint-background-text-on-ebook-readers-is-normal/)
- [MobileRead: A2 mode and ghosting thread](https://www.mobileread.com/forums/showthread.php?p=3887933)
- [Galaxus Poke 3 Q&A (dpi / contrast fix)](https://www.galaxus.fr/en/s1/questionandanswer/does-it-work-with-skoobe-352772)
- [Boox Go 10.3 review (app freezing vs third-party launchers)](https://manualdousuario.net/en/boox-go-10-3-lumi-first-impressions/)
- [Niagara Launcher alternatives (AlternativeTo)](https://alternativeto.net/software/niagara-launcher/?p=3)
- [MobileRead: Poke 3 Root and Firmware Updating (3.5 build string, update.upx)](https://www.mobileread.com/forums/showthread.php?t=361228)
- [MobileRead: BOOX Latest Firmware V3.5](https://www.mobileread.com/forums/showthread.php?p=4369555)
- [Onyx on X: Poke3 stays on Android 10 but gets firmware updates](https://twitter.com/OnyxBoox/status/1542260863285055489)
- [Boox system update page](https://www.boox.com.hk/pages/system-update)
- [Onyx Poke3 support page](https://onyxboox.com/support/boox_poke3)
- [ewritable: Boox firmware 3.5 (3.5.4 for other models)](https://ewritable.net/brands/boox/firmware/3-5/)
