---
type: investigation
tags: [evomem, mcp, iscsi, truenas, home, claude-code, hooks, latency, pydantic]
created: 2026-11-06
last_verified: 2026-11-06
status: current: server healthy, the recurring failures were client-side and a since-fixed latency tail; two items still open (Nov 2 iSCSI timeout, cold-cache first query)
---

# Why evomem "often failed" (diagnosis)

Request: ssh to the NixOS box `home` and find out why evomem often fails. Follow-up: [evomem-utcp-endpoint-fork-and-deploy.md](evomem-utcp-endpoint-fork-and-deploy.md) replaced the MCP bridge with UTCP.

## Verdict

The server was not crashing. The "failures" were four different things seen from the Claude Code side.

| # | Failure | Evidence | Status |
|---|---|---|---|
| 1 | Model calls `evomem_search` with `q` instead of `query` | 9 `validation error for evomem_searchArguments / query Field required` in the MCP logs (Sep 2 to Oct 27) | Fixed: server now accepts `query` as an alias, CLI takes positional words |
| 2 | Slow searches (10-30 s, some hitting the client timeout) | Search latency log below: worst days Oct 21-29 | Fixed 2026-10-27 by the cached-vocabulary build; no search above 10 s since Oct 31 |
| 3 | MCP bridge failed to start once | 2026-10-31 05:02: client closed the stdio server during `import mcp` (pydantic schema build, `KeyboardInterrupt` in the traceback) | One-off; startup is 0.4 s now. Moot after removing the bridge |
| 4 | iSCSI blip | `journalctl -k`: Nov 2 04:34 `ping timeout of 5 secs expired ... detected conn error (1022)` on every iSCSI connection at once | Open: single event, root cause not found |

## Step by step

### 1. Is the service up? (about 1 min)

```bash
ssh <USER>@home 'uptime; systemctl status evomem.service --no-pager | head -25; ss -ltnp | grep 7700'
ssh <USER>@home 'systemctl show evomem.service -p NRestarts -p ExecMainStartTimestamp -p Result'
```

Result: active since Oct 27 12:18, `NRestarts=0`, `Result=success`, 148 MB RSS. Not crashing. `journalctl -u evomem` is empty because the server logs only its listen line.

The data sits on a TrueNAS iSCSI LUN mounted at `/root/evomem-kb` (ext4 on `/dev/sdb`, `_netdev`), DB `.evomem.db` 650 MB + 80 MB WAL.

### 2. Kernel log for OOM / iSCSI / IO errors

```bash
ssh <USER>@home 'sudo journalctl -k --since "7 days ago" | grep -iE "oom|iscsi|connection[0-9]|I/O error|EXT4|blocked for"'
```

- Nov 2 04:34:38-42: iSCSI `ping timeout of 5 secs` on connections 1..49 simultaneously (every iSCSI session on the host, the k3s democratic-csi volumes included, not just evomem). Recovery timeout is 120 s so the filesystem stayed mounted; evomem did not restart.
- Nov 5 21:49: OOM kill of `victoria-metric` in a kubepods cgroup. Unrelated to evomem.
- Host memory was tight (15 GiB, 7.6 used, 3 GiB swap in use), which matters for the cold-read question below.

### 3. Server-side latency probe

```bash
ssh <USER>@home 'for i in $(seq 15); do curl -s -o /dev/null -w "%{http_code} %{time_total}\n" 127.0.0.1:7700/health; done'
# the search route is /api/search?q=... (my first guess /search was a 404)
ssh <USER>@home 'curl -s -o /dev/null -w "%{time_total}\n" -G --data-urlencode "q=caddy reverse proxy" 127.0.0.1:7700/api/search'
```

`/health` 0.4 ms. Uncached search 0.27-0.8 s, but the very first query after a long idle took 11.5 s (cold). Six concurrent uncached queries finished in 0.3 to 2.1 s (they serialize, no failures). IO pressure `some avg300` about 1.7 %.

### 4. Client side: the MCP logs on the Fedora machine

Claude Code keeps per-project logs in `~/.cache/claude-cli-nodejs/<project>/mcp-logs-evomem/*.jsonl`. The directory names start with `-`, so use `./` prefixes with `ls`/`cat`.

```bash
cd ~/.cache/claude-cli-nodejs
cat ./*/mcp-logs-evomem/*.jsonl | python3 -I -c '...count lines matching error|fail|timeout...'
```

Counts across 1030 log lines: 81 harmless client protocol-probe warnings (`Failed to validate request ... server/discover`), 75 `SIGINT failed, sending SIGTERM` (normal shutdown), 9 real tool failures (all the `q`/`query` mismatch), 5 `version negotiation probe closed the stdio server` (the 10-31 startup crash).

Search call durations parsed from `Tool 'evomem_search' completed successfully in Ns`:

(Counts include the failed calls; per-day numbers come from the parsed log lines.)

| Period | Searches | Over 10 s | Max |
|---|---|---|---|
| Sep | 10 | 0 | 9 s |
| Oct 5-20 | 22 | 4 | 21 s |
| Oct 21-29 | 35 | 9 | 30 s |
| Oct 31 and Nov 5 | 9 | 0 | 8 s |

The bridge's own comment explains the 30 s ceiling: upstream evomem serialized requests and an uncached search cost about 5.3 s CPU, so six queued callers hit a 30 s timeout. The fork build with the cached lexical vocabulary (deployed 2026-10-27) fixed that.

### 5. Smoke test of the old bridge

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}' \
  | EVOMEM_URL=http://192.168.50.200:7700 timeout 20 /usr/bin/python3 ~/evomem-bridge/mcp_server.py | head -c 150
```

Startup plus initialize: 0.40 s, three runs. Do not use `python3 -I` here: `mcp` lives in the user site and `-I` hides it (`ModuleNotFoundError`), which looked like a failure but was my flag.

## Cold-cache test (2026-11-06, after the UTCP deploy)

Evict only the DB file from the page cache (clean pages, one file), then time uncached searches on home over loopback:

```bash
DB=/root/evomem-kb/.evomem.db
sudo fincore $DB                                   # resident before
sudo dd of=/dev/null if=$DB iflag=nocache count=0  # fadvise DONTNEED on this one file
curl -s -o /dev/null -w "%{time_total}\n" -G --data-urlencode "q=iscsi timeout nas" 127.0.0.1:7700/api/search
sudo dd if=$DB of=/dev/null bs=1M                  # sequential read speed of the cold file
sudo python3 -c "...select name, sum(pgsize) from dbstat group by name..."   # table sizes
```

| Measurement | Result |
|---|---|
| Fully evicted, first new query | **11.5 s**; DB resident again 0 to 525 MB of 625 MB; IO pressure `some avg10` 22 % |
| Same query again (server LRU cache) | 0.4 ms |
| Another new query right after | 0.26 s |
| "Warm" control that started with 470 of 625 MB resident | 3.3 s (the missing 155 MB had to be read) |
| Sequential read of the cold file | 5.6 s = 117 MB/s (the iSCSI link is fine) |

Reading it: a search touches almost the whole DB (`chunks` 215 MB with the embeddings, `word_index` 207 MB, `idx_word_index_chunk` 201 MB). Cold, the access is not sequential: about 46 MB/s effective versus 117 MB/s sequential, so 11.5 s instead of about 5 s. The vocabulary cache from the perf build removed the CPU scan, not this I/O. Nothing protects the cache (`MemoryLow=0`, host has 15 GiB with 3 GiB swapped), and every restart (including each deploy) also starts cold. Whenever the page cache gets squeezed, the next search pays 3 to 12 s, which matches the remaining slow tail in the MCP logs.

Options, none applied: (a) a systemd timer on home that runs `cat $DB > /dev/null` every few minutes (5.6 s of sequential read, keeps it resident) plus an `ExecStartPost` warm-up; (b) `MemoryLow=900M` on `evomem.service` so reclaim takes other cgroups' pages first (untested whether it holds under the k3s memory pressure); (c) both.

## Side findings

- The Claude Code hooks in `~/.claude/settings.json` run `python3 .../hooks/hook.py` with no event argument, so every event is recorded as type `unknown` and `session-end` never triggers the fast sync (the 5-minute cron is what actually ingests sessions). Not fixed, not the cause of the failures.
- `home-nixos` main pinned upstream evomem 0.4.2 while production ran the fork perf build from a branch (PR #9 closed unmerged). See the deploy doc.

## Still open

1. ~~The 11.5 s cold first query~~ **Explained 2026-11-06** (see "Cold-cache test" below). Remaining decision: add a page-cache warmer / `MemoryLow` for `evomem.service` (not applied).
2. What caused the Nov 2 04:34 iSCSI ping timeout (TrueNAS side logs, network, or a NAS job at that hour). Check TrueNAS `/var/log/messages` around 04:30 and any scrub/snapshot task schedule.

## References

- [UTCP vs MCP](https://utcp.io/0.1/utcp-vs-mcp), used for the follow-up decision rather than the diagnosis.
