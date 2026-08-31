---
type: how-to
tags: [kubernetes, kubectl, resource-limits, oom, memory, rwo-pvc, rollingupdate, homelab]
created: 2026-08-30
last_verified: 2026-08-31
status: current
---

# Cluster-wide memory request/limit audit across all `homelab` namespace deployments

Triggered by fixing an OOMKilled Immich server (memory limit too low for
real load — see the Immich-specific fix in
[suwayomi-k8s-deployment-fixes.md](suwayomi-k8s-deployment-fixes.md)'s
sibling work that day), which raised the obvious follow-up: what does
*every other* deployment's actual usage look like against what it's
configured for?

## Method

```bash
kubectl top pods -n homelab --containers          # actual live usage
kubectl get deploy -n homelab -o json | jq '...'   # configured requests/limits
```

Compared every container's live memory usage against its configured
`requests`/`limits`, across all 18 deployments (~27 containers) in the
namespace. Two distinct problems exist and need opposite fixes:

- **Limit far above actual usage** → wasted theoretical ceiling, safe to
  trim down (doesn't free scheduling capacity immediately — only
  `requests` count toward that — but reduces node memory-pressure risk).
- **Request below actual usage** → the scheduler has an inaccurate picture
  of what the pod really needs, risking node overcommit even though
  nothing is visibly broken yet. Raise these.

## Trimmed (limit was 3-10x+ above actual usage)

| Container | Before | After |
|---|---|---|
| `oneterm/guacd` | 512Mi | 128Mi |
| `nextcloud/db` | 1Gi | 256Mi |
| `nextcloud/redis` | 256Mi | 64Mi |
| `oneterm/api` | 1Gi | 256Mi |
| `forgejo-db/postgres` | 512Mi | 256Mi |
| `cekping-agent` | 128Mi | 64Mi |
| `bookstack/bookstack` | 512Mi | 128Mi *(see regression below — reverted to 512Mi)* |
| `immich/redis` | 2Gi | 1Gi |
| `couchdb` | 512Mi | 256Mi |
| `crawl4ai` | 1536Mi | 1Gi |
| `nextcloud/app` | 2Gi | 768Mi |
| `oneterm/redis` | 128Mi | 32Mi |
| `oneterm/ui` | 128Mi | 32Mi |

## Raised (request was below actual usage)

`grafana`, `forgejo-app`, `oneterm/acl` (128Mi→384Mi — the largest gap),
`openwebui`, `oneterm/mysql`, `searxng`, `uptime-kuma`, `copyparty`,
`bookstack-db`, `immich/postgres`.

## Proactive fix found along the way: 4 more RWO+RollingUpdate deadlock risks

Before touching resources on any deployment, checked update strategy +
PVC access mode for every one being touched — this exact deadlock
(single-replica + `ReadWriteOnce` PVC + default `RollingUpdate` — new pod
can't attach the volume the old pod still holds, old pod won't die until
the new one is `Ready`) had already bitten a *different* deployment
earlier the same session (see
[suwayomi-k8s-deployment-fixes.md](suwayomi-k8s-deployment-fixes.md)).
Found the identical risk on 4 more deployments that hadn't been touched
yet: `couchdb`, `grafana`, `copyparty`, `openwebui` — all `RollingUpdate` +
`ReadWriteOnce` PVC. Switched all 4 to `Recreate` *before* changing their
resources, avoiding the deadlock entirely rather than discovering it
mid-rollout:

```bash
kubectl patch deployment <name> -n homelab --type=json -p='[
  {"op":"remove","path":"/spec/strategy/rollingUpdate"},
  {"op":"replace","path":"/spec/strategy/type","value":"Recreate"}
]'
```

## Regression caught and fixed: `bookstack` OOMKilled after its own trim

`bookstack`'s limit was trimmed 512Mi→128Mi based on a single snapshot
reading of ~32Mi actual usage — looked like an obvious 4x-headroom trim at
the time. It got OOMKilled shortly after (`exitCode: 137`, confirmed via
`kubectl get pod -o json` → `lastState.terminated`).

**Root cause**: 32Mi was the *steady-state idle* reading. The
LinuxServer.io image's own startup sequence (nginx + PHP-FPM + s6-overlay
init) has a much higher **transient** memory spike during boot that the
128Mi ceiling couldn't absorb. Confirmed via the container's own logs
showing the OOM happened mid-`[ls.io-init]`, not once serving traffic.

**Fix**: reverted to the original 512Mi limit / 128Mi request rather than
try to re-derive a new "optimal" number from another snapshot. Verified
healthy afterward: `0` restarts, and confirmed it was actually *serving*
(not just `Running`) via a direct `curl` returning `302` (normal
login-page redirect), not just trusting the pod phase.

**Lesson, the actual point of documenting this**: a single idle-usage
snapshot does not capture a container's real memory ceiling if that
container has a meaningfully different startup-vs-steady-state profile
(anything running its own init sequence, JIT/interpreter warmup, initial
cache population, etc.). Before trimming a limit based on `kubectl top`
alone, consider whether the workload has a startup burst that a point-in-time
reading wouldn't show — or trim conservatively (more headroom than the
"looks safe" number suggests) for anything with an app-server-style boot
sequence rather than a simple long-running daemon.

## Net effect

Total memory *limits* across the namespace dropped from summing well over
20Gi down to a much tighter, right-sized footprint, without sacrificing
real headroom anywhere (confirmed via the `bookstack` regression + fix
above that "right-sized" doesn't mean "bare minimum"). The under-requesting
containers now give the scheduler an accurate picture instead of a
systematically low one.

## Follow-up, 2026-08-31: 5 more containers drifted past their request, plus the real gap was elsewhere

Re-ran the same `kubectl top --containers` vs. configured `requests`
comparison a day later (triggered by investigating why a Rancher dashboard
panel's "Reserved" and "Used" memory numbers didn't track each other —
see [k8s-deployment-memory-ranking-technique.md](k8s-deployment-memory-ranking-technique.md)).
Real usage had drifted past the declared request on 5 containers since
this audit: `suwayomi` (512Mi→730Mi actual), `openwebui` (768Mi→700Mi,
already close), `immich/server` (1Gi→1000Mi, right at the line),
`crawl4ai` (320Mi→326Mi), `immich/redis` (256Mi→300Mi). Bumped requests
only (limits already had headroom) — full before/after table and exact
commands in
[homelab-system-namespace-resource-audit.md](homelab-system-namespace-resource-audit.md).

The bigger finding that day, though, was that this `homelab`-namespace
audit was never the whole picture — **every deployment outside
`homelab`** (cert-manager, metallb, fleet/capi, democratic-csi,
snapshot-controller, and `rancher` itself) had **no `resources` block at
all**, not even an under-sized one. `rancher` specifically was the
cluster's single largest memory consumer (2.2-2.3Gi) with zero declared
request — invisible to any scheduler-side accounting. See
[homelab-system-namespace-resource-audit.md](homelab-system-namespace-resource-audit.md)
for that pass, and
[rancher-startup-probe-cpu-throttle-restart-loop.md](rancher-startup-probe-cpu-throttle-restart-loop.md)
for what broke when a CPU limit was finally added to Rancher.
