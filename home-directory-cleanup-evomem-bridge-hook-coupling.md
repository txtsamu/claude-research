---
type: how-to
tags: [fedora, home, cleanup, evomem, claude-code, hooks]
created: 2026-09-18
last_verified: 2026-09-21
status: current
---

# Organizing `~/` — what's actually safe to move, and one hook-coupling gotcha

Reorganized a cluttered `/home/moo` (project folders and loose files mixed in with dotfiles and XDG default dirs) into the existing `archive/` directory. Mechanically simple, but two things weren't obvious in advance.

## What stayed put, and why

- **XDG default dirs** (`Desktop`, `Documents`, `Downloads`, `Music`, `Pictures`, `Public`, `Templates`, `Videos`) and **all dotfiles/dot-directories** (`.ssh`, `.config`, `.cache`, `.bashrc`, `.gitconfig`, `.vscode`, etc.) — live system/app config, out of scope for a "tidy up project folders" pass.
- **`claude-research/`** itself — this project's own `CLAUDE.md` hardcodes `~/claude-research` as the write-up destination for the standing auto-push workflow. Archiving it would silently break that convention.
- **`nfs_photos/`** — an active NFS automount point (`systemd-1 ... type autofs`), not a regular directory. `mv` correctly refused to touch it (`Device or resource busy`).
- **`backup-llama/`** — root-owned (`uid=0`), needed `sudo mv` instead of a plain move; a plain `mv` failed with `Permission denied`.

## The gotcha: moving `evomem-bridge/` broke live hooks

Moved `evomem-bridge/` into `archive/` along with everything else — it's just another project-looking directory at first glance. Immediately broke:

```
PostToolUse:Bash hook blocking error: python3 /home/moo/evomem-bridge/hooks/hook.py:
[Errno 2] No such file or directory
```

`~/.claude/settings.json` hardcodes `/home/moo/evomem-bridge/hooks/hook.py` across **12 separate hook entries** (`PreToolUse`, `SessionStart`, `UserPromptSubmit`, `PostToolUse`, `PostToolUseFailure`, `PreCompact`, `SubagentStart`, `SubagentStop`, `Notification`, `TaskCompleted`, `Stop`, `SessionEnd`), and `~/.claude.json` also references `/home/moo/evomem-bridge/mcp_server.py` for the MCP server config. Moved it back immediately; hooks resumed working.

**Lesson:** before moving *any* directory in `~`, grep `~/.claude/settings.json` and `~/.claude.json` (and any other tool config that might hardcode absolute paths) for that directory name — a folder that looks like just another project can be load-bearing for the tooling itself. This applies generally, not just to `evomem-bridge` specifically: any directory backing a Claude Code hook, MCP server, or systemd unit with a hardcoded absolute path is not safe to move without updating those references first.
