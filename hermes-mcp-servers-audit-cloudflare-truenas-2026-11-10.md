---
type: investigation
tags: [hermes, mcp, cloudflare, truenas, crawl4ai, audit]
created: 2026-11-10
last_verified: 2026-11-10
status: mostly resolved (Cloudflare fixed; TrueNAS replaced by a read-only WebSocket MCP server; gowa logged out; idle servers not yet removed)
---

# Hermes MCP servers: usage audit, health check, Cloudflare and TrueNAS fixes

## Time estimate

About 45 minutes of session time, from the usage audit (about 15:10 WIB) to Cloudflare working (15:52), taken from log and command timestamps (an estimate, not a stopwatch). Most of it was waiting on the user: dashboard edits to the Cloudflare token (three retests, then a new token) and the TrueNAS key decision, which is still open. Each gateway restart took about 1 minute (53 to 59 s) once the dead crawl4ai host was gone; before that, restarts took 1.5 to 4 minutes.

## Question

After the evomem MCP bridge was replaced by a plugin (see [evomem-usage-review-vs-upstream-2026-11-10.md](evomem-usage-review-vs-upstream-2026-11-10.md)), which of the other Hermes MCP servers on `home` are still used, and which still work?

## Usage (Hermes `state.db`, history since 2026-05-07)

```bash
# Python sqlite3, read-only open of /root/.hermes/state.db; real MCP tool results only
# (the tool_calls column and text mentions overcount)
select tool_name, timestamp, session_id from messages where tool_name like 'mcp%'
```

All 12 Hermes homes (main plus 11 profiles) configure the same 7 servers.

| Server | Total calls | Last 30 d | Last used | Verdict |
|---|---|---|---|---|
| camofox | 573 | 156 | 2026-11-08 | in use |
| mikrotik | 68 | 53 | 2026-11-05 | in use |
| truenas | 19 | 15 | 2026-11-06 | in use, now broken (see below) |
| proxmox | 224 | 0 | 2026-09-25 | idle 45 days; Hermes memory now says to use `pvesh` on `px1` |
| cloudflare | 5 | 0 | 2026-08-19 | now working again (see below) |
| notion | 0 | 0 | never | idle |
| gowa | 0 | 0 | never | idle, WhatsApp logged out |

Already removed: crawl4ai (14 calls, 2026-08-20/21; it retried every 20 s against an unreachable host since 2026-10-25, which made gateway start-up take about 4 minutes) and the evomem stdio bridge (50 calls, last 2026-10-31). The Claude Code project config on the desktop also had a `cloudflare` stdio server (zero real calls found in local session history).

Dead end: counting `mcp__<server>__` strings in the `tool_calls` and `content` columns gave inflated or stale numbers (for example camofox 4431); the `tool_name` column of tool-result rows matches the logs.

## Health check without trusting the config

```bash
hermes mcp test <name>                       # connects and lists tools
# one read-only call per server through the Python MCP client on home (credentials read from config, never printed)
```

| Server | Connect | Read-only call | Result |
|---|---|---|---|
| mikrotik | yes | `mikrotik_get_system_resources` | live data, RouterOS 7.25 |
| proxmox | yes | `get_nodes` | `px1` online, 43 d uptime |
| notion | yes | `API-get-self` | bot user `hermes-agent` in the workspace |
| camofox | yes | not called (opens a browser tab) | used 11 times in the last 7 days |
| cloudflare | yes | see below | fixed |
| truenas | yes | `system_version` | HTTP 500, see below |
| gowa | yes | `whatsapp_app` status | `connected=false logged_in=false` |

## TrueNAS: HTTP 500 on every authenticated call

Symptoms: every REST call with an `Authorization: Bearer <key>` header returned `500 Internal Server Error  Server got itself in trouble`, including `core/ping`; calls with no header worked (`core/ping` returned `"pong"`, protected endpoints returned 401).

```bash
# no-auth vs real key vs made-up key against https://<nas>/api/v2.0/{core/ping,system/version,system/info}
# on the NAS (TrueNAS 25.10.4, up 6 weeks; middlewared and nginx active):
ssh <nas> 'sudo tail /var/log/middlewared.log'                    # "Error handling request from 127.0.0.1" at each test
ssh <nas> 'sudo grep -a "Error handling request" /var/log/middlewared.log | tail -1'   # decode the JSON traceback
ssh <nas> 'sudo midclt call api_key.query "[]" "{\"select\":[\"id\",\"name\",\"username\",\"created_at\",\"revoked\"]}"'
```

Root cause: the traceback ends in `middlewared/plugins/api_key.py` `authenticate` -> `get_instance` -> `InstanceNotFound: ApiKey 1 does not exist`. The Hermes key starts with `1-` (key id 1), and the NAS now has a single API key, id 2 `democratic-csi-2026-10` (root, created October, used for Kubernetes storage). Key id 1 was deleted. TrueNAS 25.10.4 does not catch that exception in the REST layer, so a bearer key with an unknown id returns 500 instead of 401 (a made-up key starting `1-` gives the identical 500, which is how the key was ruled in). The same errors appear in the NAS log on 2026-11-06 around the last Hermes call, so the tool has probably been failing since then. The NAS itself is healthy (the evomem KB lives on its iSCSI disk).

Fix (not applied; waiting for a decision): create a new API key (UI: user menu, API Keys, Add, or `midclt call api_key.create`), preferably owned by a read-only user because the `truenas` tool exposes about 278 actions including reboot and shutdown, and put it in `mcp_servers.truenas.env.TRUENAS_API_KEY` of all 12 Hermes configs, then restart the gateway. Do not reuse the democratic-csi key: rotating it would break Kubernetes storage.

### TrueNAS fix attempt (later the same day)

```bash
ssh moo@nas   # TrueNAS 25.10.4; hostname truenas; midclt over sudo
midclt call alert.list                      # RESTAPIUsage: "REST API will be removed in version 26.04"
midclt call privilege.query / user.query    # privileges: FULL_ADMIN, READONLY_ADMIN (group id 41), SHARING_ADMIN
midclt call user.create '{"username":"hermes-mcp","groups":[41],"password_disabled":true,"shell":"/usr/sbin/nologin","smb":false,...}'
midclt call api_key.create '{"name":"hermes-mcp-2026-11","username":"hermes-mcp"}'    # key id 3; secret saved to a private file, never printed
```

- Health check of the NAS: pools `boot-pool` and `data` ONLINE (`data` 58% used, 3 TB free), cifs/iscsitarget/nfs/ssh running, 2 alerts (REST API deprecation, update available). The REST alert also says REST was used 5,463 times in 24 h from the `home` host; the broken Hermes key cannot be the source (its id does not exist), so another client on that host (probably the Kubernetes storage driver, not confirmed) also depends on REST and will break at 26.04.
- Historic Hermes usage of the `truenas` tool was only read-only listings (smb/nfs share lists, iSCSI targets and sessions, NFS config, pool list), so a read-only owner is enough. Created user `hermes-mcp` (id 73, `READONLY_ADMIN`, no password, no shell, not SMB) and API key id 3.
- Finding: over the deprecated REST API (`/api/v2.0/...`) the new key authenticates (`core/ping` 200) but every other endpoint returns an empty 403 (system, pool, sharing, iscsi, service, alert, disk, user, api_key), so the `truenas-mcp` npm package (REST) cannot work with a read-only key. Over the supported JSON-RPC 2.0 WebSocket API (`wss://<nas>/api/current`, `auth.login_with_api_key`) the same key works: `system.version`, `pool.query`, `sharing.smb.query`, `iscsi.target.query` return data and `auth.me` shows only `*_READ` roles.
- Options considered: (1) replace `truenas-mcp` with a small read-only stdio MCP server that speaks the WebSocket API (survives the 26.04 REST removal); (2) give the key a full-admin owner so REST accepts it (works now, but the tool can reboot or shut down the NAS and it dies at 26.04); (3) look for an existing WebSocket-based server. Option 1 was chosen.

### TrueNAS resolution: read-only WebSocket MCP server (17:29 to 17:37 WIB)

About 8 minutes measured from timestamps (estimate was 10): write 3 min, test and fix 3 min, deploy and verify 2 min.

- Source: `/root/hermes-mcp-servers/truenas-ws/server.py` on `home` (copy and tests in `~/sessions/2026-11-10-evomem-usage-check/build/truenas-ws/`: `server.py`, `test_server.py`, `e2e_real.py`, `sweep.py`, `switch_configs.py`). It uses the MCP Python SDK 2.0 already in `/opt/hermes-venv` (`from mcp.server.mcpserver import MCPServer`; the older `mcp.server.fastmcp` does not exist there) and aiohttp, one authenticated WebSocket to `wss://<nas>/api/current` with reconnect, and `auth.login_with_api_key`.
- Tools (all marked read-only): `truenas_system_info`, `truenas_pools`, `truenas_datasets`, `truenas_shares`, `truenas_iscsi`, `truenas_services`, `truenas_alerts`, `truenas_disks`, `truenas_query` (generic, any allowed method). Safety: an allowlist of read methods (no create/update/delete/start/stop/reboot), redaction of any field whose name contains secret, passw, hash, token, key, private, chap, credential or passphrase (booleans such as `key_loaded` are kept), output capped at 12,000 characters, the API key masked in errors.
- A method sweep with the read-only key showed what that role can call: all pool, dataset, disk, share, iSCSI, service, interface, alert and config reads work; `zfs.snapshot.query` and `system.build_time` return `[EACCES] Not authorized`, `update.check_available` does not exist, and `pool.processes` and `disk.temperature_agg` need arguments, so those were removed from the allowlist and no snapshot tool is offered.
- Tests: 16 unit and end-to-end tests with a fake WebSocket server (allowlist, no write verbs, parameter clamping, redaction, truncation, reconnect after a dropped socket, interleaved events, timeout, wrong key, key masking, full MCP stdio round trip) run on `home` with the Hermes venv: `cd /tmp/tnws-test && /opt/hermes-venv/bin/python3 -m unittest test_server` (do not use `python3 -I`, it hides the current directory). The tests found one real bug (`encryption_key` and `key_material` were not redacted) and a cosmetic one (double spaces after stripping HTML from alerts). Against the real NAS 9 of 9 tools worked and `pool.dataset.delete` and `user.query` were refused; two outputs were slimmed (iSCSI sessions and extents) because they hit the size cap.
- Rollout: the `truenas` entry in all 12 Hermes configs now runs `/opt/hermes-venv/bin/python3 /root/hermes-mcp-servers/truenas-ws/server.py` with `TRUENAS_URL`, the new key (id 3, read-only user `hermes-mcp`) and `TRUENAS_VERIFY_SSL`; backups in `/root/evomem-backups/hermes-curation-20261110-143511/truenas-ws-switch/`. Gateway restarted (back in about 1 minute); `hermes mcp test truenas` lists 9 tools; a real `hermes chat -Q` call used `truenas_pools` (0.57 s) and `truenas_services` (0.08 s) and reported `data` ONLINE and cifs, iscsitarget, nfs, ssh running.
- Side effects: the tool names changed (old: one `truenas` tool with category/action). The Hermes skills `devops/truenas-nas-administration/SKILL.md` and `devops/homelab-mcp-setup/references/truenas-mcp.md` still describe the old tool and were not edited. The local copy of the key was shredded; the key now exists only in the Hermes configs.

## Cloudflare: three failures in a row, then fixed

1. The old stdio package `@cloudflare/mcp-server-cloudflare` started and listed 89 tools but the API returned `401 Authentication error` (token invalid; Cloudflare's `/user/tokens/verify` said "Invalid API Token" for both the Hermes token and the separate Claude Code one).
2. A new user token (`cfut_...`) verified as active but had only zone, DNS, tunnel, Access and Workers-read access (per-resource GET sweep), and the old package's results were rejected by the Python MCP SDK (`CallToolResult` validation error: results arrive wrapped in a non-standard `toolResult`). Hermes's own client hit the same error, so the package, not the token, was the blocker for `zones_list`.
3. Switched to Cloudflare's official hosted server `https://mcp.cloudflare.com/mcp` (Streamable HTTP, `Authorization: Bearer <token>`, Code Mode: search/execute tools instead of 89). Findings: Python urllib's default user agent is blocked by Cloudflare (error 1010) while httpx (Hermes) and curl are not; the server answered `403 insufficient_scope: Token lacks required user:read or account:read scope` for the user token across three retests (`/user` 403, `/accounts/<id>` 403, `/accounts` empty list), so the dashboard edit never reached that token.
4. A new account-owned token (`cfat_...`) passed `/accounts/<id>/tokens/verify` and could read the account, KV, R2 and tunnels; the hosted server accepted it and exposed `docs`, `search`, `execute`, `whoami`. It was written to all 12 Hermes configs (`url` + `headers.Authorization`, `enabled: true`) and to the Claude Code project entry (`type: http`). After a gateway restart (about 1 minute), a real `hermes chat -Q` call to `mcp__cloudflare__whoami` returned the account name in 0.26 s. While the token was still insufficient the Hermes entries were kept `enabled: false`, because a failing entry slows gateway start-up (as crawl4ai did).

Testing a Cloudflare token without MCP: call `https://api.cloudflare.com/client/v4/user/tokens/verify` (user token) or `/accounts/<id>/tokens/verify` (account token), then GET one endpoint per resource (zones, DNS, tunnels, Access, Workers, KV, R2, D1, Pages, account, user) and read which return 200 vs 401/403. That maps the token's scopes; the dashboard cannot be driven from the CLI session.

Backups on `home`: `/root/evomem-backups/hermes-curation-20261110-143511/{crawl4ai-removal,bridge-removal,cf-token-update,cf-remote-switch,cf-account-token}/`; Claude Code config copies `~/sessions/2026-11-10-evomem-usage-check/claude.json.pre-cf-*`.

Secrets handling: pasted tokens and R2 keys reached the local hook log (`~/evomem-bridge/hooks/data/`), which the Hermes cron copies to `home`; they were scrubbed from those files on both machines, and the temporary files were shredded, but they remain in the Claude Code session transcript. The earlier `cfut_` token should be revoked and the pasted R2 secret key rotated. Config files contain other plaintext keys (for example TrueNAS and the Hermes API server key) that were printed to the terminal by an over-broad `sed` range; treat those as exposed too.

## Status and next steps

- Done: crawl4ai and the evomem bridge removed; Cloudflare working in Hermes and Claude Code; TrueNAS working again (see above).
- Done: TrueNAS tool replaced by a read-only WebSocket MCP server (works with the read-only key; survives the REST removal in TrueNAS 26.04).
- Open: update the two Hermes skills that still describe the old `truenas` tool; the Kubernetes storage driver (or whatever else on `home` makes about 5,463 REST logins a day) will break when TrueNAS 26.04 removes REST; gowa WhatsApp session is logged out; optional removal of idle servers (proxmox, gowa, and notion if not wanted); revoke the old `cfut_` token and rotate the pasted R2 secret key.
- Probe scripts: `~/sessions/2026-11-10-evomem-usage-check/build/smoke/` (`mcp_calls2.py`, `mcp_probe.py`, `mcp_probe2.py`, `tn_probe.py`, `tn_probe2.py`, `cf_check.py`, `cf_remote.py`, `cf_new_test.py`, `rm_bridge.py`, `cf_enable.py`).

## References

- [Cloudflare MCP servers changelog, 2026-07-28](https://developers.cloudflare.com/changelog/post/2026-07-28-cloudflare-mcp-servers-mcp-2026-07-28/)
- [cloudflare/mcp-server-cloudflare listing](https://mcpservers.org/servers/cloudflare/mcp-server-cloudflare)
- Main write-up: [evomem-usage-review-vs-upstream-2026-11-10.md](evomem-usage-review-vs-upstream-2026-11-10.md)
