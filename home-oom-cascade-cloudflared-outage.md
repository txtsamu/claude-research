---
type: troubleshooting
tags: [home, k3s, oom, cloudflared, cloudflare-tunnel, kubernetes, memory, fedora]
created: 2026-09-19
last_verified: 2026-09-21
status: current
---

# `home`'s Cloudflare Tunnel went down — root cause was a kernel OOM cascade, not cloudflared itself

## Symptom

Cloudflare Tunnel on `home` (192.168.50.200) reported as suddenly down. Public hostname returned Cloudflare's own edge error rather than timing out:

```
$ curl -sk -D - -o /dev/null https://ai.<PERSONAL_DOMAIN>/
HTTP/2 530
server: cloudflare
```

HTTP 530 with a `server: cloudflare` header means Cloudflare's edge was reached fine, but it couldn't reach the tunnel's origin connector — the tunnel itself was down, not just one hostname misrouted.

## First signs it was more than "cloudflared crashed"

`ssh home` hung: TCP connected instantly (`Connection established` in `ssh -v` output), but the SSH banner never arrived — timed out during banner exchange. `ping` to the same host was instant (0.2ms). HTTPS and the k3s API port (6443) also failed/hung intermittently. This pattern — ICMP fine, every TCP *application-layer* handshake stalling — pointed at the host being severely resource-starved rather than a clean single-service failure.

Confirmed on the next successful connection: `uptime` showed **`up 0:01`** — the host had rebooted roughly a minute earlier, and was now cold-starting a large number of services simultaneously (`load average: 5.97` at 1 minute of uptime).

## Root cause: kernel OOM-killer cascade

`journalctl -k -b -1` (the *previous* boot's kernel log, since the crash predated the reboot) showed the actual event, starting around 19:38 and escalating by 19:42:33:

```
containerd-shim invoked oom-killer: gfp_mask=0x140cca(GFP_HIGHUSER_MOVABLE|__GFP_COMP), order=0, oom_score_adj=1
oom-kill:constraint=CONSTRAINT_NONE,...,cpuset=cri-containerd-...scope,...,task=speaker,pid=566655,uid=0
Out of memory: Killed process 566655 (speaker) total-vm:1282696kB, anon-rss:21148kB, ...
```

...repeating across dozens of k3s/containerd-managed processes in short order: `csi-attacher`, `csi-provisioner`, `csi-resizer`, `csi-snapshotter`, various pod webhooks. Classic signature of a Kubernetes node running fully out of memory — the kernel OOM-killer picking off containerd-managed processes essentially at random once available memory hit zero.

`cloudflared`'s own log lines from the same window show it as a *casualty*, not the cause:

```
2026-09-18T12:42:56Z ERR failed to accept incoming stream requests error="failed to accept QUIC stream: timeout: no recent network activity"
2026-09-18T12:42:56Z ERR failed to run the datagram handler error="timeout: no recent network activity"
2026-09-18T12:42:56Z ERR Serve tunnel error error="accept stream listener encountered a failure while serving"
```

Its QUIC tunnel connections to Cloudflare's edge simply stopped being serviceable once the host was too starved to handle network I/O. The host then hard-rebooted at 19:43:24 (new boot ID) — consistent with the machine becoming fully unresponsive rather than the kernel gracefully recovering.

### Why 15GB of RAM wasn't enough

At the time, `home` was running — simultaneously, on one 15GB box — k3s, **two separate mariadb instances**, immich + immich-api, victoria-metrics, gitea, uptime-kuma, searxng, redis, an Erlang-based service (`beam.smp`), a Telegram-bot polling loop, camoufox (headless browser), and hermes-gateway/hermes-mcp. That's a lot of independently memory-hungry services co-located with no apparent per-pod memory limits reining them in — a single burst (see below) was enough to tip the whole node over.

## Related finding: a 46GB runaway process on a *different* host, dispatched from `home`

While free-diagnosing this, `fedora` (192.168.50.20 — the machine actually running this Claude Code session) was independently found to be almost out of memory itself: 572MB free of 61GB, swap 7.9/8GB full. Top consumer: a `python3 -` process (script piped via stdin, no visible source file) at **46.3GB RSS**.

```
$ ps -o pid,ppid,cmd -p 3043004
    PID    PPID CMD
3043004 3043000 sshd-session: moo@notty
$ who
moo      sshd         2026-09-18 19:34 (192.168.50.200)
```

That SSH session originated from `home` (192.168.50.200) at **19:34** — 8 minutes before `home`'s OOM cascade peaked at 19:42:33. Plausibly connected (a job dispatched from `home`, e.g. via hermes-gateway, that also spiked memory on the origin host before or while running elsewhere), but **not proven causally** — no source script was recoverable from the stdin-piped process to confirm what it actually was. Killed with `SIGTERM` (clean exit, no zombie), which immediately freed `fedora` back to 38GB available. Worth following up on if the same pattern recurs: what dispatches unbounded python jobs via bare `ssh ... 'python3 -' < script`, and whether it needs a memory limit.

## Recovery

No manual intervention needed for `home` itself — the OOM-triggered reboot already brought cloudflared back up on its own:

```
$ ssh home "systemctl list-units '*cloudflared*'"
cloudflared-tunnel-83033670-b996-49b7-8174-1032db860685.service   loaded active running
$ curl -sk -o /dev/null -w "%{http_code}\n" https://ai.<PERSONAL_DOMAIN>/
200
```

(NixOS names the systemd unit `cloudflared-tunnel-<tunnel-uuid>.service`, not literally `cloudflared.service` — worth remembering when checking status on this host.)

## Key lesson

A tunnel/service going down on a box that's *also* running k8s is worth checking for a node-level OOM before assuming the service itself broke — `journalctl -k -b -1` (previous boot, since a hard OOM often triggers a reboot before you get to look) is the fastest way to confirm or rule it out. The underlying capacity problem (too many memory-hungry services on 15GB) is not fixed by this investigation and will likely recur without either trimming services, adding per-pod memory limits, or increasing the host's RAM.
