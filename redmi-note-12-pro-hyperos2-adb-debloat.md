---
type: how-to
tags: [android, xiaomi, redmi, hyperos, adb, debloat, uad-ng, wireless-debugging, mediatek, technitium, advanced-blocking, hagezi, mikrotik]
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
| `com.xiaomi.discover` | System Apps Updater (reinstalls/updates Xiaomi preloads) | uninstalled (removed separately, same session) |

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

Side effect of removing `com.xiaomi.discover`: preloads it managed (Mi Notes, Screen Recorder, Gallery Editor, Sound Recorder, ...) no longer get updates through it, and it can no longer quietly reinstall removed preloads. Restore it with `install-existing` if a Xiaomi app needs updating.

## 6. DNS-level block: Redmi-only Technitium group (2026-10-19)

The same mechanism as the iQOO (`iqoo-originos6-adb-debloat-uad-list.md`) and the TV: a `redmi-phone`
group in the **Advanced Blocking** app, mapped to `192.168.50.3` only, on all three nodes
(.200, .40, .42). The Redmi has Private DNS `off` and gets `.200, .42, .40, 1.1.1.1, 1.0.0.1` over
Wi-Fi DHCP.

List: **HaGeZi `native.xiaomi`** (wildcard, 345 entries, `xiaomi.com` 183, `miui.com` 98, plus
`gitv.tv`/`ptqy` Mi TV video and `mi.com`). URL:
`https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/wildcard/native.xiaomi-onlydomains.txt`

Functional hosts the list would break (checked by walking each host's parents against the list,
since Technitium blocks a listed domain **and all its subdomains**):

| Host | Blocked via | Needed for | Action |
|---|---|---|---|
| `bigota.d.miui.net`, `hugeota.d.miui.net` | **`miui.net`** (the whole zone) | HyperOS OTA downloads | allowed (+ `cdnorg.d.miui.net`, `ultimateota.d.miui.com`) |
| `api.xmpush.global.xiaomi.com` (+ `sgp-api`, `idmb-api`, `register`, `resolver.msg.global.xiaomi.net`) | listed | Mi Push (xmsf) notifications | allowed |
| `findapi.micloud.xiaomi.net` | listed | Find Device | allowed |
| `thm.market.xiaomi.com`, `t1-t17.market.xiaomi.com` | listed | Themes app images/downloads | allowed |
| `update.intl.miui.com`, `account.xiaomi.com`, `time.xiaomi.com` | not in list | | |

Left blocked: `resolver.gslb.mi-idc.com` / `resolver.mi.xiaomi.com` (Xiaomi HTTPDNS, apps fall back
to system DNS), `api.setting.intl.miui.com`, `update.avlyun.sec.miui.com` (Security app's Avast
engine updates), all `*.feedback.xmpush*`.

```bash
# login + per-node merge, identical to the iQOO doc (password from home's agenix env file)
jq --slurpfile g redmi_group.json '.networkGroupMap["192.168.50.3"]="redmi-phone"
   | .groups = ([.groups[] | select(.name!="redmi-phone")] + $g)' advblock_before_$ip.json > advblock_new_$ip.json
/usr/bin/curl -s -X POST "http://$ip:5380/api/apps/config/set?token=$t" \
  --data-urlencode "name=Advanced Blocking" --data-urlencode "config@advblock_new_$ip.json"
```

Resulting maps: `.200` {.31 samsung-tv, .1 samsung-tv, .26 iqoo-phone, .3 redmi-phone};
`.40` {.31 samsung-tv, .26 iqoo-phone, .1 iqoo-phone, .3 redmi-phone}; `.42` {.31 samsung-tv,
.26 iqoo-phone, .3 redmi-phone}.

Verification:
- **130 of 345** list entries were *already* blocked LAN-wide by the global blocklistproject list
  (`dig ... TXT` shows `source=block-list-zone; blockListUrl=https://blocklistproject...`), e.g.
  `tracking.intl.miui.com`, `data.mistat.intl.xiaomi.com`, `sdkconfig.ad.intl.xiaomi.com`.
  On the phone `ping` shows those as `127.0.0.1`.
- **192** entries resolve normally for other clients and are now NXDOMAIN on the Redmi only, e.g.
  `miui-l7-data-other-c3.pt.miui.com`, `extranet.ap-southeast-1.miui-l7-feedback.*.elb.xiaomi.com`,
  `globalvideo.cdn.pandora.intl.xiaomi.com`, `auth.api.gitv.tv` (PC: resolves; Redmi: `unknown host`).
- Allowlisted hosts resolve on the Redmi: `bigota.d.miui.net`, `api.xmpush.global.xiaomi.com`,
  `findapi.micloud.xiaomi.net`, and `update.intl.miui.com` (not in the list).

## 7. Static lease + forced DNS redirect (2026-10-19)

Why it isn't a straight copy of the TV/iQOO setup: redirected queries are hairpin-masqueraded, so
Technitium sees them coming **from the router**, and Advanced Blocking can only tell clients apart
by source IP. `192.168.50.1` was already taken on two nodes (`.200` → samsung-tv, `.40` → iqoo-phone).
The first attempt sent the Redmi to `.42` (mapping `.1 → redmi-phone` there), but the user didn't
want `.42` used, so that was reverted. The final design gives the router a **dedicated alias IP,
`192.168.50.252`**, used only as the source for the Redmi's redirected queries, and points the
redirect at `.200`, where `.252 → redmi-phone` is mapped.

```routeros
/export file=pre-redmi-dns-2026-10-19
/ip dhcp-server lease make-static [find address=192.168.50.3]
/ip dhcp-server lease set [find address=192.168.50.3] comment="Redmi Note 12 Pro (static, DNS redirect + phone-only xiaomi blocking)"

# the DHCP pool is 192.168.50.3-254, so reserve the alias with a dummy static lease first
/ip dhcp-server lease add address=192.168.50.252 mac-address=02:00:00:00:02:52 server=dhcp1 comment="RESERVED: router alias for Redmi DNS redirect source (do not hand out)"
/ip address add address=192.168.50.252/32 interface=bridgeLocal comment="Redmi DNS redirect hairpin source"

/ip firewall mangle add chain=prerouting src-address=192.168.50.3 dst-address-list=!lan-dns protocol=udp dst-port=53 connection-state=new action=mark-connection new-connection-mark=redmi-dns-redirect passthrough=yes comment="Redmi DNS redirect mark udp"
/ip firewall mangle add chain=prerouting src-address=192.168.50.3 dst-address-list=!lan-dns protocol=tcp dst-port=53 connection-state=new action=mark-connection new-connection-mark=redmi-dns-redirect passthrough=yes comment="Redmi DNS redirect mark tcp"
/ip firewall nat add chain=dstnat src-address=192.168.50.3 dst-address-list=!lan-dns protocol=udp dst-port=53 action=dst-nat to-addresses=192.168.50.200 comment="Redmi DNS redirect udp -> Technitium .200"
/ip firewall nat add chain=dstnat src-address=192.168.50.3 dst-address-list=!lan-dns protocol=tcp dst-port=53 action=dst-nat to-addresses=192.168.50.200 comment="Redmi DNS redirect tcp -> Technitium .200"
/ip firewall nat add chain=srcnat connection-mark=redmi-dns-redirect action=src-nat to-addresses=192.168.50.252 comment="Redmi DNS redirect hairpin"
```

Technitium: `.200` map gained `"192.168.50.252": "redmi-phone"`. On `.42` the temporary
`"192.168.50.1": "redmi-phone"` was rolled back to its pre-redirect backup. Final maps:
`.200` {.31 tv, .1 tv, .26 iqoo, .3 redmi, .252 redmi}; `.40` {.31 tv, .26 iqoo, .1 iqoo, .3 redmi};
`.42` {.31 tv, .26 iqoo, .3 redmi}.

The same alias trick would let any further device get its own redirect group without needing
another Technitium node: one reserved alias IP + `src-nat to-addresses=<alias>` per device.

Verification: this PC got temporary copies of the udp mark + dstnat rules (comment `TEMP test redmi`), removed straight after:
```
dig @1.1.1.1 miui-l7-data-other-c3.pt.miui.com -> NXDOMAIN
dig @1.1.1.1 auth.api.gitv.tv                  -> NXDOMAIN
  TXT: source=advanced-blocking-app; group=redmi-phone; ...native.xiaomi-onlydomains.txt; domain=auth.api.gitv.tv
dig @1.1.1.1 bigota.d.miui.net                 -> NOERROR (allowlisted OTA)
dig @1.1.1.1 api.xmpush.global.xiaomi.com      -> NOERROR (allowlisted push)
dig @1.1.1.1 google.com                        -> NOERROR
# after removing TEMP rules: real 1.1.1.1 answers again
```

Notes / undo:
- The Redmi's MAC is randomized (`client-id 1:4e:eb:c6:40:d9:af`). Forgetting the Wi-Fi network or
  switching to a non-persistent MAC breaks the static lease.
- Undo: `/ip firewall nat remove [find comment~"Redmi DNS"]`, `/ip firewall mangle remove [find comment~"Redmi DNS"]`,
  `/ip address remove [find comment="Redmi DNS redirect hairpin source"]`,
  `/ip dhcp-server lease remove [find address=192.168.50.252]`, `/ip dhcp-server lease make-dynamic [find address=192.168.50.3]`.
  In Technitium, remove `.3` (all nodes) and `.252` (`.200`) from the maps and delete the `redmi-phone` group.

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
- [HaGeZi native.xiaomi wildcard list](https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/wildcard/native.xiaomi-onlydomains.txt)
- [HaGeZi dns-blocklists](https://github.com/hagezi/dns-blocklists)
- [UAD-ng package list](https://github.com/Universal-Debloater-Alliance/universal-android-debloater-next-generation)
