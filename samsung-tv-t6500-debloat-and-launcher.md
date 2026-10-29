---
type: troubleshooting
tags: [samsung, tizen, tv, sdb, developer-mode, debloat, mikrotik, kants2, uep, cold-boot, persistence, clean-launcher, tvunlock02, smack, app-list, launcher, home-key, app-operation-api, uid-5001, t6500, blocked]
created: 2026-10-18
last_verified: 2026-10-29
status: current
---

# Samsung TV debloat and launcher curation (KantS2 / T6500)

> **Merged 2026-10-25** from four separate docs: `samsung-tizen-tv-sdb-debug-debloat.md`,
> `samsung-tv-t6500-debloat-cold-boot-persistence.md`, `samsung-tv-clean-launcher-curation.md`,
> `samsung-tv-custom-launcher-home-routing.md`. Root-chain and UEP-bypass detail lives in the
> companion doc [samsung-tv-t6500-root-and-persistence.md](samsung-tv-t6500-root-and-persistence.md)
> (its "Debloat with root" section is the fullest account of the `pkgcmd -D` / unit-marker
> mechanics this doc's cold-boot matrix measures).
>
> **Paths relocated (2026-10-25):** `~/tizen-sdb` → `~/archive/samsung-tv-t6500-2026-10/tooling/tizen-sdb`;
> `~/samsung-tv-backup` and `~/samsung-tv-root-src` → `~/archive/samsung-tv-t6500-2026-10/{device-data,tooling}/`.

## Device

Samsung **UA43T6500AKXXD** (2020 T6500, `20_KANTS2_FHD`, Tizen 5.5, armv7l, kernel `4.1.10`),
`192.168.50.31`, MAC `64:E7:D8:EC:38:EE`, dynamic DHCP lease on the MikroTik. Host PC: fedora,
`192.168.50.20`.

## Status at a glance

| What | Status |
|---|---|
| Debloat via plain `sdb` (no root) | Nearly useless — no shell, no pull, no store-app uninstall |
| App removal via TV's own Settings menu | ✅ Works for most apps |
| Ads/telemetry via DNS | ✅ Works — see [technitium-samsung-tv-ad-telemetry-block-advanced-blocking.md](technitium-samsung-tv-ad-telemetry-block-advanced-blocking.md) |
| Debloat with root (`pkgcmd -D`, unit masks, `ConditionPathExists` markers) | ✅ Works, now boot-persistent (root doc, Chapter 7) |
| Cold-boot survival of each debloat layer, measured by hand | ✅ Matrix below — now superseded by the boot hook, kept as the baseline |
| Launcher curation (`HIDE_IDS`) | ✅ Works, persistent (files on `/opt`) |
| Custom launcher as Home/boot target | ❌ **Blocked** on `setuid(5001)` |

---

## Chapter 1 — sdb developer mode and what debloating is possible without root

*How-to, current. This predates root (see the root-and-persistence doc) and is what you're stuck
with if you only have plain sdb.*

**TL;DR:** Developer mode plus `sdb` from Tizen's package repo gets you a debug link, but on this
firmware it's nearly useless for debloating. There's no root and no interactive shell, `sdb pull`
is blocked, and `vd_appuninstall` refuses store apps. Use the TV's own Apps → Settings → Delete
menu to remove apps, and Technitium DNS blocking for ads and telemetry.

### 1. Find the TV's IP from the MikroTik

```bash
sshpass -p '<router-pass>' ssh mikrotik '/ip dhcp-server lease print detail without-paging' | grep -i -B2 -A8 samsung
```
The lease has `host-name="Samsung"`, and `64:E7:D8` is a Samsung OUI.

### 2. Enable developer mode on the TV

1. Open **Apps**, then type `1 2 3 4 5` on the remote.
2. Turn Developer mode **On** and set Host PC IP to `192.168.50.20`.
3. When this works, the Apps screen shows a "Develop mode" label.

The TV has no "USB debugging" setting because it isn't Android. Debugging goes over the network
to port **26101**.

#### Gotcha: a soft restart isn't enough

After a remote-power restart, the TV's API reported developer mode as enabled, but 26101 still
refused connections:
```bash
curl -s http://192.168.50.31:8001/api/v2/ | grep -oE '"(developerMode|developerIP)":"[^"]*"'
# "developerIP":"192.168.50.20"  "developerMode":"1"
nmap -Pn -T4 -p- --open 192.168.50.31   # 26101 NOT listed
```
(Parsing that JSON with python fails because the response contains raw control characters. Use
grep.)

**Fix:** unplug the TV from the wall for 30–60 s, power it on, and recheck Apps → 12345. After
that, `nmap` showed `26101/tcp open`.

### 3. Get sdb without installing all of Tizen Studio

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

### 4. What the debug link allows (very little)

```bash
~/tizen-sdb/sdb capability
# intershell_support:disabled  sdbd_rootperm:disabled  rootonoff_support:disabled  appcmd_support:disabled
```
- `sdb shell 'ls ...'` → `closed`. Only whitelisted `sdb shell 0 <cmd>` commands work.
- `sdb shell 0 vd_applist` lists store-installed apps with `app_id`, `app_title` and
  `app_tizen_id`. `sdb shell 0 applist` lists every app, including about 60 system components.
- `sdb pull /opt/usr/apps/<pkg>` (also tried `globalapps`, `apps_rw`) → `error: You cannot pull
  files from this path`. **You can't back up app packages.** The only backup possible is the app
  list (store IDs), for reinstalling from the store later.

#### Uninstalling via sdb fails for store apps

Tried on Vidio (`app_id` 3201903017967, package `UulqmoWUzM`, app `UulqmoWUzM.vidio`):
```bash
sdb shell 0 vd_appuninstall 3201903017967     # can not uninstall app
sdb shell 0 vd_appuninstall UulqmoWUzM        # was get app info failed
sdb shell 0 vd_appuninstall UulqmoWUzM.vidio  # can not uninstall app
sdb uninstall UulqmoWUzM                      # maps to the app_id, same "can not uninstall app"
```
On this firmware, sdb seems to remove only apps installed through it. Tizen developer forum
threads report the same thing on TVs from this era.

### 5. What actually worked (pre-root)

- **App removal:** on the TV, go to Home → Apps → Settings (gear) → select the app → **Delete**.
  This removed 9 of 11: Prime Video, Disney+, Apple TV, Qalbox, Apple Music, Spotify, HBO GO Asia,
  MOLA, Vidio. **YouTube** and **e-Manual** stayed (Delete greyed out or not taken), so use
  *Remove from Home* to hide them. Verify with `sdb shell 0 vd_applist`.
- **Ads/telemetry:** use DNS blocking scoped to the TV in Technitium. See the linked doc.

Backup of the pre-removal app list (for store reinstalls):
`~/archive/samsung-tv-t6500-2026-10/device-data/samsung-tv-backup/` on fedora
(`installed_apps.txt`, `vd_applist.txt`, `applist_full.txt`).

### References (Chapter 1)

- [Samsung forum: Unable to connect via SDB on QN65QN90DAFXZA with Developer Mode enabled](https://forum.developer.samsung.com/t/unable-to-connect-via-sdb-on-qn65qn90dafxza-with-developer-mode-enable/39639)
- [Samsung forum: Cannot connect TV in devel mode](https://forum.developer.samsung.com/t/cannot-connect-tv-in-devel-mode/9798)
- [Samsung forum: Unable to connect to developer mode of Samsung Smart TV](https://forum.developer.samsung.com/t/unable-to-connect-to-developer-mode-of-samsung-smart-tv/40905)
- [Tizen Developers: App uninstall stopped working](https://developer.tizen.org/forums/sdk-ide/app-uninstall-stopped-working)
- [SamyGO: Delete preinstalled apps from your TV](https://forum.samygo.tv/viewtopic.php?p=112924)
- [BGR: Your Samsung TV has a big bloatware problem](https://www.bgr.com/2278437/how-to-fix-samsung-tv-big-bloatware-problem/)
- [Tizen Studio binary package repo](https://download.tizen.org/sdk/tizenstudio/official/binary/)

---

## Cold-boot survival matrix

*Troubleshooting, current — this is the measured-by-hand baseline from before root persistence
existed. The boot hook (root doc, Chapter 7) now automates the re-apply described here, but the
matrix itself is still the reference for which layer lives where.*

The question this answers: the TV was unplugged from the wall and powered back on — which parts
of the debloat and root work are still in place? Short version: the two things stored as **files
on rw `/opt`** are; everything that lives in the kernel or in per-user runtime state is gone and
has to be re-applied.

### Measured matrix

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
`contents-recognition-service` (1537), `vision-data-recognition-service` (1429) and `voice-app`
(1330) all running again, `115` services total.

### Re-apply sequence (verified end to end, by hand)

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

The hosts sinkhole was deliberately **not** re-applied — see Chapter 3 below.

### Traps learned in this pass

- **Do not write the sinkhole into `/etc/hosts` directly.** Chapter 3 (launcher curation) first
  proposed that as the fix for the SMACK denial spam ("a plain 452-byte `-rw-rw-rw-` file on the
  writable `/opt` mapping"). On this build it is `-rw-r--r-- root root`, 148 bytes, and
  `Read-only file system` (`EROFS`) even from `uid=0` with `CapEff ffffffffffffffff`. A redirect
  silently achieves nothing; the script reported `sinkhole_lines=0 bytes=148`. Only `mount --bind`
  reaches the file.
- **Check whether the sinkhole is needed at all before re-creating it.** The LAN resolver already
  blocks the ad/telemetry domains — `nslookup` from the TV answers `0.0.0.0` for
  `samsungads.com`, `samsungacr.com`, `smetrics.samsung.com` and no address for
  `log.samsung.com` / `analytics.samsung.com`. Skipping the bind mount also avoids the
  `com.samsung.tv.csfs` SMACK-denial spam that made Home feel laggy.
- **`app_launcher -s <appid>` starts the app; it is not a status query.** Using it as a "did the
  deactivation survive" probe opens the app on the panel. `app_launcher -k/-t` from the `uid=901`
  shell answers `Failed to get filter count` (as `uid=0` it works and reports `App isn't
  running`). `app_launcher -l` is per-user and lists 5 entries for uid 901, so it cannot answer
  for uid 5001. `package_app_info_for_uid` in `.pkgmgr_parser.db` stays at 0 rows either way —
  activation state is not readable there.
- **UEP re-armed inside the same session.** Minutes after the flip, `sh /opt/hermes/debloat2.sh`
  printed `[uep][bash] the file is NOT signed!!` while `/opt/hermes_root -p -c '…'` still
  executed. Always invoke scripts as data: `hermes_root -p -c 'sh -c "$(cat …)"'`.
- **`FastRoot`'s SUID fast path misfires and costs 57 s.** Its probe string is `[0 |
  uid=901(sdk) |]`, so `probe.Trim().StartsWith("0")` is false and the payload falls through to
  the full DRAM cred scan (`patched=80`, `FASTROOT_END total=57958ms`) instead of the intended
  ~350 ms path. Same end state, purely a speed bug — fix the check to skip the leading `[`.
- **`sdb shell "…"` returns `closed`** on this TV; every command has to go through the
  retry-wrapped `SdbClient.capture()` on the control host (`moo@fedora`,
  `~/archive/samsung-tv-t6500-2026-10/tooling/samsung-tv-root-src/.venv/bin/python`,
  `sys.path.insert(0, ".../samsung-tv-root-src/src")`). The TV→host log path needs
  `192.168.50.31` in firewalld's trusted zone (it is).

### Consequence for expectations — superseded 2026-10-25

This matrix is what a cold boot still looks like **by hand**, but it no longer happens by hand. A
same-size raw-block patch of `/etc/profile.d/bash_prompt_custom.sh` on `/dev/mmcblk0p18` makes
`tizen-system-env.service` (which sources `/etc/profile.d/*.sh` as root) run `/opt/hermes/boot.sh`
at **uptime 1 s**: the unit markers are rewritten, the 13 `pkgcmd -D` deactivations are
re-applied, and the `/run/systemd/system` masks are re-created by two delayed stop passes, all
with no computer attached. Verified on a real cold boot — running services came back at 103
instead of 115, `/run/systemd/system` held 18 masks again, the launcher stayed functional, and
the only failed unit was the vendor `vdca-update.service`.

Anything not covered by the hook (UEP state, interactive root, `/etc/hosts` bind mount) still
needs the manual path described above. Full write-up of the boot hook itself:
[samsung-tv-t6500-root-and-persistence.md, Chapter 7](samsung-tv-t6500-root-and-persistence.md).

---

## Launcher curation (`HIDE_IDS`)

*Troubleshooting, current.*

Symptom chain: after the debloat passes (`pkgcmd -D`) the user's own launcher kept showing apps
that were supposed to be gone, and pressing its **TV** tile reported `cannot open liveTV unknown
error`. Both are launcher-side problems, not package problems.

### The launcher

| Thing | Value |
|---|---|
| Package / app ID | `tvunlock02` / `tvunlock02.Launcher` |
| Installed | 2026-10-23, under `/opt/usr/apps/tvunlock02/` (rw eMMC, survives reboot) |
| Process | `/opt/usr/apps/tvunlock02/bin/tvunlock02.Launcher` + `wrt` web-runtime children |
| Web content | `/opt/usr/apps/tvunlock02/res/wgt/{index.html,main.js,style.css,config.js,config.example.js,wallpapers.json}` |
| Data model | `main.js` arrays `INTERNAL_IDS`, `DEMO_APPS`, `BRAND_PREFIXES`, `SAMSUNG_KEEP`, `HIDE_IDS` + a `store` persisted in localStorage (`store.seeded`, `store.dock`) |

`isConsumer()` bails out on `app.show === false` ("the TV's own *show in the app list* flag is
the best first filter"), then `isCurated()` applies, in order: hide `SELF`, `tvunlock01.Peregrine`,
`-dummy$` ids and everything in `HIDE_IDS`; force-show everything in `SAMSUNG_KEEP`; drop
test/suite/sample/demo names; drop `com.samsung.*` / `org.tizen.*` internals matching
`daemon|framework|protocol|manager|support|hotel|preview|continuewatching|ep-|ewbs|p2p-|csapi|ug-|tvs-lite|agent|provider|panel|service`;
force-show `BRAND_PREFIXES` (`netflix`, `youtube`, `prime video`, `spotify`, `plex`, `dstv`); then
show any remaining user-installed app.

### Why the debloated apps stayed on screen

`pkgcmd -D -t app -n <pkg> --uid 5001` deactivates the *package*, which clears the TV-side `show`
flag — the launcher's first filter. That is not enough on its own:

- The curated rows/dock come from `SAMSUNG_KEEP` / `BRAND_PREFIXES` and from the cached `store`,
  and the launcher only re-reads app info when it starts, so a tile keeps rendering until the
  launcher is restarted.
- `getAppsInfo()` still returns deactivated apps, so any code path that walks the raw app list
  (rows, "Show all apps" tile) sees them.
- `pkgcmd -l` is **not** an availability signal: it kept listing all 257 packages, including
  every deactivated one. `app_launcher -s <appId>` is the reliable check — it answers `The app
  with ID: <id> is not available for the user 0` for a deactivated package.

Therefore the explicit kill list is `HIDE_IDS`. It was 17 entries; all 26 app IDs behind the
deactivated packages were added (27 packages, but `com.samsung.tv.adplatform` has no directory of
its own — its app id `adplatform.ADPlayer` was already in the list). Verified after the edit:
`HIDE_IDS` = 39 unique ids, and every one of the 26 is present.

App IDs were derived by matching package names against the directory names of `/usr/apps` (256
system apps) and `/opt/usr/apps` (165) — on Tizen the directory is the app ID, and for these
packages app id == package id.

### The tool: `launcher-hide.sh`

Installed on the TV at `/opt/hermes/launcher-hide.sh` (source in
[samsung-tv-kants2-exploit/launcher-hide.sh](samsung-tv-kants2-exploit/launcher-hide.sh)).

```sh
# list both arrays
sh -c "$(cat /opt/hermes/launcher-hide.sh)"

# hide (HIDE_IDS += id) / unhide (HIDE_IDS -= id) / force-show (SAMSUNG_KEEP += id)
LH_ACTION=add LH_IDS="com.a.B org.c.D" sh -c "$(cat /opt/hermes/launcher-hide.sh)"
LH_ACTION=remove LH_IDS="com.a.B"      sh -c "$(cat /opt/hermes/launcher-hide.sh)"
LH_ACTION=show  LH_IDS="com.samsung.tv.coba.livetv" sh -c "$(cat /opt/hermes/launcher-hide.sh)"
```

Two hard rules encoded in the script, both learned on this TV:

1. **Run it as data, never as a file.** While UEP is armed, `sh /opt/hermes/launcher-hide.sh`
   prints `[uep][bash] the file is NOT signed!!` and does nothing; `sh -c "$(cat
   /opt/hermes/launcher-hide.sh)"` runs fine. That is why the action and IDs are taken from
   `LH_ACTION` / `LH_IDS` environment variables instead of positional arguments.
2. **Never rewrite `main.js` with `sed -i`.** `sed -i` creates a temp file and renames it, which
   relabels the result `System`; the launcher runs as `User::Pkg::tvunlock02` and SMACK would
   then deny it read access to its own `main.js`. The script edits a copy in `/tmp`,
   sanity-checks brace/bracket/quote balance, then writes with `cat "$TMP" > "$MAIN"` —
   truncating in place keeps the inode, owner and SMACK label. A timestamped backup goes to
   `/opt/hermes/launcher-backup/`.

Editing the installed web content is fine: Tizen verifies the package signature at install time,
not on each launch.

### The TV tile / LiveTV failure

The TV rail is `{ key: "livetv", label: "TV", sub: "Tuner" }` and calls `launch({ id: LIVETV_APP
})` with `LIVETV_APP = "com.samsung.tv.coba.livetv"`; the dock also auto-inserts that app next to
Settings. Launching it from the sdb shell works (`... successfully launched pid = 3578`), and the
tuner UI actually runs as `/usr/apps/org.tizen.tv-viewer/bin/tv-viewer` — grepping for a
`coba.livetv` process is a false negative.

From the launcher (target uid 5001) it fails. `dlogutil -d` shows the reason:

```
E/AMD_WIDGET_TV: amd_widget_tv.c: __on_launch_app_start_start(82) > Failed to find appinfo. appid(com.samsung.tv.ghdaemon)
W/AUL     ( 3971): launch.c: app_request_to_launchpad_for_uid(232) > request cmd(0) : appid(com.samsung.tv.ghdaemon), target_uid(5001)
W/AUL     ( 3557): launch.c: app_request_to_launchpad_for_uid(264) > request cmd(0) result : -13
```

`-13` is `EACCES`, and "failed to find appinfo" means the app is deactivated: `app_launcher -s
com.samsung.tv.ghdaemon` → *not available for the user 0*. So the launcher's LiveTV path depends
on `com.samsung.tv.ghdaemon` (guide/home daemon), which one of the debloat v3 packages took out.
Fix direction: identify the owning package (`/usr/apps/com.samsung.tv.ghdaemon/tizen-manifest.xml`
→ `<tizen:application package="...">`), re-enable just that package, and hide the resulting tiles
with `HIDE_IDS` instead of deactivating the package.

### Side effect found: hosts sinkhole is spamming SMACK denials

debloat v1 bind-mounted `/opt/hermes/hosts.block` over `/etc/hosts` to sinkhole ad domains. That
file is labelled `System`, so every resolution attempt logs a denial:

```
lsm=SMACK ... action=denied subject="User::Pkg::com.samsung.tv.csfs" object="System"
requested=r ... name="hosts.block" path="/<mount_point>/hermes/hosts.block"
```

`com.samsung.tv.csfs` (Smart Hub) retries roughly every 0.5 s and each denial is turned into a
`smartsecurity` "user block" report (`SfTaskMessageReceiver`, `smartsecurity` pid 1669) — pure
wasted CPU and log churn, and the most likely contributor to the reported Home-button lag.

The proposed fix was to stop bind-mounting and write the sinkhole straight into `/etc/hosts` ("a
plain 452-byte `-rw-rw-rw-` file on the writable `/opt` mapping"). **That does not work on this
build:** `/etc/hosts` is `-rw-r--r-- root root`, 148 bytes, and `cat >>` answers `Read-only file
system` even from `uid=0` with `CapEff ffffffffffffffff`. Only `mount --bind` reaches it. Since
the LAN resolver already blocks these domains (see above), the bind mount was dropped altogether
instead.

### After a cold boot (measured 2026-10-24)

The `HIDE_IDS` edit is one of the two things on this TV that genuinely survives a mains
power-cycle: after an unplug/replug the array still read 39 ids and the launcher was already
running with it. Everything service-level had to be re-applied — see the cold-boot matrix above.

Also worth knowing before using `app_launcher` as a status probe: **`app_launcher -s <id>` starts
the app**. Pre-reboot it answered `not available for the user 0` for deactivated packages;
post-reboot the same commands launched them, which both proved the `pkgcmd -D` state was gone
*and* opened five apps on the panel.

### Gotchas worth remembering

- `pkgcmd -D` alone does not remove a tile from a cached launcher view; restart the launcher (or
  reboot) and, for curated rows, add the id to `HIDE_IDS`.
- `HIDE_IDS` matching is exact-string, so add the app ID, not the package name.
- A single sdb capture is not evidence: `sdb` on this model returns empty or self-contradicting
  output. Verify state in one invocation that also prints a sanity flag, and re-check before
  concluding.

---

## Custom launcher as Home target (blocked)

*Investigation, blocked. The one open thread left in this whole project.*

Goal: the user's own launcher (`tvunlock02.Launcher`) should come up as the TV's default UI on
power-on and on the remote's **Home** button. Blocked on one syscall: the Samsung app-operation
API has to be called as the TV owner (uid 5001), and this box refuses to let the root payload
become uid 5001.

### How the Home target actually works

Stock behaviour does not come from a script or a systemd unit: the TV asks a per-user setting
*what should open for the `main` operation*, and the answer on a stock set is
`com.samsung.tv.csfs` (Smart Hub). That setting is reachable through Samsung's native library:

```
/usr/lib/libcapi-appfw-app-operation-tv.so.0
  app_operation_get_current_app(const char *operation, char **app_id)
  app_operation_set_current_app(const char *operation, const char *app_id)
  operation = "http://tizen.org/appcontrol/operation/main"
```

Crucially this must run as the **TV owner: uid 5001, gid 100, supplementary groups dropped** —
the preference being read/written belongs to that user, not to root and not to the injection
identity (uid 901). Source for the mechanism and the uid requirement: `berteotti/custom-tv`,
`docs/2-set-as-home.md` plus `tools/home-routing/Program.cs` (its own doc admits that persistence
of the setting across a cold reboot was never verified on their test set — so that is still an
open question here too).

### Implementation

`payloads/home-set.*` (source in
[samsung-tv-kants2-exploit/payloads/home-set.Program.cs](samsung-tv-kants2-exploit/payloads/home-set.Program.cs)),
built as a netcoreapp3.0 console app like the other payloads:

- logs to TCP `192.168.50.20:4558` and to `/tmp/homeset.txt` (the launcher swallows stdout);
- reads the current Home target;
- with `set <appId> [expectedCurrent]` it refuses unless the current value matches the
  expectation, writes, reads back, and rolls back on mismatch;
- escalates to root first if it did not start as root (cred-patch fallback over `/dev/ntkhdma`),
  because `setuid(5001)` needs privilege.

Run it the usual way (staged in the app-private dir — `dotnet-launcher` silently refuses a DLL
under `/opt`), using the invocation solved in the root doc:

```sh
M=/home/owner/share/tmp/sdk_tools/mali
AUL_APPID=samudntest01.Mali AUL_ROOT_PATH=$M \
  /usr/bin/dotnet-launcher --standalone $M/HomeSet.dll
```

### Result: blocked on setuid(5001)

Read-only run, 2026-10-24 20:04 (log from `/tmp/homeset.txt` on the TV):

```
20:04:32 start uid=0
20:04:32 setuid(5001) failed
20:04:32 HOMESET_END
```

So the payload does run with real root (`start uid=0` — the earlier fast-root path was still in
effect), and `setgid(100)` succeeded, but the uid change is refused. That is consistent with
Tizen's LSM stack (SMACK + security-manager/CyNara) rather than with missing capabilities: the
process already has `CapEff ffffffffffffffff`, SMACK label `System`, and `setgid` to a plain group
is allowed.

The payload has since been extended (built, **not yet executed on the TV**) with:

- `__errno_location()` logging and the SMACK label of the process (`/proc/self/attr/current`),
- a `setresuid(5001,5001,5001)` retry after the plain `setuid` failure,
- a fallback that continues and calls the API anyway, to measure whether the uid actually matters
  for `get_current_app`.

### Next step (deferred)

1. Run the errno build; capture the exact failure (`EPERM` vs `EACCES`) and the reported SMACK
   label.
2. If the syscall stays refused, bypass it entirely: the DMA primitive already gives arbitrary
   physical read/write (root doc, Chapter 6), so patch the calling task's own `struct cred`
   `uid/gid/euid/egid/fsuid/fsgid` from 0 to 5001 in DRAM (the reverse of the escalation step,
   same layout, same DRAM-only safety envelope) and then call the API — no syscall involved.
3. Only then test the real question: does the Home target survive a power cycle? That needs a
   user-initiated power cycle (agent-level reboots are blocked — see
   [samsung-tv-t6500-power-states-and-remote-control.md](samsung-tv-t6500-power-states-and-remote-control.md)).
4. Also unresolved: whether a cold boot can launch the launcher at all before root exists — UEP
   re-arms on boot, so any boot-time hook must be something a *signed* vendor unit already runs,
   not our own binary (this is exactly the trick the boot-hook chapter in the root doc used for
   the debloat re-apply, but Home routing additionally needs uid 5001, which that hook doesn't
   have).

## Local payloads for this doc

The payloads behind the steps above — `pkgcmd` deactivation, `key_filter` / `managed_app` and
`widgetinfo` cleanup, and the launcher `main.js` watchdog patch — now live in
`~/archive/samsung-tv-t6500-2026-10/scripts/2026-10-25-root-session/` (with the exact
`hermes_root -p -c '…'` command bodies in `cmd/`); the host-side drivers are in
`~/archive/samsung-tv-t6500-2026-10/tooling/tv-helpers/`. Each directory has a `README.md`.
