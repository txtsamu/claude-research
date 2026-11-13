---
type: investigation
tags: [samsung, tizen, t6500, sdb, homelab, status, claude-research]
created: 2026-11-13
last_verified: 2026-11-13
status: current
---

# Quick status of the T6500 and of claude-research (2026-11-13)

Request: "check claude-research and check my tv status". No config was changed. This note records the
observed state, plus one new symptom worth knowing: the TV's sdb port accepts TCP but the Tizen sdb
handshake now fails after the local sdb server restarts.

Repo at the time: `~/claude-research`, branch `master`, commit `966e67d` ("Document user-level Prisma
Access Browser cleanup"), working tree clean, in sync with `origin/master`.

## 1. claude-research state

```
$ git status --short
(empty)
$ git log --oneline -1 origin/master
966e67d Document user-level Prisma Access Browser cleanup
```

TV-related notes present:

```
samsung-tv-kants2-exploit/
samsung-tv-t6500-debloat-and-launcher.md
samsung-tv-t6500-power-states-and-remote-control.md
samsung-tv-t6500-root-and-persistence.md
samsung-tv-t6500-sideload-and-apps.md
technitium-samsung-tv-ad-telemetry-block-advanced-blocking.md
```

No uncommitted work, nothing to salvage.

## 2. TV is on and healthy on the network

`ping 192.168.50.31` replies 0% loss (4.5–9.6 ms). The REST API at `:8001` answers:

```
PowerState: on          networkType: wired
modelName: UA43T6500AKXXD   model: 20_KANTS2_FHD
resolution: 1920x1080   OS: Tizen   countryCode: ID
developerMode: 1        developerIP: 192.168.50.20
firmwareVersion: Unknown
```

Port state (`192.168.50.31`):

| Port | State | Meaning |
|---|---|---|
| 8001 | open | REST/websocket API, answering |
| 8002 | open | same API family |
| 26101 | open (TCP) | sdb debug listener |
| 9090 | closed | not used on this firmware |

Host is `192.168.50.20` (`br0`), which matches `developerIP`, so the pairing config is correct.

## 3. New symptom: sdb handshake fails while 26101 is open

The archived toolchain still reports a device entry, but a fresh server cannot connect:

```
$ cd ~/archive/samsung-tv-t6500-2026-10/tooling/tizen-sdb
$ ./sdb connect 192.168.50.31:26101
connecting to 192.168.50.31:26101 ...
failed to connect to 192.168.50.31:26101
$ ./sdb devices
List of devices attached
```

First attempt this session printed `192.168.50.31:26101 is already connected` with the model name, then
`sdb shell 'uptime; id'` returned `error: protocol fault: no status` / `target not found`, and the local
sdb server restarted on port 26099. After that restart, every reconnect fails, including with a clean
`HOME=/tmp/opencode/sdbhome`. TCP to 26101 stays open throughout.

This differs from the older gotcha in
[samsung-tv-t6500-debloat-and-launcher.md](samsung-tv-t6500-debloat-and-launcher.md): there 26101 was
**not** in the `nmap` output at all, and the fix was unplugging the TV for 30–60 s. Here the listener is
up and refuses the handshake, which looks more like stale session/approval state on the TV side than a
downed debug daemon.

Untried fixes (in the order I would try them): toggle Developer mode off/on in Apps → `1 2 3 4 5`;
cold boot (wall unplug 30–60 s); check whether another host holds the single allowed sdb session.

## 4. Not verified

- Did not test whether the Technitium `samsung-tv` blocking group still resolves correctly. The DNS
  config was not touched; the TV is on wired Ethernet with the same lease.
- Did not read `/opt` or the root helper, because sdb shell was unavailable.
- No firmware version is exposed by the API (`Unknown`), so I cannot confirm the TV updated.

## Related

- [samsung-tv-t6500-debloat-and-launcher.md](samsung-tv-t6500-debloat-and-launcher.md)
- [samsung-tv-t6500-root-and-persistence.md](samsung-tv-t6500-root-and-persistence.md)
- [samsung-tv-t6500-power-states-and-remote-control.md](samsung-tv-t6500-power-states-and-remote-control.md)
- [technitium-samsung-tv-ad-telemetry-block-advanced-blocking.md](technitium-samsung-tv-ad-telemetry-block-advanced-blocking.md)
