---
type: how-to
tags: [agentmemory, mcp, claude-code, firewalld, homelab, multi-host]
created: 2026-07-31
last_verified: 2026-07-31
status: current
---

# Sharing an agentmemory MCP backend across two Claude Code hosts

## Goal

`agentmemory` (https://github.com/rohitg00/agentmemory) was already running on the
homelab node (`192.168.50.80`) as a persistent-memory MCP server for Claude Code
there. Wanted a second machine (`192.168.50.20`, the daily-driver desktop) to read
and write the *same* memory store, instead of growing its own separate one.

## Discovery

SSH'd into homelab as root and found the existing setup:

```bash
systemctl status agentmemory
# active, enabled, running since initial install
# ExecStart=/usr/bin/npx @agentmemory/agentmemory
# WorkingDirectory=/root/.agentmemory
# EnvironmentFile=/root/.agentmemory/.env
```

Relevant bits of `/root/.agentmemory/.env`:

```
III_REST_PORT=3111
VIEWER_HOST=0.0.0.0
# AGENTMEMORY_SECRET=      <- blank, no auth
```

Homelab's own Claude Code already had it wired up in `~/.claude.json`:

```json
"agentmemory": {
  "command": "npx",
  "args": ["-y", "@agentmemory/mcp"],
  "env": { "AGENTMEMORY_URL": "http://localhost:3111" }
}
```

So `@agentmemory/mcp` is just a thin stdio shim — it doesn't hold any data itself,
it talks to the REST API (`III_REST_PORT`, here 3111) of the long-running
`agentmemory` server. Any machine that can reach that port and speaks the same
protocol shares the same memory.

## Setup on the second host

On `192.168.50.20`, added the same MCP server at user scope, pointed at homelab's
IP instead of `localhost`:

```bash
claude mcp add agentmemory -s user \
  -e AGENTMEMORY_URL=http://192.168.50.80:3111 \
  -- npx -y @agentmemory/mcp
```

First connection attempt hung and timed out after 30s.

## Blocker: firewalld

`VIEWER_HOST=0.0.0.0` made it *look* reachable, and the port genuinely was
listening on all interfaces — but homelab's `firewalld` `public` zone (covering
both `eth0` and `eth1`, i.e. the whole LAN) only allowed a fixed port list plus
`ssh`/`dns`/`cockpit`. `3111` wasn't in it, and there was no `trusted` zone
covering the LAN subnet (only two podman bridge subnets were trusted). So the
port answered on `localhost` but was silently dropped from any other host on
`192.168.50.0/24`.

Confirmed with:

```bash
# from homelab itself — works
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3111/   # 404 (route exists, just not "/")

# from the second host — hangs
curl -m 5 -o /dev/null -w '%{http_code}\n' http://192.168.50.80:3111/   # curl: (28) timeout
```

Fix — open the port on homelab:

```bash
firewall-cmd --zone=public --add-port=3111/tcp --permanent
firewall-cmd --reload
firewall-cmd --list-ports   # confirm 3111/tcp present
```

After that, `claude mcp list` on the second host showed:

```
agentmemory: npx -y @agentmemory/mcp - ✔ Connected
```

## Result

Both `192.168.50.80` and `192.168.50.20` now point their Claude Code
`agentmemory` MCP entry at the same REST backend (`192.168.50.80:3111`), so
memories written from either machine are visible to both.

## Notes on secrets / security

`AGENTMEMORY_SECRET` is unset in `/root/.agentmemory/.env`, so the REST API has
**no authentication**. Opening `3111/tcp` on the LAN-facing `public` zone means
anything on `192.168.50.0/24` can read or write this memory store. Acceptable
for a trusted home LAN, not acceptable if that network ever gets less trusted
(guest devices, IoT VLAN, etc.) — set `AGENTMEMORY_SECRET` and pass a matching
header/token from the MCP client side before relying on this across anything
but a fully trusted network.

## Reproducing on a third host

1. Confirm `3111/tcp` is reachable from the new host (`curl` test above).
2. `claude mcp add agentmemory -s user -e AGENTMEMORY_URL=http://192.168.50.80:3111 -- npx -y @agentmemory/mcp`
3. `claude mcp list` and check for ✔ Connected.
