---
type: troubleshooting
tags: [camofox, camoufox, mcp, headless-browser, browser-automation, home, nixos, systemd, hermes, health-check]
created: 2026-11-28
last_verified: 2026-11-28
status: current
---

# camofox-browser answered HTTP 200 on `/health` but every tab creation returned 500: the Camoufox binary was never installed

Companion docs: [hermes-gateway-post-reboot-mcp-children-2026-11-28.md](hermes-gateway-post-reboot-mcp-children-2026-11-28.md)

## Time estimate

About ten minutes of wall-clock time from the first probe at 03:21 to a verified page load at 03:30 WIB, but only because the 1.31 GB browser bundle had to be downloaded twice. The diagnosis itself was two commands. The retry was forced by a self-inflicted truncated download.

## Question

"Is camofox up?"

The service was up in the narrow sense: `camofox-browser.service` was `active (running)`, port 9377 was listening, and `GET /health` returned `ok: true`. The real question was whether it could launch a browser, and the answer was no.

## Symptom

```
$ curl -s -o /dev/null -w "%{http_code}" http://localhost:9377/
200

$ curl -s http://localhost:9377/health
{"ok":true,"engine":"camoufox","browserConnected":false,"browserRunning":false,
 "activeTabs":0,"activeSessions":0,"consecutiveFailures":0, ...}

$ mcp__camofox__camofox_create_tab https://example.com
MCP call failed: MCPError: HTTP 500: {"error":"Internal server error","retryable":false}
```

`browserConnected: false` in a health payload that still says `ok: true` is the tell. The HTTP layer is healthy and the browser is not. Any monitoring that only checks the port or the status code reports this node as green while every browsing task fails.

A direct API probe reproduced the 500 without Hermes or MCP in the path, which ruled out the MCP layer:

```sh
curl -s -X POST http://localhost:9377/tabs -H 'Content-Type: application/json' \
  -d '{"userId":"probe","sessionKey":"probe-1","url":"https://example.com"}'
# {"error":"Internal server error","retryable":false}
```

Without `userId` and `sessionKey` the same endpoint returns `400 {"error":"userId and sessionKey required"}`, so a 400 there is correct behaviour and not the bug.

## Diagnosis

The unit logs to the journal under `steam-run`, because `ExecStart` wraps Node in `steam-run` for the Firefox userland libraries:

```sh
journalctl -u camofox-browser --no-pager -n 35
```

The relevant line:

```
{"level":"warn","msg":"camoufox launch attempt failed","attempt":1,"maxAttempts":1,
 "error":"Version information not found at /root/.cache/camoufox/version.json. Please run `camoufox fetch` to install."}
{"level":"error","msg":"tab create failed", ...}
{"level":"error","msg":"internal error","error":"Version information not found at /root/.cache/camoufox/version.json ..."}
```

The stack pointed at `camoufox-js`, not at the server code:

```
FileNotFoundError: Version information not found at /root/.cache/camoufox/version.json
  at Version.fromPath (node_modules/camoufox-js/dist/pkgman.js:98:19)
  at launchOptions (node_modules/camoufox-js/dist/utils.js:398:26)
```

Filesystem check confirmed it:

```sh
$ ls -la /root/.cache/camoufox
total 8
drwxr-xr-x 2 root root 4096 Nov 28 03:24 .
drwxr-xr-x 6 root root 4096 Nov 28 03:24 ..
```

Empty. The server's own source documents this exact failure mode in `isFatalInstallError()` and `camoufoxInstallRemediation()` in `server.js`: if the message matches `/Version information not found/`, retrying is pointless and the operator must run `npx camoufox-js fetch` and restart. The service was behaving as designed; the install step had simply never run on this boot.

There is also a secondary, harmless warning on every launch:

```
which: no Xvfb in (/run/wrappers/bin:/usr/bin:/usr/sbin:/nix/store/...)
{"level":"warn","msg":"xvfb not available, falling back to headless", ...}
```

Missing Xvfb only disables the virtual display path. The headless fallback is what this deployment wants anyway, so it is noise, not a cause.

## Fix

Ran the fetch from the source checkout so `camoufox-js` resolves to the version the server imports:

```sh
cd /root/camofox-browser
npx camoufox-js fetch
```

Output ends with:

```
Camoufox successfully installed.
Downloading GeoIP database [████████] 100% | 50.5 MB/50.5 MB
```

Then restart the unit so the cold-boot pre-warm picks up the new install:

```sh
systemctl restart camofox-browser.service
```

## What went wrong on the first attempt

The first fetch was launched under `timeout 600` and piped through `tail`:

```sh
timeout 600 npx camoufox-js fetch 2>&1 | tail -25
```

Two compounding mistakes:

1. **The timeout killed the download mid-stream.** The bundle is about 1.31 GB and the link was running well under 10 MB/s, so ten minutes was not enough.
2. **The pipe masked the exit code.** A pipeline returns the status of the last command, so `tail` exited 0 and the shell reported success while the fetch had been killed. The progress bar even printed `100%` and `Camoufox successfully installed` for a file that was truncated at 222 MB.

Proof the artefact was junk, not merely incomplete-looking:

```sh
$ ls -l /tmp/camoufox-4yjHgX/camoufox.zip
-rw-r--r-- 1 root root 222217216 ... camoufox.zip

$ node -e "new (require('adm-zip'))('/tmp/camoufox-4yjHgX/camoufox.zip').getEntries()"
Error: ADM-ZIP: Invalid or unsupported zip format. No END header found
```

`camoufox-js` extracts with `adm-zip`, which needs the central directory at the end of the archive. A truncated zip has none, so the extraction threw and left the install directory empty while the terminal still showed a success banner.

**Second trap:** killing a fetch during extraction deletes the install. `pkgman.js` clears `INSTALL_DIR` before `extractAllTo()`. When a stray fetch process from an earlier attempt was killed mid-flight, `/root/.cache/camoufox` vanished entirely, taking a previously good 2.5 GB install with it. Recovery was another full download. Never kill a fetch once extraction has started; let it finish, then restart the service.

## Verification

Install artefacts:

```sh
$ cat /root/.cache/camoufox/version.json
{"version":"159.0","release":"beta.43"}

$ du -sh /root/.cache/camoufox
2.5G

$ ls /root/.cache/camoufox/camoufox-bin
/root/.cache/camoufox/camoufox-bin
```

Service and browser state after restart at 03:29:59 WIB:

```sh
$ systemctl is-active camofox-browser
active

$ curl -s http://localhost:9377/health
{"ok":true,"engine":"camoufox","browserConnected":true,"browserRunning":true,
 "activeTabs":0,"activeSessions":2,"consecutiveFailures":0, ...}
```

Real navigation through the MCP tool, not just a health probe:

- `camofox_create_tab` on `https://example.com` → `httpStatus: 200`, `navigationOk: true`
- `camofox_snapshot` returned the full document text (1,052 chars, 1 ref)
- `camofox_create_tab` on `https://news.ycombinator.com` → `httpStatus: 200`, `navigationOk: true`, snapshot 38,787 chars with 194 interactive refs
- both tabs closed with `{"ok": true}`

The HN front page snapshot contained live story titles and point counts, so this was a genuine rendering pass through the anti-detection browser, not a cached or stub response.

Final state: unit `enabled` at boot, `active (running)`, cache 2.5 GB at `/root/.cache/camoufox`, no fetch processes left running.

## Key findings / gotchas

- **`ok: true` from `/health` does not mean the browser works.** Check `browserConnected` and `browserRunning` as well, or the deployment looks healthy while every tab request 500s. This is the one field worth alerting on.
- **A 500 on `POST /tabs` with `Version information not found` means the bundle is missing, not that the server is broken.** The fix is `npx camoufox-js fetch` from `/root/camofox-browser`, then `systemctl restart camofox-browser`. Retrying tab creation will never succeed on its own; the server treats this error as fatal and skips the warm retry.
- **Never wrap the fetch in `timeout`, and never pipe it to `tail`/`head`.** The bundle is 1.31 GB plus a 50 MB GeoIP database. A killed download still prints a 100% progress bar and a success line, and the pipeline hides the non-zero exit. Run it in the background, wait for the real exit code, then verify `version.json` exists before restarting anything.
- **Do not kill a fetch during extraction.** `camoufox-js` deletes the install directory first, so an interrupt leaves the system worse than before: no new install and no old one.
- A truncated Camoufox zip fails with `ADM-ZIP: Invalid or unsupported zip format. No END header found`. That message is a reliable signal of an interrupted download rather than a corrupt upstream release.
- The missing-Xvfb warning is benign here. `steam-run` provides the Firefox runtime libraries; the system stays headless by design.
- The unit is supervised by systemd with `Restart=on-failure`, so a crash self-heals but a clean `systemctl stop` stays stopped. During this session the unit was stopped manually at 03:23:52 and did not come back until restarted, which is correct semantics and worth remembering before assuming a dead port means a crash loop.

## Files

- `/etc/systemd/system/camofox-browser.service` — unit, `ExecStart` runs `steam-run node server.js` in `/root/camofox-browser`, `Restart=on-failure`, API key from `/run/agenix/camofox-api-key`.
- `/root/camofox-browser/server.js` — health payload, fatal-install detection, cold-boot pre-warm.
- `/root/camofox-browser/lib/config.js` — resolves the install directory to `$XDG_CACHE_HOME/camoufox` or `~/.cache/camoufox`.
- `/root/.cache/camoufox/` — browser bundle, 2.5 GB, version `159.0 beta.43`.
- `/root/.hermes/config.yaml` — `mcp_servers.camofox` points at `/root/camofox-browser/mcp-server.js`.
