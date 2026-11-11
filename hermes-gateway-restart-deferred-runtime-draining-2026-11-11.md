---
type: troubleshooting
tags: [hermes, hermes-gateway, telegram, systemd, home, runtime-draining, restart, cron]
created: 2026-11-11
last_verified: 2026-11-11
status: current (symptom fixed with a service restart; root cause not fully proven, see "What is NOT known")
---

# Hermes gateway rejects every message with `runtime_draining` after a deferred restart

## Symptom

`hermes-gateway.service` on `home` showed `active (running)`, but Telegram messages got no answer. `errors.log` had:

```
ERROR gateway.platforms.base: [Telegram] Error handling message: runtime_draining
hermes_state_runtime.RuntimeStoreError: runtime_draining
```

The process was alive and Telegram was connected. It had simply closed message admission because it believed a restart was in progress.

## Time estimate

Measured from log timestamps (WIB, 2026-11-11):

| Step | Time |
|---|---|
| Gateway stuck (restart requested 04:09:07, restarted by hand 04:13:32) | about 4.5 min |
| Diagnosis (service status, logs, source) | about 5 min of tool calls |
| `systemctl restart hermes-gateway` until both Telegram adapters connected (04:13:32 to 04:15:25) | about 1 min 53 s (measurement) |
| Self-clear if left alone | up to about 30 min (the 1800 s cap in the source; not observed) |

## Diagnosis steps

All commands ran from the workstation over `ssh moo@home` (the service runs as root, so log reads need `sudo`).

1. Is the service up?
   ```bash
   systemctl --no-pager status hermes-gateway     # active (running), main PID 2372546, up 10 h
   systemctl list-units --no-pager | grep -i hermes
   ```
   It was up. Only an old `Failed with result 'exit-code'` line from the 17:34 restart on Nov 10 appeared in `journalctl -p warning`.

2. Where are the logs? Not just the journal:
   ```bash
   sudo ls -la /root/.hermes/logs      # agent.log, errors.log (+ rotated .1/.2/.3)
   sudo tail -n 40 /root/.hermes/logs/errors.log
   sudo grep -E "ERROR|CRITICAL" /root/.hermes/logs/errors.log | cut -c1-200 \
     | sed -E "s/^[0-9-]+ [0-9:,]+ //" | sort | uniq -c | sort -rn | head -15
   ```
   The tail showed two `runtime_draining` tracebacks at 04:11:08 and 04:11:21. The error summary was mostly old noise (see "Ruled out").

3. Why was it draining? Grep `agent.log` for the drain/restart lines:
   ```bash
   sudo grep -nE "Restart (requested|deferred)|drain" /root/.hermes/logs/agent.log | cut -c1-300 | tail -20
   ```
   Result:
   ```
   04:09:07,951 gateway.run: Restart requested with 2 active work unit(s); deferring stop() until they finish (cap=1800s) so in-flight turns are not amputated (#77184)
   04:09:07,962 gateway.run: Restart deferred: waiting on 1 active work unit(s) (0 wedged and excluded, 1 restart-safe and excluded; 1800s remaining before force drain): [{'kind': 'cron', 'job_id': '964315af6df8', ... 'restart_safe': True}, {'kind': 'managed', 'pid': 2372546}]
   04:09:38,047 ... waiting on 1 active work unit(s) ... 1770s remaining ...: [{'kind': 'managed', 'pid': 2372546}]
   ... one line every 30 s, still going at 04:12:38 (1590 s remaining)
   ```
   - The cron worker for `964315af6df8` died at 04:09:10 (exit status 1). The job was then paused as "unverified admission".
   - After that, only `{'kind': 'managed', ...}` stayed in the wait list. The `pid` there is just the gateway's own PID used as a placeholder.

4. Read the source to see what the wait means (`/opt/hermes-source/gateway/run_shutdown.py`, `_await_active_work_before_restart`, around lines 1610-1672):
   - A restart request while work is active enters a wait of up to `_restart_after_turn_timeout` (1800 s).
   - During the wait it calls `_scale_to_zero_status("draining", ...)`, which makes the session authority reject new messages with `runtime_draining`.
   - "managed" units come from `managed_turn_count` (`gateway/run_runtime.py`), which counts unmapped claims, managed workers and owner mutations.
   - The docstring says the wait exists "so the requesting turn isn't force-interrupted". A restart requested from inside a managed agent turn can therefore be waiting on that same turn.

5. Confirm it was still stuck, then fix:
   ```bash
   sudo systemctl restart hermes-gateway
   sleep 45; systemctl is-active hermes-gateway
   sudo journalctl -u hermes-gateway --no-pager --since "-1min" | grep -E "Connected to Telegram|ERROR|runtime_draining"
   ```
   Log after the restart:
   ```
   04:14:17 gateway.run: Restart deferred wait complete — active work drained; proceeding to stop()
   04:14:29 Hermes Gateway Starting...            (new PID 2642560)
   04:15:09 [Telegram] Connected to Telegram (polling mode)           # main adapter
   04:15:25 ...telegram__home_...adapter: Connected to Telegram       # second ("home") adapter
   ```
   No `runtime_draining` after the restart.

## Fix

`sudo systemctl restart hermes-gateway`. Both Telegram adapters reconnect in about 2 minutes.

After a stuck-then-restarted gateway, also deal with the cron job that was caught in the drain. In this case the log said: `Cron 964315af6df8 paused with unverified admission: ... reconcile /root/.hermes/cron/admissions/<id>.json ... Resume the printed session ID to check whether it completed or was interrupted; do not resend the work.` Check whether the job really ran before re-triggering it. This step was not done in this session.

## What triggered the restart request (partly unknown)

- The request came at 04:09:07.951, a moment after a Telegram response was sent in a session where the user was asking Hermes to update its system prompt, and while a second `local-...` session (via `tui_gateway.ws`) was running tools.
- The `Restart requested` log line does not record who or what asked for it. That was not identified.
- A tool block seen earlier in the log (Nov 10 04:06) shows the gateway refuses commands that try to restart or stop it from inside its own process: "Blocked: command or referenced script cannot restart, stop, or uninstall the gateway from inside the gateway process". So the restart most likely came through a different internal path.

## What is NOT known

- Whether the wait would have ended by itself at the 1800 s cap (about 04:39). The restart was done by hand before that, so this was never observed.
- Whether "waiting on the requesting managed turn" is the real deadlock. This is inferred from the docstring and code, not proven. `managed_turn_count` delegates to `uncounted_runtime_work` in `gateway/session_runtime_workers.py`, which was not read.
- Whether this will recur. Earlier drain events exist but are a different kind. Nov 6 21:01 (`Gateway drain timed out after 60.0s with 1 active agent(s)`) and Nov 7 04:05 (`... 60.1s with 0 active agent(s)`) are 60 s shutdown-drain timeouts. The 1800 s `Restart deferred` message appears only in today's log: 11 occurrences, all from this single event. The rotated `agent.log.1` and `agent.log.2` have none. So no earlier occurrence of this exact state was found. An earlier statement in the session that it had happened on Nov 6/7 was wrong.
- Nov 7 04:04 cron workers were also killed with status -15 around a drain, and the same cron jobs are handed out at about 04:00. Cron jobs running at the time of a restart may be a common factor. This is a lead, not a finding.

## Ruled out (noise in `errors.log`, not the cause)

- Telegram `updater.stop() did not finish before the network-recovery deadline` (Nov 8 16:19, Nov 9 19:54). The adapter rebuilt itself each time.
- `camofox` MCP `Tab not found` and HTTP 500 errors.
- Cloudflare MCP `zones_list` "1 validation error for CallToolResult" (Nov 10 15:27).
- 429 `ttft_admission` from the upstream model API.
- `shell hook ... not allowlisted` warnings at startup and the `/handoff` and `/plan` slash-command collisions. Normal startup warnings.

## If it happens again

1. `sudo grep -E "Restart (requested|deferred)" /root/.hermes/logs/agent.log | tail -5` to confirm the state.
2. If it has been stuck for more than a minute or two, `sudo systemctl restart hermes-gateway` is safe and fast.
3. Reconcile any cron job paused with "unverified admission".
4. Worth checking in the Hermes source or upstream: why the managed turn that requested the restart is counted as awaitable work.

## References

No web sources were used. Everything above comes from the host's logs and the installed Hermes source at `/opt/hermes-source` (`gateway/run_shutdown.py`, `gateway/run_runtime.py`). The `#77184` in the log line is an upstream issue number that was not looked up.
