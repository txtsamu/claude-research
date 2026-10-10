---
type: investigation
tags: [android, iqoo, vivo, originos, otg, usb-audio, adb, jadx, reverse-engineering, fedora]
created: 2026-10-11
last_verified: 2026-10-11
status: blocked
---

# iQOO / vivo OTG auto-off: the OTG_Link_App approach cannot work (switch is a root-only sysfs node)

## Goal

USB-C earphones / DAC on the iQOO phone only work while the "OTG" switch is on, and OriginOS
switches it off again after ~5 minutes idle. [OTG_Link_App](https://github.com/Mishra-coder/OTG_Link_App)
keeps the equivalent switch on for Oppo/Realme/OnePlus by rewriting a `Settings.Global` key, and
lists vivo/iQOO as "not supported: key unknown". The aim was to find the vivo key and add the
vendor, following the repo's "Adding a new vendor" section.

## Result

**Not possible with that approach on this phone.** There is no settings key. The OTG switch in
OriginOS Settings writes the string `enabled` / `disabled` straight to a kernel sysfs file,
`/sys/devices/virtual/vusb/usb0/host_mode`, from inside the Settings process (system UID). Neither
`adb shell` nor a normal app holding `WRITE_SECURE_SETTINGS` can read or write that file. The
phone is unrooted with a locked bootloader, so status is `blocked`.

This matches step 4 of the repo's own guide: "If no key changes, the vendor keeps the switch
outside Settings, and this approach won't work."

Not done: the live before/after diff with the switch physically flipped
(`scripts/find-otg-key.sh`). The conclusion comes from reading the decompiled code plus the
permission check on the device, not from that diff. A `before` snapshot was taken but never
compared.

## Device

| | |
|---|---|
| Phone | iQOO `I2512` (manufacturer `vivo`), USB ID `2d95:6003` |
| OS | OriginOS 6, Android 16 (SDK 36), build `PD2553DF_EX_A_16.0.15.4.W20` |
| SoC | Qualcomm (`ro.vivo.product.solution=QCOM`, `ro.board.platform=volcano`) |
| Root | none; `ro.boot.verifiedbootstate=green`, `ro.boot.flash.locked=1`, `ro.debuggable=0` |
| Host | Fedora 43, `adb` from the distro package |

## Steps

### 1. Connect over ADB

```sh
lsusb                       # 2d95:6003 vivo I2512
adb devices -l              # "unauthorized" at first
adb kill-server; adb start-server
timeout 100 adb wait-for-device && adb devices -l   # after tapping "Allow USB debugging" on the phone
```

### 2. Look for an OTG key by name: none

```sh
for ns in global system secure; do adb shell settings list $ns | grep -iE 'otg|usb_host'; done   # no output
adb shell getprop | grep -i otg
```

```
[persist.vivo.otg_silicon_batt_low_thr]: [10]
[persist.vivo.phone.otg_param]: [5]
[persist.vivo.phone.usb_otg]: [Have_otg_usbc]
```

Settings tables hold 470 / 584 / 534 rows (global / system / secure); none mention OTG. The three
properties are capability flags, not the switch state.

### 3. Dead end: driving the phone UI from ADB

Tried to flip the switch from the PC so the before/after diff could run unattended. Both failed on
this ROM, so do not bother next time:

```sh
adb shell uiautomator dump /data/local/tmp/ui.xml   # ERROR: null root node returned by UiTestAutomationBridge
adb exec-out screencap -p > s1.png                  # valid 1080x2400 PNG, but entirely black
```

### 4. Decompile the Settings app to see what the switch does

```sh
adb shell pm path com.android.settings              # /system/priv-app/Settings/Settings.apk
adb pull /system/priv-app/Settings/Settings.apk .   # 252 MB
unzip -o -q Settings.apk 'classes*.dex' -d dex
strings -n 4 dex/*.dex | grep -i otg | sort -u      # finds OtgCheckBoxPreferenceController, VOtgUtils, ...

curl -sL -o jadx.zip https://github.com/skylot/jadx/releases/download/v1.5.1/jadx-1.5.1.zip && unzip -q jadx.zip
grep -l -a 'VOtgUtils.java' dex/*.dex               # classes4.dex defines it (others only reference it)
./bin/jadx --no-res -j 4 -d out2 dex/classes2.dex   # OtgCheckBoxPreferenceController
./bin/jadx --no-res -j 4 -d out4 dex/classes4.dex   # VOtgUtils
```

`com.vivo.settings.network.OtgCheckBoxPreferenceController` (preference key `otg_switch`) calls
`VOtgUtils.setOtgEnable(context, on)`:

```java
public static void setOtgEnable(Context context, boolean z) {
    if (isCcOpen() && context != null) {          // only when persist.vivo.phone.usb_otg == "Have_otg_ccopen"
        Settings.System.putInt(context.getContentResolver(), "vivo_otg_status", z ? 1 : 0);
    }
    FtFeature.setOtgEnable(z);
}
```

This phone reports `Have_otg_usbc`, so the `vivo_otg_status` branch is skipped. Even on a
`Have_otg_ccopen` model that key is only written alongside the real call; nothing found suggests
the system reacts to it being written from outside.

### 5. Decompile the framework class it calls

```sh
adb shell 'echo $BOOTCLASSPATH' | tr ':' '\n'
adb pull /system/framework/framework.jar . && unzip -o -q framework.jar 'classes*.dex' -d dex
for f in dex/*.dex; do strings -n 4 $f | grep -q '^FtFeature.java' && echo $f; done    # classes4.dex
./bin/jadx --no-res --single-class android.util.FtFeature -d outfw dex/classes4.dex
```

`android.util.FtFeature.setOtgEnable(boolean)` picks a path by SoC and writes to it with a plain
`FileWriter`. For Qualcomm (`ro.vivo.product.solution` contains `QCOM`, platform not `8937`):

```
switch: /sys/devices/virtual/vusb/usb0/host_mode    <- writes "enabled" or "disabled"
state:  /sys/devices/virtual/vusb/usb0/otg_mode
```

`isOtgEnable()` reads the same `host_mode` file back. No property, setting, broadcast or binder
call is involved. No timeout value appears in either class, so the 5-minute auto-off presumably
lives in the kernel driver.

### 6. Confirm the node is out of reach

```sh
adb shell 'ls -lZ /sys/devices/virtual/vusb/usb0/; cat /sys/devices/virtual/vusb/usb0/host_mode; id'
```

```
-????????? ? ? ? ? ? host_mode
-????????? ? ? ? ? ? otg_mode
cat: /sys/devices/virtual/vusb/usb0/host_mode: Permission denied
uid=2000(shell) ... context=u:r:shell:s0
```

The shell user cannot even stat the files. A third-party app is in a more restricted SELinux
domain than `shell`, so it cannot either; this also rules out Shizuku-style helpers that run as
`shell`.

### 7. Other shell-reachable triggers: none found

- No OTG quick-settings tile in `settings get secure sysui_qs_tiles`.
- `dumpsys package com.android.settings | grep -i otg` shows only the storage-format activity; the
  OTG fragment has no exported entry point of its own.
- `service list` has no vivo USB/OTG binder service.

## What would work

- **Root** (needs an unlocked bootloader, which this phone does not have): `echo enabled >
  /sys/devices/virtual/vusb/usb0/host_mode` on a timer.
- **UI automation on the phone** (an accessibility-based automation app that opens Settings and
  taps the switch). Not built or tested here.
- **Avoiding OTG entirely:** a 3.5 mm or Bluetooth output. The switch only times out while nothing
  is plugged in; with the earphones connected it stays on.

## Patching OTG_Link_App

Not done, since there is no key to add. A correct change for the repo would be documentation only:
record that vivo/iQOO (OriginOS 6, Qualcomm) uses `FtFeature` + sysfs and is out of reach, and
that `vivo_otg_status` (`Settings.System`) exists only on `Have_otg_ccopen` models and is
unverified.

## References

- [Mishra-coder/OTG_Link_App](https://github.com/Mishra-coder/OTG_Link_App) — README "Adding a new vendor", `scripts/find-otg-key.sh`, `docs/research-notes.md`
- [vivo OTG FAQ](https://www.vivoglobal.ph/questionlist/otg/) — official statement of the 5-minute auto-off, no always-on option
- [XDA: OTG always on](https://xdaforums.com/t/otg-always-on.4664745/) — OnePlus-only key `oneplus_otg_auto_disable`, checked and not applicable to vivo
- [skylot/jadx v1.5.1](https://github.com/skylot/jadx/releases/tag/v1.5.1) — decompiler used
