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

Confirmed by the live before/after diff (step 8): with the OTG switch flipped by hand, all 3,570
settings rows and system properties were byte-identical.

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

### 8. Live before/after diff with the switch flipped: nothing changes

Same method as the repo's `scripts/find-otg-key.sh`, extended to include `getprop`:

```sh
snap(){ { for ns in global system secure; do adb shell settings list $ns | sed "s/^/$ns: /"; done
          adb shell getprop | sed 's/^/prop: /'; } | sort > $1; }
snap before      # then flip Settings > OTG on the phone by hand
snap after
diff before after; echo $?      # no output, exit 0
```

Both files have 3,570 lines and are identical. The flip itself could not be observed from ADB
(`host_mode` is unreadable, and the phone stays in device role while cabled to the PC), so this
relies on the switch having been flipped as reported. The SELinux denial logged by step 6 names
the label on the node:

```
avc: denied { getattr } for path="/sys/devices/virtual/vusb/usb0/host_mode"
  scontext=u:r:shell:s0 tcontext=u:object_r:sysfs_otg:s0 tclass=file permissive=0
```

### 9. Watching the cutoff live over wireless ADB

The phone's only USB-C port is taken by the IEM, so ADB was moved to Wi-Fi first (while still cabled):

```sh
adb shell ip -4 -o addr show wlan0          # phone LAN IP
adb tcpip 5555 && adb connect <PHONE_IP>:5555   # accept the new authorization prompt on the phone
```

A poll loop logged `dumpsys usb` every 5 s while the user unplugged the PC cable, turned OTG on by
hand and plugged in the IEM (a Moondrop USB-C DAC cable, Conexant chip):

```sh
A="adb -s <PHONE_IP>:5555"
while :; do $A shell 'dumpsys usb | grep -E "host_connected=|current_mode="' | tr -s ' \n' ' '; date +%T; sleep 5; done
$A shell 'logcat -d -v time -b all' | grep -E '^10-11 03:09:3'      # afterwards, around the cutoff
```

Timeline (one trial):

| Time | Event |
|---|---|
| 03:04:26 | `USB_DEVICE_ATTACHED`; `host_connected=true`, `current_mode=dfp` |
| 03:09:31.044 | music app's `AudioTrack` paused, `prior state:STATE_ACTIVE` (audio was playing) |
| 03:09:31.116 | `ACTION_USB_DETACHED`; audio route falls back to SPEAKER |
| after | `dumpsys usb` still reports `host_connected=true`, `current_mode=dfp` |

So the device was dropped **5 min 5 s after attach, during active playback**. On this phone and
this IEM the timer is not idle-based, contrary to the wording of vivo's FAQ ("if it is not used in
5 minutes"). No userspace log line precedes the detach, which points at the kernel `vusb` driver;
the kernel log is not readable from `shell`, so that part is inferred.

Ruled out: `com.vivo.devicepower` (it has a `UsbDeviceReceiver` that starts on attach) contains no
OTG / `host_mode` code. The "OTG help" page in Settings (`VivoOtgHelpSettings`, shown because
`persist.vivo.phone.otg_param` has bit 0 set) only cycles signal-compatibility modes 0-4 through
`UsbManager.setEysParameter(int)`; it has nothing to do with the timeout.

Gotchas: do not run two loops that both call `adb connect` (the connection flapped to
`unauthorized`), and `pkill -f` with a pattern that also appears in the new command line kills the
new recorder too.

### 10. User-reported workaround (not instrumented)

Rebooting the phone with the IEM already plugged in keeps it working with no cutoff. Hypothesis:
the port enters host mode by itself during boot, so the manual-switch path that arms the 5-minute
timer never runs. Unverified: wireless ADB does not survive a reboot (`adb tcpip` resets), so this
could not be recorded the same way.

## What would work

- **Root** (needs an unlocked bootloader, which this phone does not have): `echo enabled >
  /sys/devices/virtual/vusb/usb0/host_mode` on a timer.
- **UI automation on the phone** (an accessibility-based automation app that opens Settings and
  taps the switch). Not built or tested here.
- **Boot with the IEM attached** (step 10), and leave it plugged in.
- **Avoiding OTG entirely:** a 3.5 mm or Bluetooth output.

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
