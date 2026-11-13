---
type: troubleshooting
tags: [fedora, systemd, uresourced, cgroup, cpuweight, temperature, t3code, cosmic, ryzen-7950x]
created: 2026-11-14
last_verified: 2026-11-14
status: current
---

# Fedora: uresourced pegged a core with a SetUnitProperties loop, lifting CPU temps 16 to 20 C

Host: `fedora` (COSMIC desktop), kernel 7.2.15-100.fc43.x86_64, systemd 258.11-1.fc43, uresourced 0.5.4-4.fc43, AMD Ryzen 9 7950X. Not a git repo change: this was a fix on the live machine.

## Request

"check why my pc temp is quite high". Idle-ish system reporting `Tctl 66.6 C`, `Tccd1 67.8 C` with a load average of about 1.1 on a 32-thread CPU.

## Root cause

`systemd --user` (PID 1800) was running at about 91% of one core and had accumulated 38h33m of CPU time over 8d22h of uptime. Not a normal daemon cost.

`dbus-monitor --session` showed one client, bus name `:1.7`, calling `org.freedesktop.systemd1.Manager.SetUnitProperties` roughly 1200 times per second:

```
method call sender=:1.7 -> destination=:1.1 path=/org/freedesktop/systemd1
  member=SetUnitProperties
   string "t3code.service"
   boolean true
   struct { string "CPUWeight" variant uint64 100 }
   struct { string "IOWeight" variant uint64 100 }
```

`busctl --user status :1.7` resolved that peer to PID 2938, `uresourced` (Fedora's "User resource assignment daemon", pulled in by `graphical-session.target`).

`t3code.service` declares `CPUWeight=1000` and `IOWeight=1000` in its own unit file. uresourced kept asserting 100. Every assertion made systemd rewrite two runtime drop-ins under `/run/user/1000/systemd/user.control/t3code.service.d/`, reload the unit and re-apply cgroup attributes. That write in turn triggered uresourced again, so the loop never settled. `strace -c -p 1800` over 5 s showed 397k syscalls, including 565 `mkdir` + 565 `setxattr` + 1695 `removexattr` + 1131 `renameat`, i.e. about 113 drop-in rewrites per second.

The daemon had no journal output at all (`journalctl --user -u uresourced` was empty), so nothing announced the loop.

## Fix applied

Masking the daemon, not editing the service. Removing the weights from `t3code.service` looked like a fix at first, but the loop came straight back on the next `daemon-reload`. uresourced is the faulty party.

```bash
systemctl --user mask uresourced.service
systemctl --user stop uresourced.service
systemctl --user revert t3code.service
```

`revert` was needed because the stale `50-CPUWeight.conf` / `50-IOWeight.conf` runtime drop-ins in `/run/user/1000/systemd/user.control/` outranked the unit file and kept `CPUWeight` at 100. After the revert, `t3code.service` reports `CPUWeight=1000`, `IOWeight=1000` again, as its unit file intends.

`t3code.service` now carries a comment above the weight lines recording why `uresourced.service` is masked, so a future "cleanup" does not unmask it.

## Verification

CPU cost of `systemd --user`, measured as utime+stime ticks from `/proc/1800/stat`, 100 ticks = 1 s CPU:

```
systemd CPU ticks in 5s before stop: 453
systemd CPU ticks in 5s after stop: 0
```

Temperatures, `sensors`, before and after:

| Sensor | Before | After |
| --- | --- | --- |
| Tctl | 66.6 C | 50.4 C |
| Tccd1 | 67.8 C | 53.1 C (43 to 53 range while settling) |
| Tccd2 | 44.4 C | 39.8 C |

Load average fell from 1.12 to 0.78 to 0.90. `t3code.service` stayed `active` throughout, no restart, `NRestarts=0`. Verified stable across three consecutive 4 to 6 second windows and across two `daemon-reload` runs: 0 ticks each time.

## Gotchas

- 66 C is not dangerous on a 7950X. Zen 4 has a 95 C Tjmax and boosts until it hits it, so the number alone was never the problem. The problem was ~0.9 core of pure waste, plus the extra heat and fan noise it caused. Idle on this chip with the `performance` governor is expected to sit in the low 50s.
- Do not trust `systemctl set-property` drop-ins when auditing a unit. Anything under `/run/user/$UID/systemd/user.control/<unit>.d/` silently overrides the unit file, and only `systemctl revert` clears it.
- The `daemon-reload` trap: my first attempt removed `CPUWeight`/`IOWeight` from the unit and looked successful for one idle window. It was not. Always re-test after a reload before declaring a systemd loop fixed.
- Secondary heat contributors left alone on purpose: `scaling_governor` is `performance` for all 32 threads (cores park at 5.4 GHz, several at 3.0 GHz), and `vesktop`, an `Isolate+` process and `opencode` each idle around 9% of a core. Neither is a fault.
- `gigabyte_wmi` reports `temp4: -55.0 C`, which is a bogus ACPI sensor, not an alarm. The board exposes no fan tachometers at all, so `sensors` cannot show case or CPU fan RPM here.
- The GPU is unrelated and cool: `amdgpu-pci-0300` edge 35 C at 7 W, `amdgpu-pci-1500` edge 47 C at 62 W.

## Not verified

- Whether the loop was specific to `t3code.service` or would have hit any other unit declaring `CPUWeight`. Only `t3code.service` had runtime weight drop-ins on this host, so I could not reproduce the trigger elsewhere.
- Whether uresourced 0.5.4-4.fc43 loops for a different reason upstream (no bug report consulted). Masking treats the symptom on this machine, not the package bug.
- Longer-term effect of running without uresourced on foreground responsiveness under heavy all-core load. On 32 threads the practical loss should be negligible, but it was not benchmarked.

## Related

- [[llama-server-qwen9b-crash-loop-cpu-heat]]
- [[gigabyte-b650m-k-argb-fan-no-light-openrgb-gbrgb]]
- [[homelab-system-namespace-resource-audit]]
- [[amdgpu-power-cap-floor-compute-profile]]
