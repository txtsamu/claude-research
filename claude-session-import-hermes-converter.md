---
type: build-log
tags: [hermes, claude-code, session-import, session-migration, sqlite, sessiondb, cron, homelab]
created: 2026-08-03
last_verified: 2026-08-03
status: current
---

# Claude Code session import into Hermes: custom converter built and deployed

## Problem

User asked (in Indonesian): "Cari di internet apakah ada toolsnya buat migrasi session?" — is there a ready-made tool to migrate **Claude Code sessions** (`~/.claude/projects/*.jsonl`) into **native Hermes sessions** so they become searchable via `session_search` and show up in `hermes sessions list`, across both hosts where Claude Code runs (homelab `.80` as `root`, fedora `.20` as `moo`).

## Research conclusion — no ready-made tool

Researched 2026-08-03; full findings live in the `hermes-session-import` skill (`references/claude-session-import-research.md`). Summary:

- **`hermes import-agent claude-code`** does NOT import sessions. Source `hermes_cli/agent_import.py` maps CLAUDE.md/AGENTS.md, permission allowlists, MCP servers, skills, memories — zero session handling.
- **`hermes-claude-import`** (github.com/magnus919, standalone skill) imports a **Claude.ai data export** (`conversations.json`/`memories.json`) into the configured **memory provider**. Not Claude Code JSONL, not native sessions.
- **hermes-webui PR #1678** (merged in v0.51.1, repo nesquena/hermes-webui — a different product) adds read-only **browsing** of Claude Code JSONL in the WebUI sidebar. View-only, never becomes searchable native sessions.
- **NousResearch/hermes-agent issue #35587** — open feature request for an official migration skill, but scoped to skills/plugins.
- Conclusion: build a small converter. The gateway's own write API (`hermes_state.SessionDB`) is the supported path.

## Implementation

### `~/.hermes/scripts/claude_session_import.py`

CLI converter: `--claude-dir <projects> --host <label> [--db <state.db>] [--dry-run]`.

- Walks `*.jsonl` under the projects dir, skipping `subagents/` child files (opt-in via `--include-subagents`).
- Parses the Claude record shape (`{"type": "user"|"assistant"|"summary"|"ai-title"|..., "message": {...}}`), mapping typed blocks:
  - `text` block → role `user` / `assistant` content
  - `thinking` block → `reasoning`
  - `tool_use` block → Hermes `tool_calls` (`arguments` = `json.dumps(input)`)
  - `tool_result` block → role `tool` with `tool_call_id` = `tool_use_id`
  - `summary` / `ai-title` lines → session title + `end_session()` when ended
  - `system`/`mode`/`last-prompt`/`fork-context-ref` lines skipped
  - Original ISO `timestamp` preserved (converted to epoch float)
- Writes via the official API: `SessionDB.create_session(..., source="claude_code")` + `append_message(...)`.
- Deterministic session id `claude_<host>_<session-uuid>` — re-runs dedupe.
- **Idempotent with an update path**: if the session already exists and the message count matches → skip; if the JSONL grew (Claude Code still running / session re-opened) → `SessionDB.replace_messages()` (atomic, reconciles counters, no duplicates).
- Caps: 50 MB per file, 10k messages per session. `--dry-run` parses and reports only.

### `~/.hermes/scripts/claude_import_watchdog.sh`

Cron-facing wrapper: rsyncs fedora's `/home/moo/.claude/projects/` → `~/.hermes/claude-staging/fedora/` (graceful skip if host unreachable), imports homelab (local) + fedora (staging), appends everything to `~/.hermes/claude-import.log`. Prints nothing when nothing changed (cron `no_agent` watchdog pattern → silent), prints `+N homelab / +M fedora baru` when sessions were added/updated.

### Cron job

`claude-code-session-import` — `no_agent: true`, schedule `0 1 * * *` (01:00 WIB), script `claude_import_watchdog.sh`, deliver to origin.

## Testing performed (all passed)

1. **Dry-run both hosts**: homelab 156 files + fedora 17 files parsed, 0 failures.
2. **Import into a COPY of state.db** (`cp ~/.hermes/state.db /tmp/test_state.db`, `--db` flag): sessions appear with correct `source=claude_code`, correct role breakdowns (user/assistant/tool), titles attached.
3. **FTS verification**: `SessionDB.search_messages('mocca')` and `'cosmic'` return hits on the imported `claude_*` session ids; `hermes sessions list` shows the `claude_*` rows with correct workspaces (`-home-moo-Music`, etc.).
4. **Idempotency**: second run → `0 imported, N skipped`.
5. **Grow/replace path**: staged a copy of a small session file, imported, appended one more user/assistant line, re-imported → `1 updated`, final `message_count == len(get_messages())` (3 == 3, no duplicates).
6. **Real run**: 177 sessions imported (160 homelab + 17 fedora) into the live `~/.hermes/state.db` after backing it up to `state.db.bak-claude-import`. The 4 large files (>5 MB, up to 26.5 MB / 788 messages) were included by raising the cap from 5 MB to 50 MB.

## Key findings / gotchas

- `SessionDB.search_sessions(source=...)` is **not** full-text search — it lists sessions by source. FTS lives in `SessionDB.search_messages()` (in `hermes_state_search.py`). `search_messages` returns slim rows (`content=None`) which is fine for verification.
- Hermes JSONL files dropped into `~/.hermes/sessions/` are NOT auto-ingested into the DB — the DB is the store of record; use the SessionDB API.
- The SQLite WAL-reset warning printed on every session open is cosmetic (sqlite 3.34.1 vs 3.51.3+); not caused by this work.
- `replace_messages()` accepts the same message-dict shape as `append_message()` — reuse the parser output directly.

## Files

- `~/.hermes/scripts/claude_session_import.py`
- `~/.hermes/scripts/claude_import_watchdog.sh`
- `~/.hermes/scripts/claude_import_cron.sh` (manual-run variant)
- `~/.hermes/claude-import.log` (run log)
- `~/.hermes/state.db.bak-claude-import` (pre-import backup)
- Skill: `hermes-session-import` (updated with the proven implementation + verification steps)
