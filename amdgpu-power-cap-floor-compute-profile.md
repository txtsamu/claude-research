---
type: how-to
tags: [rocm, rocm-smi, amdgpu, gpu, power, gfx1101, fedora]
created: 2026-09-18
last_verified: 2026-09-21
status: current
---

# AMD GPU power cap has a hardware-enforced floor — tuning power/perf via rocm-smi

While tuning the RX 7800 XT (`gfx1101`) on `fedora` for sustained LLM-inference load, tried to cap power to 150W and set performance to high. The power cap request was rejected — documenting why, and the actual tunable options this card exposes.

## Power cap floor is hardware, not a permission issue

```
$ sudo rocm-smi -d 0 --setpoweroverdrive 150
ERROR: GPU[0]: Unable to set Power OverDrive
ERROR: GPU[0]: Value cannot be less than: 205W
```

Confirmed via the raw hwmon interface, not just the rocm-smi wrapper:

```
$ cat /sys/class/drm/card1/device/hwmon/hwmon2/power1_cap_min
205000000
$ cat /sys/class/drm/card1/device/hwmon/hwmon2/power1_cap_max
244000000
$ cat /sys/class/drm/card1/device/hwmon/hwmon2/power1_cap_default
228000000
```

This card's power table enforces **205W–244W** regardless of interface used (`rocm-smi` or raw sysfs) — 150W simply isn't achievable on this board, full stop. Not a driver/tool limitation to work around.

## Performance level

```
$ sudo rocm-smi -d 0 --setperflevel high
GPU[0]: Performance level set to high
```

This succeeded independently of the power-cap rejection.

## Power profile mode (COMPUTE)

RouterOS-style profile modes exist under `pp_power_profile_mode`: `BOOTUP_DEFAULT`, `3D_FULL_SCREEN`, `POWER_SAVING`, `VIDEO`, `VR`, `COMPUTE`, `CUSTOM`, `WINDOW_3D`. `COMPUTE` is the one tuned for sustained compute workloads (vs. gaming/video-tuned profiles that optimize for burst/frame-latency patterns instead).

```
$ sudo rocm-smi -d 0 --setprofile COMPUTE
GPU[0]: Successfully set profile to: COMPUTE
```

**Side effect:** this silently flips `power_dpm_force_performance_level` from `high` back to `manual` — applying a custom profile mode requires manual perf-level to take effect. Confirmed clocks were still boosting normally afterward (not stuck at idle):

```
$ rocm-smi --showclocks -d 0
GPU[0]: sclk clock level: 1: (1596Mhz)
```

vs. the idle/default clock this card sits at otherwise (~438MHz), so `manual` + `COMPUTE` was still actively scaling up under load, not pinned low.

## Summary of tunables on this card (`gfx1101`)

- **Performance level** (`power_dpm_force_performance_level`): `auto` | `low` | `high` | `manual` | `profile_standard` | `profile_min_sclk` | `profile_min_mclk` | `profile_peak`
- **Power profile mode** (`pp_power_profile_mode`, active under `auto`/`manual`): `BOOTUP_DEFAULT`, `3D_FULL_SCREEN`, `POWER_SAVING`, `VIDEO`, `VR`, `COMPUTE`, `CUSTOM`, `WINDOW_3D`
- **Power cap**: 205W–244W range, 228W default, set via `rocm-smi --setpoweroverdrive WATTS` or raw `power1_cap` sysfs (same floor either way)
- **Manual clock states available**: sclk 500/1883/2213 MHz; mclk 96/456/772/1218 MHz
