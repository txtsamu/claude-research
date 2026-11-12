---
type: troubleshooting
tags: [rancher, monitoring, victoriametrics, kubelet, vmservicescrape, relabeling, kubernetes]
created: 2026-11-12
last_verified: 2026-11-12
status: current
---

# Rancher monitoring kubelet VMServiceScrape: `__` stripped from every relabel source label

## Context

Read-only analysis of a `VMServiceScrape` named `rancher-monitoring-kubelet` in
`kube-system` on a remote, inaccessible Rancher-provisioned cluster (Rancher
monitoring chart `104.1.2_up57.0.3`, VictoriaMetrics operator). No cluster
access, no repo changes. Worktree `/home/moo/diskos`.

## Symptom class

Kubelet targets may scrape fine, but anything relying on the `metrics_path`
label or on the cAdvisor high-cardinality drop rules is broken. Typical
visible fallout: `KubeletDown` alert fires, `k8s-resources-*` and `kubelet`
dashboards show no data, container CPU/memory recording rules empty.

## Root cause

The manifest looks like Rancher's kubelet `ServiceMonitor` mechanically
translated into a VictoriaMetrics `VMServiceScrape`, and every
`sourceLabels` entry lost its double-underscore prefix:

| Manifest value | Upstream chart value | Effect |
| --- | --- | --- |
| `sourceLabels: [name]` in 5 `metricRelabelConfigs` drops | `__name__` | regex never matches, drop rules are dead |
| `sourceLabels: [metrics_path]` in 3 `relabelConfigs` | `__metrics_path__` | no `metrics_path="/metrics"` or `"/metrics/cadvisor"` label |
| `sourceLabels: [address]` in 2 cluster label rules | `__address__` | static `replacement` still lands, but source is wrong (and `__address__` is not available at metric-relabel stage anyway) |

The operator writes `metrics_path` to the generated scrape config as a
parameter (`vmscrapes.go`, `addCommonScrapeParamsTo`), never as a label, so
nothing else recreates it.

## Why it breaks Rancher rules and dashboards

Rancher's recording rules, alerts, and dashboards filter on the label value:

- `KubeletDown`: `absent(up{job="kubelet", metrics_path="/metrics"} == 1)` -> always fires.
- `kubelet.rules` (PLEG histograms) and `kubernetes-storage` volume alerts: `metrics_path="/metrics"`.
- `k8s.rules.*`: `metrics_path="/metrics/cadvisor"` for
  `node_namespace_pod_container:*` CPU/memory recording rules.
- Dashboard panels: 27 matches in `k8s-resources-cluster`, 31 in `kubelet`,
  26 in `k8s-resources-pod`, etc.

The five dead drops mean `container_cpu_*`, `container_fs_*`,
`container_memory_swap`, `container_spec.*`, `container_file_descriptors`,
`container_tasks_state`, `container_threads_max` still get ingested. The
`id`/`pod` `. +;` rule still works because those are real metric labels.

## Verification

Pulled the actual chart and compared values:

```bash
curl -sL https://charts.rancher.io/index.yaml -o /tmp/opencode/rancher-index.yaml
curl -sL "https://charts.rancher.io/assets/rancher-monitoring/rancher-monitoring-104.1.2%2Bup57.0.3.tgz" -o /tmp/opencode/rm.tgz
tar xzf /tmp/opencode/rm.tgz -C /tmp/opencode/rmchart
python3 - <<'EOF'
import yaml
sm = yaml.safe_load(open('/tmp/opencode/rmchart/rancher-monitoring/values.yaml'))['kubelet']['serviceMonitor']
print(sm['relabelings'], sm['cAdvisorMetricRelabelings'])
EOF
```

Result: upstream uses `__metrics_path__` and `__name__`; the manifest uses
`metrics_path` and `name`.

Operator rendering confirmed from `VictoriaMetrics/operator` source:

```go
if cs.Path != "" {
    cfg = append(cfg, yaml.MapItem{Key: "metrics_path", Value: cs.Path})
}
```

`generateRelabelConfig` copies `SourceLabels` verbatim, no underscore
handling.

## Correct form

```yaml
relabelConfigs:
- action: replace
  sourceLabels: [__metrics_path__]
  targetLabel: metrics_path
metricRelabelConfigs:
- action: drop
  sourceLabels: [__name__]
  regex: container_cpu_(cfs_throttled_seconds_total|load_average_10s|system_seconds_total|user_seconds_total)
```

For the cluster labels the source label can be dropped entirely because the
replacement is static (or `instance` if it must be dynamic at metric stage).

## Other observations, lower severity

- `cluster_id` / `cluster_name` are only on endpoint 1, so cAdvisor and
  probes series have no cluster identity unless vmagent adds it globally.
  This is how Rancher's chart ships it, not a manifest-specific bug.
- `honorTimestamps: true` on the cAdvisor endpoint. VictoriaMetrics'
  own k8s-stack chart sets it false for cAdvisor (VictoriaMetrics issue
  #4697). Rancher's chart defaults to true, so treat as tuning, not defect.
- `tlsConfig.ca: {}` / `cert: {}` are harmless: the operator ignores empty
  secret selectors.
- No `interval` / `scrapeTimeout` set; inherits vmagent defaults.

## Not verified

- Whether anything else in the cluster adds a `metrics_path` label
  (global relabel, external labels). If it does, part of the impact goes away.
- Whether the `kubelet` Service actually exists in `kube-system` with
  `app.kubernetes.io/name: kubelet` and `k8s-app: kubelet`.
- Whether the VMAgent's `serviceScrapeNamespaceSelector` includes
  `kube-system` (the CR lives there, the Helm release does not).
- Whether the VMAgent service account has `nodes/metrics` RBAC. A 403 on
  kubelet scrapes is a separate failure mode with the same "no data" look.

## Related

- [[rancher-upgrade-2.15.1]]
- [[kubewall-lighter-rancher-dashboard-deploy]]
- [[rancher-talos-to-k3s-migration]]
