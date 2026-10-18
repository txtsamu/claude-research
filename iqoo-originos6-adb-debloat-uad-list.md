---
type: how-to
tags: [android, iqoo, vivo, originos, adb, debloat, uad-ng, wireless-debugging]
created: 2026-10-19
last_verified: 2026-10-19
status: current
---

# iQOO (OriginOS 6) debloat over wireless ADB, using the UAD-ng list

Debloated an iQOO phone without root: wireless ADB from the fedora desktop, cross-referenced installed packages against the Universal Android Debloater (next-gen) list, then `pm uninstall --user 0` with a `disable-user` fallback.

**Device:** iQOO model `I2512`, OriginOS 6, Android 16, region `ID` (Indonesia). Phone at `192.168.50.26` on the LAN.

## Result

- 41 packages targeted, **32 uninstalled for user 0**, **1 disabled** (`com.vivo.magazine`), **8 refused** by vivo (`DELETE_FAILED_USER_RESTRICTED`, and `disable-user` also throws a SecurityException).
- Refused (still installed and enabled): `com.bbk.iqoo.logsystem`, `com.vivo.appstore`, `com.vivo.hiboard`, `com.vivo.globalsearch`, `com.vivo.cota`, `com.iqoo.website`, `com.bbk.cloud`, `com.vivo.assistant`. OriginOS protects these at the framework level, so plain ADB can't remove or disable them. This matches forum reports that "generic ADB commands don't work with most vivo apps".

## Steps

### 1. Connect over wireless debugging (pairing needed first)

`adb connect` to the wireless debugging port failed with `failed to connect` even though the TCP port was open (`bash -c '</dev/tcp/192.168.50.26/43831'` succeeded). On Android 11+ a host must be **paired** first: Developer options → Wireless debugging → *Pair device with pairing code* shows a code and a **different** port.

```bash
adb pair 192.168.50.26:<pairing-port> <6-digit-code>
adb connect 192.168.50.26:43831      # the main wireless debugging port
adb devices -l                       # -> device product:I2512 model:I2512
```

The connect port changes whenever wireless debugging is toggled, so re-read it from the phone each session. Pairing is remembered.

### 2. Device info and package inventory

```bash
D=192.168.50.26:43831
adb -s $D shell getprop ro.build.version.release        # 16
adb -s $D shell getprop ro.vivo.os.build.display.id     # OriginOS 6
adb -s $D shell getprop ro.product.country.region       # ID
adb -s $D shell pm list packages -s | sed 's/package://' | sort > system.txt   # 392
adb -s $D shell pm list packages -3 | sed 's/package://' | sort > user.txt     # 202
adb -s $D shell pm list packages -d | sed 's/package://' | sort > disabled.txt
adb -s $D shell pm list packages -3 -i     # installer per user app
```

`-3 -i` showed every "user" app came from `com.android.vending` (Play Store), so the user had installed them. The exceptions were Facebook and TikTok (`com.google.android.packageinstaller`), which may be preloads. That's why UAD's "Recommended" hits on user apps (WhatsApp, Instagram, Office…) were **not** treated as targets.

### 3. Cross-reference against UAD-ng

```bash
curl -sL -o uad_lists.json \
  https://raw.githubusercontent.com/Universal-Debloater-Alliance/universal-android-debloater-next-generation/main/resources/assets/uad_lists.json
```

The JSON is a dict keyed by package name, with `list` (Aosp/Google/Oem/Misc/Carrier), `removal` (Recommended/Advanced/Expert/Unsafe) and `description` fields. A small `python3 -I` script grouped every installed package by `(removal, list)` and printed the vivo/bbk/iqoo system packages UAD doesn't know about. OriginOS 6 adds about 40 of these, such as `com.vivo.ai.agent`, `com.vivo.cardstore` and `com.vivo.connbase*`. UAD had 161 vivo/iQOO entries in total.

### 4. Pick targets (judgment on top of UAD)

The user chose four groups:

- **Ads, telemetry and vivo services:** `com.bbk.iqoo.logsystem com.vivo.nps com.android.bbklog com.vivo.magazine com.vivo.hybrid com.vivo.appstore com.vivo.browser com.vivo.hiboard com.vivo.globalsearch com.vivo.cota com.iqoo.website com.bbk.cloud com.vivo.unionpay com.vivo.assistant com.vivo.smartanswer android.autoinstalls.config.vivo.devices com.baidu.map.location com.tencent.soter.soterserver`
- **Factory test apps:** `com.goodix com.goodix.deltadiff com.vivo.fingerprintvit com.touchscreen.vtstouchscreencheck com.vivotouchscreen.synadeltadiff com.vos.user.vit com.vos.as.vit`
- **Google ads and telemetry:** `com.google.android.adservices.api com.google.android.federatedcompute com.google.android.ondevicepersonalization.services com.google.android.feedback com.google.android.gms.location.history com.google.android.apps.tachyon com.google.ambient.streaming com.google.ar.core com.google.android.onetimeinitializer com.android.egg com.android.traceur`
- **Qualcomm telemetry:** `com.qualcomm.qti.qms.service.connectionsecurity com.qualcomm.qti.qms.service.trustzoneaccess com.qualcomm.qti.devicestatisticsservice com.qualcomm.qti.server.qtiwifi com.qualcomm.qti.ridemodeaudio`

**Deliberately kept, even though UAD rates some of them "Recommended" (they break things on vivo):** `com.vivo.upslide` (gesture navigation), `com.vivo.safecenter` (vivo's permission manager), `com.vivo.sps` and `com.vivo.daemonService` (process management), `com.bbk.theme`, `com.vivo.setupwizard`, `com.bbk.account`, `com.bbk.updater`, `com.vivo.pushservice`, `com.vivo.vibrator4d`, `com.vivo.abe`/`com.vivo.audiofx`, and everything for fingerprint, face unlock, lockscreen or connectivity.

**Smart Remote (IR blaster app) is `com.vivo.vhome`.** UAD labels it "Smart Remote" and rates it Recommended. Keep it if you use the TV remote.

### 5. Remove

Gotcha: in a `while read` loop, `adb shell` eats stdin, so the loop stops after the first package. Redirect with `</dev/null`.

```bash
while read -r p; do
  r=$(adb -s $D shell pm uninstall -k --user 0 "$p" </dev/null 2>&1 | tr -d '\r')
  if [ "$r" != "Success" ]; then
    r2=$(adb -s $D shell pm disable-user --user 0 "$p" </dev/null 2>&1 | tr -d '\r' | tail -1)
    r="$r | disable: $r2"
  fi
  echo "$p => $r"
done < remove.txt | tee removal_log.txt
```

The user ran this themselves with `! bash debloat.sh`, because Claude Code's auto-mode classifier blocks `pm uninstall` loops as irreversible deletion.

## Restore

`pm uninstall --user 0` keeps the APK on `/system`, so nothing here needs a factory reset:

```bash
adb shell cmd package install-existing <pkg>   # uninstalled ones
adb shell pm enable <pkg>                      # com.vivo.magazine (disabled)
```

OTA updates can bring removed packages back. Re-run the loop after major updates.

## Background restriction on the 8 protected packages (done 2026-10-19)

```bash
for p in com.bbk.iqoo.logsystem com.vivo.appstore com.vivo.hiboard com.vivo.globalsearch \
         com.vivo.cota com.iqoo.website com.bbk.cloud com.vivo.assistant; do
  adb -s $D shell cmd appops set $p RUN_ANY_IN_BACKGROUND ignore </dev/null
  adb -s $D shell cmd appops set $p RUN_IN_BACKGROUND ignore </dev/null
  adb -s $D shell am set-standby-bucket $p restricted </dev/null
  adb -s $D shell am force-stop $p </dev/null
done
# verify
adb -s $D shell cmd appops get <pkg> | grep IN_BACKGROUND
adb -s $D shell am get-standby-bucket <pkg>   # 5=exempted 10=active 45=restricted
adb -s $D shell pidof <pkg>
```

Outcome:
- **Appops `ignore` stuck on all 8.** OriginOS didn't reject them.
- **Standby bucket `restricted` (45) only stuck on `com.iqoo.website`.** The rest silently stayed at 5 (exempted: appstore, cota, bbk.cloud) or 10 (active: logsystem, hiboard, globalsearch, assistant). vivo exempts its own system apps from App Standby.
- **Processes that came back right after force-stop:** `com.bbk.iqoo.logsystem`, `com.vivo.globalsearch` and `com.vivo.assistant`. They're persistent or bound by the system/launcher, so appops can't keep them stopped. The other 5 stayed stopped.
- Undo: `cmd appops set <pkg> RUN_ANY_IN_BACKGROUND allow` (and `RUN_IN_BACKGROUND allow`), plus `am set-standby-bucket <pkg> active`.

The next step for the 3 that keep running would be blocking their telemetry domains at DNS (Technitium), the same approach as `technitium-samsung-tv-ad-telemetry-block-advanced-blocking.md`.

## References

- [UAD-ng (Universal Android Debloater next-gen) repo, source of `uad_lists.json`](https://github.com/Universal-Debloater-Alliance/universal-android-debloater-next-generation)
- [Universal Android Debloater (original)](https://github.com/0x192/universal-android-debloater)
- [TechEnclave: FuntouchOS 14 debloat](https://techenclave.com/t/funtouchos-14-debloat/272600)
- [TechEnclave: FuntouchOS 14 debloat (older thread)](https://techenclave.com/threads/funtouchos-14-debloat.224435/)
- [DroidWin: vivo bloatware removal](https://droidwin.com/?p=39836)
- [Technastic: safe-to-remove packages without root](https://technastic.com/?p=15193)
