---
type: investigation
tags: [evomem, claude-code, hooks, utcp, knowledge-base, capture, rtk, auto-mode]
created: 2026-11-10
last_verified: 2026-11-10
status: current
---

# Why evomem "doesn't work well with Claude" (2026-11-10)

Question from the user during a diskOS session: "investigate why evomem seems not work well with claude". Background reading: [[evomem-usage-review-vs-upstream-2026-11-10]] (the KB rebuild), [[evomem-mcp-failures-diagnosis]], [[evomem-search-timeout-cached-vocabulary-fix]], [[evomem-utcp-endpoint-fork-and-deploy]].

## Time estimate

Measured: the investigation subagent took about 2.2 minutes (134 s, 28 tool calls); my spot-check of its main claims took about 1 minute. Fixes are not applied; see "Proposed fixes" (each is a few minutes of edits, the mirror fix depends on access to the homelab host).

## Bottom line

The server and the `evomem` CLI work. The problem is the content and the instructions around it:

1. The KB was rebuilt on 2026-11-10 from 1233 docs down to 58, and nothing from Claude Code sessions is captured any more, while `~/.claude/evomem.md` still says all sessions are auto-captured every 5 minutes.
2. The claude-research mirror in the KB is stale (34 of 202 local docs indexed, none newer than about 2026-10-05).
3. When nothing matches, search returns unrelated `weak_semantic` hits as if they were answers.
4. Minor: `evomem` calls batched with commands the rtk hook rewrites get refused by auto mode.

## Evidence

### 1. Query path is healthy (ruled out as the cause)

```bash
evomem stats                         # 0.058 s: docs 58, chunks 516, words 6512, dangling_links 33
                                     # docs_by_source: claude-research 34, inbox 20, lessons 4 (no "sessions")
evomem search talos cluster          # 0.054-0.068 s, right docs, keyword_exact / exact_title_match on top
curl http://192.168.50.200:7700/health   # {"status":"ok"} in 0.6 ms; /api/stats 10 ms; /utcp manual_version 0.4.2
```

The earlier cold-search timeout (see [[evomem-search-timeout-cached-vocabulary-fix]]) does not reproduce.

### 2. Capture path is broken for Claude Code (ranked first)

- The KB was gutted on purpose 14:35-14:58 WIB: 878 `sessions` and 299 `claude` docs moved to `/root/evomem-archive/` on home, and the Hermes cron job `evomem-claude-sync` (the only thing pushing fedora transcripts) was replaced by a no-op ([[evomem-usage-review-vs-upstream-2026-11-10]]).
- All 12 hook entries in `~/.claude/settings.json` run `python3 /home/moo/evomem-bridge/hooks/hook.py` with no event argument (verified: `grep -c` = 12). Every event is recorded as type `unknown`; this session's file under `~/evomem-bridge/hooks/data/sessions/` had 29 records, all `unknown` (reported by the subagent).
- `hook.py` was edited today (14:37) so transcript sync only runs with `EVOMEM_HOOK_SYNC=1` (verified: header comment says "trigger_sync is OFF by default"). The variable is unset.
- Result: 185 files / 56 MB of raw tool output pile up in `~/evomem-bridge/hooks/data/sessions` and go nowhere.
- `~/.claude/evomem.md` still claims "ALL Claude Code sessions ... are auto-captured into it via hooks every 5m". False since today, so Claude trusts evomem for history, finds none, and looks broken. The only write path left is explicit `evomem capture`.

### 3. claude-research mirror is stale (cause unverified)

- Local `~/claude-research`: 202 `.md` files (newest 2026-11-10 16:46). KB: 34 claude-research docs.
- Indexed docs the subagent found have local mtimes only up to 2026-10-05; about 98 newer local docs were not seen. `evomem doc` returned 404 for `evomem-usage-review-vs-upstream-2026-11-10`, `evomem-search-timeout-cached-vocabulary-fix`, `evomem-mcp-failures-diagnosis`, `diskos-strip-comments`.
- 4 indexed slugs have no local file (written on another host).
- The usage-review doc said `mirror_claude_research.py` was left running on home; nobody logged in to check, so whether it runs is unknown.
- `validate --all` reported 38 invalid docs (missing `title`/`description`).

### 4. `weak_semantic` noise (confirmed, reproduced)

```bash
evomem search snowsky disc debug --limit 3
# -> 3 hits, all weak_semantic and unrelated (ssh -vvv timing, podman->k8s plan, llama-server tok/s)
```

The CLI neither filters nor warns, and `evomem think` does the same. Absent content therefore looks like a bad answer instead of "not found".

### 5. Claude-side interference

- The rtk hook does not rewrite `evomem` commands (subagent piped sample PreToolUse JSON into `rtk hook claude`: `evomem search talos` unchanged; `ls /tmp` became `rtk ls /tmp`).
- The auto-mode refusals ("a hook changed this call's input", "another call in this response was changed") hit any Bash call the hook rewrites; the other Bash calls in the same parallel response are refused too. Seen several times in this very session (it also hit the plain `ssh` and `evomem search` calls batched next to rtk-rewritten ones). Collateral of batching, not an evomem fault.
- No `Bash(evomem:*)` allow rule in `settings.local.json`: it works only because auto mode approves it. Stale `mcp__evomem__*` entries remain (harmless since the MCP server was removed).
- `~/.claude/CLAUDE.md` imports `RTK.md` and `evomem.md`, both exist; the `evomem` skill is listed with an adequate trigger. Whether Claude follows "search first" was not measured.

## Dead ends ruled out

Server down or slow; cold-search timeout; stale cached vocabulary; the rtk hook rewriting `evomem` commands; instruction files failing to load.

## Proposed fixes (none applied, need the user's decision)

1. Choose one capture strategy for Claude Code: (a) pass the event to the hook (`hook.py session-start`, `prompt-submit`, `post-tool-use`, `session-end`) plus a curated distill step like Hermes's instead of raw transcripts; or (b) drop the hooks and rely on explicit `evomem capture` at the end of non-trivial sessions, with a rule in CLAUDE.md.
2. Rewrite `~/.claude/evomem.md` and the skill text: no auto-capture, history before 2026-11-10 is archived, capture is manual, treat `weak_semantic`-only results as "not found".
3. Fix the mirror: on home check whether `mirror_claude_research.py` is still scheduled and that `/root/evomem-kb/claude-research` is populated from `~/claude-research`; add `title`/`description` frontmatter; re-sync.
4. Make the CLI drop `weak_semantic`-only hits by default or print "no strong match" (the Hermes plugin already does).
5. Add `Bash(evomem:*)` to the allow list; remove stale `mcp__evomem__*` entries.
6. Do not batch `evomem` with commands the rtk hook rewrites.

Not inspected: home's cron/mirror state, server logs, the archive.

## Commands used (all read-only)

`evomem stats | search | doc | think | tools`; `curl` GET of `/health`, `/api/stats`, `/utcp`; `rtk hook claude` fed sample JSON; reads of `~/.claude/settings.json`, `settings.local.json`, `evomem-bridge/hooks/hook.py` (+ diff against `hook.py.orig-20261110`), the evomem skill; `crontab -l`, `systemctl --user list-timers`.

## References

- Internal: [[evomem-usage-review-vs-upstream-2026-11-10]], [[evomem-mcp-failures-diagnosis]], [[evomem-search-timeout-cached-vocabulary-fix]], [[evomem-utcp-endpoint-fork-and-deploy]]. No external sources were used.
