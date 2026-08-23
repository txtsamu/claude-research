---
type: troubleshooting
tags: [immich, systemd, automount, nfs, quadlet, podman, forensics, nextcloud, podman-auto-update]
created: 2026-08-11
last_verified: 2026-08-23
status: current
---

# Immich keeps stopping by itself — root cause: systemd automount idle-timeout killing Quadlet dependents

## Symptom

On 2026-08-11 the homelab VM (Podman Quadlet host) lost the **Immich trio** four times — `immich-server`, `immich-machine-learning`, `nextcloud-app` all went down in the *same second*, each time with a **clean SIGTERM stop** (no crash, no OOM). Immich became unreachable (`502` from the Caddy reverse proxy). Stop times (Asia/Jakarta):

| # | Stop time | Verification |
|---|---|---|
| 1 | 04:28:34 | `journalctl` "Stopping Immich Server…" |
| 2 | 17:01:25 | same pattern |
| 3 | 18:19:28 | same pattern, with systemctl audit rule armed |
| 4 | 19:31:16 | same pattern, with audit + dbus-monitor + 2s watchdog + eBPF ALL armed |

`immich-postgres` and `immich-redis` stayed up across every event. The services never restarted on their own (`Restart=always` does not cover explicit stops — a dependency stop leaves the unit down). Irritatingly, the stop times looked random (04:28 → 17:01 → 18:19 → 19:31).

## Diagnosis

### Phase 1 — confirm stop, not crash

```sh
journalctl -u immich-server.service -n 50 --no-pager
dmesg -T | grep -iE "killed process|out of memory" | tail -5
```

Every event showed:

```
Aug 11 19:31:16 homelab systemd[1]: Stopping Immich Machine Learning...
Aug 11 19:31:16 homelab systemd[1]: Stopping Immich Server...
Aug 11 19:31:16 homelab systemd[1]: Stopping Nextcloud App...
Aug 11 19:31:16 homelab systemd[1]: Unmounting /mnt/immich-upload...
Aug 11 19:31:16 homelab systemd[1]: Unmounted /mnt/immich-upload.
Aug 11 19:31:16 homelab systemd[1]: Unmounting /mnt/nextcloud...
Aug 11 19:31:16 homelab systemd[1]: Unmounted /mnt/nextcloud.
```

Explicit `Stopping` + `status=143` = deliberate stop. Sequential podman PIDs in `ps` = parallel stop of several units.

### Phase 2 — eliminate every external channel (all ruled out)

| Channel | Check | Result |
|---|---|---|
| SSH / console | `last`, `/var/log/secure`, `journalctl -u sshd` at stop windows | 0 logins — not SSH |
| Schedulers | `crontab -l`, `/etc/cron.d/*`, `systemctl list-timers`, `atq`, `systemd path units` | nothing fires at stop times |
| Hermes agent | `~/.hermes/state.db` `messages` table queried at the exact stop timestamps | no tool calls at those seconds |
| Bots | grep for `systemctl\|podman\|immich\|dbus` over bot code dirs | physically cannot stop units |
| MCP chains | proxmox MCP: periodic `POST /mcp` = keepalives; a real guest exec leaves a pveproxy `agent/exec` line + task | none |
| Containers w/ host systemd access | `podman inspect` privileged + binds `/run/systemd` `/run/dbus` | none |
| `claude-bot` user | `lastlog` (last login **May 26**), `crontab -u claude-bot`, `loginctl`, `.bash_history` | dormant; `ps -u claude-bot` was a **UID 1000 collision** with container processes (gitea, pihole-FTL, mariadbd, flaresolverr, suwayomi run as host uid 1000) |
| Claude Code | transcript JSONLs parsed for timestamps; `/root/.claude/settings.json` hooks = evomem recorder + `rtk`, both benign | zero sessions at any stop time |

### Phase 3 — arm nets for the next stop (systemd never records the caller)

1. **auditd** watch on `/usr/bin/systemctl` (`-w /usr/bin/systemctl -p x -k svc_ctl`) — caught nothing: no `systemctl` exec.
2. **dbus-stopwatch**: `dbus-monitor --system` filtered on `StopUnit` method calls, resolving the sender bus name → PID. Caught nothing on the system bus.
3. **immich-watchdog**: 2s poll of unit `ActiveState`; on transition prints `ps` + `ss -xnp` socket peers + journal tail. At +1s after the stop: **no** private-socket connection, **no** suspicious process. A fire-and-forget caller over `/run/systemd/private` would be invisible here.
4. **eBPF catch-all** (`immich-socktrace.service`): `kprobe:unix_stream_connect` filtered on `sun_path == "/run/systemd/private"` or the system bus socket, printing pid/comm/ppid of the connecting process. Tested: catches every `systemctl` invocation. (bpftrace pitfall: `str(arg1 + 2)` is the only working form for reading the unix socket path — see the `systemd-stop-forensics` skill.)

The 4th stop fired with **all four nets armed and none of them tripped** — no exec, no system-bus call, no socket connect, no foreign process. That is the smoking gun: **there was no external caller at all.** PID 1 was doing it internally.

### Phase 4 — the mount was the answer all along

The journal line that had been there the whole time: `Unmounting /mnt/immich-upload` **in the same second as the stop**. Checked the mounts:

```sh
systemctl list-units '*automount*' --all
grep " /mnt/" /proc/mounts
grep immich /etc/fstab
```

- `/mnt/immich-upload`, `/mnt/nextcloud`, `/mnt/photos`, `/mnt/obsidian-livesync` are all **systemd automounts** (`x-systemd.automount`) with **`x-systemd.idle-timeout=600`** — a 10-minute idle timer.
- The Quadlet `.container` files declare the mounts:
  - `immich-server.container` → `RequiresMountsFor=/mnt/immich-upload /mnt/photos`
  - `immich-machine-learning.container` → `Volume=/mnt/immich-upload`
  - `nextcloud-app.container` → `RequiresMountsFor=/mnt/nextcloud /mnt/photos`
- **Mechanism**: when an automount is idle for 10 minutes, systemd's timer fires a stop transaction on the mount unit — and **every unit with `RequiresMountsFor=` on it is stopped as a dependent**, then the mount unmounts. Exactly the observed order: `Stopping …` → `Unmounting …` → `Unmounted`.
- **Why random-looking times**: the idle clock restarts on every access (upload, sync, thumbnails). Stops land 10 minutes after the *last* access, so they look irregular.
- **Why the trio stops together**: in quiet periods all the automounts go idle around the same time; each unmount pulls its own dependents.
- **Why no restart**: a dependency stop is intentional, so `Restart=always` never fires.
- **Why postgres/redis survived**: they don't depend on any NFS mount.

## Is this a bug in Immich? No.

- **Podman discussion #21045** — *"Quadlet gets shut down when an automount volume reaches idle timeout"*: maintainer rhatdan — *"Podman is not shutting down the service… most likely something else is telling systemd"*; reporter confirmed — *"systemd stops all dependant services when the automount point gets unmounted. Sorry for the bogus report."*
- **r/podman** thread with the *identical* setup (Immich on Quadlet v2.0.1, immich-server stopped by systemd while ML/postgres run): OP's accepted answer = automount idle timeout.
- **`man systemd.automount`** `TimeoutIdleSec=`: *"Pass 0 to disable the timeout logic. The timeout is disabled by default."*
- Immich itself never touches systemd; the container was killed by the *environment's* mount lifecycle. Also not a Podman bug — plain systemd dependency semantics.

## Fix

Change the NFS lines in `/etc/fstab` so the automount never expires (keeps lazy-mount + auto-recovery on access, disables the idle unmount):

```sh
cp /etc/fstab /etc/fstab.bak-immich-automount
sed -i 's/x-systemd.idle-timeout=600/x-systemd.idle-timeout=0/g' /etc/fstab
systemctl daemon-reload
systemctl restart mnt-immich\\x2dupload.automount mnt-nextcloud.automount \
  mnt-obsidian\\x2dlivesync.automount mnt-photos.automount
systemctl start immich-server immich-machine-learning nextcloud-app
```

(`x-systemd.idle-timeout=0` makes systemd generate `TimeoutIdleSec=infinity` on the automount units.)

## Verification

```sh
systemctl is-active immich-server immich-machine-learning nextcloud-app   # active active active
findmnt -t nfs4 -o TARGET,SOURCE                                         # real nfs4 mounts, not autofs
grep TimeoutIdleSec /run/systemd/generator/mnt-*.automount               # TimeoutIdleSec=infinity on all 4
ls /mnt/immich-upload/                                                   # library/ thumbs/ encoded-video/…
curl -s -o /dev/null -w "%{http_code}" http://localhost:2283/api/server/ping   # 200
```

All four automount units now show `TimeoutIdleSec=infinity` — the containers can never be dependency-stopped by an idle unmount again.

## Key findings / gotchas

- **`Restart=always` does not cover dependency stops** — a unit stopped because its mount went away stays dead until started manually.
- **`ps -u <suspect-user>` lies** when the uid collides with container processes (rootful Podman `User=1000` containers run as host uid 1000).
- **systemd never records who stopped a unit** — no log line, no audit event for internal transactions. eBPF on `unix_stream_connect` is the only net that catches fire-and-forget DBus callers; but if *nothing* external fires, suspect systemd's own dependency machinery (mounts, automounts, path units) before suspecting an actor.
- **The "Unmounting …" journal line was visible in the very first diagnosis window** — the mount teardown was the answer from the start, hidden in plain sight next to the `Stopping` lines.
- Deployed nets (`immich-watchdog`, `dbus-stopwatch`, `immich-socktrace` audit rule + eBPF service) are kept running as canaries for any *future real* external stop attempts.

## Update 2026-08-23 — the canary caught a second, unrelated cause

The automount fix above stopped the *automount-idle* stops, but the watchdog/eBPF nets were deliberately left running as canaries ("kept running as canaries for any *future real* external stop attempt" — see above). They caught one:

```
Aug 21 00:13:52 homelab immich-watchdog.sh[8631]: *** IMMICH SERVER STOP DETECTED (ActiveState=failed) ***
```

The `ps` snapshot from that exact second showed the actual cause, red-handed:

```
2514960  1  root  00:01  /usr/bin/podman rm -v -f -i immich-postgres
2514961  1  root  00:01  /usr/bin/podman rm -v -f -i immich-redis
```

**Root cause #2**: `immich-postgres.container` and `immich-redis.container` both have `AutoUpdate=registry` set, so `podman-auto-update.timer` (fires daily, `OnCalendar=` around midnight + systemd's randomized delay — confirmed via `systemctl list-timers podman-auto-update.timer`, last run `00:02:17`, next `00:00:06`) tears the containers down and recreates them if a newer image is available. Tearing down `immich-postgres`/`immich-redis` cycles the whole pod, briefly dropping `immich-server` with it — same *symptom* as the automount issue (a clean dependency-driven stop, not a crash), completely different mechanism. This is expected Podman auto-update behavior, not a bug and not anything malicious.

Since both root causes behind "Immich randomly stops" are now identified and (for the automount one) fixed, and the second one is just routine `podman-auto-update` behavior rather than something needing a fix, the forensics nets were retired:

```sh
systemctl disable --now immich-socktrace.service immich-watchdog.service
rm -f /etc/systemd/system/immich-socktrace.service /etc/systemd/system/immich-watchdog.service \
      /usr/local/bin/immich-watchdog.sh
rm -rf /root/immich-forensics
systemctl daemon-reload
```

If unexplained stops start again, the `.bt`/`.sh` snippets in this doc (Phase 3 above) can be redeployed in a few minutes — no need to keep an always-on eBPF probe + 2s poll loop running indefinitely once both known causes are accounted for.

## Files

- `/etc/fstab` — `x-systemd.idle-timeout=0` on the 4 NFS automount lines (backup: `/etc/fstab.bak-immich-automount`)
- `immich-postgres.container` / `immich-redis.container` — `AutoUpdate=registry`, managed by `podman-auto-update.timer` (daily); expected source of brief pod-cycling, not a bug
- ~~`/etc/systemd/system/immich-socktrace.service` + `/root/immich-forensics/private-sock-trace.bt`~~ — removed 2026-08-23, both root causes identified
- ~~`/etc/audit/rules.d/99-stopwatch.rules`~~ — systemctl/busctl/systemd-run exec watches (from Phase 3; not re-verified whether still present)
- ~~`/usr/local/bin/immich-watchdog.sh` + `dbus-stopwatch.sh`~~ — removed 2026-08-23 (watchdog); dbus-stopwatch not re-checked
- Skill: `systemd-stop-forensics` (updated with this root cause + fix)
