---
type: how-to
tags: [8bitdo, ultimate-2c, controller, firmware, linux, fedora, webusb, webhid, udev, brave]
created: 2026-10-27
last_verified: 2026-10-27
status: current
---

# 8BitDo Ultimate 2C Wireless: firmware update from Linux via web.8bitdo.com

Checked whether the controller (8BitDo Ultimate 2C Wireless, 2.4 GHz dongle) had a firmware update and flashed it from Fedora using 8BitDo's browser-based updater. The official desktop updater (Ultimate Software V2) is Windows/macOS only.

## Summary

- Latest official firmware for "Ultimate 2C Wireless Controller (2.4G)" per 8BitDo's support page: **v1.09** (removes the phantom Home button input in XInput mode, improves 2.4G connection stability).
- Linux can't read the real firmware version: `bcdDevice` in sysfs is the dongle's USB revision (`1.14` here) and does not map to 8BitDo's v1.0x numbering. The version is only visible in the updater UI.
- Flashing worked through https://web.8bitdo.com in Brave (Chromium) after granting udev access. Page reported "update complete"; the device re-enumerated and still works (`js0` present, XInput via `xpad`).
- The before/after version shown by the updater was not recorded in this session.
- Post-update input test: all face buttons, bumpers, triggers, d-pad, sticks, Start/Back and Home work with no drift or phantom Home press. L3/R3 clicks were not detected (see step 6).

## Steps

### 1. Identify the hardware

```bash
lsusb | grep -i 8bitdo
ls -l /dev/input/by-id/ | grep -i joystick
journalctl -k --since "-15min" | grep -i -E "2dc8|8bitdo|xpad"
```

Here: `2dc8:310a` "8BitDo Ultimate 2C Wireless (WUKONG)" bound by `xpad`, exposed as `/dev/input/js0`. A second 8BitDo device `2dc8:301c` "IDLE" was also present; it exposes no gamepad (likely a second dongle with nothing paired) and was left alone.

### 2. Find the latest firmware and updater

- 8BitDo support page lists v1.09 as latest for the 2C Wireless (2.4G): https://support.8bitdo.com/
- Ultimate Software V2 (Windows 10 1903+/macOS 13+) has no Linux build.
- 8BitDo runs a beta web updater, "Ultimate Software Online", at https://web.8bitdo.com. It needs **WebUSB/WebHID, i.e. a Chromium-based browser** (Firefox does not work). The Ultimate 2C Wireless is in its device list.

### 3. Grant the browser access (udev)

Checked first whether the user could already open the device nodes:

```bash
stat -c '%A %U:%G %n' /dev/bus/usb/001/072
test -r /dev/bus/usb/001/072 && test -w /dev/bus/usb/001/072 && echo ok || echo "cannot rw"
```

- `/dev/hidraw*` for vendor `2dc8` was already accessible: Steam's `/usr/lib/udev/rules.d/60-steam-input.rules` gives it `MODE=0660, TAG+="uaccess"`.
- `/dev/bus/usb/...` (needed for WebUSB) was `root:root 0664`, so **not** writable by the user. Fixed with a narrow rule:

```bash
printf 'SUBSYSTEM=="usb", ATTR{idVendor}=="2dc8", TAG+="uaccess"\n' | sudo tee /etc/udev/rules.d/70-8bitdo-webusb.rules \
  && sudo udevadm control --reload-rules \
  && sudo udevadm trigger --subsystem-match=usb --attr-match=idVendor=2dc8
```

The web page itself suggests a broader rule (`SUBSYSTEM=="hidraw", ATTRS{idVendor}=="2dc8", MODE="0666", GROUP="users", TAG+="uaccess"` followed by a bare `udevadm trigger`). Not used: `MODE=0666` lets any local process write to the controller, and `uaccess` alone is enough. An explicit hidraw rule was added anyway in case the Steam package is ever removed:

```bash
printf 'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="2dc8", MODE="0660", TAG+="uaccess"\n' | sudo tee /etc/udev/rules.d/71-8bitdo-hidraw.rules \
  && sudo udevadm control --reload-rules \
  && sudo udevadm trigger --subsystem-match=hidraw
```

Verify (every 8BitDo node should print `can rw` for the logged-in user):

```bash
for n in /dev/hidraw*; do [ "$(udevadm info -q property -n $n | grep ^ID_VENDOR_ID=)" = "ID_VENDOR_ID=2dc8" ] && { stat -c '%A %U:%G %n' $n; test -r $n && test -w $n && echo "  can rw" || echo "  CANNOT rw"; }; done
```

### 4. Run the web updater

```bash
brave-browser --new-window https://web.8bitdo.com
```

1. Pick **Ultimate 2C Wireless Controller** (not "2C Wired", not the Ultimate 2 cards).
2. At "Select a device to upgrade" there are two options, **Controller** and **Receiver**. No 8BitDo documentation found says which comes first for this model. Chose **Controller**, because v1.09 is listed under the controller entry and the changelog does not mention the receiver.
3. Connected the controller by data-capable USB cable (not via the dongle) before starting.
4. Started the update only after confirming the page recognised the device. The page reported "update complete".

### 5. Verify

```bash
lsusb | grep 2dc8
ls -l /dev/input/by-id/ | grep joystick
journalctl -k --since "-15min" | grep -i -E "2dc8|8bitdo|xpad"
```

The kernel log shows the controller re-enumerating (`input: 8BitDo Ultimate 2C Wireless Controller`, new hidraw nodes) and the gamepad node `js0` still present. Dongle `bcdDevice` still `0114` (the update changed the controller, not the dongle's USB revision).

### 6. Post-update input test

`evtest` was not installed, so a small Python script reads the evdev node directly (no packages needed) and summarises which buttons and axes were exercised. Usage: `python3 -I padtest.py /dev/input/eventN SECONDS`.

Look the node up each time: replugging the dongle moves it (it went `event20` -> `event23` here, and between plugs the by-id symlink is gone):

```bash
node=$(readlink -f /dev/input/by-id/*8BitDo*Wireless*-event-joystick | head -1)
python3 -I padtest.py "$node" 45
```

`padtest.py`:

```python
#!/usr/bin/env python3
"""Read an evdev gamepad node and report which buttons/axes were exercised.
usage: padtest.py /dev/input/eventN SECONDS"""
import struct, sys, time, select, os

KEYS = {0x130:"A",0x131:"B",0x133:"X",0x134:"Y",0x136:"LB",0x137:"RB",
        0x13a:"Back/View",0x13b:"Start/Menu",0x13c:"Guide/Home",0x13d:"L3",0x13e:"R3",
        0x132:"BTN_C",0x135:"BTN_Z",0x138:"BTN_TL2",0x139:"BTN_TR2",0x13f:"BTN_THUMBR2",
        0x2c0:"TRIGGER_HAPPY1",0x2c1:"TRIGGER_HAPPY2",0x2c2:"TRIGGER_HAPPY3",0x2c3:"TRIGGER_HAPPY4"}
ABS = {0:"LeftX",1:"LeftY",2:"LT",3:"RightX",4:"RightY",5:"RT",16:"DpadX",17:"DpadY"}
EVFMT = "llHHi"; SZ = struct.calcsize(EVFMT)
dev, secs = sys.argv[1], float(sys.argv[2])
fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
btn = {}; axis = {}
end = time.time() + secs
while time.time() < end:
    r,_,_ = select.select([fd],[],[],0.2)
    if not r: continue
    try: data = os.read(fd, SZ*64)
    except BlockingIOError: continue
    for i in range(0, len(data)-SZ+1, SZ):
        _,_,t,c,v = struct.unpack(EVFMT, data[i:i+SZ])
        if t == 1:
            n = KEYS.get(c, f"KEY_{c:#x}")
            btn.setdefault(n, [0,0]); btn[n][0 if v else 1] += 1
            print(f"{'down' if v else 'up  '} {n}", flush=True)
        elif t == 3:
            n = ABS.get(c, f"ABS_{c}")
            lo,hi = axis.get(n,(v,v)); axis[n] = (min(lo,v),max(hi,v))
print("\n=== SUMMARY ===")
print("buttons pressed:", ", ".join(sorted(btn)) or "none")
print("axes (min..max):")
for n,(lo,hi) in sorted(axis.items()): print(f"  {n}: {lo}..{hi}")
```

Results (after the firmware update):

| Test | Result |
|---|---|
| A, B, X, Y, LB, RB | OK, clean down/up pairs, no chatter |
| Back/View, Start/Menu | OK |
| Guide/Home | OK (3 clean presses) |
| D-pad (all 4 directions) | OK |
| LT / RT | full `0..255` |
| Both sticks | full `-32768..32767` on both axes (needs a full push; partial pushes show e.g. `24045`) |
| Drift / phantom Home, 15 s hands off | **no events at all**, consistent with the v1.09 phantom-Home fix working |
| L3 / R3 (stick clicks) | **not detected** in the 30 s test, no event and no unmapped key code. Unknown whether not pressed firmly enough or a hardware fault; focused retest pending |

Gotchas hit while testing:

- The first "drift" run was invalid: the command started before the controller was put down, so it recorded button presses and full stick sweeps. Wait for an explicit "hands off" before starting a drift capture.
- Mid-test the dongle was unplugged (`usb 1-4: USB disconnect` in the kernel log), the event node vanished and `open()` returned `FileNotFoundError`. Check `lsusb | grep 2dc8` and the by-id symlink before blaming the controller.
- Brave (open on web.8bitdo.com via the Gamepad API) and `cosmic-osk` had the node open. That's read-only and does not block other readers, so it was not the cause of the empty first capture (nothing was being pressed).

## Dead ends / notes

- Reading the current firmware version from Linux: `bcdDevice`, `lsusb -v` and `dmesg` give only USB descriptors, not the 8BitDo firmware version. Use the updater UI.
- The Receiver option was not touched. If connection problems persist, try updating the receiver separately.
- Brave 155 supports WebUSB/WebHID with no flags. If no device picker appears, check `brave://settings/content/usbDevices`.
- The web updater is a beta, unlisted on 8BitDo's English site, and may change or be removed. The Windows route (Wine/Lutris or a Windows VM with USB passthrough) is the fallback per community reports.

## References

- [8BitDo support page (firmware list, v1.09 changelog)](https://support.8bitdo.com/)
- [8BitDo Ultimate Software V2 (Windows/macOS updater)](https://app.8bitdo.com/Ultimate-Software-V2)
- [8BitDo's Semi-Secret Web-Based Firmware Updater (rdnlsmith)](https://rdnlsmith.com/posts/2026/001/8bitdo-web/): web.8bitdo.com URL, Chromium-only, udev rule suggestion
- [GamingOnLinux: Ultimate 2 review (no official Linux firmware updater)](https://gamingonlinux.com/2025/05/the-8bitdo-ultimate-2-wireless-controller-is-a-top-premium-feeling-controller/)
- [KitGuru: 8BitDo web-based Ultimate Software updater announcement](https://www.kitguru.net/desktop-pc/mustafa-mahmoud/8bitdo-announces-new-web-based-ultimate-software-updater/)
