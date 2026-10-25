---
type: troubleshooting
tags: [samsung, tizen, kants2, uep, debloat, cold-boot, persistence, sdb, t6500]
created: 2026-10-24
last_verified: 2026-10-25
status: current
---

# What actually survives a cold boot on the T6500 (debloat + root)

> **Path relocated (2026-10-25):** `~/samsung-tv-root-src` → `~/archive/samsung-tv-t6500-2026-10/tooling/samsung-tv-root-src`.

The question this answers: the TV was unplugged from the wall and powered back on —
which parts of the debloat and root work are still in place? Short version: the two
things stored as **files on rw `/opt`** are; everything that lives in the kernel or in
per-user runtime state is gone and has to be re-applied.

Target: `UA43T6500AKXXD`, Tizen 5.5, KantS2 / NT72172, kernel 4.1.10.
Companion docs: [samsung-tv-uep-bypass-and-kants2-root.md](samsung-tv-uep-bypass-and-kants2-root.md)
(root chain + debloat passes), [samsung-tv-clean-launcher-curation.md](samsung-tv-clean-launcher-curation.md)
(the launcher-side `HIDE_IDS` list).

## Measured matrix

Verified 2026-10-24, `/proc/uptime` = 203 s after the unplug/replug. Check uptime first —
otherwise the "did it survive" verdict describes the previous boot, not this one.

| Layer | Store | Survives? | How to check |
|---|---|---|---|
| Launcher curation (`HIDE_IDS`) | `/opt/usr/apps/tvunlock02/res/wgt/main.js` | **yes** | `sed -n '/var HIDE_IDS = \[/,/^  \];/p' <js> \| grep -c '"'` → `39` |
| `ConditionPathExists=!` unit markers | `/opt/usr/share/systemd/system/{pisa-service,canalysis-daemon}` | **yes** | `systemctl show <unit> -p ConditionResult` → `ConditionResult=no` (not just `is-active`) |
| `pkgcmd -D --uid 5001` deactivations | per-user DB `/opt/dbspace/user/5001/{.appsvc.db,.component.db}` | **no** | those files come back with mtime `1970-01-01`; deactivated packages launch again |
| `systemctl stop` / `mask --runtime` | systemd runtime | **no** | running services `104 → 115`; 11 units return |
| `/etc/hosts` bind-mount sinkhole | mount namespace | **no** | `grep -c ' /etc/hosts ' /proc/mounts` → `0`, file back to 148 bytes |
| UEP state word + cred patch | kernel DRAM | **no** | `/opt/hermes_root -p -c 'id -u'` → `Operation not permitted` |

Boot-time symptoms seen at 203 s: `media-analytics-service` (pid 1484),
`contents-recognition-service` (1537), `vision-data-recognition-service` (1429) and
`voice-app` (1330) all running again, `115` services total.

## Re-apply sequence (verified end to end)

```sh
# 1. flip UEP off + root, from the sdb shell (uid=901) - payload in sdk_toolpath
AUL_APPID=samudntest01.Mali AUL_ROOT_PATH=/home/owner/share/tmp/sdk_tools/mali \
  /usr/bin/dotnet-launcher --standalone /home/owner/share/tmp/sdk_tools/mali/FastRoot.dll
# -> uid=0(root) CapEff ffffffffffffffff context="System"

# 2. debloat runtime layer as DATA (UEP re-arms mid-session for file exec)
/opt/hermes_root -p -c 'sh -c "$(cat /opt/hermes/debloat2.sh)"'
# -> 16 units stopped+masked, 13 ad/ACR/analytics packages pkgcmd -D'd, running=105

# 3. launcher curation: nothing to do - HIDE_IDS is already persistent
```

Result after the run: running services `115 → 104` (exact pre-reboot number), zero live
telemetry processes, `HIDE_IDS` still `39`, ICMP 0 % loss, `:8001/api/v2/` `"PowerState":"on"`.

The hosts sinkhole was deliberately **not** re-applied — see below.

## Traps learned in this pass

- **Do not write the sinkhole into `/etc/hosts` directly.** The launcher-curation doc
  proposed that as the fix for the SMACK denial spam ("a plain 452-byte `-rw-rw-rw-`
  file on the writable `/opt` mapping"). On this build it is `-rw-r--r-- root root`,
  148 bytes, and `Read-only file system` (`EROFS`) even from `uid=0` with
  `CapEff ffffffffffffffff`. A redirect silently achieves nothing; the script reported
  `sinkhole_lines=0 bytes=148`. Only `mount --bind` reaches the file.
- **Check whether the sinkhole is needed at all before re-creating it.** The LAN resolver
  already blocks the ad/telemetry domains — `nslookup` from the TV answers `0.0.0.0` for
  `samsungads.com`, `samsungacr.com`, `smetrics.samsung.com` and no address for
  `log.samsung.com` / `analytics.samsung.com`. Skipping the bind mount also avoids the
  `com.samsung.tv.csfs` SMACK-denial spam that made Home feel laggy.
- **`app_launcher -s <appid>` starts the app; it is not a status query.** Using it as a
  "did the deactivation survive" probe opens the app on the panel. `app_launcher -k/-t`
  from the `uid=901` shell answers `Failed to get filter count` (as `uid=0` it works and
  reports `App isn't running`). `app_launcher -l` is per-user and lists 5 entries for
  uid 901, so it cannot answer for uid 5001. `package_app_info_for_uid` in
  `.pkgmgr_parser.db` stays at 0 rows either way — activation state is not readable there.
- **UEP re-armed inside the same session.** Minutes after the flip, `sh /opt/hermes/debloat2.sh`
  printed `[uep][bash] the file is NOT signed!!` while `/opt/hermes_root -p -c '…'` still
  executed. Always invoke scripts as data: `hermes_root -p -c 'sh -c "$(cat …)"'`.
- **`FastRoot`'s SUID fast path misfires and costs 57 s.** Its probe string is
  `[0 | uid=901(sdk) |]`, so `probe.Trim().StartsWith("0")` is false and the payload falls
  through to the full DRAM cred scan (`patched=80`, `FASTROOT_END total=57958ms`) instead of
  the intended ~350 ms path. Same end state, purely a speed bug — fix the check to skip the
  leading `[`.
- **`sdb shell "…"` returns `closed`** on this TV; every command has to go through the
  retry-wrapped `SdbClient.capture()` on the control host (`moo@fedora`,
  `~/samsung-tv-root-src/.venv/bin/python`, `sys.path.insert(0, "/home/moo/samsung-tv-root-src/src")`).
  The TV→host log path needs `192.168.50.31` in firewalld's trusted zone (it is).

## Consequence for expectations — superseded 2026-10-25

This matrix is what a cold boot still looks like **by hand**, but it no longer happens by
hand. A same-size raw-block patch of `/etc/profile.d/bash_prompt_custom.sh` on
`/dev/mmcblk0p18` makes `tizen-system-env.service` (which sources `/etc/profile.d/*.sh` as
root) run `/opt/hermes/boot.sh` at **uptime 1 s**: the unit markers are rewritten, the 13
`pkgcmd -D` deactivations are re-applied, and the `/run/systemd/system` masks are re-created
by two delayed stop passes, all with no computer attached. Verified on a real cold boot —
running services came back at 103 instead of 115, `/run/systemd/system` held 18 masks again,
the launcher stayed functional, and the only failed unit was the vendor `vdca-update.service`.

Anything not covered by the hook (UEP state, interactive root, `/etc/hosts` bind mount) still
needs the manual path described above. See
[samsung-tv-t6500-persistent-root-boot-hook.md](samsung-tv-t6500-persistent-root-boot-hook.md).
