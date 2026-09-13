---
type: investigation
tags: [kubernetes, k3s, resource-limits, victoriametrics, right-sizing, home, memory, checkmk, monitoring]
created: 2026-09-10
last_verified: 2026-09-13
status: current
---

# Right-sizing `home`'s k8s resource requests/limits — done

**Status: complete.** 60 hours of real VictoriaMetrics data collected, request/limit changes applied to every deployment via `kubectl set resources`, all rollouts clean, node memory limit overcommit dropped from **145% → 116%**. See [[warp-vm-nixos-migration-plan]] for the original memory-overcommit finding this stems from, and [[k3s-swap-nixos-correct-setup]] for the (still-in-place) swap stopgap.

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

## Final pass (2026-09-13, ~60h of real data)

`quantile_over_time(0.95, container_memory_working_set_bytes{namespace="homelab",container!=""}[60h])` plus a matching `max_over_time(...)` query (not just P95 — see below for why both mattered) against every container.

**The headline finding, and the whole reason the point-in-time snapshot was worth discarding**: several apps have a much wider P95-to-real-max gap than an idle snapshot could ever show, and in more than one case the *point-in-time proposal from three days earlier would have been a real regression*:

| Container | P95 (60h) | Real MAX (60h) | Old snapshot proposal (2026-09-10, not applied) | What actually shipped |
|---|---|---|---|---|
| immich `server` | 2462Mi | **3857Mi** | limit **2Gi** ← would have OOM-killed it | request 2560Mi, limit **4608Mi** (↑ from 4Gi) |
| immich `redis` | 24Mi | **338Mi** (job-queue bursts) | request 64Mi / limit 128Mi ← would have OOM-killed it | request 128Mi, limit **512Mi** |
| forgejo `app` | 358Mi | **904Mi** (git-gc-class spike) | request 160Mi / limit 320Mi ← would have OOM-killed it | request 384Mi, limit **1152Mi** |
| checkmk | 1157Mi | 1307Mi | request 1280Mi (this one was already right) | request 1280Mi, limit 1664Mi |

Every other container (suwayomi, flaresolverr, openwebui, uptime-kuma, crawl4ai, nextcloud's three containers, bookstack's two, couchdb, searxng, forgejo's postgres sidecar, plus the monitoring stack's own `vmsingle`) had a tight, stable P95≈MAX and got sized straightforwardly off P95+10-15% for the request and real-MAX+~25-30% for the limit. copyparty, cekping-agent, and nextcloud's redis sidecar were left unchanged — either already well-sized or too small in absolute terms to be worth the churn.

Applied via `kubectl set resources deployment/<name> -n homelab -c <container> --requests=memory=Xi --limits=memory=Yi` (and `statefulset/...` for `vmsingle` itself) — one command per container needing a change, no manifests to hand-edit since these were originally deployed imperatively.

**Verification, real not just "rollout succeeded"**:
- `kubectl rollout status` clean on all 13 touched deployments
- 0 pods in a bad state cluster-wide afterward
- `kubectl describe node home` → memory limits **145% → 116%** of node capacity (requests actually went *up*, 52% → 65%, since several containers — checkmk, immich-server, suwayomi — were under-requesting relative to real usage; the fix was never "shrink everything," it was "match reality")
- Every `.lan` app route re-checked with a real HTTP request post-rollout, not just "pod is Running." Two (`nextcloud.lan`, `openwebui.lan`) briefly returned `000`/`502` during the rollout's pod-replacement window itself — both cleared on their own within a minute once the new pod became Ready, confirmed to not be a real regression by retesting.

## Kept running long-term (2026-09-13)

Decided to keep VictoriaMetrics rather than tear it down — the one-off measurement job is done, but ongoing visibility into real per-container usage is worth having. Two changes to go from "temporary 48h tool" to "standing fixture":

- **Retention: `7d` → `60d`.** Sized off real observed growth (`du -sh` on the data dir showed ~171MB over the first ~3 days, so ~60MB/day → roughly 4-5GB over 60 days, comfortably inside the new PVC).
- **PVC: `2Gi` → `10Gi`.** `local-path`'s StorageClass has `allowVolumeExpansion: false`, so this needed a full `helm uninstall` + delete the StatefulSet-managed PVC (which, unlike a Deployment's PVC, is **not** auto-deleted on uninstall - a real gotcha, caught before assuming a plain `helm upgrade` would resize it) + reinstall, rather than an in-place resize. Acceptable since only ~3 days/171MB of measurement-exercise data existed at that point.
- Left the compute resource requests/limits (128Mi/384Mi... now 192Mi/384Mi after the right-sizing pass above) and the Helm-chart-not-Operator choice as-is — no functional reason to churn either just because retention got longer.

`local-path` still means this data lives on the node's own root disk (72% used / ~26G free before this), not a separate volume — worth keeping an eye on if that fills up, since a 10Gi reservation on an already-tight disk is a real, if modest, tradeoff for the visibility.

Re-verified post-reinstall: both scrape targets (`kubernetes-nodes-cadvisor`, `kubernetes-nodes`) came back healthy, `--retentionPeriod=60d` confirmed on the running process's actual args (not just the values file), and real per-container data confirmed flowing again.

## Open follow-up

If dashboards/alerting are ever wanted on top of this (not asked for yet - PromQL queried directly has been sufficient), that's the point to reconsider the Operator-based install (`victoria-metrics-k8s-stack`, VMAgent/VMAlert/Grafana declaratively managed) rather than bolting more pieces onto the plain Helm chart by hand.

## References

- [Kubernetes autoscaling explained: HPA, VPA & best practices — Sedai](https://sedai.io/blog/kubernetes-autoscaling)
- [How to Right-Size Kubernetes Resource Requests and Limits — oneuptime.com](https://oneuptime.com/blog/post/2026-01-06-kubernetes-right-size-resources/view)
- [Kubernetes Requests and Limits: The Complete 2026 Guide — ScaleOps](https://scaleops.com/blog/kubernetes-resource-requests-and-limits/)
- [So You Want to Be a Wizard: How Kubernetes Memory Requests and Limits Actually Work — CloudBolt](https://www.cloudbolt.io/how-kubernetes-requests-limits-work/memory/)
- [Guides: Kubernetes monitoring via VictoriaMetrics Single](https://docs.victoriametrics.com/guides/k8s-monitoring-via-vm-single/)
- [VictoriaMetrics K8s Stack — Helm Charts](https://docs.victoriametrics.com/helm/victoria-metrics-k8s-stack/) (the Operator-based alternative, deliberately not used here)
