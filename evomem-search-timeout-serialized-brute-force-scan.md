---
type: troubleshooting
tags: [evomem, mcp, timeout, search, latency, sqlite, embeddings, homelab]
created: 2026-10-27
last_verified: 2026-10-27
status: current
---

# evomem MCP `evomem_search` returns `error: timed out`

## Symptoms

1. `mcp__evomem__evomem_search` with `limit=5` returned `{"result":"error: timed out"}`.
2. Calling it with arg `q` failed pydantic validation: the MCP tool parameter is `query` (the *HTTP* parameter is `q`; `~/.claude/evomem.md` wrongly documented the tool arg as `q`).

## Architecture (how it is wired)

- MCP server entry in `~/.claude.json` -> `mcpServers.evomem`: `/usr/bin/python3 /home/moo/evomem-bridge/mcp_server.py`, env `EVOMEM_URL=http://192.168.50.200:7700`.
- The bridge is a thin FastMCP wrapper doing `urllib` HTTP calls to the Rust server (`evomem 0.4.2`) on host `home` (192.168.50.200, ssh alias `home`, user moo with sudo). The bridge had a hard-coded **30 s** `urlopen` timeout; its `except Exception` turns that into the string `error: timed out`.
- Server: `evomem.service` (NixOS), `evomem --knowledge /root/evomem-kb serve --host 0.0.0.0 --port 7700`. KB lives on an iSCSI ext4 volume (TrueNAS) mounted at `/root/evomem-kb`; SQLite DB `.evomem.db` (~527 MB, WAL ~80 MB).
- Hooks: `~/.claude/settings.json` runs `~/evomem-bridge/hooks/hook.py` which POSTs `/api/capture`; `sync_to_evomem.py` writes notes then POSTs `/api/sync`.

## Diagnosis (in order)

```bash
# reachability / health
curl -s -m 8 -o /dev/null -w "%{http_code} %{time_total}s\n" http://192.168.50.200:7700/health      # 200 0.0006s
curl -s -m 8 -o /dev/null -w "%{http_code} %{time_total}s\n" http://192.168.50.200:7700/api/stats   # 200 0.75s
ping -c2 192.168.50.200                                                                                # 0.2 ms, no loss
# search latency: repeat query = cached (0.0007s), any NEW query = ~5.2-5.5s, in every mode
curl -s -m 60 -o /dev/null -w "%{time_total}s\n" "http://192.168.50.200:7700/api/search?q=alpha%20zebra%20quux&limit=5"
# service state
ssh home 'uptime; systemctl status evomem; journalctl -u evomem -n 40 --no-pager'   # active, up since Sep 29, no errors, load ~0.8, 98% idle
# same cost without HTTP/network at all (so not network/VPN):
ssh home 'sudo /nix/store/*-evomem-0.4.2/bin/evomem --knowledge /root/evomem-kb --json search "foo bar baz1" --limit 3'   # real 5.27s, user 5.13s
```

Findings: service healthy, network fine, no lock held by the sync hook (`POST /api/sync` takes 0.4 s). But a search is **CPU-bound ~5.2 s of user time** even for a query with 0 hits, even via the local CLI. `strace -c` of the CLI showed ~88k `pread64` calls: it reads every chunk (embeddings are 512-dim `hash-v1-d512` BLOBs stored in the `chunks` table, 42,969 chunks; `word_index` has 8.1M rows) and brute-force scores them. Cost scales linearly with chunk count (auto-captured Claude/other sessions are ~95% of docs).

Then the key test, concurrency:

```bash
for i in 1 2 3 4 5 6; do (curl -s -m 90 -o /dev/null -w "par$i %{time_total}s\n" "http://192.168.50.200:7700/api/search?q=parallel%20test%20$i&limit=3") & done; wait
# par3 5.4s, par1 11.0s, par4 16.4s, par5 21.8s, par6 27.2s, par2 32.6s
```

The server handles requests **strictly serially** (one global DB/mutex) even with 8 cores. So N simultaneous callers (several Claude sessions, subagents, hermes bridges on the server itself, capture/sync hooks) wait ~N x 5.3 s. With >=6 queued requests the bridge's 30 s timeout fires. `think` costs the same (~5.5 s); `stats` ~0.75 s; capture/sync are fast but also queue behind searches.

## Dead ends ruled out

- Service down/hung: no, active since Sep 29, responds to /health in <1 ms.
- Network/VPN: no, LAN, 0.2 ms RTT; same slowness locally on the server.
- iSCSI/slow disk: no, `top` shows `wa 0.0`, time is user CPU, pages are cached.
- Sync hook holding a lock: `/api/sync` returns in 0.4 s with 0 changes.
- DB bloat/freelist: `pragma freelist_count`=0; WAL of 80 MB is not the cause (not touched/wiped).
- No cron on the box; hooks are per-event, not a 5 min job on the server.

## Fix applied

1. Bridge timeout raised from 30 s to 120 s (env override `EVOMEM_TIMEOUT`) in `/home/moo/evomem-bridge/mcp_server.py`:
   ```python
   DEFAULT_TIMEOUT = int(os.environ.get("EVOMEM_TIMEOUT", "120"))
   def _call(method, path, body=None, timeout=DEFAULT_TIMEOUT): ...
   ```
   Takes effect on next MCP reconnect (`/mcp` in Claude Code or new session).
2. `~/.claude/evomem.md`: documented `evomem_search(query, ...)` (not `q`) and the ~5 s / serialized behavior.
3. No data deleted, no service restart, no index rebuild.

## Verification

After the fix, `mcp__evomem__evomem_search(query="diskos theme change USB audio bug", limit=5)` returned 5 hits and `evomem_stats` returned 1072 docs / 42,971 chunks.

## Still open (root cause is structural)

- Each uncached query = ~5 s and grows with the KB. Real fixes need server-side work: parallel reads / read-only connection pool, an ANN or pre-filtered candidate set (e.g. restrict vector scan to BM25 candidates), or pruning/consolidating the ~800 auto-captured `sessions` docs. Those are changes to evomem itself or a destructive prune, so not done here.
- Avoid firing many evomem calls in parallel from agents.
