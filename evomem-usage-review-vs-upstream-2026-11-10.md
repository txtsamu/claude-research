---
type: investigation
tags: [evomem, evonic, knowledge-base, claude-code-hooks, review]
created: 2026-11-10
last_verified: 2026-11-10
status: findings-only (no changes made)
---

# evomem: is our usage correct? (review against anvie/evomem and anvie/evonic)

## Time estimate

About 10 minutes of tool calls (measured, one session): repo reads about 2 min, local hook and server inspection about 5 min, write-up about 3 min. No fix was applied.

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

## Suggested changes (none applied)

1. Stop writing full tool output into the KB: summarize each session to prompts plus a short outcome, or store transcripts outside the KB directory.
2. Add `description` to generated notes and use `type: note` (or move them under a workspace `index.md` as upstream expects); run `evomem validate --all`.
3. Escape or strip leading `>` from transcript text so it cannot create typed edges.
4. Sync only changed files and not while a session note is still being appended (for example at session end only), and raise the sync client timeout above the worst-case sync duration.
5. Decide whether the 13 `mcp_server.py` processes on `home` are still needed.

## References

- https://github.com/anvie/evomem (README, `src/server/mod.rs`, `src/validate.rs`, `src/capture.rs`, `src/cli.rs`)
- https://github.com/anvie/evonic (README, memory engine section)
- Related local write-ups: [evomem-utcp-endpoint-fork-and-deploy.md](evomem-utcp-endpoint-fork-and-deploy.md), [evomem-search-timeout-cached-vocabulary-fix.md](evomem-search-timeout-cached-vocabulary-fix.md)
