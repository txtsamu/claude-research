---
type: investigation
tags: [kubernetes, k3s, resource-limits, victoriametrics, right-sizing, home, memory, checkmk]
created: 2026-09-10
last_verified: 2026-09-10
status: current
---

# Right-sizing `home`'s k8s resource requests/limits — in progress, 48h data collection running

**Status: mid-flight.** Real usage data is being collected via a freshly-deployed VictoriaMetrics instance; final numbers and the actual `kubectl patch`/manifest changes haven't been applied yet. This doc will get a follow-up update once the 48h window closes. See [[warp-vm-nixos-migration-plan]] for the original memory-overcommit finding this stems from, and [[k3s-swap-nixos-correct-setup]] for the (already-applied) stopgap mitigation.

## Why

Checkmk flags `home` memory CRIT at 157% of physical RAM committed (kernel-level `Committed_AS` virtual memory accounting). Investigating the actual driver turned up **two distinct kinds of overcommit**, confirmed with real numbers rather than assumption:

1. **Kernel-level**: `Committed_AS` (28.7 GiB) vs `CommitLimit` (16.5 GiB, RAM+swap) — inherently inflated since it sums every process's *reserved* virtual memory, not what's actually resident. Real RSS (`ps aux --sort=-rss`) showed the actual drivers: `k3s server` itself at 1.2 GB (k3s bundles API server + etcd + scheduler + controller-manager + kubelet + containerd supervision into one process), plus a genuinely dense stack of independently-heavy processes — a JVM (Suwayomi), several separate Python interpreters (open-webui, hermes-gateway, headroom-proxy, immich-api), a kept-warm headless browser (camoufox), Postgres backends, checkmk's Apache, etc.
2. **Kubernetes scheduler-level**: pod memory *requests* sum to a healthy 52% of node capacity (what the scheduler actually uses for admission), but pod memory *limits* sum to **145%** — a completely separate, independent form of overcommit. `kubectl describe node home` under "Allocated resources" is the fastest way to see this at a glance.

Neither is a bug — it's what running a full k8s control plane + 13 apps + ~10 native daemons on one 16GB box looks like, a pre-existing structural fact from before this migration even started, not something the migration caused.

## Methodology (researched, sourced)

Current best-practice consensus for right-sizing:
- **Requests** should reflect real demand: target the P95 (or P99, sources differ slightly) of observed usage over a representative window (24-48h minimum, ideally longer to catch weekly patterns), plus a 10-20% buffer.
- **Memory limits** should stay *close* to the request (1.25-1.5x), not a big multiplier like CPU gets — because memory limit breaches are destructive (OOM-kill, binary) where CPU throttling is merely slower. This is the opposite intuition from CPU limits, where 2-5x the request (or removing the limit entirely) is normal for burst headroom.
- **Tools**: metrics-server + `kubectl top` gives an instant point-in-time snapshot (already used once, see below); a real percentile needs either VPA in recommendation-only mode (builds its own internal decaying histogram from repeated metrics-server polls, no separate timeseries DB needed) or a Prometheus-compatible store queried with `quantile_over_time`.
- **QoS classes**: `request == limit` → Guaranteed (last evicted, for anything production-critical); `request < limit` → Burstable (most common); no resources set → BestEffort (first evicted).
- **Common pitfalls flagged in the research**: copy-pasting identical resource values across unrelated apps regardless of actual profiling; setting requests 10-20x above real usage (wastes schedulable capacity); limits more than ~5x requests causing real contention if multiple pods burst simultaneously; missing resource specs entirely (BestEffort QoS, evicted first under any pressure).

## First-pass point-in-time snapshot (superseded once 48h data lands)

`kubectl top pods -n homelab --containers` against the currently-configured requests/limits turned up real, specific over- and under-provisioning — not hypothetical:

- **Worst limit-overcommit offender**: `immich`'s three containers configured with `4Gi + 2Gi + 1Gi = 7Gi` combined memory limit against **999Mi + 537Mi + 17Mi ≈ 1.5Gi** actual combined usage — over 4x real usage, and roughly 30% of the *entire node's* limit overcommit from this one app alone.
- **A real correctness gap, not just tidiness**: `checkmk`'s memory *request* (512Mi) was actually *below* observed real usage (1.1Gi) — the scheduler thinks it needs less than half what it actually uses.
- Several smaller apps (forgejo, nextcloud's db sidecar, immich's redis sidecar) had limits 8-15x their real usage.

A full proposed before/after table was drafted from this snapshot (available in this session's own transcript if needed), but **not applied** — the snapshot is a single point in time, not a real percentile, and immich/forgejo/suwayomi in particular can spike much higher during actual bulk imports/git-gc/library scans than an idle-ish moment shows. Applying tight limits off a lucky quiet snapshot risked introducing real OOM-kills the "fix" was supposed to prevent.

## What's actually running now: VictoriaMetrics (not the Operator, not Prometheus)

Deployed the plain `victoria-metrics-single` Helm chart directly — **not** the VictoriaMetrics Operator (that earns its keep managing several VM components — VMAgent, VMAlert, etc. — declaratively as a growing permanent platform; for one temporary 48h measurement job, the operator's own controller pod is overhead this memory-constrained box doesn't need for a one-off job). Chosen over Prometheus specifically for the much lighter memory footprint at comparable functionality (same PromQL query language, remote-write/scrape compatible).

```bash
helm repo add vm https://victoriametrics.github.io/helm-charts/
helm repo update
sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml helm install vmsingle vm/victoria-metrics-single \
  -n homelab -f vmsingle-values.yaml
```

Key values (kept deliberately light so the monitoring doesn't undermine the thing it's measuring):
```yaml
server:
  retentionPeriod: "7d"
  persistentVolume:
    enabled: true
    storageClassName: local-path   # NOT the TrueNAS iSCSI backend - short-lived data, doesn't need SAN-grade storage
    size: 2Gi
  resources:
    requests: { cpu: 50m, memory: 128Mi }
    limits: { cpu: 500m, memory: 384Mi }
  scrape:
    enabled: true
    config:
      scrape_configs:
        - job_name: "kubernetes-nodes-cadvisor"     # the one that actually matters - per-pod/container CPU+memory
          metrics_path: /metrics/cadvisor
          scheme: https
          kubernetes_sd_configs: [{ role: node }]
          # ...ca_file/bearer_token_file/relabel_configs per the standard k8s-via-SD pattern
```

### Real bug found and fixed: kubelet's port 10250 was never open in `home`'s firewall

The `kubernetes-nodes-cadvisor` scrape target came up `down` with a connection timeout (not refused) against `https://<home-ip>:10250/metrics/cadvisor`. `home`'s NixOS firewall only ever opened `6443` (the k3s API server) — port `10250` (kubelet's own API, which both cAdvisor scraping and, apparently through some different path, `metrics-server`'s own `kubectl top` scraping depend on) had never been opened externally, and simply went unnoticed until something tried to reach it from outside the node's own network namespace. Fixed in `k3s.nix`:
```nix
networking.firewall.allowedTCPPorts = [ 6443 10250 ];
```
After the fix and a `nixos-rebuild switch`, the `cadvisor` target came up healthy; confirmed with a direct PromQL query showing real, correctly-labeled per-container data (`container_memory_working_set_bytes{namespace="homelab",pod=~"immich.*"}` returning `server 1235Mi / redis 17Mi / postgres 545Mi` — closely matching the earlier `kubectl top` snapshot, confirming the data is genuine).

## Next steps (when picking this back up)

1. Let the 48h window complete (started 2026-09-10, ~16:02 local).
2. Query real P95/P99 per container:
   ```
   quantile_over_time(0.95, container_memory_working_set_bytes{namespace="homelab",container!=""}[48h])
   ```
3. Recompute request/limit proposals from that (formula above), not the point-in-time snapshot.
4. Present the before/after table for review before applying (same pattern as every other production change in this migration — confirm before batch `kubectl patch`/manifest changes across 13 deployments).
5. After applying: re-check `kubectl describe node home`'s "Allocated resources" limit percentage dropped meaningfully, and that no app regressed (real HTTP checks on every `.lan` route, not just "pod is Running").
6. Decide whether to tear down the VictoriaMetrics instance afterward (it was explicitly scoped as a temporary measurement tool, 7d retention) or keep it running longer-term — if keeping it, worth reconsidering the Operator-based install at that point since it'd no longer be a one-off job.

## References

- [Kubernetes autoscaling explained: HPA, VPA & best practices — Sedai](https://sedai.io/blog/kubernetes-autoscaling)
- [How to Right-Size Kubernetes Resource Requests and Limits — oneuptime.com](https://oneuptime.com/blog/post/2026-01-06-kubernetes-right-size-resources/view)
- [Kubernetes Requests and Limits: The Complete 2026 Guide — ScaleOps](https://scaleops.com/blog/kubernetes-resource-requests-and-limits/)
- [So You Want to Be a Wizard: How Kubernetes Memory Requests and Limits Actually Work — CloudBolt](https://www.cloudbolt.io/how-kubernetes-requests-limits-work/memory/)
- [Guides: Kubernetes monitoring via VictoriaMetrics Single](https://docs.victoriametrics.com/guides/k8s-monitoring-via-vm-single/)
- [VictoriaMetrics K8s Stack — Helm Charts](https://docs.victoriametrics.com/helm/victoria-metrics-k8s-stack/) (the Operator-based alternative, deliberately not used here)
