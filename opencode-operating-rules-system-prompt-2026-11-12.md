---
type: how-to
tags: [opencode, system-prompt, instructions, config, agent-behavior, honesty, provost]
created: 2026-11-12
last_verified: 2026-11-12
status: current
---

# OpenCode: installing custom operating rules into the global system prompt (2026-11-12)

No repo or branch involved. Work was done in `/home/moo/diskos` (not a git repo) against the global OpenCode config at `~/.config/opencode/`. Related: [[diskos-2026-11-12-standards-review-adrs-and-ui-naming]] (the session that created the standing note rule in `AGENTS.md`), [[agentmemory-shared-mcp-multi-host-setup]].

## Request

Add a pasted block of agent operating rules (honesty and epistemic humility, Gary Provost sentence rhythm, a search-first protocol, source and statistics integrity, bash scripting preferences, one-liner troubleshooting commands, markdown MOPs) to the OpenCode system prompt.

## What was done

Two files changed in the global config directory.

1. Created `~/.config/opencode/instructions/operating-rules.md` (96 lines). The pasted text was kept verbatim in intent, with headings converted to Markdown so the numbering survives model-side parsing.
2. Added an `instructions` entry to `~/.config/opencode/opencode.json`:

```json
"instructions": [
  "~/.config/opencode/instructions/operating-rules.md"
]
```

The rest of the config (camofox plugin, `websearch.provider`, subagent permission, `experimental.subagent_depth`) was left untouched.

## Why a separate file instead of appending to AGENTS.md

Both routes reach the model. `AGENTS.md` files are discovered automatically and combined with configured `instructions` in this order (from the OpenCode instructions docs):

```text
1. Agent or provider system prompt
2. Code Mode tool guidance
3. MCP server, reference, and skill guidance
4. Global and project AGENTS.md files, then configured instructions
5. Built-in date and environment context
6. Session-specific instruction entries
```

A separate file keeps the standing "document every session" rule in `AGENTS.md` readable on its own, and makes the behavior block easy to swap or disable without touching the other rule.

## The path resolution gotcha

Relative entries in `instructions` are searched from the workspace upward to the project root, not relative to the config file. A relative path would therefore miss. Using the `~/` form resolves from `$HOME` and works from any workspace:

| Entry | Resolution |
| --- | --- |
| Relative path or glob | Workspace up to project root |
| `~/path` | From `$HOME` |
| Absolute path | Used as written |
| `http(s)://` | Fetched at config load, 5s timeout |

## Verification

JSON parses and the entry is present:

```console
$ cd /home/moo/.config/opencode && python3 -c "import json;d=json.load(open('opencode.json'));print(d.get('instructions'))" && wc -l instructions/operating-rules.md
['~/.config/opencode/instructions/operating-rules.md']
96 instructions/operating-rules.md
```

Config changes reload without a restart. The live session confirmed it, receiving an injected block labeled `New instructions apply from: /home/moo/.config/opencode/instructions/operating-rules.md` followed by the full file text. No restart or `/reload` was needed.

## Known conflicts worth remembering

- The new search-first rule ("every query, without exception") collides with the `opencode` skill guidance to answer V2 questions from `https://opencode.ai/docs/` and not from general web search. Search still happens, but for OpenCode docs questions the docs pages win as the source of truth.
- This file also imposes "no em dash", simple code, and no unsolicited backward compatibility. Those now apply globally, in every project, not just diskOS work.
- `~/.config/opencode/AGENTS.md` still exists and still loads first among instruction files, so both rule sets are active together.

## Not verified

- Did not start a fresh session in a different workspace to confirm the `~/` entry resolves identically there. The rule is documented, and the injected block proves the file loads in this workspace, but the cross-workspace path resolution was not exercised.
- Did not check whether any project-level `opencode.json` in `/home/moo/diskos` or its parents defines its own `instructions` array. None was observed, but only the global file was inspected.
