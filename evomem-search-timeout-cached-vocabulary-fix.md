---
type: troubleshooting
tags: [evomem, mcp, timeout, search, latency, sqlite, rust, nixos, homelab]
created: 2026-10-27
last_verified: 2026-10-27
status: resolved
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

Findings: service healthy, network fine, no lock held by the sync hook (`POST /api/sync` takes 0.4 s). But a search is **CPU-bound ~5.2 s of user time** even for a query with 0 hits, even via the local CLI. `strace -c` of the CLI showed ~88k `pread64` calls and the first guess was a brute-force embedding scan - **that guess was wrong** (see "Real root cause" below: 43k x 512 floats is milliseconds). Cost scales with `word_index` size (8.1M rows; auto-captured Claude/other sessions are ~95% of docs).

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

## Real root cause (found in the source) and the actual fix

The first pass blamed a brute-force vector scan. Reading the source (`txtsamu/evomem`, fork of `anvie/evomem`; prod runs upstream's prebuilt static musl release v0.4.2 via the `home-nixos` flake) showed the vector scan is cheap. The cost is in `src/search/lexical.rs` + `src/store/words.rs`, run on **every** search:

1. `Store::vocabulary()` = `SELECT DISTINCT w.word FROM word_index w JOIN chunks c JOIN docs p WHERE p.deleted_at IS NULL` - walks all 8.1M postings with two joins per row.
2. `resolve_word()` then called `stem(vw)` (allocating) on every vocabulary word for every query word, and `bounded_levenshtein` allocated two `Vec<char>` per candidate before its own length check.
3. The server holds one `Mutex<Store>`, so all of this is serialized across callers.

Fix (branch `perf/cache-lexical-vocabulary` in `txtsamu/evomem`, 4 files, +83/-25, no schema or data change):
- `Store::vocabulary()` returns a cached `Arc<Vec<VocabWord{word, stem}>>` (stems precomputed), invalidated in `replace_chunks_for_page`.
- Rebuild uses an index skip-scan instead of `DISTINCT`+joins:
  ```sql
  WITH RECURSIVE w(word) AS (
    SELECT MIN(word) FROM word_index
    UNION ALL
    SELECT (SELECT MIN(word) FROM word_index WHERE word > w.word) FROM w WHERE w.word IS NOT NULL)
  SELECT word FROM w WHERE word IS NOT NULL
  ```
  The cache may contain words that only exist in soft-deleted docs; harmless because postings/df are always read with the live-doc filter.
- Cheap char-length reject before the Levenshtein DP.

### How it was verified (no production data copied off the server)

Copying the KB DB to the workstation was blocked (it holds session transcripts), so benchmarking used a synthetic KB of the same shape:

```bash
# toolchain: podman, rust:1-bookworm image; sources in ~/sessions/2026-10-27-evomem-timeout/src/evomem
podman run --rm -v $PWD/src:/src:Z -v $PWD/cargo-home:/cargo:Z -v $PWD/build:/out:Z docker.io/library/rust:1-bookworm sh /out/build.sh   # cargo test (24 pass) + release build of old and new
python3 build/gen_kb.py data/synth-kb 1000            # 1000 docs -> 42,239 chunks, 897k-word vocabulary
build/evomem-old --knowledge data/synth-kb init && build/evomem-old --knowledge data/synth-kb sync   # ~100 s
build/evomem-{old,new} --knowledge data/synth-kb --json search "<q>" --limit 5                       # outputs byte-identical (cmp)
build/evomem-{old,new} --knowledge data/synth-kb serve --host 127.0.0.1 --port 779x                  # then curl timing
```

| | old | new |
|---|---|---|
| one-shot CLI search | 3.8 s | 0.65 s (includes the one-time vocabulary build) |
| server, uncached query | 3.8 s | 0.13 s (first query after start/write 0.65 s) |
| 6 concurrent queries, last finishes at | 22.7 s | 0.82 s |

A `capture` of a brand-new word was searchable immediately afterwards (cache invalidation works).

### Deploy (what prod runs now)

Prod builds evomem in `hosts/home/evomem.nix` of `txtsamu/home-nixos` with `fetchzip` of a static musl release zip.

```bash
# static build (musl) so it runs like the previous prebuilt binary
podman run ... rust:1-bookworm sh build/build-musl.sh        # apt musl-tools; rustup target add x86_64-unknown-linux-musl; cargo build --release --target x86_64-unknown-linux-musl
python3 -c "zip with a single file 'evomem' (mode 0755)"     # evomem-0.4.2-perf1-x86_64-unknown-linux-musl.zip
git push -u origin perf/cache-lexical-vocabulary             # in txtsamu/evomem
gh release create v0.4.2-perf1 <zip> --repo txtsamu/evomem --target perf/cache-lexical-vocabulary
# home-nixos: change src.url to the fork release, hash from the build error (nix-prefetch-url --unpack gave a DIFFERENT hash than fetchzip; use the "got:" value)
ssh home 'sudo nixos-rebuild dry-build  --flake github:txtsamu/home-nixos/evomem-perf-vocab-cache#home --refresh'
ssh home 'sudo nixos-rebuild switch     --flake github:txtsamu/home-nixos/evomem-perf-vocab-cache#home --refresh'   # restarts evomem.service, ~1 s
```

Before switching, confirmed the host ran exactly `main` (`nixos-version --configuration-revision` = 140ca7d), so only the evomem change was applied. Rollback: `ssh home 'sudo nixos-rebuild switch --rollback'` (generation 45 = old upstream binary).

Result on the live server (1072 docs / 43,072 chunks, 116k-word vocab): uncached search 0.27-0.64 s (was ~5.3 s); 6 concurrent queries all done in 1.6 s (was 33 s); stats unchanged.

Note: the system is currently built from branch `evomem-perf-vocab-cache` (PR txtsamu/home-nixos#9). Until that PR is merged, a rebuild from `main` would revert evomem to the slow upstream binary.

## Still open

- PR #9 (home-nixos) needs merging so `main` matches the running system.
- The serialization (one `Mutex<Store>`) is still there; it just matters far less at ~0.3 s/query. A read-only connection pool would make it fully parallel.
- The remaining ~0.1-0.3 s is the per-word `word_chunk_count` joins and the vector scan; the vocabulary scan could also use a BK-tree/FST for typo lookups.
- Upstream (`anvie/evomem`) has not been sent the patch.
- The second bridge copy at `/root/evomem-bridge/mcp_server.py` on home (hermes) still has the 30 s timeout; with ~0.3 s searches it no longer matters.
- Dead end noted: avoid `pkill -f`/`pgrep -f` with a pattern that also appears in your own command line - it kills the invoking shell.

- Each uncached query = ~5 s and grows with the KB. Real fixes need server-side work: parallel reads / read-only connection pool, an ANN or pre-filtered candidate set (e.g. restrict vector scan to BM25 candidates), or pruning/consolidating the ~800 auto-captured `sessions` docs. Those are changes to evomem itself or a destructive prune, so not done here.

## References

- Source (fork): https://github.com/txtsamu/evomem (branch `perf/cache-lexical-vocabulary`, release `v0.4.2-perf1`)
- Upstream: https://github.com/anvie/evomem
- Deploy config: https://github.com/txtsamu/home-nixos (`hosts/home/evomem.nix`, PR #9)
