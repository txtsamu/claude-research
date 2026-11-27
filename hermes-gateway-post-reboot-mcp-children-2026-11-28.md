---
type: troubleshooting
tags: [hermes, hermes-gateway, mcp, telegram, gowa, k3s, home, nixos, systemd, polkit, reboot]
created: 2026-11-28
last_verified: 2026-11-28
status: current
---

# hermes-gateway after the 2026-11-28 reboot: gowa race, 13 MCP child pairs, and sudo for systemctl

## Time estimate

About 20 minutes of wall-clock session time, from the post-reboot SSH check at 02:56 WIB to the `hermes-mcp` root-cause diagnosis just after 03:10 WIB (measured from command timestamps). The gateway restart took roughly 50 seconds: `systemctl restart` returned at 03:00:28, the gateway was `active (running)` immediately, and Telegram reported `Connected (polling mode)` at 03:01:18, then again on the profile adapter at 03:01:36. The `hermes-mcp` restart took seconds, but proving that its child dies takes about 30 seconds per attempt, and the live-socket probe waits 6 to 8 seconds.

## Question

After rebooting `home` (192.168.50.200, NixOS 26.05, kernel 6.18.60), is `hermes-gateway` running? If not, why; if yes, is anything visibly wrong?

## What was run, in order

### 1. Host-level post-boot check

```bash
ssh home 'hostname; uptime; who -b; systemctl --failed --no-pager; df -h /; free -h'
```

Result: booted 02:54, 0 failed units, root 61% used (56G/98G), 15Gi RAM with 9.6Gi available. Load was 3.97 at one minute, which is normal for k3s plus Immich starting cold on an 8-core box.

### 2. Locate the unit and confirm state

```bash
ssh home 'systemctl list-units --all --no-pager | grep -i hermes'
ssh home 'systemctl status hermes-gateway --no-pager -n 0 | head -12'
```

Four units matched:

```
hermes-gateway.service              active running   Hermes Agent Gateway - Messaging Platform Integration
hermes-mcp.service                  active running   Hermes MCP Bridge (pre-warmed stdio daemon)
provision-src-hermes.service        active exited    Provision hermes source checkout at /opt/hermes-source
provision-venv-hermes.service       active exited    Provision hermes Python venv at /opt/hermes-venv
```

Gateway state at the time:

```
Active: active (running) since Sat 2026-11-28 02:54:53 WIB
Main PID: 1100 (hermes)
NRestarts: 0
```

### 3. Check the journal for errors

```bash
ssh home 'journalctl -u hermes-gateway -b -p err --no-pager -q | tail'
ssh home 'journalctl -u hermes-gateway -b --no-pager -q | grep -iE "mcp|spawn|telegram" | tail -20'
```

No `err`-level lines at all. What did show up:

- Shell hooks (`session-workspace.py`, `enforce-session-workspace.py`) skipped for the `critic`, `device`, `diskos`, `net`, and `ops` profiles because they are not in each profile's `shell-hooks-allowlist.json`. Fix is `HERMES_ACCEPT_HOOKS=1` or approving per profile; not a failure.
- Skill slash-command collisions: `handoff` and `plan` duplicate core commands, so they register as `/skill handoff` and `/skill plan`.
- Repeated `MCP server 'gowa' failed initial connection after 3 attempts, parking until a reconnect is requested` against `192.168.50.240:3000`, roughly every 8 seconds from 02:55:17 to 02:55:49, then it stopped.

### 4. Why gowa failed: it was still restarting

```bash
ssh home 'export KUBECONFIG=/etc/rancher/k3s/k3s.yaml; k3s kubectl -n homelab get pod,svc -o wide | grep -i gowa'
ssh home 'curl -s -o /dev/null -w "http %{http_code}\n" --max-time 5 http://192.168.50.240:3000/'
```

The `gowa` pod `gowa-7d59d45f9-cg6cn` was `Running` but had restarted twice, with its newest start about 90 seconds after the gateway. By 02:58 the endpoint answered `http 200`. So this was a boot ordering race, not a broken service: the gateway came up before the LoadBalancer pod behind `192.168.50.240:3000`.

### 5. The suspicious part: 13 identical MCP child pairs

```bash
ssh home 'pgrep -fc "truenas-ws/server.py"; pgrep -fc "camofox-browser/mcp-server.js"'
ssh home 'ps -eo pid,ppid,etimes,rss,cmd | grep -E "truenas-ws/server.py|camofox-browser/mcp-server.js" | grep -v grep'
```

Counts were 13 and 13, all direct children of the gateway PID, about 74–88 MB RSS each, for roughly 1.9 GB combined. First read looked like leaked retry churn from the gowa outage.

### 6. Restart to clear it (this is where the first diagnosis was wrong)

```bash
ssh home 'systemctl restart hermes-gateway'
# Failed to restart hermes-gateway.service: Access denied
ssh home 'sudo -n true && echo ok'
# ok
ssh home 'sudo systemctl restart hermes-gateway'
```

`moo` is in `wheel` and has passwordless sudo, but plain `systemctl restart` is refused by polkit for a non-root SSH session. Use `sudo`.

After the restart the main PID changed from 1100 to 18275, Telegram reconnected at 03:01:18 and 03:01:36, and there were 0 error lines. The 13 pairs came straight back with new PIDs, all children of 18275, spawned within the first ~45 seconds.

### 7. Confirm it is baseline, not a leak

```bash
ssh home 'sudo tail -c 2000 /root/.hermes/spawn-ledger.json'
ssh home 'sudo find /root/.hermes/profiles -maxdepth 1 -mindepth 1 -type d | wc -l'
```

The spawn ledger labels every one of them `"purpose": "mcp-helper"` with the same `spawner_pid`. There are 11 profile directories under `/root/.hermes/profiles` (`audio`, `critic`, `dev`, `device`, `diskos`, `finance`, `net`, `ops`, `orvix`, `research`, `uiux`). The earlier MCP audit already established that "all 12 Hermes homes (main plus 11 profiles) configure the same 7 servers", so per-home MCP children are the design, not a fault. That accounts for the pairs: one set per Hermes home, not one per gateway.

The zombie is separate:

```bash
ssh home 'ps -eo pid,ppid,stat,cmd | awk "\$3 ~ /Z/"'
# 1111  1101 Z  [hermes] <defunct>
```

PID 1101 is `hermes-mcp.service`, so restarting the gateway does not reap it. A zombie holds no memory, only a process-table slot.

### 8b. Restarting hermes-mcp: the zombie comes straight back

```bash
ssh home 'sudo systemctl restart hermes-mcp'
ssh home 'ps -eo pid,ppid,stat,cmd | awk "\$3 ~ /Z/"'
# 32153  32149 Z  [hermes] <defunct>
```

A new daemon PID at 03:06:05 produced a new zombie within seconds. Probing the Unix socket made a live `hermes mcp serve` child appear, then it died about 30 seconds later and became the next zombie, and the probe got `ConnectionResetError`. Running the command by hand with stderr visible gave the root cause:

```bash
ssh home 'sudo bash -c "sleep 25 | timeout 20 /usr/local/bin/hermes mcp serve --accept-hooks"'
# hermes mcp: 'serve' is not a `hermes mcp` command.
# Hermes as an MCP server moved out of core into the 'mcp-serve' plugin:
# `hermes mcp serve` is now `hermes mcp-serve`.
# Install it with: `hermes plugins install mcp-serve`.

ssh home 'sudo /usr/local/bin/hermes plugins list'
# agentmemory, evomem  -> mcp-serve is NOT installed
```

So `hermes-mcp.service` is legacy and broken: `/root/.hermes/mcp-daemon.py` still spawns `hermes mcp serve`, the CLI prints the deprecation notice and exits 0, the daemon never calls `wait()`, and the exit becomes a zombie. Its "Hermes ready." line is a lie, because the ready thread just sleeps `WARM_SECS` without checking the child. Any client that connects to `/run/hermes-mcp.sock` gets a connection reset.

Nothing currently uses it: `hermes-mcp.sock` and `mcp-client.py` are referenced only by the daemon, the client script, and old `state.db` history. There is no `mcp-client.py` entry in `/root/.hermes/config.yaml`, `/root/.claude.json`, the laptop's `~/.claude.json`, or `~/.mcp.json`.

The likely fix, if the capability is wanted, is two changes: `hermes plugins install mcp-serve`, then change `HERMES_ARGS` in `/root/.hermes/mcp-daemon.py` from `["mcp", "serve", "--accept-hooks"]` to `["mcp-serve", "--accept-hooks"]` and restart. The alternative is `sudo systemctl disable --now hermes-mcp` since it serves nothing.

### 8. Settled reading

```bash
ssh home 'uptime; systemctl show hermes-gateway -p MemoryCurrent -p NRestarts; pgrep -fc truenas-ws/server.py'
```

```
03:03:48 up 8 min, load average: 6.09, 5.08, 2.36
MemoryCurrent=2227929088
NRestarts=0
13
```

Load had peaked at 15.95 right after the restart, then fell to 6.09. `vmstat` showed 70–83% CPU idle, so the number was boot-time I/O churn (Immich at 1.7 GB RSS plus k3s), not CPU saturation.

## Gotchas

- **Use `sudo systemctl restart`.** `moo` gets `Access denied` from polkit on a plain restart even though `sudo -n true` succeeds.
- **gowa is a boot-order dependency.** The gateway starts before the k3s LoadBalancer pod behind `192.168.50.240:3000` is ready, retries three times per server, logs `connecting → parked`, then recovers on its own once the pod answers. Do not read the retry burst as a failure.
- **13 MCP child pairs are baseline.** They are per-Hermes-home children (main plus 11 profiles), about 1.9 GB RSS. Restarting does not reduce them, and killing individual children only breaks their MCP client until it respawns.
- **The `[hermes] <defunct>` zombie belongs to `hermes-mcp.service`, not the gateway.** It survives a gateway restart, and a `hermes-mcp` restart recreates it within seconds; the daemon's `hermes mcp serve` child exits because that subcommand moved to the uninstalled `mcp-serve` plugin. The fix is a plugin install plus a one-line `HERMES_ARGS` change, not a restart.
- **Load average is misleading here.** An 8-core box at load 16 with CPU 80% idle just means uninterruptible I/O from other services, not a runaway gateway.

## What was not verified

- The exact mapping of 13 child pairs to 12 homes. The arithmetic suggests 12 homes plus one helper, but nothing on-box printed a per-child profile name, so this is inference from the spawn ledger and the earlier audit, not a direct read.
- Whether the MCP memory footprint can be reduced by making servers lazy instead of pre-warmed. No config key for pre-warming was found in `/root/.hermes/config.yaml`.
- Thermals. `sensors` returned nothing, so the box may not have `lm_sensors` configured.
- Whether `hermes plugins install mcp-serve` works offline and what it pulls; it was not attempted.
- Whether the gateway needs the socket at all. Evidence says no, but that is from config and history, not a live connection trace.

## References

No external sources were used. Everything above came from the host itself (`systemctl`, `journalctl`, `ps`, `kubectl`, `curl`, the Hermes spawn ledger and config), plus these earlier notes.

Related notes:

- [[hermes-mcp-servers-audit-cloudflare-truenas-2026-11-10]] — establishes that all 12 Hermes homes configure the same MCP servers, which explains the 13 child pairs.
- [[hermes-gateway-restart-deferred-runtime-draining-2026-11-11]] — restart behaviour and runtime draining.
- [[home-vm-reboot-hangs-k3s-killall-self-stop-2026-11-28]] — the reboot/shutdown issue checked immediately before this session.
