---
type: troubleshooting
tags: [ssh, cloudflared, cloudflare-access, cloudflare-tunnel, pam, vps, ssh-multiplexing]
created: 2026-08-03
last_verified: 2026-08-03
status: current
---

# vpd: slow SSH connects through cloudflared Access, fixed with ControlMaster

## Symptom

`ssh vpd` (a small 1-vCPU/1GB KVM VPS reached via `cloudflared access ssh --hostname <VPD_HOSTNAME>`, `~/.ssh/config`) took anywhere from ~0.7s to ~2.9s for a trivial remote command — noticeably slower than the direct LAN hosts in the same config, and inconsistent run to run.

Relevant `~/.ssh/config` entry (before the fix):

```
Host vpd
    HostName <VPD_HOSTNAME>
    User <VPD_USER>
    ProxyCommand cloudflared access ssh --hostname %h
```

## Diagnosis

Piped `ssh -vvv` output through a per-line timestamp wrapper to see where the wall-clock time actually went:

```sh
ssh -vvv -o BatchMode=yes vpd exit 2>&1 | while IFS= read -r line; do
  printf '%s %s\n' "$(date +%s.%N)" "$line"
done
```

Three distinct costs showed up (see also [arm-cluster-ssh-motd-slow.md](arm-cluster-ssh-motd-slow.md) for the same "look at the gap between debug lines" technique applied to a different root cause):

1. **~440ms before the SSH banner even arrives** — `cloudflared access ssh` is spawned fresh by `ProxyCommand` on *every* invocation and has to negotiate Cloudflare Access + establish the tunnel before any SSH bytes flow.
2. **~150-180ms RTT × ~7 round trips (~1s cumulative)** — normal SSH2 handshake back-and-forth (KEXINIT, KEX ECDH reply, service-accept, pubkey offer, pubkey verify). Real network latency to a genuinely distant origin, not a misconfiguration.
3. **~1.0s idle gap with nothing in flight** — sat between `Entering interactive session` (channel opened, PAM session phase starts) and the server's first reply. No debug lines in between, so this isn't handshake overhead, it's the server itself pausing.

Checked (3) directly on the box:
- `/etc/update-motd.d/*` scripts: all ≤0.05s each — not the culprit (unlike the arm-cluster case, where an MOTD script's `curl` timeout *was* the cause).
- `uptime` load 0.13, `vmstat` steal ~1% — box isn't CPU-starved.
- `/etc/pam.d/common-session` includes `pam_systemd.so` — registers the login session with `systemd-logind` over D-Bus. On a 1-vCPU KVM guest this is the most likely source of the ~1s pause, though not pinned down with a proof-positive timer (would need root on the box + `systemd-analyze` or logind debug logging to confirm precisely).
- `sshd` on this box is reached through a `cloudflared tunnel` daemon running inside a podman/quadlet container (`systemctl status cloudflared` → `cloudflared.service`, a `.container` quadlet unit), i.e. traffic takes Cloudflare edge → tunnel container → sshd, an extra hop server-side vs. a bare-metal listener.

## Fix

None of the three costs is a bug — they're legitimate per-connection setup costs. The actual fix is to stop paying them on *every single command*: added SSH connection multiplexing to the global `Host *` block so the first connection in a window is reused by everything after it.

```
Host *
    GSSAPIAuthentication no
    AddressFamily inet
    ServerAliveInterval 60
    ServerAliveCountMax 3
    # Reuse one connection (skips cloudflared spawn + full handshake on repeat connects)
    ControlMaster auto
    ControlPath ~/.ssh/control-%r@%h:%p
    ControlPersist 10m
```

Applies to all `cloudflared`-proxied hosts in the config (`pc`, `vps`, `zenx`, `bri`, `arm1`, `warp`, `vpd`), not just this one.

## Result

```
first connection (cold, establishes ControlMaster): 2.465s
second connection (reuses socket):                  0.088s
```

~28x faster for any connection after the first, for up to 10 minutes of inactivity (`ControlPersist 10m`).

## If this recurs / generalizing

For any `ProxyCommand`-based host (cloudflared, corporate jump host, etc.) that feels slow on *every* command but fine once "warmed up" in the same shell: check `ControlMaster`/`ControlPersist` before chasing the proxy or the remote server — most of the cost is often the proxy handshake being repeated needlessly, not anything wrong on either end.

If the delay instead sits specifically between session-open and the shell/command starting (not the handshake itself), that's server-side PAM/session setup — check `/etc/update-motd.d/*` timings first (cheap, common culprit, see the arm-cluster write-up), then `pam_systemd`/`logind` if MOTD is already fast, as was the case here.
