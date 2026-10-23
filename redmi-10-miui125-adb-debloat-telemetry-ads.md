---
type: how-to
tags: [android, xiaomi, redmi, miui, miui-12-5, adb, debloat, telemetry, ads, mediatek, magisk, selene]
created: 2026-10-23
last_verified: 2026-10-23
status: current
---

# Redmi 10 (selene, MIUI 12.5 Global) ADB debloat: telemetry and ads, keep Xiaomi utilities

User goal: remove telemetry and ads, but **keep the useful Xiaomi apps** (compass, scanner, etc.).
Same method as `redmi-note-12-pro-hyperos2-adb-debloat.md`. `pm uninstall -k --user 0` is reversible,
so nothing here is permanent.

## Device

| | |
|---|---|
| Model | `21121119SG` (Redmi 10 2022, Indonesia/Global), codename `selene`, `ro.product.mod_device=selenes_id_global` |
| SoC | MediaTek (Huaqin ODM: `com.huaqin.*`, `com.mediatek.*` packages) |
| OS | MIUI 12.5 (`ro.miui.ui.version.name=V125`), Android 11 (SDK 30), region `US` prop |
| Root | Magisk installed, `adb shell su -c id` gives `uid=0` |
| Launcher / IME | third-party launcher (`bitpit.launcher`), Gboard. Checked **before** removing the MIUI home and Mint Keyboard |
| ADB | USB, `adb devices -l` |

## 1. Inventory

```bash
adb devices -l
adb shell getprop ro.product.model; adb shell getprop ro.build.version.release
adb shell getprop ro.miui.ui.version.name
adb shell pm list packages -3 | sort                                # user apps
adb shell pm list packages -s --user 0 | sed 's/package://' | sort > system_pkgs.txt   # 287 system pkgs
adb shell pm list packages -d --user 0                              # disabled: nfc, mipicks, mipay.wallet.in
adb shell pm list packages -u | grep -E 'analytics|msa|joyose|hybrid|yellowpage|bugreport|miservice'
```

Gotcha: plain `pm list packages` hides packages already removed for user 0. `-u` includes them. Comparing
a candidate against `system_pkgs.txt` (user-0 view) tells you whether it is still present:

```bash
grep -qx com.miui.analytics system_pkgs.txt && echo PRESENT || echo absent
```

**Already removed by an earlier debloat** (present with `-u`, absent for user 0): `com.miui.analytics`,
`com.miui.msa.global` (MSA, the ad service), `com.miui.hybrid(.accessory)`, `com.miui.yellowpage`,
`com.miui.bugreport`, `com.miui.miservice`, `com.xiaomi.joyose`, `com.mi.globalbrowser`.

**Compass is not on this phone at all.** `com.miui.compass` is not in the `-u` list either, so the ROM
never shipped it. The scanner is `com.miui.qr` and was left alone.

## 2. Pre-flight checks before removing

```bash
adb shell settings get secure default_input_method      # com.google.android.inputmethod.latin (Gboard)
adb shell cmd shortcut get-default-launcher             # bitpit.launcher, so com.miui.home is not the active home
```

## 3. Packages removed (18)

```
com.facebook.appmanager  com.facebook.services  com.facebook.system     # Facebook preinstalled stubs
com.miui.daemon                                                         # MIUI Daemon, usage/perf reporting
com.mi.android.globalminusscreen                                        # App Vault feed (ads)
com.xiaomi.mipicks                                                      # GetApps store (was already disabled)
com.miui.cleaner                                                        # Cleaner, ad/recommendation surface
com.miui.securityadd                                                    # Security add-on (ad/rec content)
com.xiaomi.simactivate.service                                          # SIM activation phone-home
com.mint.keyboard                                                       # Mint Keyboard, ads/data collection
com.google.mainline.telemetry   com.google.android.feedback             # Google telemetry/feedback agents
com.debug.loggerui  com.huaqin.btlogger  com.huaqin.diaglogger         # MTK/Huaqin debug loggers
com.mipay.wallet.id  com.mipay.wallet.in  com.xiaomi.payment            # Mi Pay / Mi Wallet
```

Undo commands are under "Reverting" below.

```bash
for p in $(cat debloat_core.txt); do
  printf '%-45s ' "$p"
  adb shell pm uninstall -k --user 0 "$p" </dev/null 2>&1 | tr -d '\r'
done
```

**Gotcha: `</dev/null` is required.** The first attempt used `while read p; do adb shell ... ; done < file`.
`adb shell` reads stdin, swallowed the rest of the file, and only the first package was processed. A
`for p in $(cat file)` loop with `</dev/null` fixes it (or use `adb shell -n`). The leftover
`Failure [not installed for 0]` on `com.facebook.appmanager` in the rerun is just the first run having
already removed it.

## 4. Verification

```bash
adb shell pm list packages --user 0 | grep -E 'miui.qr|calculator|notes|screenrecorder|weather2|mediaeditor|soundrecorder|maxmpz|bitpit|latin|vending|gms$'
adb shell pm list packages --user 0 | wc -l          # 296 after
adb logcat -d -b crash | tail -5                     # empty
adb shell dumpsys window | grep -m1 mCurrentFocus   # launcher in focus
```

Kept and still working: scanner (`com.miui.qr`), Calculator, Notes, Screen Recorder, Weather, Media Editor,
Sound Recorder, FM, Poweramp, the launcher, Gboard, Play Store/GMS. No crashes in the crash buffer.

## 5. Not done (needs the user's call, or is not an ADB job)

| Candidate | Why held back |
|---|---|
| `com.miui.videoplayer` (Mi Video), `com.miui.player` (Mi Music) | Ad-heavy, but they are Xiaomi media apps. The user has Poweramp |
| `com.miui.gallery`, `com.xiaomi.calendar`, `com.android.thememanager` | Ad/recommendation surfaces, but each has a user-facing role |
| `com.miui.cloudservice`, `cloudbackup`, `micloudsync`, `com.xiaomi.micloud.sdk`, `cloudservice.sysbase` | Mi Cloud sync. Remove only if the user never uses it |
| `com.xiaomi.xmsf`, `com.xiaomi.xmsfkeeper` | Mi Push. Some apps depend on it for notifications |
| `com.xiaomi.mi_connect_service`, `miplay_client`, `milink.service`, `upnp` | Casting / Mi Connect |
| `com.google.android.apps.turbo`, `projection.gearhead`, `apps.wellbeing`, `apps.googleassistant` | Google extras, not ads/telemetry per se |

Two settings exist on the device but their value semantics were **not** confirmed, so they were not written
over ADB: `global/personalized_ad_enabled=3`, `secure/upload_log_pref=1`. Use the UI toggles instead:

- Settings > Passwords & security > Privacy > **Ad services** > turn off *Personalized ad recommendations*
  (Xiaomi notes this reduces targeting, not the number of ads in system apps).
- Settings > Passwords & security > Privacy > **Usage and diagnostics** (the exact path on 12.5 may differ).

Optional network layer: Private DNS was unset (`private_dns_mode=null`). Pointing the phone at the
homelab Technitium/Advanced Blocking list would cover the apps that remain.

## Reverting

```bash
adb shell cmd package install-existing com.miui.daemon      # any single package

# everything in section 3 (same package list as debloat_core.txt)
for p in com.facebook.appmanager com.facebook.services com.facebook.system com.miui.daemon \
  com.mi.android.globalminusscreen com.xiaomi.mipicks com.miui.cleaner com.miui.securityadd \
  com.xiaomi.simactivate.service com.mint.keyboard com.google.mainline.telemetry \
  com.google.android.feedback com.debug.loggerui com.huaqin.btlogger com.huaqin.diaglogger \
  com.mipay.wallet.id com.mipay.wallet.in com.xiaomi.payment; do
  adb shell cmd package install-existing "$p" </dev/null
done
```

## References

- [How to close Ad services? (Xiaomi support)](https://www.mi.com/uk/support/article/KA-12885/)
- [MIUI 13 Privacy White Paper, Usage and Diagnostics](https://trust.mi.com/docs/miui-privacy-white-paper-global/4/12)
- Sibling doc: `redmi-note-12-pro-hyperos2-adb-debloat.md` (method), `iqoo-originos6-adb-debloat-uad-list.md`
