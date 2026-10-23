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

## 5. Commands used

```bash
adb shell su -c 'id; magisk -v; getenforce'
adb shell su < probe.sh          # /proc/swaps, zram0 sysfs, vm sysctls, props, init rc grep, /data/adb/modules
adb shell su < probe2.sh         # per-module module.prop + disable/remove flags, magisk-swapspace scripts
```
