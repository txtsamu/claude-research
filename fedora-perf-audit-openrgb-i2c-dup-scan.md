---
type: troubleshooting
tags: [fedora, performance, use-method, sysstat, openrgb, i2c, cosmic-de]
created: 2026-07-26
last_verified: 2026-07-26
status: current
---

# Fedora desktop: performance audit + OpenRGB duplicate-scan i2c warning fix

## Why

User (on the Fedora/COSMIC desktop box, 32-core / 61GB RAM / dual AMD GPU) asked for a system audit to find what might be making it slow or bottlenecked, and asked to research the current best-practice method first rather than just guessing at tools.

## Step 1: Research current methodology

Searched for the latest (2026) guidance before touching the system. Landed on Brendan Gregg's **USE method** as the still-current standard: for every resource (CPU, memory, disk, network, GPU), check three things —

- **U**tilization — % time busy
- **S**aturation — extra work queued waiting
- **E**rrors — error events

Pair it with `vmstat`/`mpstat`/`iostat` for CPU/disk, `free` for memory, `btop`/`top` for a live view, and `dmesg`/`journalctl` for errors. Sources: [oneuptime.com USE method guide](https://oneuptime.com/blog/post/2026-03-02-how-to-profile-system-bottlenecks-with-use-method-on-ubuntu/view), [betterstack.com Linux monitoring tools 2026](https://betterstack.com/community/comparisons/linux-monitoring-tools/).

## Step 2: Run the audit

Checked each resource in turn (system was ~4 minutes post-boot at audit time):

| Resource | Command(s) | Result |
|---|---|---|
| CPU | `uptime`, `vmstat 1 3`, `nproc` | 96-98% idle, governor = `performance`, no throttling |
| Memory | `free -h` | 6.3GB/61GB used, 0 swap used, 12GB cache |
| Disk | `df -h`, `nvme smart-log` | 26% used on root NVMe, SMART clean (0 media errors), 149 lifetime unsafe shutdowns (noted, not urgent) |
| GPU | `rocm-smi` | Both GPUs 0% util; GPU0 holding 73% VRAM at rest (see `llama-server` note below) |
| Processes | `ps -eo pid,ppid,%cpu,%mem,comm --sort=-%cpu/-%mem` | Nothing runaway; `llama-server` (background LLM server) using ~4GB RAM + most of GPU0's VRAM even idle |
| systemd | `systemctl list-units --failed` | 0 failed units |
| Kernel/journal | `dmesg`, `journalctl -p 3 -b` | No real errors; only cosmetic COSMIC `Failed to create watcher` config-missing noise, and a recurring `i2c adapter quirk: msg too long` warning (investigated below) |

**Conclusion at this point:** system was not actually bottlenecked — it was idle/healthy. The two things worth chasing were (a) no `sysstat` installed, so disk/per-core saturation couldn't be measured directly, and (b) the i2c kernel log spam.

## Step 3: Install sysstat

```bash
sudo dnf install -y sysstat
```

Installs `iostat`, `mpstat`, `sar`. The package's `%post` scriptlet auto-enabled `sysstat.service` (+ `sysstat-collect.timer`, `sysstat-summary.timer`, `sysstat-rotate.timer`), so historical CPU/disk stats now get collected automatically going forward — useful for catching an intermittent slowdown after the fact via `sar` instead of only live.

## Step 4: Investigate the OpenRGB i2c warning

Kernel log showed repeated:
```
kernel: i2c i2c-2: adapter quirk: msg too long (addr 0x0050, size 128, read)
kernel: i2c i2c-3: adapter quirk: msg too long (addr 0x0050, size 128, read)
```

`0x0050` is the standard I2C address range for RAM SPD/RGB EEPROMs. Checked the user's OpenRGB config (`/etc/openrgb/OpenRGB.json`) and confirmed Corsair Dominator RAM RGB is configured (`CorsairDominatorSettings`), so this wasn't spurious — OpenRGB is legitimately trying to talk to the RAM's RGB controller.

**Root cause found:** two separate OpenRGB processes were running and *both* independently scanning i2c hardware at login:

```bash
systemctl list-units --all | grep -i openrgb
# openrgb-server.service        — system-wide, root, `--server` (SDK server on 0.0.0.0:6742)
# app-OpenRGB@autostart.service — per-user GUI, from ~/.config/autostart/OpenRGB.desktop
```

The GUI autostart entry (`Exec=/usr/bin/openrgb --startminimized`) does its own local hardware detection by default — it wasn't just a tray-icon client of the already-running server. Two processes independently issuing the same oversized (128-byte) SMBus block read against the RAM's SPD EEPROM is why the `i2c-piix4` driver's quirk warning logged twice per boot.

Checked whether this was ongoing spam or just a boot-time blip:
```bash
journalctl -k --since "5 minutes ago" | grep -ic i2c
# 0
```
Confirmed it only fires during the ~10s post-login detection burst, not continuously — so this was redundant duplicate work + log noise at boot, not an ongoing background drain.

## Step 5: Fix — make the GUI a client instead of a second scanner

Edited `~/.config/autostart/OpenRGB.desktop`:

```diff
-Exec=/usr/bin/openrgb --startminimized
+Exec=/usr/bin/openrgb --startminimized --nodetect --client 127.0.0.1:6742
```

`--nodetect` skips local hardware detection; `--client 127.0.0.1:6742` connects to the already-running `openrgb-server.service` and pulls its already-detected device list instead. This keeps both the headless SDK server (for any external OpenRGB SDK clients) and the tray icon, but only one process now touches the i2c bus at boot.

Applied and verified:
```bash
systemctl --user daemon-reload
systemctl --user restart app-OpenRGB@autostart.service
journalctl --user -u app-OpenRGB@autostart.service --since "1 minute ago"
# Connected to server / Received controller count from server: 1 / All controllers received
journalctl -k --since "1 minute ago" | grep -i i2c
# (empty — no new warnings)
```

## Outcome

- System was healthy/idle throughout — no real bottleneck existed at audit time.
- `sysstat` now installed and collecting, so a future slowdown can be diagnosed with `iostat -xz 1`, `mpstat -P ALL 1`, or historical `sar` data instead of starting from zero.
- OpenRGB no longer double-scans i2c hardware at login; tray icon still works (now as an SDK client), kernel log noise roughly halved.
- Noted but not actioned: `llama-server` runs persistently in the background and holds most of GPU0's VRAM even at idle — flagged to the user as the first thing to check if GPU/VRAM pressure ever shows up with other workloads.

## If revisiting later

- If the i2c warning still appears *after* this fix, it's coming solely from `openrgb-server.service`'s own detection and is a benign upstream limitation (the `i2c-piix4` SMBus controller rejects the >32-byte block read OpenRGB's SPD reader requests) — not fixable short of patching OpenRGB or the kernel driver. Don't re-chase it as if it were new.
- `openrgb-server.service` binds `0.0.0.0:6742` (all interfaces) rather than localhost-only. Not touched in this pass since it wasn't the reported problem, but worth tightening to `127.0.0.1` if external SDK clients aren't actually needed — flag to user before changing.
