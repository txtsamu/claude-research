---
type: troubleshooting
tags: [horizon, minecraft, minecraft-26-3, offline-launcher, linux, fedora, horizon-prepare, mojang-manifest]
created: 2026-11-09
last_verified: 2026-11-09
status: current
---

# Horizon Offline Launcher "doesn't work" on Fedora: no prepared game files

Project: https://github.com/gerdaroot/Horizon-Offline-launcher (launcher for Horizon, a Rust rewrite of Minecraft Java 26.3).

## Time estimate
Measured: about 1 minute of wall-clock work once the cause was known. Library and asset download 28 s (5213 files, 593 MB); `horizon-prepare --prepare --complete` 18 s.

## Symptom
Launcher installed (`~/.local/bin/horizon-offline-launcher`) and starts without crashing, but the game never runs.

## Diagnosis (in order)
1. Launcher binary OK: `ldd` showed no missing libs, and `timeout 15 horizon-offline-launcher` stayed up with no error. No `launcher-crash.txt` anywhere.
2. Ran the game client directly from `~/.local/share/horizon-launcher/versions/<nightly>/`:
   `./horizon-client`. Log at `~/.local/share/horizon/logs/latest.log`:
   `Horizon's prepared game files are missing: no horizon-resources.json in .../.local/horizon-client/26.3`.
   Vulkan was fine (RADV, RX 7800 XT), so it is not a GPU problem.
3. Cause: Horizon ships none of Minecraft's code or assets. A "Prepare" step builds them from your own Minecraft 26.3. There was no `~/.minecraft`, so nothing to prepare from.
4. The user then downloaded `client.jar` and `server.jar` into `~/Downloads`. Checked they are real 26.3:
   ```
   unzip -p client.jar version.json     # id 26.3, world_version 5023
   sha1sum client.jar server.jar
   curl -s -o 26.3.json https://piston-meta.mojang.com/v1/packages/80608ff6753705b6a82e2cb86a5937d4d233abd4/26.3.json
   # downloads.client.sha1 = e877b6a0..., downloads.server.sha1 = 33680f5f...  (both matched)
   ```
   (The manifest URL comes from `~/.local/share/horizon-launcher/minecraft/version_manifest_v2.json`.)
5. Two jars alone are still not enough: `horizon-prepare --help` shows it also needs the version JSON, the 114 libraries (Maven layout) and the asset store (`indexes/` + `objects/`). The README's "Missing ...libraries..." FAQ is this case.

## Fix
Build a standard `~/.minecraft` from Mojang's public manifest plus the user's own client jar, then run prepare:
```
# script: build_minecraft_dir.py (kept in this repo's sibling session dir, ~/sessions/2026-11-09-horizon-offline-launcher/)
# - copies 26.3.json and client.jar to ~/.minecraft/versions/26.3/{26.3.json,26.3.jar}
# - downloads each linux-allowed library artifact (sha1 verified) to ~/.minecraft/libraries/
# - downloads assets/indexes/<id>.json then every object from resources.download.minecraft.net
cd ~/.local/share/horizon-launcher/versions/nightly-*/
./horizon-prepare --prepare --complete --server-jar ~/Downloads/server.jar --minecraft-dir ~/.minecraft
./horizon-prepare --check; echo $?     # 0 = complete
```
Result: `Prepared Horizon native-client resources: .../.local/horizon-client/26.3`, `Sound assets ready: 4962 files`, `--check` exit 0. Re-running `./horizon-client` loaded 35723 block states, 1658 items, audio output up, first frame OK, no ERROR lines.

## Where to get the jars
The jars are Mojang's own files on `piston-data.mojang.com`; the URL path is the file's sha1, so the URL itself tells you the expected checksum:
```
https://piston-data.mojang.com/v1/objects/e877b6a07acd633fb3bb475002175cec036e7b87/client.jar   # 26.3 client
https://piston-data.mojang.com/v1/objects/33680f5f2ac32864d6d7cf5e56a705fdb3e05f4c/server.jar   # 26.3 server
```
Those two URLs come from `downloads.client.url` / `downloads.server.url` in the 26.3 manifest above. For other versions, cliffano's gist is a table of server.jar and client.jar links for every Minecraft version (release, snapshot, RC and old versions), also pointing at `piston-data.mojang.com`. The gist was last active 2026-11-04. I only read its top rows (26.4-snapshot-7) and did not look up 26.3 in it, so use the manifest as the authority and the gist as a convenient index. The linked comment (6074804) is only the owner replying "All good!" to someone asking to reuse the list; it has no technical content.

## Notes and gotchas
- Dead end: assuming a crash. The launcher was fine; the failure only shows in the client's own log.
- The `Horizon` menu entry (`~/.local/share/applications/horizon-launcher.desktop`) points at the *official* launcher in `~/Downloads/horizon-launcher-linux-x86_64/` (Microsoft sign-in). The offline one is run as `horizon-offline-launcher`.
- `rtk curl` mangled the JSON manifest (control characters); use `rtk proxy curl` for raw output.
- Not verified: pressing Prepare/Play inside the offline launcher's own GUI (the prepared folder here belongs to the official launcher's versions dir). With `~/.minecraft` now present, Prepare on "Automatic" should find it.

## References
- https://github.com/gerdaroot/Horizon-Offline-launcher (README: requirements, first run, FAQ)
- https://piston-meta.mojang.com/v1/packages/80608ff6753705b6a82e2cb86a5937d4d233abd4/26.3.json (Mojang 26.3 version manifest, checksums)
- https://gist.github.com/cliffano/77a982a7503669c3e1acb0a0cf6127e9 (Download links of Minecraft server jar and client jar for all versions)
