---
type: troubleshooting
tags: [openrgb, gigabyte, b650m-k, rgb-fusion, it5701, it5702, hidraw, argb, reverse-engineering, ilspy, fedora, systemd]
created: 2026-10-20
last_verified: 2026-10-20
status: current
---

# Gigabyte B650M K: case-fan ARGB won't light in OpenRGB — reverse-engineered a tiny replacement

**Host:** Fedora 43, Gigabyte B650M K Rev 1.1 (ITE IT5701, USB `048d:5702`, firmware 4.0.26.2). Fans: Ocypus Delta C70 case, 3-pin 5V ARGB, plugged into the board's **D_LED2** header.

## Symptom

In OpenRGB the fan only lit after the sequence *Wave → Direct → pick colour*. Static worked but reset as soon as OpenRGB closed. A newer OpenRGB build (git master, 1.1+) did not light the fan at all (CLI and GUI), and no longer offered Wave.

## Resolution (what actually works)

A ~200-line Python script (`gbrgb`, below) that talks to `/dev/hidrawN` with the exact packets Gigabyte Control Center sends. A hardware "Static" effect on **zone 6** (= D_LED2) lights the fan and **stays lit after the process exits**. A oneshot systemd unit re-applies the colour at boot and after sleep.

Root cause of the original behaviour: OpenRGB's attach/close handling resets the controller, so lighting only survives while OpenRGB is open. Nothing resets it when a plain tool just writes the effect and exits.

## Steps, in order

1. **Search first.** Nothing found for this exact symptom. Closest: [OpenRGB #343](https://gitlab.com/CalcProgrammer1/OpenRGB/-/issues/343) (X570, Direct ignored on a LED header, no fix listed).
2. **Read OpenRGB's driver** (`Controllers/GigabyteRGBFusion2USBController/`). Facts: 64-byte HID feature reports, report ID `0xCC`; zone effect = `CC <0x20+zone> <struct>`; apply = `CC 28 <mask>`; "keep lighting" = `CC 47 01`; flash save = `CC 5E 00`.
3. **Get Gigabyte's software.** The winget URL for RGB Fusion B24.1202.1 now 404s. Used the board's Support page (Utility tab) instead: *GIGABYTE Control Center Full Installation Package* 26.09.10.01 (it bundles the `rgbMotherboard` module). Downloaded by hand (the site 403s curl).
   ```bash
   mkdir pkg && unzip -q ~/Downloads/GCC_26.09.10.01.zip -d pkg          # one NSIS .exe inside
   mkdir x && cd x && 7z x -y ../pkg/*.exe                               # unpack, never run
   mkdir ../mb && cd ../mb && 7z x -y ../x/GBT_rgbMotherboard_UC_*.exe   # nested NSIS installer
   ```
   Files that matter: `RgbMotherboard.dll` (.NET, class `IT8297_5702`), `LedIoControl.dll`, `MB_RGB_Capability.dll`, `GBT_rgbMotherboard_UC.dll`.
4. **Decompile** the managed DLLs (no Ghidra needed). [REA](https://github.com/morluto/rea) (`rea inspect-managed-members`) only gives metadata/CIL; for C# source use ILSpy:
   ```bash
   sudo dnf install -y dotnet-sdk-9.0
   dotnet tool install --global ilspycmd --version 9.1.0.7988   # latest 11.x needs a newer SDK
   export PATH=$PATH:$HOME/.dotnet/tools
   ilspycmd -p -o src_rgbmb mb/RgbMotherboard.dll               # one .cs per type
   ```
5. **Findings in `MCU_8297.cs`:**
   - `SaveSetting()` = `CC 5E` is only used after colour calibration.
   - `SaveLedParameter(en)` = `CC 47 <en>`, sent by Gigabyte's app on suspend/close (1) and resume (0), **but only if the firmware advertises `support_cmd_flag & 1`**.
   - `SetDLedOutputCount` = `CC 34` (LED count tier: 0=32, 1=64, 2=256, 3=512, 4=1024), same as OpenRGB.
   - `TurnOff_DStrip` uses zones 5/6 (apply bits `0x20`/`0x40`) for D_LED1/D_LED2.
   - Effect packet = `CC <0x20+zone>` + `DataFormat_8297` (zone_sel0 u32, zone_sel1 u32, reserved, mode, max_brightness, min_brightness, color0 u32, color1 u32, 4x u16 timings, 4 params).
6. **Read the controller:** `CC 60 00` then GET_FEATURE. Reply bytes 4-7 = fw `4.0.26.2`, byte 11 = `support_cmd_flag` = **`0x00`**. So this firmware does *not* support `0x47`; OpenRGB's persistence code (and my own patch to it) never fires. "Saving Not Supported" in OpenRGB is consistent.
7. **Build the tool** (script below) and run a **zone sweep** (`gbrgb sweep`): lights each hardware zone 0-10 red in turn. The fan lit on **zone 6**.
8. **Persistence:** since the firmware can't keep state itself, re-apply from systemd (below).

## Dead ends (don't re-tread)

- **My patch to OpenRGB** (send `CC 47 01` in the controller destructor and after init, fork `txtsamu/OpenRGB`, branch `fix/gigabyte-fusion2-keep-lighting-on-exit`): useless on this board — support flag is 0, and `SupportsSetPersistentLighting()` guards it. Also OpenRGB master segfaults on exit here (Logitech Nano Receiver HID++ 2.0 watcher thread race), which kills the process before destructors run. Not pursued.
- **OpenRGB master removes Wave for this board on purpose**: the layout table (`GigabyteFusion2USB_Devices.cpp`, `B650M K` = `0x0820005F` / `0x0870005F`, effect mask `0x05F`) has no Wave bits. Old package (1.0rc2 git74cbdcc) listed every mode.
- **LED-count tier / `CC 34` mismatch**: ruled out; OpenRGB's mapping equals Gigabyte's and it seeds from the controller's own report.
- `strace` does not show HID feature-report bytes; use gdb or the tool's `-v` to see packets.

## Install

```bash
sudo install -m755 gbrgb.py /usr/local/bin/gbrgb          # script below
sudo gbrgb config 6 ff00ff                                 # zone 6 = D_LED2; name or RRGGBB
sudo tee /etc/systemd/system/gbrgb.service <<'E'
[Unit]
Description=Apply Gigabyte RGB Fusion 2 lighting (D_LED2 fan)
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/gbrgb apply

[Install]
WantedBy=multi-user.target
E
sudo tee /etc/systemd/system/gbrgb-resume.service <<'E'
[Unit]
Description=Re-apply Gigabyte RGB lighting after sleep
After=suspend.target hibernate.target hybrid-sleep.target suspend-then-hibernate.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/gbrgb apply

[Install]
WantedBy=suspend.target hibernate.target hybrid-sleep.target suspend-then-hibernate.target
E
sudo systemctl daemon-reload && sudo systemctl enable --now gbrgb.service && sudo systemctl enable gbrgb-resume.service
```

Change colour later: `sudo gbrgb config 6 ff8800 && sudo systemctl start gbrgb.service`.
Needs the OpenRGB udev rules (`openrgb --generate-udev-rules /etc/udev/rules.d/60-openrgb.rules`) to run unprivileged; the services run as root and don't need them.

**Caveats:** do not run OpenRGB at the same time (its attach resets the controller). Resume unit untested (can't suspend from the session). Only solid colour on one zone; the other zones and effects are not implemented. The other hardware zones' names in the script are guesses except 5/6.

## `gbrgb.py`

```python
#!/usr/bin/env python3
"""gbrgb - tiny Gigabyte RGB Fusion 2 (ITE IT5701/IT5702, USB 048d:5702) controller for Linux.

Packet layout taken from Gigabyte Control Center's RgbMotherboard module
(MCU_8297.cs) and cross-checked against OpenRGB's GigabyteRGBFusion2USBController.
Talks to /dev/hidrawN directly; needs the OpenRGB udev rules (uaccess) or root.
Stop OpenRGB before using it.
"""
import argparse
import fcntl
import glob
import json
import os
import struct
import sys
import time

REPORT_ID = 0xCC
VID, PID = 0x048D, 0x5702

EFFECT_STATIC = 1
ZONE_NAMES = {  # hardware zone index -> header (from Gigabyte's code: TurnOff_DStrip uses 5/6)
    0: "zone0 (I/O?)", 1: "zone1", 2: "zone2", 3: "zone3 (PCIe?)", 4: "zone4",
    5: "D_LED1?", 6: "D_LED2?", 7: "zone7", 8: "zone8", 9: "zone9", 10: "zone10",
}


def hidiocsfeature(n):
    return (3 << 30) | (n << 16) | (ord("H") << 8) | 0x06


def hidiocgfeature(n):
    return (3 << 30) | (n << 16) | (ord("H") << 8) | 0x07


def find_hidraw():
    for sys_dev in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            with open(os.path.join(sys_dev, "device", "uevent")) as f:
                text = f.read()
        except OSError:
            continue
        for line in text.splitlines():
            if line.startswith("HID_ID="):
                _, vid, pid = line.split("=")[1].split(":")
                if int(vid, 16) == VID and int(pid, 16) == PID:
                    return "/dev/" + os.path.basename(sys_dev)
    sys.exit("no 048d:5702 hidraw device found")


class Fusion2:
    def __init__(self, path=None, verbose=False):
        self.path = path or find_hidraw()
        self.fd = os.open(self.path, os.O_RDWR)
        self.verbose = verbose

    def send(self, *payload):
        data = bytes([REPORT_ID]) + bytes(payload)
        data += bytes(64 - len(data))
        if self.verbose:
            print("  >", data[:16].hex(" "))
        fcntl.ioctl(self.fd, hidiocsfeature(64), data)

    def info(self):
        self.send(0x60, 0x00)
        buf = bytearray(64)
        buf[0] = REPORT_ID
        fcntl.ioctl(self.fd, hidiocgfeature(64), buf)
        return bytes(buf)

    # -- commands (opcode names from MCU_8297.cs) ----------------------------------
    def apply(self, mask=0xFF, mask_hi=0x00):          # Apply(): CC 28 <mask>
        self.send(0x28, mask & 0xFF, mask_hi & 0xFF)

    def strip_ctrl(self, bits):                          # Enable_DLedStripCtrl(): CC 32 <bits>
        self.send(0x32, bits)

    def keep_lighting(self, enable):                     # SaveLedParameter(): CC 47 <0/1>
        self.send(0x47, 1 if enable else 0)

    def led_count(self, *tiers):                         # SetDLedOutputCount(): CC 34
        t = list(tiers) + [0] * (6 - len(tiers))
        self.send(0x34, (t[1] << 4) | t[0], (t[3] << 4) | t[2], (t[5] << 4) | t[4])

    def effect(self, zone, mode, rgb, brightness=100, p0=0, p1=0, p2=0, p3=0, params=(0, 0, 0, 0)):
        """write_to_mcu(): CC <0x20+zone | 0x90+zone-8> then DataFormat_8297."""
        hdr = 0x20 + zone if zone < 8 else 0x90 + (zone - 8)
        r, g, b = rgb
        color0 = (r << 16) | (g << 8) | b                # OpenRGB: RGBToBGRColor -> 0x00RRGGBB
        body = struct.pack("<IIBBBBIIHHHHBBBB",
                           1 << zone, 0, 0, mode, brightness, 0,
                           color0, 0, p0, p1, p2, p3, *params)
        self.send(hdr, *body)

    def reset(self):                                      # ResetController()
        for z in range(8):
            self.send(0x20 + z, 0, 0)
        self.apply(0xFF)

    def static(self, zone, rgb, brightness=100):
        self.effect(zone, EFFECT_STATIC, rgb, brightness)
        self.apply(1 << zone if zone < 8 else 0xFF, (1 << (zone - 8)) if zone >= 8 else 0)


def parse_color(s):
    s = s.lstrip("#")
    names = {"red": "ff0000", "green": "00ff00", "blue": "0000ff", "white": "ffffff",
             "purple": "ff00ff", "yellow": "ffff00", "cyan": "00ffff", "off": "000000"}
    s = names.get(s.lower(), s)
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def cmd_info(dev, a):
    raw = dev.info()
    print("hidraw        :", dev.path)
    print("raw reply     :", raw[:48].hex(" "))
    print("product       :", raw[12:40].split(b"\0")[0].decode(errors="replace"))
    print("fw version    : %d.%d.%d.%d" % tuple(raw[4:8]))
    print("strip counts  : argb01=0x%02x argb23=0x%02x argb45=0x%02x" % (raw[8], raw[9], raw[10]))
    print("support flags : 0x%02x  (bit0 = keep-lighting 0x47, bit1 = 0x48)" % raw[11])


def init(dev):
    dev.info()
    dev.reset()
    dev.send(0x31, 0)          # EnableBeat(false)
    dev.strip_ctrl(0)          # all built-in effects enabled on the D_LED headers
    dev.led_count(0, 0, 0, 0, 0, 0)


def cmd_sweep(dev, a):
    init(dev)
    print("Each zone lights RED for %ds. Tell me the zone number when your FAN turns red.\n" % a.seconds)
    for z in range(11):
        print("  >>> zone %-2d  (%s)" % (z, ZONE_NAMES.get(z, "")))
        dev.static(z, (255, 0, 0))
        time.sleep(a.seconds)
        dev.static(z, (0, 0, 0))
    print("\nsweep done")


def cmd_set(dev, a):
    init(dev)
    zones = range(11) if a.zone == "all" else [int(z) for z in a.zone.split(",")]
    for z in zones:
        dev.static(z, parse_color(a.color))
    keep = (not a.no_keep) and (dev.info()[11] & 1)
    if keep:
        dev.keep_lighting(True)
    print("set zone(s) %s -> %s (keep-lighting cmd %s)" % (list(zones), a.color, "sent" if keep else "not supported by firmware, skipped"))


CONFIG = "/etc/gbrgb.json"


def cmd_config(dev_unused, a):
    cfg = {"zones": {str(z): a.color for z in a.zones.split(",")}}
    with open(CONFIG, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    print("wrote", CONFIG, cfg)


def cmd_apply(dev, a):
    with open(a.config) as f:
        cfg = json.load(f)
    init(dev)
    for z, color in cfg["zones"].items():
        dev.static(int(z), parse_color(color))
    print("applied", cfg["zones"])


def open_with_retry(path=None, verbose=False, tries=30):
    for i in range(tries):
        try:
            return Fusion2(path, verbose)
        except (SystemExit, OSError):
            time.sleep(1)
    sys.exit("controller not available")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info").set_defaults(fn=cmd_info)
    s = sub.add_parser("sweep")
    s.add_argument("-s", "--seconds", type=float, default=4)
    s.set_defaults(fn=cmd_sweep)
    s = sub.add_parser("set")
    s.add_argument("zone", help="zone index, comma list, or 'all'")
    s.add_argument("color", help="name or RRGGBB")
    s.add_argument("--no-keep", action="store_true")
    s.set_defaults(fn=cmd_set)
    s = sub.add_parser("config", help="write %s (needs root)" % CONFIG)
    s.add_argument("zones", help="zone index or comma list, e.g. 6")
    s.add_argument("color")
    s.set_defaults(fn=cmd_config)
    s = sub.add_parser("apply", help="apply the saved config (used by the systemd units)")
    s.add_argument("--config", default=CONFIG)
    s.set_defaults(fn=cmd_apply)
    a = p.parse_args()
    dev = None if a.cmd == "config" else open_with_retry(verbose=a.verbose)
    a.fn(dev, a)


if __name__ == "__main__":
    main()
```

## References

- [OpenRGB issue #343 — Gigabyte X570, Direct ignored on LED header](https://gitlab.com/CalcProgrammer1/OpenRGB/-/issues/343)
- [OpenRGB Gigabyte RGB Fusion 2 USB driver source](https://gitlab.com/CalcProgrammer1/OpenRGB/-/tree/master/Controllers/GigabyteRGBFusion2USBController)
- [OpenRGB udev rules doc](https://gitlab.com/CalcProgrammer1/OpenRGB/-/blob/master/Documentation/UdevRules.md)
- [REA (Reverse Engineer Anything)](https://github.com/morluto/rea)
- [ILSpy / ilspycmd](https://www.nuget.org/packages/ilspycmd)
- [Ocypus fan FAQ (ARGB 3-pin, motherboard software control)](https://www.ocypus.com/faq/fan)
- [Ocypus Delta C70 ARGB specification](https://www.ocypus.com/specification/case/delta-c70-argb--0.html)
- [GIGABYTE B650M K support page (Utility downloads)](https://www.gigabyte.com/Motherboard/B650M-K-rev-11/support)
