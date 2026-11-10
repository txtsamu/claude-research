---
type: investigation
tags: [evomem, evonic, knowledge-base, claude-code-hooks, review]
created: 2026-11-10
last_verified: 2026-11-10
status: implemented 2026-11-10 (Hermes plugin v0.2.0 live in log-only mode; evomem MCP bridge still configured)
---

# evomem: is our usage correct? (review against anvie/evomem and anvie/evonic)

## Time estimate

Review: about 10 minutes (measured). Implementation: launched 14:35 WIB, backup 2 s, four parallel agents (measured: hook 24 s, KB migration 2 min, recall/tools 10.6 min, writer/distiller 19 min), gateway restarted 14:58, verified with a real chat 15:03, so about 28 minutes in total. The planned 15 minutes was optimistic: the writer/distiller agent set the pace, and the gateway needs about 4 minutes to reconnect after a restart (measured; earlier restarts took 1.5 to 3.7 minutes).

## Question

Compare how this setup uses evomem (server on `home`, fork build v0.4.2-utcp1, Claude Code hooks writing session notes into the KB) with what the upstream repos say, and say what is wrong or suboptimal.

## What was checked, in order

```bash
# upstream metadata + READMEs
gh api repos/anvie/evomem --jq '{description,default_branch,pushed_at,license:.license.spdx_id}'
gh api repos/anvie/evonic --jq '{description,default_branch,pushed_at,license:.license.spdx_id}'
gh api repos/anvie/evomem/readme --jq .content | base64 -d
gh api repos/anvie/evonic/readme --jq .content | base64 -d
# upstream source: server routes, capture, validate, CLI
gh api repos/anvie/evomem/contents/src/server/mod.rs --jq .content | base64 -d
gh api repos/anvie/evomem/contents/src/validate.rs    --jq .content | base64 -d
gh api repos/anvie/evomem/contents/src/capture.rs     --jq .content | base64 -d
# local side
cat ~/evomem-bridge/hooks/hook.py ~/evomem-bridge/sync_to_evomem.py
ssh moo@home 'sudo du -sh /root/evomem-kb/*; sudo ls -l /root/evomem-kb/.evomem.db*'
curl -s http://192.168.50.200:7700/api/stats
```

Upstream facts:
- anvie/evomem (last push 2026-07-20, no LICENSE file on GitHub although the README says MIT): "a directory of markdown files → hybrid lexical + hash-vector + typed-graph search, no LLM at query time". Disk is the source of truth; `sync` re-indexes; `capture` writes `inbox/<stamp>-<slug>.md` with `type: note` and indexes it at once. Benchmarks: 1,000 pages is a 26 MB DB, search about 40 ms.
- REST routes upstream: `/health`, `/api/search`, `/api/think`, `/api/graph`, `/api/stats`, `/api/docs/{slug}`, `/api/capture`, `/api/sync`. The CLI also has `--server <url>` and `--json`, plus a `validate` command (title, description, type in a fixed list, soft-warn only).
- anvie/evonic (AGPL-3.0, pushed 2026-11-07) is a separate agent platform that embeds Evomem as its per-agent "memory engine" (FTS5 fallback). Only its README was read; it was removed from `home` on 2026-11-06 and is not part of the current setup.

## Findings

**Used correctly**
- The server, REST endpoints, search modes, `capture` and `sync` match upstream. The KB is markdown on disk plus a `.evomem.db` index, as designed.
- The fork's `/utcp` manual and the `evomem` wrapper script are additions on top of the upstream API, not misuse. Upstream's own CLI (`evomem --server http://host:7700 search ...`) does the same job; the wrapper's `doc` and `graph` map to upstream `page` and `graph-query`.

**Not how upstream intends it**
1. Raw transcripts as the bulk of the KB. `sync_to_evomem.py` writes one note per Claude Code session (all prompts and up to 4000 chars of every tool result). Result: 878 `sessions` + 299 `claude` docs out of 1,233 (96%), 54,176 chunks, a 693 MB DB plus an 80 MB WAL. Upstream's benchmark is 26 MB for 1,000 curated pages. `claude/` alone is 64 MB, with single notes of 3-5 MB. This dilutes search and makes every sync heavier.
2. Frontmatter does not meet upstream's own standard. The generated notes have `title`, `type: session`, `created`, `aliases` but no `description`. `evomem validate` requires title, description and type, and reserves `session`/`group` for workspace `index.md` docs. This is only a soft warning upstream. `evomem validate --all` was not run.
3. Typed-link syntax inside transcripts. Upstream parses `> key: value` blockquote lines as typed edges. Transcript text contains such lines, and stats show 1,627 `mentions` links, 1,269 dangling links and only 2 meaningful edges. The cause was not proven; it is the likely source.
4. Whole-KB sync under one lock. In upstream `src/server/mod.rs` every handler (`search`, `stats`, `sync`, ...) takes `lock(&app.store)`, so a running `/api/sync` blocks all reads. The hook and its safety-net sync call `/api/sync` with a 30 s client timeout; the server keeps working after the client gives up. Live session notes are rewritten on every sync, so the largest, most-changing files are re-chunked each time.

**The earlier "evomem is hung" observation**
At the start of the session `/api/stats` and `/api/search` timed out at 60 s while `/health` was fine. About 20 minutes later they answered normally (stats 1.2 s, search 0.5 s). During the outage the DB WAL was being written (mtime within seconds) and `last_synced_at` in stats (07:18:31 UTC) matched that write. So the timeouts were most likely a long sync holding the store mutex, not a dead service. Not directly proven: the lock was not observed. Correction to an earlier chat remark: `ps` showed 0.0% CPU and 6 MB RSS, but `%CPU` in `ps` is a lifetime average and does not show current load, so that was not evidence of idleness.

**Correction (found during implementation)**
All 12 hook entries in `~/.claude/settings.json` call `hook.py` with no event argument, so the event is always "unknown" and `session-end` (the only caller of `trigger_sync`) never fired from Claude Code. The notes were pushed by a Hermes cron job, `evomem-claude-sync` (every 5 min, `/root/.hermes/cron/jobs.json`), which rsynced the JSONL from fedora and ran `sync_to_evomem.py`. The mirror step of that job (`mirror_claude_research.py`, hardlinking claude-research docs into the KB) is wanted and was left running.

**Other observation**
- `home` runs 13 long-lived `/root/evomem-bridge/mcp_server.py` processes (12 started 3.5 days ago at boot, one 1 day ago). MCP was removed on the fedora side on 2026-11-06, but these come from the Hermes side; whether they are needed or leaked was not checked.

## Addendum: how Hermes memory works and how it is wired to evomem

Commands run (read-only) on `home`:

```bash
ssh moo@home 'sudo grep -n -i -E "evomem|memory" /root/.hermes/config.yaml'
ssh moo@home 'sudo cat /root/.hermes/plugins/evomem/__init__.py'
ssh moo@home 'sudo sed -n 1,90p /opt/hermes-source/agent/memory_provider.py'
ssh moo@home 'sudo wc -c /root/.hermes/memories/MEMORY.md /root/.hermes/memories/USER.md'
gh api repos/anvie/evonic/contents/backend/agent_runtime/evomem_writer.py --jq .content | base64 -d
```

Hermes memory:
- Built-in store: `~/.hermes/memories/MEMORY.md` (limit 4000 chars, currently 4048 bytes) and `USER.md` (limit 1375), injected into every session, writes need approval (`write_approval: true`).
- On top of that, exactly one external provider plugin (`memory.provider`), with hooks: `system_prompt_block`, `prefetch` (per-turn recall injected into the prompt), `get_tool_schemas`/`handle_tool_call`, `sync_turn`, `on_memory_write`, `on_pre_compress`, `on_session_end`. Bundled providers: byterover, retaindb.
- Current setup: `memory.provider: evomem` is a user plugin (`~/.hermes/plugins/evomem/__init__.py`) that is capture-only. It appends every turn (user 500 chars, assistant 2000 chars) and every memory write to JSONL, then runs `sync_to_evomem.py`, which turns the JSONL into one markdown note per session and calls `/api/sync`. `prefetch` and `system_prompt_block` return "" and it exposes no tools, so Hermes never gets evomem recall automatically. Search and capture go through a separate MCP server (`mcp_servers.evomem` -> `/root/evomem-bridge/mcp_server.py`), which is why `home` has many of those processes.

How the author's own agent platform (Evonic) uses evomem (`evomem_writer.py`):
- Curated docs, not transcripts: frontmatter with `title`, `type`, `description`, `tags`, `aliases`, `created`, `updated`.
- Relationships as inline `[[Doc Title]]` wiki-links inside sentences; entities are just docs with `type: place|person|...`.
- `session`/`group` only for collection `index.md` files; a standalone doc is coerced to `note`.
- Atomic file writes, then a debounced (5 s) `sync`; one evomem per agent; FTS5 fallback if evomem is down; a "KB Organizer" sub-agent extracts entities, dedups and links after conversations.
- Evonic is AGPL-3.0, so copying its code has licence consequences; re-implementing the idea does not.

### Second memory system on Hermes, and does `hermes update` remove it?

Checked in `/opt/hermes-source` (read-only, source reading only; no `hermes update` was run):

```bash
ssh moo@home 'sudo grep -n -i -E "one external|already registered" /opt/hermes-source/agent/memory_manager.py'
ssh moo@home 'sudo sed -n 1,60p /opt/hermes-source/plugins/memory/__init__.py'      # loader order
ssh moo@home 'sudo sed -n 1,40p /opt/hermes-source/hermes_cli/memory_provider_migration.py'
ssh moo@home 'cd /opt/hermes-source && sudo git status --short'                     # empty = no local patches
```

- Built-in MEMORY.md/USER.md is always on, plus at most ONE external provider (`memory_manager.py`: "Only one external memory provider is allowed"). evomem as the external provider is therefore already the "second" system. A different external provider (byterover, honcho, ...) cannot run at the same time; evomem would have to drop to MCP-only (`mcp_servers.evomem`, which does not use the provider slot but gives no automatic capture or prefetch).
- Update safety: the plugin lives in `/root/.hermes/plugins/evomem/` (outside the git checkout and venv), the `mcp_servers` entry and `plugins.enabled` live in `config.yaml`, and the bridge scripts live in `/root/evomem-bridge/`. `hermes update` only rewrites the source tree and venv; its `rmtree` calls act on recovery staging dirs. `memory_provider_migration.py` only acts on a fixed list of providers that left core (`hindsight, honcho, mem0, supermemory, openviking, retaindb, byterover, holographic`), and evomem is not in it. `/opt/hermes-source` has no local patches.
- Remaining risks: a future change to the `MemoryProvider` interface could break the plugin (it would fail to load, not be deleted); a bundled provider named `evomem` would shadow the user plugin (loader order: bundled, then user); the hard-coded `/root/evomem-bridge` paths must stay.

## Implementation (2026-11-10)

Backup first (2 s): `/root/evomem-backups/hermes-curation-20261110-143511/` on `home` holds the old plugin (`plugin-replaced/`), `config.yaml` (and `.pre-deploy`), the hook scripts, `kb-markdown.tgz` (all KB markdown), `old-db/` and `crawl4ai-removal/`.

1. KB migration (11 s downtime, rebuild 6 s, measured). `sync_to_evomem.py` on `home` replaced by a no-op (original `.orig-20261110`); `sessions/` (878) and `claude/` (299) moved to `/root/evomem-archive/` (README there has the rollback); stopped `evomem.service`, moved `.evomem.db*` away, `evomem --knowledge /root/evomem-kb init` then `sync`, started the service. Result: docs 1233 -> 56, chunks 54232 -> 514, DB 694 MB (+80 MB WAL) -> 5.2 MB, dangling links 1276 -> 33. `validate --all`: 38 invalid (34 `claude-research` docs lack `title`/`description`, 4 `lessons` lack `description`); not fixed.
2. Claude Code hook on fedora: `trigger_sync()` in `~/evomem-bridge/hooks/hook.py` returns unless `EVOMEM_HOOK_SYNC=1` (original `hook.py.orig-20261110`).
3. New Hermes plugin v0.2.0 in `/root/.hermes/plugins/evomem/` (`__init__.py`, `recall.py`, `tools.py`, `writer.py`, `distill.py`, `plugin.yaml`; sources in `~/sessions/2026-11-10-evomem-usage-check/build/plugin/`):
   - `prefetch()` runs a bounded (1.2 s) background search for the current query and injects hits; hits tagged only `weak_semantic` are dropped, because on a small KB the hash-vector matches outrank real keyword matches (measured: `weak_semantic` scored 0.041 vs 0.035 for a `keyword_exact` hit).
   - Tools `evomem_search/think/graph/doc/capture` call the REST API directly with short timeouts.
   - `on_session_end` and `on_pre_compress` distil the conversation with the auxiliary model (`auxiliary.evomem_distill`, deepseek-flash, added to `config.yaml`) into curated docs (description, tags, inline `[[links]]`, secrets redacted, `> key:` lines neutralized); trivial sessions (under 2 user turns or 300 characters) are skipped. `EVOMEM_WRITE_MODE=log` (default) writes proposals to `/root/evomem-proposed/` only; set `live` to write into the KB.
   - Subagent, cron and flush contexts do nothing. No raw transcripts are stored.
4. Gateway: `systemctl restart hermes-gateway.service` at 14:58; fully connected 15:02:33 (3 platforms).
5. Verification: 66 + 76 unit tests, plus a local smoke test against production (read-only), plus a 10.2 s end-to-end distill with the real model on `home` (two valid docs, KB unchanged), plus a real `hermes chat -Q` that called `evomem_search` through the plugin (0.02 s) and logged `Memory provider 'evomem' registered (5 tools)`.
6. crawl4ai MCP server removed on request from the main `config.yaml` (it was `enabled: false`) and the 11 profile configs (it was enabled there and retried every 20 s against an unreachable host since 2026-10-25); each file parsed as valid YAML afterwards and the other MCP servers are unchanged. Takes effect at the next gateway restart.

Remaining / next: review `/root/evomem-proposed/` for a few real sessions, then set `EVOMEM_WRITE_MODE=live` for the gateway (systemd environment) and remove `mcp_servers.evomem` (and the stdio bridge) from the configs once the plugin tools are trusted; the 13 `mcp_server.py` processes belong to `hermes-mcp.service` (pre-warmed bridge). Rollback of the plugin: put `plugin-replaced/` back as `/root/.hermes/plugins/evomem` and restart the gateway.

## Follow-up: bridge removal, MCP audit, Cloudflare token (2026-11-10, later)

- Removed `mcp_servers.evomem` (the stdio bridge) from all 12 Hermes configs and replaced the old transcript-recording plugin copy that each of the 11 profiles carried in its own `profiles/<name>/plugins/evomem/` with the new plugin (user plugins are profile-scoped); added `auxiliary.evomem_distill` to each profile (copy of that profile's `memory_query_rewrite` settings, timeout 90). Backups: `/root/evomem-backups/hermes-curation-20261110-143511/bridge-removal/`. Gateway restarted 15:06:23, reconnected 15:07:16 (about 53 s; the earlier 4-minute starts were dominated by retries against the unreachable crawl4ai host). Verified with real `hermes chat -Q` calls in the default and `dev` profiles: `Memory provider 'evomem' registered (5 tools)`, `evomem_search` 0.02 s, no `evomem-bridge/mcp_server.py` processes left.
- MCP audit (Hermes session DB `state.db`, messages with `tool_name like 'mcp%'`, history since 2026-05-07): mikrotik 68 calls (53 in last 30 days), camofox 573 (156), truenas 19 (15), proxmox 224 (last 2026-09-25), cloudflare 5 (last 2026-08-19), notion 0, gowa 0. Per-server health (`hermes mcp test <name>`, then one read-only call through the MCP client on `home`): all 7 connect; mikrotik, proxmox, notion return real data; cloudflare returned 401 (invalid token, also invalid for the separate Claude Code config); truenas REST API returns HTTP 500 for every endpoint including `core/ping` (NAS-side problem, MCP server is fine); gowa answers but `logged_in=false`.
- Cloudflare: a new user API token was supplied and written to all 12 Hermes configs and the Claude Code project config (backups: `.../cf-token-update/`, `~/sessions/2026-11-10-evomem-usage-check/claude.json.pre-cf-token`). Token check: `/user/tokens/verify` active, can read zones and list tunnels, but 401 on Workers KV and 403 on account read, so tools needing those scopes still fail. The Cloudflare MCP server returns zone data, but its results use a non-standard wrapper that the Python MCP SDK rejects; Hermes's own client was not tested. Gateway needs a restart to pick up the new env.
- The token was pasted into chat, so it also reached the local hook log (`~/evomem-bridge/hooks/data/sessions/*.jsonl`, copied to `home` by the Hermes cron). Scrubbed from those files on both machines; it remains in the Claude Code session transcript.
- Commands: see the probe scripts in `~/sessions/2026-11-10-evomem-usage-check/build/smoke/` (`mcp_calls2.py`, `mcp_probe.py`, `mcp_probe2.py`, `tn_probe.py`, `cf_check.py`, `set_cf_token.py`, `rm_bridge.py`).

## Suggested changes (status)

1. Stop writing full tool output into the KB: summarize each session to prompts plus a short outcome, or store transcripts outside the KB directory.
2. Add `description` to generated notes and use `type: note` (or move them under a workspace `index.md` as upstream expects); run `evomem validate --all`.
3. Escape or strip leading `>` from transcript text so it cannot create typed edges.
4. Sync only changed files and not while a session note is still being appended (for example at session end only), and raise the sync client timeout above the worst-case sync duration.
5. Decide whether the 13 `mcp_server.py` processes on `home` are still needed.

## References

- https://github.com/anvie/evomem (README, `src/server/mod.rs`, `src/validate.rs`, `src/capture.rs`, `src/cli.rs`)
- https://github.com/anvie/evonic (README, memory engine section)
- Related local write-ups: [evomem-utcp-endpoint-fork-and-deploy.md](evomem-utcp-endpoint-fork-and-deploy.md), [evomem-search-timeout-cached-vocabulary-fix.md](evomem-search-timeout-cached-vocabulary-fix.md)
