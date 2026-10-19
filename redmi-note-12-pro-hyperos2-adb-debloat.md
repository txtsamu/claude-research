---
type: how-to
tags: [android, xiaomi, redmi, hyperos, adb, debloat, uad-ng, wireless-debugging, mediatek]
created: 2026-10-19
last_verified: 2026-10-19
status: current
---

# Redmi Note 12 Pro 5G (HyperOS 2) debloat over wireless ADB

Second-pass debloat of the Redmi: inventory, cross-reference against the UAD-ng list, remove only
user-approved packages. The same method as `iqoo-originos6-adb-debloat-uad-list.md`.

## Device

| | |
|---|---|
| Market name / model | `ro.product.marketname=Redmi Note 12 Pro 5G`, `22101316G`, codename `ruby` (the user calls it the "Pro+ 5G". The Pro+ is `22101316UG`, same codename) |
| SoC | MediaTek `MT6877V/TTZA` (Dimensity 1080) |
| OS | HyperOS 2.0, `OS2.0.17.0.UMOIDXM`, Android 14 (SDK 34), region `ID` |
| ADB | wireless debugging, `192.168.50.3:<port>` (already paired with this PC) |

## 1. Inventory

```bash
D=192.168.50.3:<port>
adb connect $D
for p in ro.product.marketname ro.product.model ro.mi.os.version.incremental ro.build.version.release ro.miui.region ro.soc.model; do
  echo "$p=$(adb -s $D shell getprop $p)"; done
adb -s $D shell pm list packages -s     | sed 's/package://' | sort > system.txt       # 206
adb -s $D shell pm list packages -3 -i  | sed 's/package://' | sort > user_inst.txt    # 224 (+ installer)
adb -s $D shell pm list packages -d     | sed 's/package://' | sort > disabled.txt
adb -s $D shell pm list packages        | sed 's/package://' | sort > installed.txt    # 430
adb -s $D shell pm list packages -u     | sed 's/package://' | sort > all_incl_uninstalled.txt  # 565
comm -23 all_incl_uninstalled.txt installed.txt    # packages already uninstalled for user 0
```

`pm list packages -u` minus the installed list is a quick way to see **what a previous debloat already
removed**. On this phone that was **135 packages**, from an earlier session. Main ones: MSA ads
(`com.miui.msa.global`), `com.miui.analytics`, GetApps (`com.xiaomi.mipicks`), `com.mi.globalbrowser`,
`com.mi.globalminusscreen`, `com.xiaomi.joyose`, Facebook stubs, Mi Cloud/Backup, Mi Video/Music,
Mi Calendar, Google ad/telemetry modules, and MediaTek engineering/log apps.

Full list of the 135 previously removed packages:

```
android.autoinstalls.config.Xiaomi.model com.android.bluetoothmidiservice com.android.calllogbackup 
com.android.cameraextensions com.android.egg com.android.hotwordenrollment.okgoogle 
com.android.hotwordenrollment.xgoogle com.android.inputsettings.overlay.miui 
com.android.managedprovisioning.overlay com.android.microdroid.empty_payload com.android.mms 
com.android.overlay.gmscontactprovider com.android.overlay.gmssettingprovider 
com.android.overlay.gmssettings com.android.overlay.gmstelecomm com.android.overlay.gmstelephony 
com.android.providers.partnerbookmarks com.android.rkpdapp com.android.role.notes.enabled 
com.android.settings.overlay.miui com.android.stk.overlay.miui 
com.android.systemui.accessibility.accessibilitymenu com.android.systemui.overlay.miui 
com.android.theme.font.notoserifsource com.android.traceur com.android.virtualmachine.res 
com.bsp.catchlog com.debug.loggerui com.facebook.appmanager com.facebook.services 
com.facebook.system com.fingerprints.sensortesttool com.goodix.gftest com.google.ambient.streaming 
com.google.android.accessibility.switchaccess com.google.android.adservices.api 
com.google.android.apps.restore com.google.android.apps.safetyhub 
com.google.android.apps.subscriptions.red com.google.android.apps.turbo com.google.android.as 
com.google.android.as.oss com.google.android.cellbroadcastreceiver.overlay.miui 
com.google.android.cellbroadcastservice.overlay.miui com.google.android.federatedcompute 
com.google.android.feedback com.google.android.gms.location.history 
com.google.android.marvin.talkback com.google.android.ondevicepersonalization.services 
com.google.android.onetimeinitializer com.google.android.overlay.gmsconfig.asi 
com.google.android.overlay.gmsconfig.common com.google.android.overlay.gmsconfig.geotz 
com.google.android.overlay.gmsconfig.personalsafety com.google.android.overlay.healthconnect 
com.google.android.overlay.modules.captiveportallogin.forframework 
com.google.android.overlay.modules.documentsui 
com.google.android.overlay.modules.modulemetadata.forframework 
com.google.android.overlay.modules.permissioncontroller 
com.google.android.overlay.modules.permissioncontroller.forframework 
com.google.android.partnersetup com.google.android.printservice.recommendation 
com.google.android.projection.gearhead com.google.android.safetycenter.resources 
com.google.mainline.adservices com.mediatek.callrecorder com.mediatek.engineermode 
com.mediatek.gbaservice com.mediatek.lbs.em2.ui com.mediatek.mdmconfig com.mediatek.mdmlsample 
com.mediatek.miravision.ui com.mediatek.MtkSettingsResOverlay 
com.mediatek.SettingsProviderResOverlay com.mediatek.systemuiresoverlay com.mediatek.voicecommand 
com.mediatek.voiceunlock com.mediatek.ygps com.mi.globalbrowser com.mi.globalminusscreen 
com.milink.service com.miui.accessibility com.miui.analytics com.miui.aod com.miui.backup 
com.miui.bugreport com.miui.cit com.miui.cleaner com.miui.cloudbackup com.miui.cloudservice 
com.miui.daemon com.miui.extraphoto com.miui.micloudsync com.miui.miservice com.miui.misightservice 
com.miui.miwallpaper.overlay com.miui.miwallpaper.overlay.customize com.miui.msa.global 
com.miui.phone.carriers.overlay.h3g com.miui.phone.carriers.overlay.vodafone com.miui.phrase 
com.miui.player com.miui.settings.rro.device.hide.statusbar.overlay 
com.miui.settings.rro.device.type.overlay com.miui.system.overlay com.miui.touchassistant 
com.miui.videoplayer com.miui.vsimcore com.miui.wallpaper.overlay 
com.miui.wallpaper.overlay.customize com.miuix.editor com.miui.yellowpage com.modemdebug 
com.tencent.soter.soterserver com.wdstechnology.android.kryten com.xiaomi.aiasst.vision 
com.xiaomi.aicr com.xiaomi.barrage com.xiaomi.calendar com.xiaomi.cameratools com.xiaomi.glgm 
com.xiaomi.joyose com.xiaomi.micloud.sdk com.xiaomi.mi_connect_service com.xiaomi.mipicks 
com.xiaomi.mircs com.xiaomi.mirror com.xiaomi.mtb com.xiaomi.payment com.xiaomi.simactivate.service 
com.xiaomi.touchservice com.xiaomi.trustservice com.xiaomi.xmsfkeeper org.ifaa.aidl.manager 
org.mipay.android.manager 
```

Already disabled: `com.google.android.youtube` (ReVanced/Morphe builds used instead),
`com.google.android.ims`, `com.google.android.gms.supervision`, `com.google.android.devicelockcontroller`.

## 2. Cross-reference

Same `uad_lists.json` from UAD-ng (download command in the iQOO doc). Grouped the installed,
non-disabled packages by `(removal, list)`, tagged each with its installer
(`S` system / `play` / `preload` = installer null / `com.xiaomi.discover` = Xiaomi's preload updater).
Packages installed by `com.xiaomi.discover` or with a null installer are the Xiaomi preloads.
`play` ones are the user's own.

## 3. Removed this session (user-approved "green" tier)

```bash
printf '%s\n' com.amazon.appmanager com.miui.android.fashiongallery com.preff.kb.xm cn.wps.xiaomi.abroad.lite \
  com.miui.virtualsim com.miui.weather2 com.google.mainline.telemetry com.android.dreams.basic com.android.cts.ctsshim > remove.txt
while read -r p; do
  r=$(adb -s $D shell pm uninstall -k --user 0 "$p" </dev/null 2>&1 | tr -d '\r')
  [ "$r" != Success ] && r="$r | disable: $(adb -s $D shell pm disable-user --user 0 "$p" </dev/null 2>&1 | tr -d '\r' | tail -1)"
  echo "$p => $r"
done < remove.txt
```

(`</dev/null` matters: without it `adb shell` eats the loop's stdin and only the first package runs.)

| Package | What | Result |
|---|---|---|
| `com.amazon.appmanager` | Amazon preload tracker | uninstalled |
| `com.miui.android.fashiongallery` | Wallpaper Carousel (lockscreen content/ads) | uninstalled |
| `com.preff.kb.xm` | Facemoji "Emoji & Font Keyboard" | `Failure [-1000]`, **disabled** |
| `cn.wps.xiaomi.abroad.lite` | Mi Doc Viewer (WPS) | uninstalled |
| `com.miui.virtualsim` | Mi Roaming | uninstalled |
| `com.miui.weather2` | Mi Weather | `Failure [-1000]`, **disabled** |
| `com.google.mainline.telemetry` | Google module telemetry | uninstalled |
| `com.android.dreams.basic` | screensaver | uninstalled |
| `com.android.cts.ctsshim` | CTS test stub | uninstalled |

`-1000` hit two packages that HyperOS treats as updatable preloads (installer `com.xiaomi.discover`).
`disable-user` worked for both. The default keyboard is Gboard
(`settings get secure default_input_method`), so disabling Facemoji is harmless.

**Kept at the user's request**, even though UAD rates them Recommended or Advanced: `com.xiaomi.scanner`, `com.miui.qr`,
`com.miui.compass`, `com.google.android.apps.healthdata`, `com.android.hotspot2.osulogin` (Passpoint sign-in).

Unlike the iQOO, Claude Code's auto-mode classifier allowed this `pm uninstall` loop to run directly
(the user had explicitly named the packages).

## 4. Remaining optional candidates (not removed)

- Xiaomi apps: Mi Notes, Screen Recorder, Calculator, Files Manager, Gallery Editor (`com.miui.mediaeditor`),
  Media Viewer, Sound Recorder, Mi Share, Floating window (`com.miui.freeform`), Recording Assistant
  (`com.miui.audiomonitor`), ShareMe, Mi Home, Mi Remote (`com.duokan.phone.remotecontroller`, IR remote).
- `com.xiaomi.discover` (System Apps Updater): it reinstalls and updates Xiaomi preloads. Many guides remove it.
- Google apps: Chrome, Messages, Gboard (in use), Maps, Photos, Gmail, Wellbeing, Health Connect, Gemini, Google app.

## 5. Do not touch on HyperOS

`com.miui.securitycenter`, `securitycore`, `securityadd` (permission management), `com.miui.powerkeeper`,
`miui.systemui.plugin` (control centre breaks), `com.miui.core`, `com.xiaomi.xmsf` (push), `com.miui.home`,
`com.android.updater`, `com.miui.global.packageinstaller`, `com.xiaomi.ugd` (GPU driver updater),
`com.android.thememanager` / `com.miui.miwallpaper` (wallpaper breakage), `com.xiaomi.account`,
`com.xiaomi.finddevice`, `com.miui.face`, `com.android.incallui`, `com.android.camera` (MIUI camera),
`com.miui.misound` (earphone EQ), and MediaTek IMS/radio/TEE packages.

The hyperos-debloat README notes that removing the gaming optimisation packages
(`com.xiaomi.joyose`, `com.xiaomi.migameservice`, ...) can hurt game performance. `joyose` is already removed here.
Restore it if games stutter.

## Restore

```bash
adb -s $D shell cmd package install-existing <pkg>   # uninstalled ones
adb -s $D shell pm enable <pkg>                      # com.preff.kb.xm, com.miui.weather2
```

## References

- [BloodBlinker/hyperos-debloat](https://github.com/BloodBlinker/hyperos-debloat): method, gaming-package restore list
- [ovsky/hyperos-debloater](https://github.com/ovsky/hyperos-debloater): tiered HyperOS package database
- [barteqcz/MIUI-debloater](https://github.com/barteqcz/MIUI-debloater)
- [GetDroidTips: Debloat Redmi Note 12 and 12 Pro](https://www.getdroidtips.com/debloat-redmi-note-12-pro/)
- [DroidWin: Xiaomi debloat](https://droidwin.com/?p=56833)
- [Dr.Fone: ADB on Xiaomi to remove bloatware](https://drfone.wondershare.com/android-xiaomi/how-to-use-adb-on-xiaomi-to-remove-bloatware.html)
- [Snapcraft: Android Debloater (Xiaomi ratings)](https://snapcraft.io/install/android-debloater/manjaro)
- [UAD-ng package list](https://github.com/Universal-Debloater-Alliance/universal-android-debloater-next-generation)
