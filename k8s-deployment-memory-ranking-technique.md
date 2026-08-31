---
type: how-to
tags: [kubernetes, kubectl, memory, rancher, monitoring, homelab, warp-vm]
created: 2026-08-31
last_verified: 2026-08-31
status: current
---

# Ranking Talos cluster deployments by real memory usage, and why Rancher's "Reserved vs Used" numbers don't match

Originated the resource-audit chain documented in
[homelab-system-namespace-resource-audit.md](homelab-system-namespace-resource-audit.md) —
started as a simple "what's using the most RAM" check.

## Technique: join `kubectl top pods` with owner references

`kubectl top pods` reports per-*pod*, not per-*deployment* — and pod
names carry a random ReplicaSet-hash suffix, so grouping by workload needs
an actual owner-reference lookup, not string-matching the pod name:

```sh
kubectl top pods -A --no-headers > /tmp/pod_top.txt
kubectl get pods -A -o json > /tmp/pods.json
```
Then in Python: for each pod, walk `metadata.ownerReferences` — a
`ReplicaSet` owner's own name minus its trailing `-<hash>` gives the
Deployment name (regex `^(.*)-[a-z0-9]{6,10}$`); `DaemonSet`/`StatefulSet`/
`Job`/`CronJob` owners are used directly. Sum `kubectl top`'s parsed
`Mi`/`Gi`/`Ki` memory per resulting `(namespace, workload, kind)` key, sort
descending. To scope to specific nodes only (e.g. workers, excluding
control-plane static pods), also pull `spec.nodeName` per pod from the
same JSON and filter before aggregating.

## Mistake made and self-caught: reusing cached files across follow-up questions

Saved `/tmp/pod_top.txt`/`/tmp/pods.json` once, then reused them for a
follow-up "workers only" breakdown a few messages later **without
re-fetching**. In between, the user had scaled `oneterm` to `0` replicas
— the stale files still showed its old ~0.76Gi figure as though it were
current. User caught it by asking "why is memory still high" after
scaling down; live re-check confirmed `oneterm` was genuinely at 0Mi
(`kubectl get deployment oneterm -n homelab` → `0/0/0`, no pods, no `top`
entries) — the number reported earlier really was just stale.

**Lesson**: cached intermediate files are fine *within* a single
investigation, but re-fetch (`kubectl top`/`kubectl get -o json`) at the
start of any follow-up question rather than reusing them across turns —
cluster state changes between messages, especially when the user is
actively acting on what you just told them (scaling something down,
restarting a deployment, etc.).

## Why Rancher's dashboard "Reserved" and "Used" memory numbers don't track each other

Surfaced while investigating a specific Rancher panel reading `Reserved
7.83/21.78 GiB (35.95%)` / `Used 16.86/23.2 GiB (72.67%)`:

- **The two different denominators (21.78 vs 23.2 GiB) are worker-node
  scoped, not cluster-wide**: `21.78Gi` = sum of the 3 workers'
  *allocatable* memory (capacity minus Talos's own per-node reserved
  overhead); `23.2Gi` = sum of their raw *capacity*. Confirmed by
  computing `kubectl get nodes -o json` capacity/allocatable directly and
  matching the exact figures — this Rancher panel is scoped to schedulable
  (worker) nodes specifically, not the whole 6-node cluster.
- **"Reserved" only counts pods with an actual `resources.requests.memory`
  set.** Summed real pod requests on workers only (`kubectl get pods -A -o
  json`, filtered to worker `nodeName`, summed
  `containers[].resources.requests.memory`) → **7.83Gi exactly**, matching
  the panel. At the time, `rancher` itself (the single biggest real
  consumer, 2.2-2.3Gi) had **no request declared at all** — invisible to
  this number despite being the top line item in actual usage.
- **"Used" reflects real OS-level memory** (via node-exporter/Prometheus,
  not `kubectl top`'s cAdvisor-based container working-set sum) — includes
  page cache, containerd, kubelet, and Talos OS overhead that no
  individual pod "owns". `kubectl top nodes` summed to ~9.9Gi across
  workers at the same moment Rancher's UI showed 16.86Gi "Used" — the
  ~7Gi gap is exactly that system-level overhead.

Net: a "Reserved" far below "Used" is not automatically a leak or a
misconfiguration — it means requests are absent/too-low relative to real
usage (Kubernetes only enforces `limits`, not `requests`, so nothing stops
a pod from running well past what it nominally asked for) and/or the
dashboard's usage metric includes non-pod-attributable OS overhead that
request-based bookkeeping was never going to capture anyway.
