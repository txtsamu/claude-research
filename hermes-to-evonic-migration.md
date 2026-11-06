---
type: how-to
tags: [hermes, evonic, telegram, cron, systemd-timers, nixos, home, migration, evomem, multi-agent, profiles]
created: 2026-11-06
last_verified: 2026-11-06
status: ROLLED BACK to Hermes on 2026-11-06 19:28 WIB (Evonic left running idle); was live 17:59-19:25 WIB; inbound Telegram confirmed by a real message at 18:26-18:28 WIB; 3 agent cron jobs staged disabled; PR #15 merged
---

# Migrate Hermes (multi-profile team, memories, skills, Telegram bot, cron) to Evonic

Request: move the Hermes agent data to Evonic (check first whether Evonic has a tool for it), then also the Telegram bot, the multi-profile setup, and the cron jobs. Scripts are in [hermes-to-evonic-migration/](hermes-to-evonic-migration/). Background on Evonic and how it was deployed on `home`: [evonic-vs-hermes-agent-benchmark.md](evonic-vs-hermes-agent-benchmark.md).

## Time estimate

Measured: timers deploy (`nixos-rebuild switch`) 35 s; Telegram cutover about 1 minute of script time, with Telegram unavailable for roughly 40 s (Hermes' Telegram platform went to `disconnected` at 17:58:20 WIB, Evonic logged `connected and polling` at 17:58:59); KB import and index of 11 agents about 3 minutes; build of the 11 portable agent files a few seconds. Estimate (not measured): about 4 hours of session wall clock, most of it investigation and waiting for a subagent to build the NixOS timers.

## Was there a tool for it? No.

- Evonic's only importer is `evonic agent import` for its own `evonic.agent` v1 JSON (system prompt, config keys, tool and skill ids, variables, KB markdown files). The repo has no mention of Hermes. `scripts/migrate_brain_to_kb.py` is an internal layout migration.
- `hermes migrate` imports INTO Hermes (OpenClaw, Claude Code, Codex, Cursor, ...); it cannot export.
- So a one-off converter was written. Evonic skills are code packages (`skill.json`, `tools.json`, Python backend), Hermes skills are prose runbooks (`SKILL.md`), so Hermes skills became KB notes, not Evonic skills.

## What Hermes held (inventory on `home`, `/root/.hermes`, 7.6 GB)

| Hermes | Size | Mapped to |
|---|---|---|
| `memories/MEMORY.md`, `USER.md` | 5 KB, entries split on a paragraph sign | KB notes, one per entry (`hermes-memory/`) |
| 302 skills, 81 of them under `.archive`, 4 without frontmatter, 3 duplicate names | 41 MB | KB notes (`hermes-skills/`), archived skipped, duplicates get ` (category)` |
| 10 named profiles + default (`audio critic dev device diskos finance net ops research uiux`) | 30-35 MB each | one Evonic agent each |
| `state.db` 2 966 sessions / 87 997 messages, plus 1 498 JSON/JSONL files in `sessions/` | 900 MB | NOT migrated (JSON/SQLite, not markdown; the first record of each file is a tool-schema dump) |
| Telegram bot (only the default profile had a token) | | Evonic Telegram channel |
| 11 cron jobs: 8 `no_agent` scripts, 3 agent jobs | | see Cron |
| kanban 14 old tasks, `SOUL.md` of default (empty) | | not migrated |

Profiles are specialist personas: each has `SOUL.md` (about 2 KB role prompt), `profile.yaml` (description), its own `memories/`, and a copy of a subset of the default skills (12-20 modified per profile, none unique).

## Steps

All scripts run as root on `home`, read `/root/.hermes`, and write to `/srv/migrate` (0700). Credentials found in memories and skills were copied as is by the user's explicit choice (71 files with credential-looking lines, 8 with token-shaped strings, one plaintext login in `USER.md`), so everything under `/srv/migrate` and the Evonic KBs is sensitive.

### 1. Convert + build one portable agent per profile

```bash
scp hermes_to_evonic_kb.py build_portable.py <USER>@home:/srv/migrate/
ssh <USER>@home 'sudo python3 /srv/migrate/build_portable.py --out /srv/migrate/portable'
```

`hermes_to_evonic_kb.py` writes docs with the frontmatter Evonic enforces (`title`, `description`, `type`; strings via `json.dumps` so quotes and colons cannot break YAML), docs flat inside one collection folder per kind (Evonic allows docs at the KB root or one folder deep, each folder with an `index.md` of type `group`). `build_portable.py` makes `hermes_default` (owns Telegram, routes to specialists, prompt generated from the profile descriptions) and `hermes_<profile>` (prompt = that `SOUL.md` plus a short Evonic note). Config per agent: model `deepseek-v4.1-flash`, tools `bash read_file write_file str_replace patch`, `sandbox_enabled=0` (home has no Docker), `agent_messaging_enabled=1`, `messaging_acl` whitelist of the other 10 team agents (an empty ACL means "may message anyone"; values must be scalars so the ACL is a JSON string).

### 2. Import and index

```bash
ssh <USER>@home 'sudo sh /srv/migrate/import_agents.sh'   # evonic agent import <file> --id <id> --yes, as the evonic user
ssh <USER>@home 'sudo sh /srv/migrate/resync.sh'          # sync with EVOMEM_BINARY and EVOMEM_TIMEOUT=300
ssh <USER>@home 'sudo sh /srv/migrate/verify_kb.sh'
```

Result: 268 docs / 3 603 chunks in `hermes_default`, 149 / 2 171 in `hermes_ops`, 68-101 docs in the other specialists. A search for "armbian tv box reboot hang" in `hermes_ops` returns the right runbook. Dangling links (113 in default) are bash `[[ ]]` tests inside code blocks.

Gotchas: (a) the `evonic agent import` writes files but does not index; (b) Evonic's evomem client needs `EVOMEM_BINARY` in the environment (the systemd service has it, an ad-hoc `runuser` does not) and has a 5 s default timeout `EVOMEM_TIMEOUT`, which silently failed the sync of the 268-doc KB (`sync -> False`); the service now sets 120; (c) `evomem validate` only looks at files newer than the last sync, so "validated 0 files" after a sync is normal; (d) the `evomem` CLI prints text, not JSON.

### 3. Telegram

Staged first, disabled (`stage_telegram.py`): creates a `telegram` channel on `hermes_default` with config `{mode: restricted, bot_token, allowed_users: [chat ids], user_names}`, using Hermes' `TELEGRAM_ALLOWED_USERS` and the chat names from its cron job origins so Evonic does not ask users for their name. Also calls `getMe` and `getWebhookInfo` (read-only, no poller conflict): the bot uses polling, no webhook. Evonic's channel code refuses to run if another instance polls the same token, and Telegram allows one poller per token, hence a strict order:

1. deploy the cron timers (below) so nothing depends on Hermes;
2. fill the timers' credential files and pause the 8 Hermes script jobs;
3. `golive_c_telegram_cutover.py`: back up `/root/.hermes/.env` to `.env.pre-telegram-move` (0600), comment out the `TELEGRAM_BOT_TOKEN` line (atomic rewrite, same owner and mode), restart `hermes-gateway`, check its `gateway_state.json` shows Telegram `disconnected`, set the Evonic channel `enabled=1`, restart `evonic`, grep its journal for `connected and polling` and for `conflict`.

Rollback: `cp -p /root/.hermes/.env.pre-telegram-move /root/.hermes/.env && systemctl restart hermes-gateway`, disable the Evonic channel (`update_channel(<id>, {"enabled": 0})` in Evonic's DB layer) and restart `evonic`, then `hermes cron resume <id>` for the paused jobs.

### 4. Cron: split by job type

Evonic's scheduler action types are `emit_event`, `static_message`/`agent_message`, `session_prompt`, `webhook`, `poll_monitor`: there is no "run a script". Eight of the Hermes jobs are plain scripts run as root (one of them is the 5-minute `evomem-claude-sync` that feeds evomem), so they cannot sensibly run through an LLM agent in an unprivileged sandbox. They became root systemd timers (home-nixos PR #15, `hosts/home/scheduled-jobs.nix`, written by a subagent from Hermes' own scheduler source, then reviewed and tested by me):

- one `scheduled-job-<name>` oneshot + timer per job, same cwd (`/root/.hermes/scripts`), interpreter rule (`.sh` bash, else the Hermes venv python), 3600 s timeout, `flock` per job; empty stdout sends nothing, non-zero exit or timeout sends a one-line notice, a last JSON line `{"wakeAgent": false}` is silent, `MEDIA:` lines are uploaded as documents; `deliver=local` jobs never message anyone;
- stdout goes to Telegram through `tg-notify` (stdlib sender) with the bot token read from a `LoadCredential` file (`/var/lib/scheduled-jobs/telegram-bot-token`, root 0600, created empty by tmpfiles so the unit never fails to start, filled by hand);
- the repo is PUBLIC, so chat ids are NOT in git: jobs name `main` or `other`, resolved at run time from `/var/lib/scheduled-jobs/chat-ids` (`alias=<id>` per line). The first version of the PR committed the ids; the fix commit removes them, but they remain in that earlier commit of the PR until it is squash-merged (and visible in the PR's commit list);
- known differences from Hermes: no secret redaction of script output (it goes to the journal), images sent as documents, failure notice wording is approximate, Hermes' managed Python is replaced by `/opt/hermes-venv/bin/python` (the three `.py` jobs only use the stdlib).

Tested before deploy with a fake Bot API on home: alias `main` -> chat 1, `other` -> chat 2, numeric passthrough, empty output sends nothing, `local` sends nothing, failing script sends a notice, unknown alias warns and does not send. The first version of that test used a malformed fake token and `tg-notify` correctly refused it, which looked like a runner bug until the token was shaped properly.

Deployed from the PR branch, then `golive_a_credentials.py` (fills the two files from Hermes' `.env` and the camofox job's origin chat; prints sizes and aliases only) and `golive_b_pause_hermes_jobs.sh` (`hermes cron pause <id>` x8, with a copy of `jobs.json`) ran within two minutes, before two timers fired at 18:00. At 18:00 the timers ran and Hermes did not (its last runs of those jobs were 06:00 and 12:00, both disabled). Timer timing note: `OnBootSec=2min` is already past on activation, so the 5-minute job fires immediately after a deploy.

The 3 agent jobs (`Daily Claude session report`, `proxmox-backup-autofix`, `Daily Hermes efficiency research`) were staged as DISABLED Evonic `session_prompt` schedules (`stage_schedules.py`) on `hermes_default`, `hermes_ops`, `hermes_research` with the original prompts and a preface. They stay disabled because they need what an Evonic agent does not have: root ssh keys to Proxmox and TrueNAS (the autofix job), web and camofox tools plus write access to a root-owned git repo (the research job), and a collector script (the session report). They were left enabled in Hermes, which can no longer deliver their results to Telegram.

## First real use (18:26-18:28 WIB, from the Evonic log, no message text read)

The allowed chat sent `/help`, `/status`, an attachment, then a follow-up and `/new`. Evonic handled the commands, ran one turn on `hermes_default` (3 LLM calls: two `bash` tool calls, then a final answer) and sent the reply through the Telegram channel; no errors or token conflicts were logged. The third call alone took about 65 s (provider latency), so the answer arrived about 2 minutes after the first message. The follow-up messages that arrived during the turn were queued into the running loop ("session busy, injecting into active loop"), which is Evonic's behavior for a busy session. Prompt size was about 9.2K tokens per call (28 309 in / 536 out for the turn), against about 3.4K for the stripped-down benchmark agent, because this agent runs with Evonic's default features and the full system prompt. The service's cgroup memory rose from 770 to 1 106 MB during this (mostly file cache). Evonic's session logs live in `agents/<id>/sessions/<sid>.jsonl` and, with the trace setting on, `agents/<id>/llm_traces/<sid>.jsonl`; the message store is `agents/<id>/chat.db`, not the main `evonic.db`.

## Found later: `recall` did not use the migrated KB (fixed 18:34 WIB)

Symptom: on "check claude-research" the agent's `recall` and `recall_sessions` returned "No memories found" and it fell back to grepping the filesystem (and looked in the wrong place, `shared/agents/<id>`, which is the workspace; the KBs are in `agents/<id>/kb`). Diagnosis, in the order that narrowed it down: the same query run directly with the `evomem` CLI against the agent's KB returned the right note as the top hit above the 0.03 score floor, so the index was fine; the service log had no evomem errors since the cutover; an in-process call of `memory_manager.search_memories` as the `evonic` user printed `engine: fts5` although `is_available()` was true. Cause: the service's `/opt/evonic-source/.env` still held the lean settings written for the benchmark by `evonic_home_setup.py`, including `EVONIC_MEMORY_ENGINE=fts5`, so `recall` searched Evonic's own (empty) memory table and never the KB. The benchmark config had never been reverted when the migrated agents were put on the same instance. Fix: remove that line (backup `.env.pre-memory-fix`), restart `evonic`; afterwards `search_memories('hermes_default', 'claude-research')` returns `engine: evomem` with 3 hits. Lesson: a shared instance keeps the last config anyone wrote, so check `.env` after reusing a benchmark install, and verify "can it recall X" with a direct call, not by the tool name appearing in a trace.

Benchmark settings still in that `.env` and left as they are, to be decided: `EVOMEM_KB_ORGANIZER=off` (no LLM edits to the migrated notes), `ACTIVE_CONTEXT_MODE=off`, `TWO_PASS_ENABLED=0`, `EVONIC_SESSION_ARCHIVE=1` (writes every request and response, including KB text that may contain credentials, to `agents/<id>/llm_traces`). Also seen: asking the bot to "connect to my github" made the agent try `ls ~/.ssh`; Evonic's safety pipeline flagged it `requires_approval` (ssh_access) and waited for an approval in Telegram.

### Same session: more leftovers and a stuck agent (18:31-18:40 WIB)

- "Agent is at maximum concurrent capacity (1/1 slots in use)" on Telegram: Evonic's shipped defaults are one concurrent turn per agent (`max_concurrent_llm_per_agent=1`) and one globally (`max_concurrent_llm_global=1`). The slot was held by a turn waiting for a safety approval: asked "can you connect to my github?", the agent ran `ls ~/.ssh`, the safety pipeline returned `requires_approval` (ssh_access) and the loop waits up to 300 s (default decision on timeout: reject) while every later message is queued with that busy notice. My restart for the `.env` fix did not clear it: Evonic resumes unreplied sessions at startup ("Resumed unreplied session"), so the same question ran again and asked a second time (18:35:05 until the 18:40:05 timeout). Avoid restarting while a human message is unanswered, or expect it to be replayed.
- Two benchmark-only app settings were also still off and are restored to their defaults (read at runtime, no restart): `long_running_guard_enabled` and `root_fs_scan_guard_enabled` (both default to on; they limit runaway and filesystem-wide bash commands).
- Fixed at 18:52 WIB (home-nixos PR #16): inside the service the PromptPurify L5e prompt-injection classifier failed to load (`numpy: libstdc++.so.6: cannot open shared object file`). Three separate causes, found one after another: (1) `libstdc++` missing from the library path (NixOS has none by default for manylinux wheels); (2) after that, `libz.so.1` missing too (numpy and opencv); (3) the classifier also needs `onnxruntime`, an optional Evonic dependency that is not in `requirements.txt` and was not in the venv, so fixing the paths alone would only have changed the error text. The fix sets `LD_LIBRARY_PATH = lib.makeLibraryPath [ stdenv.cc.cc.lib zlib ]` on the unit and pins `onnxruntime==1.31.1`, `flatbuffers==25.12.19`, `packaging==26.3`, `protobuf==7.36.2` in `hosts/home/venvs/evonic.txt`. `provision-venv-*` only rebuilds a venv that is missing (a healthy one is just snapshotted), so the packages were also installed once into the live venv with `pip install --no-deps` using exactly those versions; the next provision run snapshots them. An earlier claim that numpy "imports without LD_LIBRARY_PATH" was only true in a plain shell, not in the service environment. Verification: reproduced in a clean `env -i` as the service user; numpy, cv2 and onnxruntime imported using the exact `LD_LIBRARY_PATH` read out of the built unit; after the deploy Evonic's own loader (`injection_guard._get_ml_runner`) run with the unit's real `Environment=` returned the loaded classifier, scoring a benign message 0.000 and an injection attempt 0.998 in about 25 ms. The restart cost about 16 s of Telegram downtime and did not replay anything ("all 84 human session(s) have replies").
- PR #16 was squash-merged into home-nixos `main` (947584f) after checking that `main`'s tree equals the deployed branch head, so deploys from `main` keep the library path and the classifier.

### Health check at 19:10 WIB and two cautions

Service active with 0 restarts, 0 errors in the log since the last restart, Telegram polling, 11 agents enabled, recall via Evonic's own function returned `engine: evomem` hits for the default and ops agents, 8 timers loaded, no failed units, 221 MB memory. The latest turn (39 tool calls, 3 min 8 s) finished and replied. Cautions: (1) a diagnostic process that imports `backend.agent_runtime.*` runs Evonic's startup recovery and marks the live turn "interrupted" in the shared DB (it did not break that turn, but it caused the "clearing stale in-process busy flag" line earlier); probe with the `evomem` CLI, read-only sqlite or the journal instead. (2) Agent `bash` runs as the same OS user as the server, and the agent was seen running `sqlite3` on `.db` files (flagged by the safety pipeline at warning level, not blocked); `evonic.db` holds the provider API key and the channel config holds the bot token. Options: drop `bash` from agents that do not need it, or run agent shells as another user via the `run_as_user` setting plus a narrow sudo rule. Not changed.

## Why it felt slower, and the rollback (19:15-19:34 WIB)

Measured from Evonic's `llm_traces` and Hermes' `state.db` (read-only). Evonic, one long turn on `hermes_default`: 38 sequential LLM calls (35 `bash`), 189 s, 94 percent of it inside LLM calls (median 4.1 s per call, 3.4 s at normal context, 5.8 s above 25K prompt tokens) and 6 percent tools, safety checks and waiting; the prompt grew from 9.5K to 39K tokens per call (877K prompt tokens for the turn). The 9.5K start is 27 tool schemas (23K chars, 60 percent of the request) plus a 14K-char system prompt, against 3.4K tokens for the stripped benchmark agent. Consecutive calls in a turn share about 100 percent of their prefix (36 of 37 pairs), so prompt caching is possible, but Evonic's traces record only prompt/completion/total tokens, so cache hits were not measurable. Hermes over 21 days of Telegram: 230 turns, median 131 s, mean 283 s, p90 729 s, median 11 assistant steps per turn, short turns (3 steps or fewer) about 13 s, 97 percent of prompt tokens served from cache (3 897 API calls, 3.2K new input tokens per call), and it streams tool progress into Telegram (`tool_progress: all`), whereas Evonic sent one message at the end. So heavy turns were comparable in wall time; Evonic looked slower because of far more steps per question, a larger prompt, 3.5 s of fixed buffering (2.0 s in, 1.5 s out), silence while working, and the incidents above. Not applied (offered): zero the buffers, cap `max_tool_iterations` and tell the agent to batch commands, trim the tool list while keeping `recall`/`remember`.

Rollback, in the order that avoids two pollers on one token and double cron runs, as `rollback_to_hermes.py`: (1) disable the Evonic Telegram channel in its DB, restart `evonic`, confirm it no longer logs `connected and polling`; (2) restore the `TELEGRAM_BOT_TOKEN` line in `/root/.hermes/.env` from `.env.pre-telegram-move` (only that line, atomic rewrite, mode kept); (3) stop the 8 `scheduled-job-*.timer` units; (4) restart `hermes-gateway`, wait for Telegram `connected` (112 s on this host); (5) `hermes cron resume` x8. Result: Hermes Telegram connected with no conflict, Evonic not polling, 0 active timers, 11 of 11 Hermes jobs enabled; Hermes ran its overdue jobs as catch-up (the 18:00 chat digest repeated once). Stopping timers at runtime is not durable on NixOS, so PR #17 comments out the `scheduled-jobs.nix` import (build-only check: 0 scheduled-job units, `evonic.service` unchanged), deployed from its branch in 31 s and then squash-merged into `main` (b31c598) after checking `main`'s tree equals the deployed head, so a deploy from `main` no longer brings the timers back. Evonic, its 11 agents and KBs were left in place with the Telegram channel disabled; to re-migrate, re-enable the channel with `golive_c_telegram_cutover.py` (it re-comments the Hermes token) and re-import PR #15's import line together with `golive_b_pause_hermes_jobs.sh`. Left on `home`: `/var/lib/scheduled-jobs` (bot token and chat ids, root 0600), `/srv/migrate`, `/root/.hermes/.env.pre-telegram-move`.

## Capability differences to keep in mind

- Hermes profiles had MCP tools (TrueNAS, Proxmox, MikroTik, Cloudflare, Notion, evomem, camofox, crawl4ai, gowa). Evonic agents have bash and file tools only, running as an unprivileged `evonic` user without a sandbox; `hermes_ops` and `hermes_net` lose their infrastructure tooling.
- Anyone on the Telegram allowlist can drive an agent with a shell as that user. The allowlist is the two ids Hermes already allowed.
- Evonic's KB organizer and memory features were left at their defaults for these agents (extra LLM calls after conversations); the benchmark instance in the other write-up had them off.

## Resource use of Evonic (measured on `home`, 8 cores, 15.9 GB)

Over 3 h 43 min of uptime and about 130 agent runs the service used 48 CPU-seconds in total. One 50 s task with 12 tool calls cost 5.4 CPU-s (average 11 percent of one core, peak 53 percent); a 33 s task cost 1.2 CPU-s. Memory: 153 MB resident, 131 MB anonymous; the cgroup total was 770 MB, of which 551 MB is reclaimable file cache. Not measured: 11 agents active together, the Telegram poller, the KB organizer.

## Open items

- PR #15 was squash-merged into home-nixos `main` (5c0b7b9) on 2026-11-06, after verifying `main`'s tree equals the deployed branch head and holds no chat ids (also none in `main`'s history; the ids remain only in the closed PR's own commit list). Before the merge, a `nixos-rebuild` from `main` would have removed the timers while the Hermes jobs were paused and silently stopped the evomem sync.
- Delete `/srv/migrate` on `home` when satisfied (portable agent JSON with copied credentials), rotate the plaintext login that was in Hermes' `USER.md`.
- Decide about the 3 staged agent schedules (give the agents the access they need, or keep those jobs in Hermes with another way to deliver).
- Hermes sessions (2 966) were not migrated; if wanted, distill them into KB notes (see [evomem-search-algorithm-research.md](evomem-search-algorithm-research.md) on why raw transcripts make a poor index).

## References

- Evonic source, read for the importer, channel, scheduler and ACL behavior: <https://github.com/anvie/evonic> (`backend/agent_portability.py`, `backend/channels/telegram.py`, `models/mixins/channels.py`, `backend/scheduler.py`, `backend/tools/lib/messaging_acl.py`, `backend/agent_runtime/evomem_client.py`)
- Hermes Agent source on the host (`/opt/hermes-source/cron/scheduler_script.py` and related) and `hermes migrate|cron|profile --help`
