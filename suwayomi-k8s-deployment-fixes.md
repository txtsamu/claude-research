---
type: troubleshooting
tags: [suwayomi, kubernetes, kubectl, rollout, rwo-pvc, flaresolverr, byparr, cloudflare, socks-proxy, warp-vm, vpz]
created: 2026-08-30
last_verified: 2026-08-30
status: current
---

# Suwayomi on k8s: rollout deadlock, Cloudflare-bypass proxy split, and a false lead on the real root cause

Several separate but related fixes made to the `suwayomi` Deployment (namespace `homelab`) in one session, triggered by a user report of manga sources failing to load. Documenting as one doc since they're all part of the same troubleshooting arc, even though the actual root cause (see
[pod-internet-egress-isp-ttl-bug.md](pod-internet-egress-isp-ttl-bug.md#update-2026-08-30-the-fix-above-only-protected-the-first-packet-of-each-connection--fasttrack-was-silently-undoing-it-for-everything-after))
turned out to be a router-level bug unrelated to Suwayomi specifically.

## 1. `rollout restart` deadlocked on a single-replica RWO volume

**Symptom:** `kubectl rollout restart deployment/suwayomi` hung indefinitely —
`kubectl rollout status` showed `1 old replicas are pending termination` and
never progressed.

**Cause:** the deployment uses the default `RollingUpdate` strategy with a
single replica and a `ReadWriteOnce` PVC (`suwayomi-data`). `RollingUpdate`
tries to bring the *new* pod up before killing the *old* one (bounded by
`maxSurge`/`maxUnavailable`), but an RWO volume can only attach to one pod at
a time — the new pod can't attach while the old one holds it, and the old
one won't be killed until the new one is `Ready`. Classic deadlock for any
single-replica workload on an RWO volume.

**A deceptive further trap:** deleting the old pod directly does *not* fix
this — the old **ReplicaSet** still has `desired=1` (Kubernetes hasn't
decided to scale it down yet, since the new RS isn't `Ready`), so deleting
its pod just makes the RS immediately reschedule a replacement, which
re-grabs the volume. The actual unblock is to scale the *old ReplicaSet*
itself to zero directly:

```bash
kubectl scale rs <old-replicaset-name> -n homelab --replicas=0
```

**Permanent fix:** switched the deployment's strategy to `Recreate` (kills
the old pod first, *then* starts the new one — the standard choice for any
single-replica RWO-backed workload):

```bash
kubectl patch deployment suwayomi -n homelab --type=json -p='[
  {"op":"remove","path":"/spec/strategy/rollingUpdate"},
  {"op":"replace","path":"/spec/strategy/type","value":"Recreate"}
]'
```

All rollouts since (image updates, env var changes) have completed cleanly
with no further manual intervention.

## 2. Cloudflare-protected manga sources need a trusted-reputation egress IP — SOCKS proxy split between two boxes

**Symptom:** some manga sources failed with `SOCKS server general failure`
(traced to the SOCKS proxy's upstream — Cloudflare WARP — being down, see
§3), and separately, sources requiring `FlareSolverr`'s Cloudflare-challenge
solving (`aquareader.org` / "Aqua Manga") failed with
`Error solving the challenge. Timeout after 60.0 seconds.` even once the
proxy itself was healthy again.

**Root cause of the FlareSolverr-specific failure:** the `flaresolverr`
sidecar container's `PROXY_URL` had been pointed at a newly-built SOCKS
proxy on `vpz` (a plain hosting-provider VPS). Cloudflare's bot-management
weighs source-IP reputation heavily — datacenter/hosting-provider ASNs get
challenged far more aggressively (sometimes an unsolvable interactive
challenge, sometimes an outright block) than residential-grade IPs.
Confirmed via web research (multiple independent sources) that this is a
well-known, structural limitation — no FlareSolverr config tweak fixes it,
the fix is routing through a trusted-reputation IP.

**Fix — split the two containers' egress across two different proxies,**
matching each to what it actually needs:

| Container | Proxy | Why |
|---|---|---|
| `suwayomi` (direct source-site + own infra requests) | `vpz` SOCKS proxy (`<VPZ_PUBLIC_IP>:1080`, auth required — public-internet-facing) | No IP-reputation requirement for plain requests |
| `flaresolverr` (Cloudflare-challenge solving) | `warp-vm` SOCKS proxy (`192.168.50.200:1080`, LAN-only, no auth needed) | Routes via Cloudflare WARP — WARP IPs are effectively trusted/residential-grade to Cloudflare's own bot-management |

```bash
kubectl set env deployment/suwayomi -n homelab -c suwayomi \
  SOCKS_PROXY_HOST=<vpz-ip> SOCKS_PROXY_PORT=1080 \
  SOCKS_PROXY_USERNAME=<user> SOCKS_PROXY_PASSWORD=<pass>

kubectl set env deployment/suwayomi -n homelab -c flaresolverr \
  PROXY_URL=socks5://192.168.50.200:1080
```

Verified via a direct `POST /v1` challenge-solve request against
`aquareader.org`: `"status": "ok", "message": "Challenge solved!"`, real
`cf_clearance` cookie issued.

### Byparr evaluated as a FlareSolverr replacement — didn't work, reverted

Before landing on the proxy-split fix above, briefly tried
[Byparr](https://github.com/ThePhaseless/Byparr) (`ghcr.io/thephaseless/byparr:latest`)
as a drop-in FlareSolverr replacement — same port (`8191`), same `/v1` API
shape (confirmed compatible via real-world GitHub issue evidence, since its
own README doesn't document the endpoint), uses Camoufox (Firefox-based,
better anti-detection than FlareSolverr's patched Chromium) instead.

**Result: worse, not better, in this environment.** `ps aux` inside the
container during a request showed the API server running but **no browser
process ever launched** — it hung silently past 90+ seconds with zero error
logged, worse than FlareSolverr's own clean 60-second timeout failure.
Reverted to the real FlareSolverr image. Not investigated further (e.g.
whether it's a Kubernetes-specific sandboxing/capability issue) since the
proxy-split fix alone fully resolved the actual symptom — Byparr was
pursued as a possible *additional* improvement, not a required one.

## 3. Cloudflare WARP daemon was stopped and disabled — broke the pre-existing `warp-vm` SOCKS proxy

Separately from the above: `warp-vm`'s `microsocks` SOCKS5 proxy (used by
Suwayomi/FlareSolverr since before this session — routes egress through
Cloudflare WARP for apps that need it, fixes a recurring silent-drop issue
on this ISP's connection) was up and listening, but every request through it
failed with `SOCKS server general failure`. Root cause: `warp-svc`
(Cloudflare's own WARP client daemon, the thing microsocks actually proxies
*through*) had been cleanly `SIGTERM`'d and `systemctl disable`d on
2026-08-28 — almost certainly a leftover from that day's unrelated
WARP-routing outage cleanup (see
[lan-wide-warp-failover-routing-outage.md](lan-wide-warp-failover-routing-outage.md)),
with nobody remembering this second, narrower use of the same WARP client.

```bash
sudo systemctl enable --now warp-svc
```

`warp-cli status` confirmed `Connected`/`Network: healthy` immediately
after; `curl -x socks5h://192.168.50.200:1080 https://ifconfig.me` returned
a real Cloudflare-network IP.

## 4. Image updated to latest stable, and a `imagePullPolicy` staleness trap

Deployment was pinned to `ghcr.io/suwayomi/suwayomi-server:preview` with
`imagePullPolicy: IfNotPresent` — meaning it would **never** re-check for a
newer image on that floating tag once *any* image existed locally matching
that tag name, silently going stale indefinitely. Confirmed via the
project's own docs (`Suwayomi-Server-docker` README): `:preview` = "the
latest preview release... can be buggy", `:latest`/`:stable` = "the latest
stable release".

Fixed in two steps:
1. Changed `imagePullPolicy` to `Always` (necessary for *any* floating tag
   to actually stay current across rollouts going forward).
2. Per user preference, switched the tag itself from `:preview` to
   `:stable` — verified via the server's own startup log
   (`Running Suwayomi-Server v2.3.2243`), matching the latest tagged
   release on the project's GitHub releases page exactly.

## 5. The actual root cause of the original extension-catalog fetch failures

The `Failed to fetch extension store 'Keiyoushi ...'` / `StreamResetException`
errors that kicked off this whole investigation were **not** caused by
anything in this doc — disabling Suwayomi's own SOCKS proxy (§2) removed
one contributing factor (proxy overhead stacked on top of already-slow pod
egress) but the fetch kept failing intermittently even after. The real
cause was a router-level bug (RouterOS FastTrack silently bypassing an
existing ISP-TTL mangle fix for established connections) — see the
[full write-up and fix](pod-internet-egress-isp-ttl-bug.md#update-2026-08-30-the-fix-above-only-protected-the-first-packet-of-each-connection--fasttrack-was-silently-undoing-it-for-everything-after).
Once that was fixed at the router, the exact failing fetch went from timing
out to completing in 69ms — no further Suwayomi-side change needed.

**Lesson for next time a k8s pod's outbound requests are slow/flaky in this
cluster specifically:** check the linked TTL/FastTrack doc *first*, before
assuming it's proxy config, DNS, or CNI-related. The symptom (small/early
exchanges fine, larger or longer ones fail or hang for several seconds) is
distinctive enough to recognize quickly once known.
