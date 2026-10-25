---
type: how-to
tags: [samsung, smart-tv, tizen, sdb, developer-mode, debloat, mikrotik, nmap]
created: 2026-10-18
last_verified: 2026-10-25
status: current
---

# Samsung Tizen TV: developer mode, sdb connection, and what debloating is actually possible

> **Paths relocated (2026-10-25):** `~/tizen-sdb` → `~/archive/samsung-tv-t6500-2026-10/tooling/tizen-sdb`; `~/samsung-tv-backup` → `~/archive/samsung-tv-t6500-2026-10/device-data/samsung-tv-backup`.

Device: Samsung **UA43T6500AKXXD** (2020 T6500, Tizen 5.5), 192.168.50.31, MAC `64:E7:D8:EC:38:EE`, dynamic DHCP lease on the MikroTik.
Host PC: fedora, 192.168.50.20.

**TL;DR:** Developer mode plus `sdb` from Tizen's package repo gets you a debug link, but on this firmware it's nearly useless for debloating. There's no root and no interactive shell, `sdb pull` is blocked, and `vd_appuninstall` refuses store apps. Use the TV's own Apps → Settings → Delete menu to remove apps, and Technitium DNS blocking for ads and telemetry (see [technitium-samsung-tv-ad-telemetry-block-advanced-blocking.md](technitium-samsung-tv-ad-telemetry-block-advanced-blocking.md)).

## 1. Find the TV's IP from the MikroTik

```bash
sshpass -p '<router-pass>' ssh mikrotik '/ip dhcp-server lease print detail without-paging' | grep -i -B2 -A8 samsung
```
The lease has `host-name="Samsung"`, and `64:E7:D8` is a Samsung OUI.

## 2. Enable developer mode on the TV

1. Open **Apps**, then type `1 2 3 4 5` on the remote.
2. Turn Developer mode **On** and set Host PC IP to `192.168.50.20`.
3. When this works, the Apps screen shows a "Develop mode" label.

The TV has no "USB debugging" setting because it isn't Android. Debugging goes over the network to port **26101**.

### Gotcha: a soft restart isn't enough

After a remote-power restart, the TV's API reported developer mode as enabled, but 26101 still refused connections:
```bash
curl -s http://192.168.50.31:8001/api/v2/ | grep -oE '"(developerMode|developerIP)":"[^"]*"'
# "developerIP":"192.168.50.20"  "developerMode":"1"
nmap -Pn -T4 -p- --open 192.168.50.31   # 26101 NOT listed
```
(Parsing that JSON with python fails because the response contains raw control characters. Use grep.)

**Fix:** unplug the TV from the wall for 30–60 s, power it on, and recheck Apps → 12345. After that, `nmap` showed `26101/tcp open`.

## 3. Get sdb without installing all of Tizen Studio

`sdb` is a standalone package in Tizen's official repo:
```bash
curl -s -o listing.html https://download.tizen.org/sdk/tizenstudio/official/binary/
grep -oE 'sdb_[^"<]*ubuntu-64\.zip' listing.html | sort -uV | tail -1   # sdb_4.2.36_ubuntu-64.zip
curl -O https://download.tizen.org/sdk/tizenstudio/official/binary/sdb_4.2.36_ubuntu-64.zip
unzip sdb_4.2.36_ubuntu-64.zip            # binary at data/tools/sdb
mkdir -p ~/tizen-sdb && cp data/tools/sdb ~/tizen-sdb/ && chmod +x ~/tizen-sdb/sdb
```
(The rtk curl filter mangled the big directory listing, so save it to a file first.)

Connect:
```bash
~/tizen-sdb/sdb connect 192.168.50.31:26101
~/tizen-sdb/sdb devices      # 192.168.50.31:26101  device  UA43T6500AKXXD
```

## 4. What the debug link allows (very little)

```bash
~/tizen-sdb/sdb capability
# intershell_support:disabled  sdbd_rootperm:disabled  rootonoff_support:disabled  appcmd_support:disabled
```
- `sdb shell 'ls ...'` → `closed`. Only whitelisted `sdb shell 0 <cmd>` commands work.
- `sdb shell 0 vd_applist` lists store-installed apps with `app_id`, `app_title` and `app_tizen_id`. `sdb shell 0 applist` lists every app, including about 60 system components.
- `sdb pull /opt/usr/apps/<pkg>` (also tried `globalapps`, `apps_rw`) → `error: You cannot pull files from this path`. **You can't back up app packages.** The only backup possible is the app list (store IDs), for reinstalling from the store later.

### Uninstalling via sdb fails for store apps

Tried on Vidio (`app_id` 3201903017967, package `UulqmoWUzM`, app `UulqmoWUzM.vidio`):
```bash
sdb shell 0 vd_appuninstall 3201903017967     # can not uninstall app
sdb shell 0 vd_appuninstall UulqmoWUzM        # was get app info failed
sdb shell 0 vd_appuninstall UulqmoWUzM.vidio  # can not uninstall app
sdb uninstall UulqmoWUzM                      # maps to the app_id, same "can not uninstall app"
```
On this firmware, sdb seems to remove only apps installed through it. Tizen developer forum threads report the same thing on TVs from this era.

## 5. What actually worked

- **App removal:** on the TV, go to Home → Apps → Settings (gear) → select the app → **Delete**. This removed 9 of 11: Prime Video, Disney+, Apple TV, Qalbox, Apple Music, Spotify, HBO GO Asia, MOLA, Vidio. **YouTube** and **e-Manual** stayed (Delete greyed out or not taken), so use *Remove from Home* to hide them. Verify with `sdb shell 0 vd_applist`.
- **Ads/telemetry:** use DNS blocking scoped to the TV in Technitium. See the linked doc.

Backup of the pre-removal app list (for store reinstalls): `~/samsung-tv-backup/` on fedora (`installed_apps.txt`, `vd_applist.txt`, `applist_full.txt`).

## References

- [Samsung forum: Unable to connect via SDB on QN65QN90DAFXZA with Developer Mode enabled](https://forum.developer.samsung.com/t/unable-to-connect-via-sdb-on-qn65qn90dafxza-with-developer-mode-enable/39639)
- [Samsung forum: Cannot connect TV in devel mode](https://forum.developer.samsung.com/t/cannot-connect-tv-in-devel-mode/9798)
- [Samsung forum: Unable to connect to developer mode of Samsung Smart TV](https://forum.developer.samsung.com/t/unable-to-connect-to-developer-mode-of-samsung-smart-tv/40905)
- [Tizen Developers: App uninstall stopped working](https://developer.tizen.org/forums/sdk-ide/app-uninstall-stopped-working)
- [SamyGO: Delete preinstalled apps from your TV](https://forum.samygo.tv/viewtopic.php?p=112924)
- [BGR: Your Samsung TV has a big bloatware problem](https://www.bgr.com/2278437/how-to-fix-samsung-tv-big-bloatware-problem/)
- [Tizen Studio binary package repo](https://download.tizen.org/sdk/tizenstudio/official/binary/)
