---
type: investigation
tags: [android, xiaomi, redmi, miui, magisk, root, swap, zram, lmkd, selene, mediatek, adb]
created: 2026-10-23
last_verified: 2026-10-23
status: current
---

# Redmi 10 (selene, MIUI 12.5): Magisk root state, swap/zram status, installed modules

Read-only inspection, nothing was changed. Device and debloat context:
`redmi-10-miui125-adb-debloat-telemetry-ads.md`.

## 1. Root works over ADB

```bash
adb shell su -c id          # uid=0(root) context=u:r:magisk:s0
adb shell su -c 'magisk -v' # 30.7:MAGISK:R   (code 30700)
```

- `su` is `/product/bin/su -> magisk`. Bootloader unlocked (`ro.boot.verifiedbootstate=orange`,
  `ro.boot.flash.locked=0`), SELinux `Enforcing`. Magisk app `com.topjohnwu.magisk` plus MMRL (`com.dergoogler.mmrl.wx`).
- The adb shell is granted root silently (no prompt), so Magisk's Superuser policy already allows `shell`.

**Gotcha: multi-line `adb shell su -c '...'` loses its quoting.** adb flattens the arguments, so `su -c` got no
argument ("option requires an argument -- c") and every following line ran as the unprivileged shell
(`Permission denied` on `/proc/swaps`, `/sys/block/zram0/*`, `/data/adb/modules`). Feed a script on stdin instead:

```bash
adb shell su < probe.sh 2>&1 | tr -d '\r'
```

## 2. Swap: already enabled (zram)

```
/proc/swaps:  /dev/block/zram0  partition  2306044 kB  used 925684 kB  prio -2
MemTotal 3810824 kB, MemAvailable ~1.5 GB, SwapTotal 2306044 kB, SwapFree ~1.38 GB
```

| Item | Value |
|---|---|
| Type | zram, `disksize=2361393152` (~2.2 GB, about 60% of RAM) |
| Algorithm | `lz4` (options `lzo [lz4] deflate`), `max_comp_streams=8` |
| Boot config | `/vendor/etc/fstab.enableswap`: `/dev/block/zram0 none swap defaults zramsize=55%` |
| Writeback | `backing_dev=/dev/block/loop27`; MIUI Extended Memory (`persist.miui.extm.enable=1`, `persist.miui.extm.bdsize=1024`, ~1 GB). It is a writeback target for zram, not a separate swap entry |
| `vm.swappiness` | 100 (also `sys.mem.swappiness_on_start/launcher=100`) |
| `vm.vfs_cache_pressure` | 120, `min_free_kbytes=7236`, `extra_free_kbytes=30375`, `page-cluster=0` |
| lmkd | running, `use_minfree_levels=true`, `swap_free_low_percentage=10`, `thrashing_limit=10`, minfree `18432:0 ... 161280:950` |
| Kernel | `4.14.186-perf`, `CONFIG_SWAP=y`, `CONFIG_ZRAM=y`; no `/proc/config.gz` entry for ZSWAP/KSM seen |

Only ~0.9 GB of the 2.2 GB zram is used and about 1.5 GB of RAM is still available, so the device is not
currently starved.

## 3. Magisk modules (`/data/adb/modules`)

| Module | Version | Notes |
|---|---|---|
| `LowRAMFlagJos` (LowRAM-Flag Plus) | v4.1 | Activates Android Go mode (low-RAM flag) |
| `NLSound` | v4.5 | Audio quality tweaks |
| `encore` (Encore Tweaks) | 5.2.1 | Has a **`remove` flag**: it is scheduled for deletion at the next reboot |
| `magisk-swapspace` | v2.4 | Persistent swap file via `magiskswap`. **Not active**: no swap file exists under `/data`, and `/proc/swaps` shows only zram. Its `service.sh` only runs `swapon` if `ENABLE-SWAP=true` |

`ls /data/adb/modules` as the unprivileged shell returned nothing, which first suggested "no modules". It
was just a permission denial.

## 4. What root enables (candidate follow-ups, not done)

- Systemless debloat: Magisk module that removes system APKs, or `pm disable` for packages that refuse `pm uninstall`.
- Tune zram: `echo <bytes> > /sys/block/zram0/disksize` (needs `swapoff`, `reset`, `mkswap`, `swapon`), or tweak
  `vm.swappiness` / `vfs_cache_pressure` via `sysctl`/`echo` and persist with a `service.d` script.
- Persistent swap file via the already-installed `magisk-swapspace` (flash-backed, slower than zram; f2fs swap
  file support on a 4.14 kernel should be tested, not assumed).
- Hosts-based ad blocking (systemless hosts), firewall rules (`iptables` exists; `CONFIG_NETFILTER_XT_TARGET_TPROXY`
  and `IP_NF_TARGET_REDIRECT` are `=y`, `CONFIG_TUN=y`), per-app network blocking.
- Back up app data, read `/data/data/*`, edit `/data/adb/service.d` boot scripts, flash/patch boot image via Magisk.
- Set and read protected settings: confirm the meaning of `global/personalized_ad_enabled` and
  `secure/upload_log_pref` by flipping the UI toggle and diffing `settings list global/secure`.

## 5. Performance / RAM audit (read-only, 2026-10-23)

`dumpsys meminfo`: Total 3.81 GB, free+cached ~2.16 GB, used PSS 2.56 GB, ZRAM 296 MB physical for 1.1 GB swapped.
`/proc/pressure/memory` was ~0 (avg10/avg60 `0.00`): **no memory stall, the phone is not RAM-starved**.

| Finding | Detail | Action candidate |
|---|---|---|
| Load average ~26 is a false alarm | `ps -A -o PID,STAT,NAME` shows ~25 permanent `D`-state MediaTek kernel threads (`wdtk-*`, `ccci_*`, `charger_thread`, `gauge_*`, `hang_detect`...). They count toward loadavg but use no CPU; `procs_blocked 0`, idle CPU ~700% | None |
| `logd` uses ~124 MB PSS | `persist.logd.size=50M`; `logcat -g`: main buffer 50 MiB (49 consumed), kernel 50 MiB | `logcat -b all -G 256K` now, `setprop persist.logd.size 256K` to persist; saves ~100 MB. Costs debug-log history only |
| Root-manager processes | `com.dergoogler.mmrl.wx:root:0` x3 (~58 MB RSS each) + `com.topjohnwu.magisk:root:0` (~134 MB RSS) | Close MMRL/Magisk apps when not in use |
| Orphans of removed packages | `com.miui.daemon` (18 MB) still running after `pm uninstall --user 0` | Reboot clears them; also applies the pending `encore` module removal |
| Optional Xiaomi services still resident | `mi_connect_service` 22 MB, `milink.service` 19 MB, `xmsf` 11 MB, `miwallpaper` 32 MB, `securitycenter.remote` 31 MB | Remove Mi Connect/MiLink if casting is unused |
| Google app | `googlequicksearchbox` x3 procs ~230 MB (`:googleapp`, `:search`, `:interactor`) | Disabling loses Assistant, Discover, search widget, Lens |
| Two launchers resident | `bitpit.launcher` 87 MB + `com.miui.home` 69 MB | Keep `com.miui.home`: MIUI recents/gestures depend on it |
| Big user apps | Quetta browser (4 processes, ~400 MB), Play Store (2 procs, ~160 MB), GMS 125 MB | User choice |
| Animations | `window/transition_animation_scale=1.0`, `animator_duration_scale=null` | `settings put global window_animation_scale 0.5` (and the other two): feels faster, fully reversible |
| Governor / IO | `schedutil`; eMMC scheduler `cfq`, `read_ahead_kb=128` | Leave; gains would be marginal |
| Dex state | `dumpsys package dexopt` output was not conclusive | `cmd package compile -m speed-profile -a` is safe, takes a while |

Left alone on purpose: `swappiness=100` (PSI shows no thrash), `lmkd`/minfree values, `com.miui.home`, `com.miui.securitycenter`,
`com.miui.powerkeeper`, `com.huaqin.sarcontroller` (SAR/regulatory), `com.lbe.security.miui` (permission manager).

## 6. Commands used

```bash
adb shell su -c 'id; magisk -v; getenforce'
adb shell su < probe.sh          # /proc/swaps, zram0 sysfs, vm sysctls, props, init rc grep, /data/adb/modules
adb shell su < probe2.sh         # per-module module.prop + disable/remove flags, magisk-swapspace scripts
```
