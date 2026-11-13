---
type: troubleshooting
tags: [samsung, tizen, t6500, netflix, pkgcmd, debloat, incident, sdb, uep, app-store]
created: 2026-11-13
last_verified: 2026-11-13
status: current
---

# Uninstalling Netflix on the T6500: how a deactivation became an outage, and what fixed it

Target: Samsung `UA43T6500AKXXD` (`20_KANTS2_FHD`, Tizen 5.5), `192.168.50.31`.
Host: fedora, `192.168.50.20`. Repo `~/claude-research`, branch `master`, commit `2ee000d` at start.

Requested: "help me uninstall netflix from my tv". Outcome: Netflix was deactivated, could
**not** be reactivated with `pkgcmd -A`, the Samsung store reinstall failed with
*"Unable to install. Please try again later."*, and the set was only restored by the user
doing a recovery on the TV itself. It works again now.

## 1. What Netflix actually is on this set

```
$ pkgcmd -l | grep -i netflix
system apps  pkg_type [tpk] pkgid [org.tizen.netflix-app] name [Netflix] version [5.2.59020] storage [internal]

$ sdb shell 0 applist | grep -i netflix
    'Netflix'   'org.tizen.netflix-app'
```

Package ID equals app ID: `org.tizen.netflix-app`. The package-manager DB also reports
`app_root_path = /opt/usr/apps/org.tizen.netflix-app`, and `installed_internal`, even though
`pkgcmd -l` labels it a **system app**. Preinstalled, so the Apps-menu Delete is greyed out and
Samsung offers **Reinstall** instead.

## 2. The mistake

The deactivation was run over the sdk sdb channel (`uid 901`), not as root:

```
$ tvcap.py 'pkgcmd -D -t app -n org.tizen.netflix-app --uid 5001'
__app_return_cb req_id[1] pkg_type[app] pkgid[org.tizen.netflix-app] appid[org.tizen.netflix-app] key[end] val[ok]
spend time for pkgcmd is [217]ms
rc=0
```

It returned success and Netflix stopped launching. Two things were wrong with the plan around it:

1. **`-D` is allowed for the sdk user, but `-A` is not.** Every activation attempt failed, with
   or without root:

   ```
   as uid 901:  Undefined error(-1)processing result : Undefined Error [-999] failed
   as uid 0:    Failed to get appinfo[org.tizen.netflix-app]
                Undefined error(-1)processing result : Undefined Error [-999] failed
   -t tpk:      processing result : General error [-1] failed
   ```

2. **`pkgcmd -s` fails for every package from the sdk channel**, so the usual state probe was
   useless. The DB showed `app_disable=false` in `.pkgmgr_parser.db` `package_app_info`, and
   **no row at all** for Netflix in `package_app_info_for_uid`. The deactivation was not
   represented in any table that could be cleanly flipped back.

Lesson: on this firmware, do not run `pkgcmd -D` unless a working `pkgcmd -A` path is proven
first. The documented root invocation is
`/opt/hermes_root -p -c 'sh -c "$(cat /home/owner/share/tmp/sdk_tools/reen.sh)"'`, and that
needs UEP off.

## 3. Misleading evidence along the way

`app_launcher -s org.tizen.netflix-app` answered `not available for the user 901`. That is the
**caller's** uid, not the target user, and it is the same answer the notes record for a healthy
app passed with the wrong ID (root doc gotcha 1). It was read as proof of deactivation. Do not
treat it as a state check.

`pkgcmd --help` confirms `--uid` "only affect\[s\] app activation/deactivation", but there is no
query flag that reports the per-user activation state. That gap is why the DB was inspected by
hand.

## 4. Root was reachable, activation still failed

UEP was armed, so `/opt/hermes_root` was refused (`Operation not permitted`). The staged
FastRoot payload flipped it anyway, even though the AUL app `samudntest01.Mali` is **no longer
installed** (`sdb shell 0 applist` has no `samudn` entry):

```
$ tvcap.py 'AUL_APPID=samudntest01.Mali AUL_ROOT_PATH=/home/owner/share/tmp/sdk_tools/mali \
            /usr/bin/dotnet-launcher --standalone /home/owner/share/tmp/sdk_tools/mali/FastRoot.dll'
TV callback stopped responding after 65s
$ tvcap.py '/opt/hermes_root -p -c "id -u"'
0
```

So UEP went off before the callback died. Root was available. It did not help: `pkgcmd -A`
still failed as uid 0.

## 5. Recovery

The set's own app-store reinstall failed first:

> Unable to install. Please try again later.

That is consistent with the store seeing a half-registered package. What restored Netflix was a
**recovery performed on the TV** (soft reset / reinstall after the set was power-cycled). The
exact sequence was done by the user and not observed from the host, so treat the precise step as
unverified. It now opens normally.

## 6. Current state to check next time

- Netflix is active again. It is **not** in `/opt/hermes/debloat3_boot.sh` (`grep -c netflix` = 0),
  so a future reboot will not re-disable it.
- The Clean Launcher is gone: `/opt/usr/apps` has no `tvunlock02` and no `samudntest01`, so the
  `HIDE_IDS` curation described in the older notes no longer exists on this set.
- UEP state: after the recovery the set may have rebooted, which re-arms UEP.

## 7. If you actually want Netflix gone, the safe order

1. Prove root and `pkgcmd -A` work **before** any `-D` (run `-A` on an already-active package and
   confirm no `-999`).
2. Deactivate: `pkgcmd -D -t app -n org.tizen.netflix-app --uid 5001` as uid 0.
3. Immediately add the package to `/opt/hermes/debloat3_boot.sh` so it survives reboots.
4. If anything looks wrong, do the cold boot first. It is the cheapest reset and Samsung's own
   first recommendation.

## Related

- [samsung-tv-t6500-debloat-and-launcher.md](samsung-tv-t6500-debloat-and-launcher.md)
- [samsung-tv-t6500-root-and-persistence.md](samsung-tv-t6500-root-and-persistence.md)
- [samsung-tv-t6500-power-states-and-remote-control.md](samsung-tv-t6500-power-states-and-remote-control.md)
- [homelab-tv-status-check-2026-11-13.md](homelab-tv-status-check-2026-11-13.md)
- [Samsung support: Why are my Samsung TV apps not working or loading?](https://www.samsung.com/uk/support/tv-audio-video/my-tv-apps-wont-open/)
