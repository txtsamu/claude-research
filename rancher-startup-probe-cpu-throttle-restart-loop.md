---
type: troubleshooting
tags: [rancher, kubernetes, cpu-limits, startup-probe, helm, cattle-system, homelab]
created: 2026-08-31
last_verified: 2026-08-31
status: current
---

# Rancher restart-loop after adding CPU/memory limits — startup-probe timeout, not OOM

Part of a broader "set requests/limits on everything that's missing them"
pass (see [homelab-system-namespace-resource-audit.md](homelab-system-namespace-resource-audit.md)).
`rancher` had **no `resources` set at all** (`resources: {}` in the chart
values) despite being the single largest memory consumer on the cluster
(2.2-2.3Gi across 2 replicas).

## Sizing decision

Sized off real observed usage (`kubectl top pods -n cattle-system -l app=rancher`:
885Mi / 1327Mi per replica) rather than either of the two official
reference points found (HA-production: 2 CPU/4Gi request, 4 CPU/8Gi limit
— way oversized for a 3-worker/8-24Gi homelab; small/non-HA: 250m/256Mi
request, 1000m/1Gi limit — this exact profile is what caused the incident
below):

```sh
helm upgrade rancher rancher-latest/rancher --namespace cattle-system --version 2.15.1 \
  --reuse-values \
  --set resources.requests.memory=1Gi \
  --set resources.requests.cpu=250m \
  --set resources.limits.memory=3Gi \
  --set resources.limits.cpu=1000m
```

## Symptom

Both replicas stuck in a restart loop:
```
Warning  Unhealthy  Startup probe failed: Get "http://<pod-ip>:80/healthz": dial tcp <pod-ip>:80: connect: connection refused
```
Not OOMKilled (`lastState.terminated.reason: "Error"`, `exitCode: 1`, not
`OOMKilled`) — ruled that out immediately via
`kubectl describe pod ... | grep -A20 Events` and the previous-container
logs.

## Root cause

`kubectl logs <pod> --previous` showed the container mid-bootstrap
(applying dozens of embedded CRDs, restoring catalog git repos) when it
received `SIGTERM` — `[WARNING] signal received: "terminated", canceling
context...`. The chart's default `startupProbe` (`failureThreshold: 12`,
`periodSeconds: 10` = **120s total**) wasn't generous enough for this
CPU-heavy bootstrap phase once capped at `1000m` (1 core) — previously
unconstrained, Rancher could burst multiple cores through this exact
phase.

First fix attempt (bump CPU limit alone) **wasn't sufficient**:
```sh
helm upgrade rancher rancher-latest/rancher --namespace cattle-system --version 2.15.1 \
  --reuse-values --set resources.limits.cpu=2000m
```
Made genuine incremental progress each restart (got further into the
controller-startup sequence — CRDs → leader election → cluster
controllers — before each kill) but still didn't finish inside 120s,
worsened by 2 replicas now doing leader-election/websocket handshakes
with each other during the simultaneous rollout.

## Actual fix: loosen the startup probe, not just CPU

The chart exposes `startupProbe` as an overridable value block:
```sh
helm upgrade rancher rancher-latest/rancher --namespace cattle-system --version 2.15.1 \
  --reuse-values --set startupProbe.failureThreshold=30   # 120s -> 300s
```

**Gotcha**: this specific `helm upgrade` returned client-side
`Error: UPGRADE FAILED: another operation (install/upgrade/rollback) is
in progress` (a prior upgrade's SSH session got interrupted mid-flight,
leaving the release stuck in `pending-upgrade`) — but the manifest change
had *already* reached the Kubernetes API before the client-side lock
check failed. Confirmed via `helm history rancher -n cattle-system`
showing the release settle to `deployed` anyway, and
`kubectl get deploy rancher -o jsonpath='{.spec.template.spec.containers[0].startupProbe}'`
showing `failureThreshold: 30` live on the actual Deployment despite the
CLI error. **Don't trust the Helm CLI's own exit code/error alone here —
check the live cluster object.**

## Result

```
NAME                       READY   STATUS    RESTARTS   AGE
rancher-f7d988977-qm8vl   1/1     Running   0          3m36s
rancher-f7d988977-zpmtm   1/1     Running   0          3m35s
```
Final config: `requests: cpu=250m, memory=1Gi` / `limits: cpu=2000m,
memory=3Gi`, `startupProbe.failureThreshold=30`.

## Lesson

Adding resource limits to something that's never had them is not a
memory-only concern — a CPU limit that's fine for steady-state can starve
a one-time CPU-heavy bootstrap sequence past whatever startup-probe window
the chart assumes for an *unconstrained* container. Before capping CPU on
anything with its own multi-phase bootstrap (CRD installation, DB
migrations, cache warmup, etc. — not just Rancher), check whether the
chart's startup/readiness probe timing was tuned assuming unconstrained
CPU, and budget the probe window accordingly rather than just the limit
value itself.
