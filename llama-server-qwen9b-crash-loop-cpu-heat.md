---
type: troubleshooting
tags: [llama-server, systemd, rocm, cpu-temp, crash-loop, fedora]
created: 2026-07-31
last_verified: 2026-07-31
status: current
---

# llama-server Qwen3.5-9B systemd unit crash-looping, spiking CPU temp

## Why

User suspected a "rogue" `llama-server` process was spiking CPU temperature and asked to investigate.

## Step 1: Check for duplicate/runaway processes

```bash
pgrep -fa llama-server
ps -eo pid,ppid,%cpu,%mem,etime,cmd --sort=-%cpu | head -20
sensors
```

Only one `llama-server` process was running, at 99.3% CPU, but its `ELAPSED` time was only ~1 minute — i.e. it had just (re)started. `sensors` showed `Tctl: +71.5°C` (elevated but not throttle territory), GPU dies cool (47-57°C). Not a duplicate-process situation.

## Step 2: Check parent process and service manager

```bash
ps -o pid,ppid,user,lstart,cmd -p 1856   # parent = systemd --user
systemctl --user status llama-server.service
```

Found the process belonged to a user-level systemd unit: `llama-server.service - llama.cpp HIP server - Qwen3.5 9B`, and the status output showed:

```
Active: active (running) since ...; 6s ago
...
Jul 31 07:36:17 fedora systemd[1856]: llama-server.service: Scheduled restart job, restart counter is at 26201.
```

**Restart counter at 26,201.** At ~16s per cycle (5s `RestartSec` + ~11s HIP/ROCm init before failing), that's roughly 4.8 days of continuous crash-looping — consistent with the service's own reported uptime duration elsewhere in the audit.

Also present: a *separate*, unrelated system-level `llama-server.service` (`/etc/systemd/system/llama-server.service`) serving a Gemma4-12B model, which had run cleanly for 4d18h and stopped normally (exit 0) about 2 minutes before the investigation started. Not implicated.

## Step 3: Confirm GPU offload wasn't actually happening

```bash
rocm-smi --showuse
# GPU[0]: GPU use (%): 2
```

GPU essentially idle despite `-ngl 99` (offload all layers). Confirms the sustained load was CPU-bound crash-loop overhead, not real inference work.

## Step 4: Root-cause the crash via journal

```bash
journalctl --user -u llama-server.service --no-pager -n 150 -o short-iso
```

Every cycle logged:
```
error while handling argument "--flash-attn": error: unknown value for --flash-attn: '--cache-type-k'
```

The unit file (`~/.config/systemd/user/llama-server.service`) passed a bare `--flash-attn` flag with no value:
```
--flash-attn \
--cache-type-k q8_0 \
```
The installed `llama-server` build now requires `-fa/--flash-attn` to take an explicit value (`on|off|auto`). With no value supplied, the arg parser consumed the next token (`--cache-type-k`) as flash-attn's value, rejected it, and exited 1 — every single restart, forever.

## Step 5: First fix attempt — patch the flag

```diff
-  --flash-attn \
+  --flash-attn on \
```
```bash
systemctl --user daemon-reload
systemctl --user restart llama-server.service
```

This fixed the arg-parsing error, but the service then failed on a *different*, terminal error:
```
gguf_init_from_file: failed to open GGUF file '/home/moo/models/qwen35-9b/Qwen3.5-9B-Q4_K_M.gguf' (No such file or directory)
```

## Step 6: Real fix — remove the service, model no longer exists

User confirmed the Qwen3.5-9B model isn't used anymore (superseded by the Gemma4-12B setup). Rather than keep patching a unit for a deleted model:

```bash
systemctl --user stop llama-server.service
systemctl --user disable llama-server.service
rm -f ~/.config/systemd/user/llama-server.service
systemctl --user daemon-reload
```

Verified: `systemctl --user status llama-server.service` → "could not be found"; `pgrep -fa llama-server` → no matching process.

Checked `/home/moo/models/qwen35-9b/` and `/home/moo/models/` — both already gone/empty, so no model files were left to clean up either.

## Step 7: Confirm the model actually in use (Gemma4-12B) is healthy

User confirmed the 12B is the only model in use now. It was found `enabled` but currently stopped (clean exit, not a crash) — likely stopped incidentally around the same time as this investigation. Started it back up:

```bash
systemctl start llama-server.service   # the /etc/systemd/system one, Gemma4-12B
systemctl status llama-server.service
rocm-smi --showuse --showmemuse
```

Came up clean: `active (running)`, no restart-loop pattern, GPU0 VRAM allocation climbing as the model loaded (11% and rising).

## Outcome

- Identified and eliminated a ~4.8-day-old systemd crash-loop (`llama-server.service`, user unit, Qwen3.5-9B) that was the actual source of the abnormal CPU heat — not a malicious/rogue process.
- Root cause: a `llama-server` CLI breaking-change (`--flash-attn` now requires an explicit value) combined with `Restart=on-failure` turned a one-line arg error into indefinite restart churn.
- Service and unit file fully removed since the underlying model file no longer exists and isn't used.
- Confirmed the actually-used Gemma4-12B system service is running normally with no crash-loop symptoms.

## If revisiting later

- If a new llama.cpp-based systemd unit is set up in the future, prefer `Restart=on-failure` with a bounded `StartLimitBurst`/`StartLimitIntervalSec` (e.g. in `[Unit]`: `StartLimitIntervalSec=300`, `StartLimitBurst=5`) so a bad flag or missing model file causes the unit to give up and go `failed` instead of restarting thousands of times — that would have surfaced this as one `systemctl --failed` entry instead of a multi-day silent CPU load.
- The 12B unit (`/etc/systemd/system/llama-server.service`) runs as `User=root` and binds `--host 0.0.0.0` (all interfaces) — not touched in this pass since it wasn't the reported problem, but worth reviewing if network exposure matters here.
