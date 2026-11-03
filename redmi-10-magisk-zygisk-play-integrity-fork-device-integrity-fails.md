---
type: investigation
tags: [android, xiaomi, redmi-10, selene, magisk, zygisk, play-integrity, playintegrityfork, adb, miui]
created: 2026-11-03
last_verified: 2026-11-03
status: blocked
---

# Redmi 10 (selene): Zygisk + Play Integrity Fork set up, BASIC passes, DEVICE/STRONG still fail

Phone: Xiaomi Redmi 10 `21121119SG` (selene), MIUI 12.5.7 / Android 11, kernel 4.14.186, Magisk 30.7, bootloader unlocked (`ro.boot.verifiedbootstate=orange`), real Google Play Services 26.42.31 + Play Store (not microG; a ReVanced GmsCore `app.revanced.android.gms` is also installed).

**Result:** Zygisk is on and Play Integrity Fork (PIF) v18 is loaded and spoofing (confirmed in logcat). The Play Integrity API Checker shows **MEETS_BASIC_INTEGRITY = pass, MEETS_DEVICE_INTEGRITY = fail, MEETS_STRONG_INTEGRITY = fail**, both without any fingerprint and with the `autopif4.sh` Pixel Canary fingerprint (also with `DEVICE_INITIAL_SDK_INT=25`). The blocker is a working *private* fingerprint from an old certified device (not found yet). STRONG needs a hardware keybox via Tricky Store and was deliberately not attempted.

## Time estimate

Total hands-on work about 25 min (est.) over two days, plus waiting for the user to unlock the phone (not counted). Per-step figures are measured from timestamps/outputs unless marked "est.".

| Step | Time |
|---|---|
| Install PIF module + enable Zygisk | under 1 min (est.) |
| Reboot to activate (`adb reboot` until `sys.boot_completed=1`) | about 1 min (measured: boot completed 13:56:34 after reboot at about 13:55) |
| Download + install checker APK | under 2 min (est.) |
| One checker run (tap Check, wait) | about 10 s (fixed `sleep 10`) |
| `autopif4.sh` | about 10-20 s (est.; needs phone internet) |

## Steps (in order)

All `adb shell 'su -c "..."'` commands run as root through Magisk. Work dir used: `~/sessions/2026-11-02-android-zygisk-pif/`.

### 1. Check the starting state

```bash
adb devices -l
adb shell 'getprop ro.product.model; getprop ro.build.version.release; getprop ro.boot.verifiedbootstate'
adb shell 'su -c "id; magisk -v; magisk --sqlite \"select * from settings\"; ls /data/adb/modules"'
adb shell 'pm list packages -s | grep -E "com.google.android.gms|com.android.vending"'   # real GMS present?
```

Zygisk was off (`settings` only had `bootloop`). Real GMS and Play Store present, so the Play Integrity API can work at all.

### 2. Install PIF v18 and enable Zygisk

```bash
gh api repos/osm0sis/PlayIntegrityFork/releases/latest --jq '.tag_name,(.assets[]|.browser_download_url)'
curl -sL -o PlayIntegrityFork-v18.zip https://github.com/osm0sis/PlayIntegrityFork/releases/download/v18/PlayIntegrityFork-v18.zip
sha256sum PlayIntegrityFork-v18.zip      # 625ebe65631f761e1521009f10a205d74255adf2e35732923d65106643cad9a6
unzip -q PlayIntegrityFork-v18.zip -d extracted   # read customize.sh / autopif4.sh before installing (it runs as root)
adb push PlayIntegrityFork-v18.zip /data/local/tmp/
adb shell 'su -c "magisk --install-module /data/local/tmp/PlayIntegrityFork-v18.zip"'
adb shell 'su -c "magisk --sqlite \"REPLACE INTO settings (key,value) VALUES(\\\"zygisk\\\",1)\""'
adb shell 'su -c "rm /data/local/tmp/PlayIntegrityFork-v18.zip"'
```

The module has no fingerprint (`pif.json` is intentionally not shipped), so it does nothing yet. The module stays in `update` state until reboot.

### 3. Reboot and verify Zygisk is loaded

```bash
adb reboot
adb wait-for-device; adb shell getprop sys.boot_completed     # 1
adb shell 'su -c "grep -m1 libzygisk /proc/\$(pidof zygote64)/maps"'   # libzygisk.so present = Zygisk injected
```

Gotcha: after a reboot the phone is at the lock screen with file-based encryption. Until the user unlocks it, app data is unavailable (`mkdir failed: errno 126 (Required key not available)` in logcat), so the checker app and UI automation cannot run.

### 4. Install the Play Integrity API Checker (`gr.nikolasspyr.integritycheck`)

The GitHub repo (1nikolas/play-integrity-checker-app) has no releases and the package is not on F-Droid/IzzyOnDroid, so the APK came from APKMirror (v2.2, Aug 2025, an `.apkm` split bundle):

```bash
UA="Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"; B=https://www.apkmirror.com
# release page -> app page -> "download/?key=..." page -> download.php?id=...&key=... (each link is scraped from the previous HTML with grep)
curl -sL -A "$UA" -e "$B" -o checker-2.2.apk "$B/wp-content/themes/APKMirror/download.php?id=<id>&key=<key>"
sha256sum checker-2.2.apk    # cee08a903ee2a7cafd7afc3435c209f995503a81bcac8de564b6efb53894a1eb
unzip -q checker-2.2.apk -d x
keytool -printcert -jarfile x/base.apk   # signer CN=Android, O=Google Inc. (Play App Signing key), SHA256 17:95:2B:5C:...:CF:79:E3
```

Install base + English/Indonesian + density split (the phone is 440 dpi, so `xxhdpi`):

```bash
adb install-multiple x/base.apk x/split_config.en.apk x/split_config.in.apk x/split_config.xxhdpi.apk
# -> INSTALL_FAILED_USER_RESTRICTED (MIUI "Install via USB" guard; phone asleep so no prompt could be accepted)
```

Worked around with a root `pm` session (note: `pm install-multiple` does not exist inside `su` on this Android 11, and `install-write` needs absolute paths):

```bash
adb shell 'mkdir -p /data/local/tmp/chk' && adb push x/base.apk x/split_config.*.apk /data/local/tmp/chk/   # only the 4 needed splits
adb shell 'su -c "S=\$(pm install-create -i com.android.vending | grep -oE \"[0-9]+\"); for f in base.apk split_config.en.apk split_config.in.apk split_config.xxhdpi.apk; do pm install-write \$S \$f /data/local/tmp/chk/\$f; done; pm install-commit \$S; rm -rf /data/local/tmp/chk"'
```

### 5. Run the checker from the shell

`uiautomator dump` returns "null root node" for this app, and plain `adb shell input tap` is rejected on MIUI (`INJECT_EVENTS`), so use `su` for the tap and read the result from a screenshot:

```bash
adb shell 'su -c "monkey -p gr.nikolasspyr.integritycheck -c android.intent.category.LAUNCHER 1; sleep 3; input tap 540 1546; sleep 10"'
adb exec-out screencap -p > check.png        # CHECK button is at (540,1546) on this 1080x2400 screen
```

Baseline (no fingerprint): BASIC pass, DEVICE fail, STRONG fail.

### 6. Try fingerprints

```bash
adb shell 'su -c "cd /data/adb/modules/playintegrityfix && sh autopif4.sh --strong"'   # writes custom.pif.prop (Pixel 11 Pro Fold Canary, api 32)
adb shell 'su -c "sh /data/adb/modules/playintegrityfix/killpi.sh"'                      # restart GMS/Play Store processes after any change
```

- `--strong` Canary fingerprint (first API level 32): same result, BASIC pass / DEVICE fail.
- Without `--strong` (Pixel 10 Pro XL Canary): still sets `DEVICE_INITIAL_SDK_INT=32`; same result.
- Forced `DEVICE_INITIAL_SDK_INT=25` and `*api_level=25` by hand with `sed -i` on `custom.pif.prop`: same result.

Confirming the module works (not a setup bug): set `verboseLogs=100` in `custom.pif.prop`, run `killpi.sh`, run the check, then `adb shell 'su -c "logcat -d | grep PIF"'` shows `PIF/Native: [ro.product.first_api_level]: 30 -> 32` and `[ro.build.id]: RP1A.200720.011 -> ZP11.260918.007`. (`ro.build.fingerprint` is logged "unchanged" at the native prop layer; the fingerprint itself is spoofed in the Java `Build` fields.) Set `verboseLogs` back to 0 afterwards.

## Why DEVICE still fails

The PIF README says Pixel Beta/Canary fingerprints "can no longer pass DEVICE integrity", recent-device values only pass with full hardware-backed attestation, and a *private* fingerprint from an older, unbanned certified device is needed (public ones are banned quickly). The phone's own fingerprint cannot be used because the bootloader is unlocked. No such fingerprint was available in the session.

## Next steps (not done)

1. Get a private fingerprint of an old certified device and put it in `/data/adb/modules/playintegrityfix/custom.pif.prop` (template `example.pif.prop`; the repo's XDA how-to describes building one from a `build.prop` dump), then `killpi.sh` and re-run the checker. After a pass, Play Store may cache "not certified" for up to 24 h (clear its storage + reboot).
2. STRONG: needs Tricky Store (or a fork) with an unrevoked hardware keybox; not attempted.
3. Optional hardening if an app still detects root: enable "Enforce DenyList" (keep `com.google.android.gms` off the list) or install Shamiko. Zygisk DenyList is currently off.

## Current phone state

Magisk `zygisk=1`; modules: LowRAM-Flag Plus, Magisk SwapSpace, NLSound (disabled), Play Integrity Fork v18 (with a Pixel Canary `custom.pif.prop` that expires about 2026-11-18). Checker app installed. The phone's Download folder already held `boot_a.img` and `magisk_patched-30700_*.img` (not created in this session, origin unverified; useful as a possible boot-image backup if a module ever bootloops).

## References

- [osm0sis/PlayIntegrityFork (README: install, verdicts, private fingerprints)](https://github.com/osm0sis/PlayIntegrityFork)
- [PlayIntegrityFork releases (v18, 29 Aug 2026 changelog)](https://github.com/osm0sis/PlayIntegrityFork/releases)
- [1nikolas/play-integrity-checker-app (source of the checker)](https://github.com/1nikolas/play-integrity-checker-app)
- [Play Integrity API Checker 2.2 on APKMirror](https://www.apkmirror.com/apk/nikolas-spiridakis/play-integrity-api-checker/play-integrity-api-checker-2-2-release/)
- [Improved verdicts in Android 13 and later (Google)](https://developer.android.com/google/play/integrity/improvements)
