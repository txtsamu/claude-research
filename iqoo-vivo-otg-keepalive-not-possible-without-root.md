---
type: investigation
tags: [android, iqoo, vivo, originos, otg, usb-audio, adb, jadx, reverse-engineering, fedora]
created: 2026-10-11
last_verified: 2026-10-19
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

### 10. Boot-with-IEM-attached workaround (verified 2026-10-19)

Rebooting the phone with the IEM already plugged in keeps it working with no cutoff, and the OTG
switch never has to be turned on.

**Verified on 2026-10-19.** The phone was rebooted with the Moondrop IEM plugged in. Wireless
debugging was then re-enabled by hand, since it turns itself off at boot and comes back on a new
port. Checked at 13 min 17 s uptime, more than 2.5x the usual cutoff:

```sh
D=<PHONE_IP>:<new-wireless-debug-port>
adb -s $D shell cat /proc/uptime                                   # 797 s
adb -s $D shell dumpsys usb | grep -E 'host_connected=|current_mode='  # host_connected=true current_mode=dfp
adb -s $D shell dumpsys audio | grep 'Devices: usb_headset'        # usb_headset(4000000) active
adb -s $D logcat -d -v time -b all | grep -E 'USB_DEVICE_ATTACHED|ACTION_USB_DETACHED|onAudioDevicesAdded'
#   -> no output: no attach and no detach event since boot
```

Why it works: in the instrumented trials above, the ~5-min cut is a fixed timer counted from an
**attach event** (manual OTG switch or a physical replug, both logged as `USB_DEVICE_ATTACHED`).
When the IEM is attached through boot, the port comes up in host mode before userspace logs any
attach. With no attach event, the timer is never armed. The user confirmed the IEM was plugged in
for the whole reboot.

Caveats:
- Any unplug/replug, use of the OTG switch, or a reboot **without** the IEM attached goes back
  to the 5-min timer.
- Unrelated to the same day's debloat (`iqoo-originos6-adb-debloat-uad-list.md`). The timer lives
  in the kernel `vusb` driver, and no removed or restricted package touches OTG.
  `com.vivo.devicepower` was left installed.

## Can this phone be rooted? (so the sysfs write becomes possible)

Looked into it on 2026-10-11. Short version: no clean path, and nothing that helps this problem.

- **Official bootloader unlock: none.** vivo/iQOO has never run an unlock program; the "OEM
  unlocking" developer toggle is cosmetic on retail firmware. The standard Magisk / KernelSU route
  needs an unlocked bootloader (KernelSU's own FAQ states this), so it does not apply.
- **Exploit-based temporary root exists but is a dead end here.**
  [RootMyVivo](https://github.com/zenyxx-xd/RootMyVivo) uses GhostLock (CVE-2026-43499, a futex PI
  use-after-free) to load KernelSU in memory on a locked bootloader. Problems for this device:
  - Root is **lost on every reboot** — and the working OTG fix (step 10) *is* a reboot, so this
    root can never be present at the moment it would be needed. You would be re-running a flaky
    kernel exploit after each restart just to write one sysfs value.
  - The exploit only works on **kernels up to 6.6.139 (or 6.1.144)**; 6.6.140+ is patched. This
    phone is on a recent (Oct 2026) security patch, so its kernel may already be out of range. The
    exact `uname -r` was **not captured** — adb-over-Wi-Fi dropped to `unauthorized` before it
    could be read; re-accept the prompt and run `adb shell uname -r` to settle it.
  - Only iQOO Neo 11 and Z10 Turbo Pro are author-confirmed. The I2512 is not on the list. The
    author calls panics a "timing lottery" and ships a prebuilt exploit payload you must trust.
- **Conclusion:** even successful exploit-root buys nothing for the OTG timeout, because it does
  not persist across the reboot the fix relies on. The reboot-with-IEM-attached workaround remains
  the right answer. Rooting is only worth pursuing for broader goals (custom ROM, full control),
  and there the un-unlockable bootloader is the real blocker.

## Same issue reported on the official iQOO forum (not just this phone)

This is a known, unresolved OriginOS behaviour, not something specific to this unit. The closest
match is an iQOO India community thread, **"USB-C Earphones Not Recognized on iQOO 15 – OTG
Dependency and Auto Disconnect"** ([community.iqoo.com/in/thread/137185](https://community.iqoo.com/in/thread/137185)):

- Device: iQOO 15, Android 16, build `PD2505CF_EX_A16.0.20.1.W30` (same family, newer model than
  this I2512).
- Symptom, almost identical to ours: Samsung AKG Type-C earphones are not recognised when plugged
  in normally (no USB-detected notification, no audio). They work **only when OTG is manually
  enabled**, and then **"OTG automatically turns off after approximately 5 minutes"** and the
  audio stops. USB pendrives and the same earphones on other phones work fine.
- The poster's reading matches what the decompiled code shows: the firmware treats USB-C audio as
  an OTG accessory, and the auto power-off looks hard-coded and non-disableable.
- Their three asks: confirm USB Audio Class support, ship firmware that keeps USB-C audio detected
  without OTG, and add an option to disable OTG auto-off while an audio device is connected.
- **Status: unresolved.** No iQOO staff or user reply, ~1.7k views at time of reading.

Related reports: iQOO 12 users describe dongle DACs breaking (static then silence) after the
stable OriginOS 6 / Android 16 update ([gsmarena newscomm-70653](https://m.gsmarena.com/newscomm-70653.php)
comments). Older cross-vendor threads describe the same 10-minute timeout on other phones and an
ADB/Shizuku `otg_timeout=0` edit via a settings-DB editor — not applicable here, since OriginOS
keeps the switch in a kernel node, not the settings DB (see step 8).

Takeaway: the realistic "fix" is to report it to iQOO support with the exact model/build and add
weight to the existing thread; there is no user-side software fix on current firmware.

## Tested: the ADB `otg_timeout=0` settings-DB edit does nothing here (confirmed empirically)

The cross-vendor workaround (set `otg_timeout=0` / `otg state=true` via a settings-DB editor over
ADB/Shizuku) was tested directly on 2026-10-11, not just ruled out from the decompile.

1. No such key exists. Searching every namespace returns only unrelated timeouts (screen, backup,
   battery):
   ```sh
   for ns in global system secure; do adb shell settings list $ns | grep -iE 'otg|timeout|host_mode'; done
   # -> screen_off_timeout, backup_agent_timeout_parameters, verifier_timeout, ... no otg* anywhere
   ```
2. Writing the candidate keys "succeeds" but is inert — `settings put` accepts any key name and
   just creates a row the system ignores. None changed OTG state:
   ```sh
   adb shell dumpsys usb | grep -E 'host_connected=|current_mode='   # host_connected=true current_mode=dfp
   for kv in 'global otg_timeout 0' 'global otg_switch 1' 'system vivo_otg_status 1'              'global persist.sys.oplus.otg_support 1' 'secure otg_enabled 1'; do
       adb shell settings put $kv            # all readback fine
   done
   adb shell dumpsys usb | grep -E 'host_connected=|current_mode='   # unchanged: host_connected=true current_mode=dfp
   ```
   (The five inert rows were deleted afterwards with `settings delete`.)
3. The real node is still unreachable, read and write, from `shell`:
   ```
   cat /sys/devices/virtual/vusb/usb0/host_mode   -> Permission denied
   echo enabled > .../host_mode                   -> Permission denied (SELinux sysfs_otg)
   ```

So the settings-DB workaround is confirmed inapplicable to OriginOS: the switch and its timer are
not in the settings DB at all. `settings put` is the wrong layer; the write has to reach the
kernel node, which needs root.

## Mechanism confirmed: fixed ~5-min timer from each attach; replug restarts it

A second instrumented trial (replug, not manual toggle) pinned down the timer. adb was on Wi-Fi so
the USB-C port was free for the IEM; events read from the device's own `logcat -b all` buffer
(the Wi-Fi poller dropped mid-session, but the on-device log is authoritative):

| Session | Trigger | Attach | Detach | Duration |
|---|---|---|---|---|
| 1 | manual OTG switch | 03:04:26 | 03:09:31 | 5 min 5 s |
| 2 | physical replug | 03:20:42 | 03:25:48 | 5 min 6 s |

Findings:

- **Fixed timer from attach, not idle-based.** In session 2 the track was `STATE_ACTIVE` right up
  to the detach, and a pause/resume at 03:23:31 did not move the deadline. The cut lands ~5 min
  after *attach* regardless of playback. This directly contradicts vivo's FAQ wording ("turned off
  automatically if it is not used in 5 minutes").
- **Replug re-enters host mode with no settings change.** `ACTION_USB_ATTACHED` →
  `host_connected=true`, `current_mode=dfp`, `onAudioDevicesAdded` — purely from the cable's
  physical attach (CC detection). So the switch sits below the settings layer, and a fresh attach
  starts a fresh ~5-min session. The practical consequence: when it cuts out, a quick unplug/replug
  of the IEM restores audio for another ~5 min, faster than reopening Settings > OTG.
- `current_mode` is USB-C port-role state (dfp = Downstream Facing Port = host; ufp = device;
  none = detached), reported by the USB HAL — not a writable key. It mirrors `host_connected`.

This is consistent with the boot-with-IEM workaround (step 10) behaving differently: a cold attach
at boot brings the port up in host mode via the same hardware path, apparently without arming the
timer that the in-session attach does.

## What would work

- **Root** (needs an unlocked bootloader, which this phone does not have): `echo enabled >
  /sys/devices/virtual/vusb/usb0/host_mode` on a timer.
- **UI automation on the phone** (an accessibility-based automation app that opens Settings and
  taps the switch). Not built or tested here.
- **Boot with the IEM attached** (step 10, verified 2026-10-19), and leave it plugged in.
- **Avoiding OTG entirely:** a 3.5 mm or Bluetooth output.

## Patching OTG_Link_App

Not done, since there is no key to add. A correct change for the repo would be documentation only:
record that vivo/iQOO (OriginOS 6, Qualcomm) uses `FtFeature` + sysfs and is out of reach, and
that `vivo_otg_status` (`Settings.System`) exists only on `Have_otg_ccopen` models and is
unverified.

## References
- [iQOO community: USB-C Earphones Not Recognized on iQOO 15 – OTG Dependency and Auto Disconnect](https://community.iqoo.com/in/thread/137185) — near-identical symptom, unresolved
- [GSMArena: iQOO 12 OriginOS 6 stable update](https://m.gsmarena.com/newscomm-70653.php) — comments report dongle DAC regressions after the Android 16 update

- [Mishra-coder/OTG_Link_App](https://github.com/Mishra-coder/OTG_Link_App) — README "Adding a new vendor", `scripts/find-otg-key.sh`, `docs/research-notes.md`
- [vivo OTG FAQ](https://www.vivoglobal.ph/questionlist/otg/) — official statement of the 5-minute auto-off, no always-on option
- [XDA: OTG always on](https://xdaforums.com/t/otg-always-on.4664745/) — OnePlus-only key `oneplus_otg_auto_disable`, checked and not applicable to vivo
- [skylot/jadx v1.5.1](https://github.com/skylot/jadx/releases/tag/v1.5.1) — decompiler used
