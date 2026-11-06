---
type: investigation
tags: [evonic, hermes, agent-benchmark, nixos, home, deepseek, opencode-go, evomem, fork, subagents]
created: 2026-11-06
last_verified: 2026-11-06
status: current: 96-run benchmark finished; accuracy is a tie (suite too easy to separate), Evonic is faster, Hermes uses fewer tool calls and output tokens
---

# Evonic vs Hermes: same model, same 16 tasks (benchmark + NixOS deployment of Evonic)

Request: fork Evonic (the Evomem author's agent platform), deploy it on `home`, and benchmark its agent performance against Hermes. Code and raw results are in [evonic-hermes-benchmark/](evonic-hermes-benchmark/).

## Time estimate

Measured: `nixos-rebuild switch` that added Evonic 9 min 07 s (almost all of it building the Python venv); full benchmark 1 h 55 min (started 14:24:34 WIB, last of 96 runs recorded by 16:19); no compile step. Per run (median): Evonic 24.8 s, Hermes 36.4 s. Estimate (not measured): about 3 h of total wall clock for the whole session including building the harness and two agents working in parallel.

## Result (96 runs = 16 tasks x 3 reps x 2 agents, deepseek-v4.1-flash on both)

| | valid runs | passed | median wall s | mean tool calls | mean tokens in | mean tokens out |
|---|---|---|---|---|---|---|
| Evonic 1.6.0 | 47 | 47 (100 %, CI 92-100) | 24.8 | 7.9 | 42 697 | 1 504 |
| Hermes 0.22.7 | 48 | 48 (100 %, CI 93-100) | 36.4 | 5.2 | 26 702 | 759 |

One Evonic run (`C4_find_the_config` rep 2) is **invalid**: the provider failed on all 5 attempts, so it is excluded, not counted as a fail.

Paired by (task, rep), Evonic divided by Hermes, median ratio with bootstrap 95 % CI and sign test:

| metric | ratio | 95 % CI | Evonic lower / higher | p |
|---|---|---|---|---|
| wall seconds | 0.52 | 0.45-0.78 | 36 / 11 of 47 | 0.0003 |
| tokens in | 1.05 | 0.94-1.78 | 22 / 25 | 0.77 (no difference) |
| tokens out | 1.52 | 1.27-2.23 | 11 / 36 | 0.0003 |
| tool calls | 1.50 | 1.18-1.67 | 7 / 30 | 0.0002 |

By category (median wall s, Evonic vs Hermes): authoring 17 vs 33, tool use 19 vs 35, recovery 26 vs 40, coding 38 vs 39. Median total tokens on coding tasks: 64 604 vs 28 967 (Evonic about 2.2x more, from more tool round-trips and a larger fixed prompt).

Readings, with the limits that apply:
- **Accuracy: tie.** 16 of 16 tasks tied; the suite is too easy to separate the two (both bounded by the same model). It does not show they are equally capable on harder work.
- **Speed: Evonic is about 1.9x faster** per task in this setup. Part of Hermes's time is provider-side: all six slowest runs were Hermes (up to 200 s) and Hermes retries a failing provider call internally with back-off, which counts in its wall time. The ratio therefore mixes agent overhead and retry behaviour.
- **Effort: Hermes does the same tasks with about 1/3 fewer tool calls and about half the output tokens.**
- **Provider errors surfaced differently:** attempts that hit a provider failure: Evonic 22 of 69 (32 %), Hermes 7 of 55 (13 %). Evonic shows `API rate limit reached` within about 2.5 s and gives up; Hermes retries 3 times (about 100 s) before giving up. Evonic also issues more LLM requests per task, so it may simply meet the limit more often; not separable here.
- **Turn limits did not bind:** Hermes capped at 40 turns, Evonic at its default 100 iterations; the maximum seen was 24 tool calls (Evonic) and 12 (Hermes).

## What was compared (and what was held equal)

| | Hermes | Evonic |
|---|---|---|
| Version | v0.22.7 (/opt/hermes-source) | 1.6.0, commit 87834dc, fork branch `home/v1.6.0` |
| Model | deepseek-v4.1-flash via opencode-go | same model, same base URL, same key |
| Tools | `terminal`, `file` toolsets only | bash, read_file, write_file, str_replace, patch (plus hard-wired `send_file`, `monitor`) |
| Run as | `nobody`, transient sandboxed systemd unit, `--safe-mode` (no user config, rules, memory, plugins, MCP), fresh `HERMES_HOME` per run | `evonic` system user, hardened service, fresh chat session per task |
| Extras off | all | memory engine (fts5), KB organizer, safety checker, task classifier, agent state, summarizer, CMP, tool compression (Evonic's defaults make extra LLM calls) |

This is the core agent loop of each, not Evonic as shipped (default Evonic exposes 27 tools and adds helper LLM calls). Production Hermes was never used: its config has TrueNAS, Proxmox, MikroTik, Cloudflare and Notion MCP tools, none reachable from the benchmark.

Tasks (16, deterministic fixtures, no LLM judge): tool use (create files, grep and count, CSV to JSON, organize by extension), coding (implement against a docstring with hidden cases, fix a buggy module, write a CLI, de-duplicate across modules), recovery (broken script, malformed config, read-only file, find the right config key), authoring (postmortem from notes, changelog grouping, entity extraction scored by F1, constrained summary). Each task has a reference solution; `selftest.py` proves every checker fails on an untouched fixture and passes on the reference (this caught two bugs in my own tasks before any agent ran).

Procedure: for each rep and task a random order, agents interleaved, fresh workdir, fixture chowned to the agent's user for the run and back afterwards. A provider failure (HTTP 429, "overloaded", 5xx, connection errors) retries the whole run from a clean fixture, up to 5 attempts, 45 s x attempt back-off, identical for both agents.

## Steps and commands

### 1. Fork and pin

`txtsamu/evonic` already existed as a stale June fork (v0.7.0). Not touched at first; upstream v1.6.0 was pushed as a new branch:

```bash
git clone https://github.com/anvie/evonic.git evonic && cd evonic
git remote add fork https://github.com/txtsamu/evonic.git
git push fork origin/main:refs/heads/home/v1.6.0
```

Later, on request, the fork's `main` was synced without a force push: a merge commit with parents (old fork main, upstream main) and upstream's tree (`git commit-tree origin/main^{tree} -p fork/main -p origin/main`), pushed as a fast-forward. A `--force-with-lease` reset was blocked by the auto-mode classifier. All 1 131 commits that were only on the fork's old main were patch-equivalent to upstream ones (upstream rewrote its history), none were the user's.

### 2. NixOS module (home-nixos PR #13, branch `evonic`, written by a subagent, reviewed before deploy)

`hosts/home/evonic.nix` + entries in `provision.nix` (source `provision-src-evonic` pinned by rev, venv `provision-venv-evonic` from a lock `venvs/evonic.txt` built on home's Python 3.13), system user `evonic`, state in `/var/lib/evonic` (symlinked from the checkout), `evonic.service` foreground on **127.0.0.1:8080 only** (no Caddy, tunnel, DNS or firewall rule), `FORCE_INSECURE_COOKIES=1`, `MemoryMax=4G`, full systemd sandbox. I added `ReadWritePaths = [ ... "-/srv/bench/work" ]` for the benchmark workspace. CI (`nix flake check` + closure build) passed. Deploy:

```bash
ssh <USER>@home 'sudo nixos-rebuild switch --flake github:txtsamu/home-nixos/evonic#home --refresh'   # 9 min 07 s
```

PR #13 is **not merged** at the time of writing: `main` does not contain Evonic, so a deploy from `main` would remove the service (the same drift trap as the evomem perf build, see [evomem-utcp-endpoint-fork-and-deploy.md](evomem-utcp-endpoint-fork-and-deploy.md)). Removal steps are in the header of `evonic.nix`.

### 3. First-time setup and lean benchmark config

```bash
ssh <USER>@home 'cd /opt/evonic-source && sudo runuser -u evonic -- env HOME=/var/lib/evonic ./evonic setup --non-interactive'
ssh <USER>@home 'sudo python3 /srv/bench/code/provision_evonic.py'   # creates agent "bench", model, lean settings, admin password
ssh <USER>@home 'sudo systemctl restart evonic'
```

`provision_evonic.py` reads the one provider key from Hermes' env file and passes it to `evonic_home_setup.py` as an environment variable of the `evonic` user (never on a command line, never printed). `evonic_home_setup.py` writes `.env` keys (`EVONIC_MEMORY_ENGINE=fts5`, `EVOMEM_KB_ORGANIZER=off`, `EVONIC_SESSION_ARCHIVE=1` for per-call token usage, ...) and sets the agent flags in SQLite (`message_buffer_seconds=0` is essential: the default 2 s makes `POST /chat` return `{"buffered":true}` with no answer).

### 4. Drivers

- `hermes_driver.py`: `systemd-run --wait --pipe -p User=nobody -p ProtectSystem=strict -p ProtectHome=yes -p PrivateTmp=yes -p NoNewPrivileges=yes -p LoadCredential=key:/run/bench/opencode_key ... hermes --usage-file U chat --safe-mode --provider opencode-go -m deepseek-v4.1-flash -t terminal,file --yolo --max-turns 40 --in WORKDIR --query-file F --oneshot -Q --format stream-json`. Gotchas found by running it: `--usage-file` is a top-level option (before `chat`); `--run-budget` is rejected with `--format stream-json` (systemd `RuntimeMaxSec` is the hard limit instead); NixOS units need `PATH=/run/current-system/sw/bin` or `cat`/`mkdir` are missing; PrivateTmp hides `/var/tmp`, so work dirs live in `/srv/bench/work`.
- `evonic_driver.py` (built and proven against a mock OpenAI server by a subagent before touching a real key): login with session cookie plus double-submit CSRF token, one agent with the workspace switched per task via `PUT /api/agents/bench`, fresh `user_id` per task, back-off on the hard-coded 10 chat POSTs per minute limit (sleep not counted in wall time), tokens summed from `agents/bench/llm_traces/<session>.jsonl` (provider `usage`; needs `EVONIC_SESSION_ARCHIVE=1`). Trace files belong to the `evonic` user, so the reader falls back to `sudo cat`.

### 5. Run

```bash
cd /srv/bench/code && /opt/evonic-venv/bin/python bench.py --agents hermes,evonic --reps 3 --out /srv/bench/results/full.jsonl
# ran as: sudo systemd-run --unit=bench-full --uid=<USER> ... (survives a dropped ssh session)
python3 report.py results/full.jsonl
```

## Findings that cost time (read before repeating this)

1. **The provider, not the agents, was the main source of noise.** The first 8-run pilot had 3 of 4 Hermes runs and 1 Evonic run fail with `HTTP 429 ... [overloaded] the server is overloaded; retry shortly` from opencode-go, which would have scored them as agent failures. The retry-and-mark-invalid logic (identical for both agents) was added after that and re-validated with a second pilot (8 of 8 pass) before the real run. Cause of the overloads not established: the message says upstream capacity, not a quota.
2. **Evonic rewrites `"` and `'` in user text to curly quotes** (`backend/normalizer.py`), which would penalize it on exact-string tasks. All prompts carry literals in backticks and the suite asserts no quote character remains in any prompt.
3. Evonic cannot drop `send_file` and `monitor` (hard-wired), and sends about 3.4K prompt tokens of fixed overhead per request even for a trivial question.
4. Evonic's chat endpoint is capped at 10 POSTs per minute (hard-coded); it never mattered with one POST per task.

## Not shown by this benchmark

Harder or longer tasks, multi-file refactors over many turns, memory across sessions (Evonic's evomem-backed memory and KB organizer were switched off on purpose), other models, concurrency, or Evonic's default configuration. n = 3 reps per task. Wall time includes provider latency. Mean input tokens count cached tokens for both agents (provider-reported prompt tokens).

## Cleanup state

Evonic stays deployed and running (loopback only). `/srv/bench/` on home holds the harness, results, work dirs and `evonic_password` (0600); `/run/bench` (the provider key credential) is removed after every run; Hermes' per-run state in `/var/lib/hermes-bench` is deleted after each run. Remove everything with the steps in `evonic.nix` plus `sudo rm -rf /srv/bench`.

## References

- Evonic: <https://github.com/anvie/evonic> (README, `routes/agents.py`, `backend/normalizer.py`, `config.py`)
- Hermes Agent CLI help (`hermes chat --help`, `hermes --help`), run on the host
- [OpenCode rate-limit notes (third-party, unofficial)](https://standardcompute.com/fix/opencode-rate-limited) and [OpenCode Zen 429 error page](https://manifest.build/errors/opencode-zen/429-freeusagelimiterror-60fcef/): looked at while explaining the 429s; neither explains `[overloaded]`
