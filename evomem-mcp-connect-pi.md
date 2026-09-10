---
type: how-to
tags: [evomem, mcp, pi, coding-agent, knowledge-base, homelab, nixos, memory]
created: 2026-09-09
last_verified: 2026-09-09
status: current
---

# Connecting the evomem knowledge server (MCP) to the pi coding agent

## Goal

The [pi coding agent](https://pi.dev) had no memory backend. There was already an
`evomem` knowledge server (a persistent, hybrid lexical+vector+graph memory store)
running on the homelab, and it was bridged to Claude Code via an MCP server. The
goal was to give **pi** the same access — so its agent can search, think over, and
capture from the evomem knowledge base.

## Discovery / topolog

- **pi** runs on the daily-driver desktop `fedora` at `192.168.50.20` (hostname `fedora`).
- **evomem** runs on the `home` NixOS host at `192.168.50.202` (hostname `home`)
  as a systemd service exposing a **REST API on `:7700`**.

Confirmed on the remote:

```bash
ssh moo@192.168.50.202 'systemctl status evomem'
#   evomem.service — "Evomem knowledge server (REST API on :7700)", active/running
ssh moo@192.168.50.202 'ps aux | grep evomem'
#   /usr/local/bin/evomem --knowledge /root/evomem-kb serve --host 0.0.0.0 --port 7700
ssh moo@192.168.50.202 'ss -ltnp | grep 7700'
#   LISTEN 0.0.0.0:7700
```

The knowledge root is `/root/evomem-kb`, backed by a TrueNAS iSCSI LUN
(`evomem-kb`, mounted via `iscsi-login-evomem-kb.service`).

### The MCP bridge

An MCP bridge already existed at `~/evomem-bridge/mcp_server.py` (FastMCP). It is a
thin wrapper that translates MCP tool calls into HTTP calls against the evomem REST
API, exposing these tools:

`evomem_search`, `evomem_think`, `evomem_capture`, `evomem_graph`,
`evomem_stats`, `evomem_sync`, `evomem_doc`.

This bridge was configured for **Claude Code** in `~/.claude.json`:

```json
"mcpServers": {
  "evomem": {
    "type": "stdio",
    "command": "/usr/bin/python3",
    "args": ["/home/moo/evomem-bridge/mcp_server.py"],
    "env": { "EVOMEM_URL": "http://192.168.50.200:7700" }
  }
}
```

> **Gotcha — stale IP:** that config pointed `EVOMEM_URL` at `192.168.50.200:7700`,
> which is now dead (`curl` returns `HTTP 000`, no response). The live server is
> `192.168.50.202:7700`. Both IPs return `404` on `/` (it's a REST API, not a web
> root), so test against a real endpoint like `/api/stats` instead.

## Why pi can't just use the MCP bridge

pi (this version — see
`docs/usage.md`: "It intentionally does not include built-in MCP...") has **no
built-in MCP client**. You connect external systems to pi via **extensions** or
packages, not an `mcpServers` block.

So "connect evomem MCP to pi" means: write a pi extension that exposes the evomem
tools as native pi tools. The bridge's tool logic is just REST calls, so the cleanest
extension calls the evomem REST API **directly** — same tools, same semantics, and
no python/MCP-SDK runtime dependency on the pi side.

## The fix: a pi extension bridging evomem

Created `~/.pi/agent/extensions/evomem.ts` (auto-discovered globally). It registers the
seven evomem tools via `pi.registerTool()` (using `typebox` for schemas) plus a
`/evomem-status` command for a quick connectivity/stats check. It calls the REST API
with Node's global `fetch`, defaulting to `http://192.168.50.202:7700`:

```ts
const EVOMEM_URL = process.env.EVOMEM_URL ?? "http://192.168.50.202:7700";
```

Tools registered: `evomem_search`, `evomem_think`, `evomem_capture`,
`evomem_graph`, `evomem_stats`, `evomem_sync`, `evomem_doc` — matching the MCP
bridge's tool names and argument shapes.

## Verification

The extension loaded and registered in pi. Drove pi in RPC mode (no model call
needed) and asked it to list commands:

```bash
PI=/home/moo/.local/lib/node_modules/@earendil-works/pi-coding-agent
printf '%s\n' '{"type":"get_commands"}' |
  ( cat; sleep 3 ) | node "$PI/dist/cli.js" --mode rpc --offline --no-approve
```

`get_commands` returned `evomem-status` with
`sourceInfo.path: "/home/moo/.pi/agent/extensions/evomem.ts"`, `source: "extension"`,
`scope: "user"`. The same synchronous factory that registered the command also
registers all seven tools, so the tools are live too.

The REST API itself was verified directly:

```bash
curl http://192.168.50.202:7700/api/stats
# {"chunks":24091,"docs":884,"indexed_words":58730,...}
curl "http://192.168.50.202:7700/api/search?q=test&limit=2"
# {"hits":[{...}],...}
```

## Files / commands that matter

| Item | Location |
|---|---|
| pi extension (the connection) | `~/.pi/agent/extensions/evomem.ts` |
| Claude Code MCP config (has stale `.200` URL) | `~/.claude.json` → `mcpServers.evomem` |
| evomem MCP bridge (python, REST wrapper) | `~/evomem-bridge/mcp_server.py` |
| evomem server systemd unit | `evomem.service` on `192.168.50.202` |
| evomem knowledge root | `/root/evomem-kb` (TrueNAS iSCSI LUN) |

## To reload / use in pi

- In a running pi session, `/reload` to pick up the new extension,
  or start pi fresh (extensions are auto-discovered on startup).
- `/evomem-status` → connectivity + KB stats.
- Call any `evomem_*` tool. Override the backend URL with the `EVOMEM_URL` env var.

## Notes

- The evomem MCP bridge for Claude Code still points at the dead `192.168.50.200`.
  If Claude Code (or `~/.claude.json`) is still in use, update `EVOMEM_URL` to
  `http://192.168.50.202:7700` there too.
- No credentials/tokens are involved in this connection; the evomem API on `:7700`
  is unauthenticated on the LAN.

## References

- [pi coding agent](https://pi.dev)
