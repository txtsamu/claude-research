---
type: investigation
tags: [hermes, mcp, cloudflare, truenas, crawl4ai, audit]
created: 2026-11-10
last_verified: 2026-11-10
status: partly resolved (Cloudflare fixed; TrueNAS needs a new API key; gowa logged out; idle servers not yet removed)
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

## Cloudflare: three failures in a row, then fixed

1. The old stdio package `@cloudflare/mcp-server-cloudflare` started and listed 89 tools but the API returned `401 Authentication error` (token invalid; Cloudflare's `/user/tokens/verify` said "Invalid API Token" for both the Hermes token and the separate Claude Code one).
2. A new user token (`cfut_...`) verified as active but had only zone, DNS, tunnel, Access and Workers-read access (per-resource GET sweep), and the old package's results were rejected by the Python MCP SDK (`CallToolResult` validation error: results arrive wrapped in a non-standard `toolResult`). Hermes's own client hit the same error, so the package, not the token, was the blocker for `zones_list`.
3. Switched to Cloudflare's official hosted server `https://mcp.cloudflare.com/mcp` (Streamable HTTP, `Authorization: Bearer <token>`, Code Mode: search/execute tools instead of 89). Findings: Python urllib's default user agent is blocked by Cloudflare (error 1010) while httpx (Hermes) and curl are not; the server answered `403 insufficient_scope: Token lacks required user:read or account:read scope` for the user token across three retests (`/user` 403, `/accounts/<id>` 403, `/accounts` empty list), so the dashboard edit never reached that token.
4. A new account-owned token (`cfat_...`) passed `/accounts/<id>/tokens/verify` and could read the account, KV, R2 and tunnels; the hosted server accepted it and exposed `docs`, `search`, `execute`, `whoami`. It was written to all 12 Hermes configs (`url` + `headers.Authorization`, `enabled: true`) and to the Claude Code project entry (`type: http`). After a gateway restart (about 1 minute), a real `hermes chat -Q` call to `mcp__cloudflare__whoami` returned the account name in 0.26 s. While the token was still insufficient the Hermes entries were kept `enabled: false`, because a failing entry slows gateway start-up (as crawl4ai did).

Testing a Cloudflare token without MCP: call `https://api.cloudflare.com/client/v4/user/tokens/verify` (user token) or `/accounts/<id>/tokens/verify` (account token), then GET one endpoint per resource (zones, DNS, tunnels, Access, Workers, KV, R2, D1, Pages, account, user) and read which return 200 vs 401/403. That maps the token's scopes; the dashboard cannot be driven from the CLI session.

Backups on `home`: `/root/evomem-backups/hermes-curation-20261110-143511/{crawl4ai-removal,bridge-removal,cf-token-update,cf-remote-switch,cf-account-token}/`; Claude Code config copies `~/sessions/2026-11-10-evomem-usage-check/claude.json.pre-cf-*`.

Secrets handling: pasted tokens and R2 keys reached the local hook log (`~/evomem-bridge/hooks/data/`), which the Hermes cron copies to `home`; they were scrubbed from those files on both machines, and the temporary files were shredded, but they remain in the Claude Code session transcript. The earlier `cfut_` token should be revoked and the pasted R2 secret key rotated. Config files contain other plaintext keys (for example TrueNAS and the Hermes API server key) that were printed to the terminal by an over-broad `sed` range; treat those as exposed too.

## Status and next steps

- Done: crawl4ai and the evomem bridge removed; Cloudflare working in Hermes and Claude Code.
- Open: TrueNAS key (decision: which user owns it, who creates it); gowa WhatsApp session logged out; optional removal of idle servers (proxmox, gowa, notion if not wanted); revoke the old `cfut_` token and rotate the R2 secret key.
- Probe scripts: `~/sessions/2026-11-10-evomem-usage-check/build/smoke/` (`mcp_calls2.py`, `mcp_probe.py`, `mcp_probe2.py`, `tn_probe.py`, `tn_probe2.py`, `cf_check.py`, `cf_remote.py`, `cf_new_test.py`, `rm_bridge.py`, `cf_enable.py`).

## References

- [Cloudflare MCP servers changelog, 2026-07-28](https://developers.cloudflare.com/changelog/post/2026-07-28-cloudflare-mcp-servers-mcp-2026-07-28/)
- [cloudflare/mcp-server-cloudflare listing](https://mcpservers.org/servers/cloudflare/mcp-server-cloudflare)
- Main write-up: [evomem-usage-review-vs-upstream-2026-11-10.md](evomem-usage-review-vs-upstream-2026-11-10.md)
