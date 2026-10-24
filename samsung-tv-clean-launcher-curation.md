---
type: troubleshooting
tags: [samsung, tizen, clean-launcher, tvunlock02, debloat, smack, app-list, kants2]
created: 2026-10-24
last_verified: 2026-10-24
status: current
---

# Curating the custom Clean Launcher app list on the Samsung UA43T6500AKXXD

Symptom chain: after the debloat passes (`pkgcmd -D`) the user's own launcher kept
showing apps that were supposed to be gone, and pressing its **TV** tile reported
`cannot open liveTV unknown error`. Both are launcher-side problems, not package
problems. This doc covers what the launcher actually filters on and how to curate
it safely; the Home-key routing question is in
[samsung-tv-custom-launcher-home-routing.md](samsung-tv-custom-launcher-home-routing.md).

## The launcher

| Thing | Value |
|---|---|
| Package / app ID | `tvunlock02` / `tvunlock02.Launcher` |
| Installed | 2026-10-23, under `/opt/usr/apps/tvunlock02/` (rw eMMC, survives reboot) |
| Process | `/opt/usr/apps/tvunlock02/bin/tvunlock02.Launcher` + `wrt` web-runtime children |
| Web content | `/opt/usr/apps/tvunlock02/res/wgt/{index.html,main.js,style.css,config.js,config.example.js,wallpapers.json}` |
| Data model | `main.js` arrays `INTERNAL_IDS`, `DEMO_APPS`, `BRAND_PREFIXES`, `SAMSUNG_KEEP`, `HIDE_IDS` + a `store` persisted in localStorage (`store.seeded`, `store.dock`) |

`isConsumer()` bails out on `app.show === false` ("the TV's own *show in the app
list* flag is the best first filter"), then `isCurated()` applies, in order:
hide `SELF`, `tvunlock01.Peregrine`, `-dummy$` ids and everything in `HIDE_IDS`;
force-show everything in `SAMSUNG_KEEP`; drop test/suite/sample/demo names; drop
`com.samsung.*` / `org.tizen.*` internals matching
`daemon|framework|protocol|manager|support|hotel|preview|continuewatching|ep-|ewbs|p2p-|csapi|ug-|tvs-lite|agent|provider|panel|service`;
force-show `BRAND_PREFIXES` (`netflix`, `youtube`, `prime video`, `spotify`, `plex`,
`dstv`); then show any remaining user-installed app.

## Why the debloated apps stayed on screen

`pkgcmd -D -t app -n <pkg> --uid 5001` deactivates the *package*, which clears the
TV-side `show` flag — the launcher's first filter. That is not enough on its own:

- The curated rows/dock come from `SAMSUNG_KEEP` / `BRAND_PREFIXES` and from the
  cached `store`, and the launcher only re-reads app info when it starts, so a tile
  keeps rendering until the launcher is restarted.
- `getAppsInfo()` still returns deactivated apps, so any code path that walks the
  raw app list (rows, "Show all apps" tile) sees them.
- `pkgcmd -l` is **not** an availability signal: it kept listing all 257 packages,
  including every deactivated one. `app_launcher -s <appId>` is the reliable check —
  it answers `The app with ID: <id> is not available for the user 0` for a
  deactivated package.

Therefore the explicit kill list is `HIDE_IDS`. It was 17 entries; all 26 app IDs
behind the deactivated packages were added (27 packages, but `com.samsung.tv.adplatform`
has no directory of its own — its app id `adplatform.ADPlayer` was already in the
list). Verified after the edit: `HIDE_IDS` = 39 unique ids, and every one of the 26
is present.

App IDs were derived by matching package names against the directory names of
`/usr/apps` (256 system apps) and `/opt/usr/apps` (165) — on Tizen the directory is
the app ID, and for these packages app id == package id.

## The tool: `launcher-hide.sh`

Installed on the TV at `/opt/hermes/launcher-hide.sh` (source in
[../samsung-tv-kants2-exploit/launcher-hide.sh](../samsung-tv-kants2-exploit/launcher-hide.sh)).

```sh
# list both arrays
sh -c "$(cat /opt/hermes/launcher-hide.sh)"

# hide (HIDE_IDS += id) / unhide (HIDE_IDS -= id) / force-show (SAMSUNG_KEEP += id)
LH_ACTION=add LH_IDS="com.a.B org.c.D" sh -c "$(cat /opt/hermes/launcher-hide.sh)"
LH_ACTION=remove LH_IDS="com.a.B"      sh -c "$(cat /opt/hermes/launcher-hide.sh)"
LH_ACTION=show  LH_IDS="com.samsung.tv.coba.livetv" sh -c "$(cat /opt/hermes/launcher-hide.sh)"
```

Two hard rules encoded in the script, both learned on this TV:

1. **Run it as data, never as a file.** While UEP is armed,
   `sh /opt/hermes/launcher-hide.sh` prints `[uep][bash] the file is NOT signed!!`
   and does nothing; `sh -c "$(cat /opt/hermes/launcher-hide.sh)"` runs fine. That is
   why the action and IDs are taken from `LH_ACTION` / `LH_IDS` environment variables
   instead of positional arguments.
2. **Never rewrite `main.js` with `sed -i`.** `sed -i` creates a temp file and
   renames it, which relabels the result `System`; the launcher runs as
   `User::Pkg::tvunlock02` and SMACK would then deny it read access to its own
   `main.js`. The script edits a copy in `/tmp`, sanity-checks brace/bracket/quote
   balance, then writes with `cat "$TMP" > "$MAIN"` — truncating in place keeps the
   inode, owner and SMACK label. A timestamped backup goes to
   `/opt/hermes/launcher-backup/`.

Editing the installed web content is fine: Tizen verifies the package signature at
install time, not on each launch.

## The TV tile / LiveTV failure

The TV rail is `{ key: "livetv", label: "TV", sub: "Tuner" }` and calls
`launch({ id: LIVETV_APP })` with `LIVETV_APP = "com.samsung.tv.coba.livetv"`; the
dock also auto-inserts that app next to Settings. Launching it from the sdb shell
works (`... successfully launched pid = 3578`), and the tuner UI actually runs as
`/usr/apps/org.tizen.tv-viewer/bin/tv-viewer` — grepping for a `coba.livetv`
process is a false negative.

From the launcher (target uid 5001) it fails. `dlogutil -d` shows the reason:

```
E/AMD_WIDGET_TV: amd_widget_tv.c: __on_launch_app_start_start(82) > Failed to find appinfo. appid(com.samsung.tv.ghdaemon)
W/AUL     ( 3971): launch.c: app_request_to_launchpad_for_uid(232) > request cmd(0) : appid(com.samsung.tv.ghdaemon), target_uid(5001)
W/AUL     ( 3557): launch.c: app_request_to_launchpad_for_uid(264) > request cmd(0) result : -13
```

`-13` is `EACCES`, and "failed to find appinfo" means the app is deactivated:
`app_launcher -s com.samsung.tv.ghdaemon` → *not available for the user 0*. So the
launcher's LiveTV path depends on `com.samsung.tv.ghdaemon` (guide/home daemon),
which one of the debloat v3 packages took out. Fix direction: identify the owning
package (`/usr/apps/com.samsung.tv.ghdaemon/tizen-manifest.xml` →
`<tizen:application package="...">`), re-enable just that package, and hide the
resulting tiles with `HIDE_IDS` instead of deactivating the package.

## Side effect found: hosts sinkhole is spamming SMACK denials

debloat v1 bind-mounted `/opt/hermes/hosts.block` over `/etc/hosts` to sinkhole ad
domains. That file is labelled `System`, so every resolution attempt logs a denial:

```
lsm=SMACK ... action=denied subject="User::Pkg::com.samsung.tv.csfs" object="System"
requested=r ... name="hosts.block" path="/<mount_point>/hermes/hosts.block"
```

`com.samsung.tv.csfs` (Smart Hub) retries roughly every 0.5 s and each denial is
turned into a `smartsecurity` "user block" report (`SfTaskMessageReceiver`,
`smartsecurity` pid 1669) — pure wasted CPU and log churn, and the most likely
contributor to the reported Home-button lag.

Fix (not applied yet): stop bind-mounting. `/etc/hosts` on this TV is a plain
452-byte `-rw-rw-rw- root root` file that lives on the writable `/opt` mapping, so
the sinkhole entries can be written into it directly, keeping its original label:

```sh
cp /etc/hosts /opt/hermes/hosts.orig          # backup (once)
umount /etc/hosts 2>/dev/null                 # drop the bind mount
# then append "0.0.0.0 <domain>" lines directly into /etc/hosts
```

## Gotchas worth remembering

- `pkgcmd -D` alone does not remove a tile from a cached launcher view; restart the
  launcher (or reboot) and, for curated rows, add the id to `HIDE_IDS`.
- `HIDE_IDS` matching is exact-string, so add the app ID, not the package name.
- A single sdb capture is not evidence: `sdb` on this model returns empty or
  self-contradicting output. Verify state in one invocation that also prints a
  sanity flag, and re-check before concluding.
