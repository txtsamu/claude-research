---
type: troubleshooting
tags: [camofox, camoufox, home, nixos, systemd, hermes, cache-cleanup, provisioning, opencode, websearch]
created: 2026-11-28
last_verified: 2026-11-28
status: current
---

# Why the Camoufox bundle kept disappearing: a Hermes cache sweep deleted `~/.cache/camoufox`, and provisioning could not restore it

Companion docs: [camofox-browser-missing-binary-http500-2026-11-28.md](camofox-browser-missing-binary-http500-2026-11-28.md), [hermes-gateway-post-reboot-mcp-children-2026-11-28.md](hermes-gateway-post-reboot-mcp-children-2026-11-28.md)

The companion HTTP 500 note covers the symptom and the immediate reinstall. This note covers the part that note could not see: what deleted the bundle, why a reboot did not heal it, and the config change that keeps it from happening again.

## Time estimate

About 20 minutes of wall-clock time, diagnosis first probe at 03:20 WIB to a verified websearch result around 03:36, then a few more minutes for the write-up and push.

- Diagnosis (journal, health, filesystem): ~5 minutes.
- 1.31 GB bundle download: **52 seconds measured** (`curl` reported `00:52`, ~24 MB/s).
- Zip extraction (2,365 entries, 2.5 GB on disk): roughly 1 minute, not separately timed.
- `nixos-rebuild switch` from the GitHub flake, twice: roughly 1 to 2 minutes each, estimated, not measured.

## Symptom

OpenCode's `websearch` tool failed on every query with a bare, unhelpful error:

```
ServiceUnavailableError: Web search request failed: camofox
HTTP 503
```

The provider itself was registered (`opencode api get /api/websearch/provider` listed `camofox`), and the plugin loaded cleanly. The camofox server was up and listening, and `GET /health` returned `ok: true`. The tell was inside the payload:

```json
{"ok":true,"engine":"camoufox","browserConnected":false,"browserRunning":false,...}
```

A direct `POST /tabs` reproduced the failure: `500 {"error":"Internal server error","retryable":false}`. No OpenCode or MCP layer involved.

## Root cause

`journalctl` on the previous boot had the answer. At 02:24:23 WIB a Hermes agent session running in `/root/hermes-workspace/20261127_193833_e6701372` executed a disk-cleanup `rm -rf` over a long list of cache paths. That list included:

```
/root/.cache/camoufox
```

With the 1.2 GB browser bundle gone, the camofox server could not launch a browser. The reboot at 02:54 then made it permanent in practice, because `provision-src-camofox.service` only installs when the source checkout is missing:

```sh
dir=/root/camofox-browser
if [ -e "$dir" ] && [ -n "$(ls -A "$dir")" ]; then
  exit 0
fi
git clone ...
cd "$dir" && ... npm ci ... && ... npx camoufox-js fetch
```

The checkout at `/root/camofox-browser` still existed, so the provisioner exited immediately and never noticed that the browser bundle, a separate 2.5 GB directory, was gone.

So there were two defects stacked:

1. The bundle lived in a generic cache path that a cache sweep is supposed to delete.
2. When it was deleted, nothing on the host could repair it without manual intervention.

The earlier note's line about "the install step had simply never run on this boot" was a reasonable guess at the time. The journal shows the step had run on the previous boot and worked; the cache was deleted afterward.

## Fix

Keep the bundle outside the cache sweep path and teach the provisioner to use the same location.

`hosts/home/camofox.nix`:

```nix
environment = {
  NODE_ENV = "production";
  CAMOFOX_CRASH_REPORT_ENABLED = "false";
  CAMOFOX_ADDONS = "/root/camofox-browser/addons/quetta_xpi";
  CAMOFOX_DISABLE_DEFAULT_ADDONS = "1";
  CAMOUFOX_INSTALL_DIR = "/root/camofox-browser/.camoufox";
};
```

`hosts/home/provision.nix`, in the camofox `post`:

```nix
post = "export CAMOUFOX_INSTALL_DIR=/root/camofox-browser/.camoufox; ${pkgs.steam-run}/bin/steam-run ${pkgs.nodejs_22}/bin/npm ci --no-audit --no-fund && ${pkgs.steam-run}/bin/steam-run ${pkgs.nodejs_22}/bin/npx camoufox-js fetch";
```

The export has to cover `npm ci`, not just the explicit `fetch`: `camoufox-js`'s npm postinstall is what downloads the browser by default, so an env prefix on the `fetch` alone would have left a second copy in `~/.cache/camoufox` on a fresh provision.

Moved the existing install rather than re-downloading it:

```sh
sudo mv /root/.cache/camoufox /root/camofox-browser/.camoufox
```

Committed and pushed to `txtsamu/home-nixos` (`7035328`, then `ea0abc4`), and deployed the documented way, from the repo, never from the checkout on the host:

```sh
ssh moo@home 'sudo nixos-rebuild switch --flake github:txtsamu/home-nixos#home --refresh'
```

The rebuild restarted `camofox-browser.service` and `provision-src-camofox.service`. The second rebuild only touched the provision script.

## Verification

Unit environment after the switch:

```sh
$ systemctl show camofox-browser -p Environment | tr ' ' '\n' | grep CAMOUFOX
CAMOUFOX_INSTALL_DIR=/root/camofox-browser/.camoufox
```

Provision script after the second switch:

```sh
$ sudo grep -o 'export CAMOUFOX_INSTALL_DIR=[^;]*' \
    /nix/store/*-unit-script-provision-src-camofox-start/bin/provision-src-camofox-start
export CAMOUFOX_INSTALL_DIR=/root/camofox-browser/.camoufox
```

Browser state:

```sh
$ curl -s http://localhost:9377/health
{"ok":true,"engine":"camoufox","browserConnected":true,"browserRunning":true,
 "activeTabs":0,"activeSessions":0,"consecutiveFailures":0,...}
```

The process tree confirms the new path, not just the env:

```sh
$ ps aux | grep camoufox-bin | head -1
root 56264 ... /root/camofox-browser/.camoufox/camoufox-bin -no-remote -headless ...
```

End-to-end through OpenCode, the actual failing tool:

```sh
$ opencode api post /api/websearch --data '{"query":"nixos camoufox install dir","providerID":"camofox"}'
results: 10
```

and a direct `websearch` tool call returned the usual result list. The old `/root/.cache/camoufox` path was removed; it has not reappeared.

## Dead ends and gotchas

- **Two fetches raced, twice.** The camofox server pre-warms on a request, and another session was troubleshooting the same host. My first `camoufox-js fetch` failed at 100% with `ETXTBSY: text file is busy, open '/root/.cache/camoufox/camoufox-bin'` because the server launched the binary while the zip was still being extracted. The second attempt failed with `ADM-ZIP: Invalid filename`, which in practice means a truncated or corrupted download, not a bad upstream release. `pkgman.js` deletes `INSTALL_DIR` on any install failure, which is why the directory vanished again mid-flight.
- **Do not trust the progress bar.** `camoufox-js` streamed 1.31 GB, printed 100%, then failed on extraction. The reliable check is the sha256 against GitHub's asset digest, not the progress output.
- **The manual fallback that worked:** download the pinned asset with `curl -L --fail`, verify `sha256` against the release API's `digest`, extract with Python's `zipfile`, write `version.json` (`{"version":"159.0","release":"beta.43"}`, the exact values `CamoufoxFetcher` computes), `chmod -R 755`, then start the unit. No `adm-zip` involvement.
- **`steam-run` wraps the whole process tree.** The unit's `ExecStart` runs `steam-run node server.js`, so the Node native addons and the Firefox subprocess both get an FHS userland. Do not "simplify" this to plain `node`.
- **`ok: true` from `/health` is not health.** `browserConnected` and `browserRunning` are the fields that matter.
- **The missing-Xvfb warning is benign.** It only disables the virtual display path; headless is the intended mode here.

## What was not verified

- The fresh-provision path (`/root/camofox-browser` absent, so `npm ci` plus `fetch` actually run) was not exercised. The `export` fix is static: the generated script was inspected, not run end to end. A from-scratch reinstall would be the real test.
- The repo's full `nix flake check` was not run on the laptop, which has no Nix. Formatting was checked with `nixfmt --check` on the host instead; CI remains the authority.
- The Hermes cleanup that caused this was a one-off agent action, not a scheduled job. Whether future sweeps touch `/root/camofox-browser/.camoufox` is unknown. It is outside `~/.cache`, which is the class of path the sweep targeted.

## Files

- `hosts/home/camofox.nix` — unit plus `CAMOUFOX_INSTALL_DIR`.
- `hosts/home/provision.nix` — camofox `post` with the exported install dir.
- `/root/camofox-browser/.camoufox/` — browser bundle, 2.5 GB, version `159.0 beta.43`.
- `/root/.cache/camoufox` — deliberately absent now.
- `~/.config/opencode/plugins/camofox/index.ts` — OpenCode websearch provider, talks to the server over HTTP only, no local path knowledge.

## References

- [jo-inc/camofox-browser](https://github.com/jo-inc/camofox-browser) — server, health payload, `isFatalInstallError`, pre-warm behaviour.
- [Camoufox v159.0-beta.43 release](https://github.com/daijro/camoufox/releases/tag/v159.0-beta.43) — the pinned Linux x86_64 asset and its size.
- [daijro/camoufox](https://github.com/daijro/camoufox) — upstream browser project.
- [OpenCode web search docs](https://opencode.ai/docs/websearch/) — provider selection and the `websearch` permission, for the OpenCode side of the failure.
- [txtsamu/home-nixos](https://github.com/txtsamu/home-nixos) — commits `7035328` and `ea0abc4`.
