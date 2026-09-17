---
type: how-to
tags: [perses, victoriametrics, dashboard, kubernetes, k3s, mariadb, home, monitoring, caddy, technitium, kube-state-metrics, promql]
created: 2026-09-13
last_verified: 2026-09-17
status: current
---

# Perses dashboard on `home`, VictoriaMetrics as the datasource

Context: [[home-k8s-resource-rightsizing-victoriametrics]] stood up a lightweight VictoriaMetrics instance for a resource right-sizing exercise, then kept it running for ongoing visibility. This doc covers adding a real visualization layer on top of it - [[warp-vm-nixos-migration-plan]] for the overall `home` migration this all sits on.

## The storage-backend decision (read this before copying the values)

Perses only ships two storage backends - `file` (JSON/YAML files on disk) or `sql` (a real MySQL/MariaDB-compatible database). There's no built-in SQLite option. Which backend you pick also decides the Kubernetes workload kind:

- `file` → StatefulSet + a small PVC. Simplest, zero extra dependencies.
- `sql` → Deployment, but requires an actual MariaDB/MySQL server as a dependency.

**Perses' own docs are explicit that `sql` is recommended only for multi-instance deployments** (shared/consistent storage across replicas) - for a single instance, `file` is the officially sufficient choice, and doesn't need a database server at all. This setup deliberately used `sql` anyway (user's call, wanting the Deployment kind specifically) - flagging this clearly since it's not the lightest option, and the tradeoff (a whole extra MariaDB instance for what a single-instance Perses doesn't functionally need) is worth knowing about before copying this pattern elsewhere.

## What's running

- `perses-mariadb` - plain Deployment + 1Gi PVC (`local-path`), dedicated `perses` database/user, `MARIADB_RANDOM_ROOT_PASSWORD=yes` (root access never needed - only the app-level `perses` user is used)
- `perses` - the official `perses/perses` Helm chart, `config.database.sql` pointed at `perses-mariadb.homelab.svc.cluster.local:3306`, DB password injected via `envVars` (`PERSES_DATABASE_SQL_PASSWORD`, chart auto-creates the backing Secret) rather than hardcoded into the values file
- VictoriaMetrics wired up as the default `GlobalDatasource` (`kind: PrometheusDatasource` - VictoriaMetrics speaks the Prometheus HTTP API natively, no adapter needed)
- One dashboard, "home: Node & k3s Cluster" - 6 panels, real PromQL against the metrics already being collected (see below)
- Exposed at `perses.lan` via Caddy, same ClusterIP-direct `reverse_proxy` pattern already used for `rancher.lan` (Perses' Service is ClusterIP-only - no MetalLB LoadBalancer IP spent on another internal-only dashboard)

## MariaDB

```yaml
# perses-mariadb.yaml (Deployment + PVC + Service, homelab namespace)
- image: mariadb:11
  env:
    MARIADB_DATABASE: perses
    MARIADB_USER: perses
    MARIADB_PASSWORD: <from Secret perses-mariadb-secret>
    MARIADB_RANDOM_ROOT_PASSWORD: "yes"
  resources:
    requests: { cpu: 20m, memory: 128Mi }
    limits: { cpu: 300m, memory: 320Mi }
```
Password generated fresh (`openssl rand -base64 24`) and stored as a plain `kubectl create secret generic` - not committed anywhere.

## Perses Helm values (the real gotcha: `file` must be explicitly nulled)

```yaml
resources:
  requests: { cpu: 20m, memory: 96Mi }
  limits: { cpu: 300m, memory: 256Mi }

config:
  database:
    file: null   # <- required. The chart's default values.yaml already sets `database.file`,
                 #    and Perses refuses to start with both file *and* sql configured -
                 #    "[ERROR] Both 'config.database.file' and 'config.database.sql' cannot
                 #    be set at the same time." - your own values.yaml adding `sql:` on top
                 #    isn't enough, the inherited default has to be nulled out explicitly.
    sql:
      user: "perses"
      net: "tcp"
      addr: "perses-mariadb.homelab.svc.cluster.local:3306"
      db_name: "perses"

envVars:
  - name: PERSES_DATABASE_SQL_PASSWORD
    value: "<the mariadb password>"   # PERSES_<YAML_PATH> env-var override pattern
```

```bash
helm repo add perses https://perses.github.io/helm-charts
helm repo update
helm install perses perses/perses -n homelab -f perses-values.yaml
```

## Real bug: the ConfigMap+sidecar provisioning path has a startup race - don't trust it for a one-shot setup

The chart supports a `sidecar.enabled: true` mode (a `kiwigrid/k8s-sidecar` container watching ConfigMaps labeled `perses.dev/resource: "true"`, writing them into a shared provisioning folder) - this is the chart's own recommended, non-deprecated way to provision datasources/dashboards declaratively. Tried it first; it never worked:

- The **main Perses container checks its provisioning folder exactly once, at startup** (confirmed from the logs - a single `provisioning.Execute()` call, not a loop).
- The **sidecar's own initial sync can take ~2 minutes** when `allNamespaces: true` (it has to list ConfigMaps across the whole cluster), confirmed via its own timestamped logs (`Writing .../victoriametrics.yaml` at +3s, but `Writing .../project.yaml` and `.../dashboard.yaml` not until +2min).
- Both containers start at roughly the same time, in the same pod. The main container's one-shot check reliably loses this race - every restart repeated `lstat /etc/perses/provisioning: no such file or directory`, even after confirming (via `kubectl exec ... ls`) that the sidecar *had* already written the files by the time of a second restart attempt.
- `provisioning.interval: 10m` in the chart's values looked like it might mean a periodic re-scan that would eventually self-heal past the race - waited ~9 minutes, it didn't help within that window (untested whether it ever would; not worth the wait once the alternative below was confirmed to just work).

**Fixed by skipping the provisioning-folder mechanism entirely** and creating the `Project`, `GlobalDatasource`, and `Dashboard` resources directly via the Perses REST API instead:
```bash
curl -X POST http://<perses-pod-ip>:8080/api/v1/projects \
  -H 'Content-Type: application/json' -d '{"kind":"Project","metadata":{"name":"default"}}'

curl -X POST http://<perses-pod-ip>:8080/api/v1/globaldatasources \
  -H 'Content-Type: application/json' -d @datasource.json

curl -X POST http://<perses-pod-ip>:8080/api/v1/projects/default/dashboards \
  -H 'Content-Type: application/json' -d @dashboard.json
```
These land straight in the SQL database, so they persist across pod restarts with zero dependency on the sidecar - confirmed by disabling the sidecar afterward (reclaiming its ~32-96Mi) and verifying the dashboard was still there after a full pod restart.

## Datasource resource

**Real bug, found by the user's browser (2026-09-17): every panel failed with `NetworkError when attempting to fetch resource`.** The datasource was originally created with `directUrl` -

```yaml
# WRONG for this setup - browsers can't resolve cluster-internal DNS
kind: GlobalDatasource
metadata:
  name: victoriametrics
spec:
  default: true
  plugin:
    kind: PrometheusDatasource
    spec:
      directUrl: http://vmsingle-victoria-metrics-single-server.homelab.svc.cluster.local:8428
```

`directUrl` means the **browser itself** fetches straight from that address - fine if the datasource has a real, browser-reachable URL, but `vmsingle-victoria-metrics-single-server.homelab.svc.cluster.local` is a Kubernetes-internal Service DNS name, only resolvable from inside the cluster's own pod network. It worked fine when I tested it server-side (`curl` from `home`'s host network, which - like Caddy's ClusterIP routes elsewhere on this box - can reach cluster-internal addresses just fine), which is exactly what made it look done before a real browser ever loaded the dashboard.

**Fix: switch to `proxy` mode**, which flips the fetch path so the **Perses backend** (which genuinely lives inside the cluster's reach) does the querying on the browser's behalf, and only ships the *results* to the browser:

```yaml
kind: GlobalDatasource
metadata:
  name: victoriametrics
spec:
  default: true
  plugin:
    kind: PrometheusDatasource
    spec:
      proxy:
        kind: HTTPProxy
        spec:
          url: http://vmsingle-victoria-metrics-single-server.homelab.svc.cluster.local:8428
          allowedEndpoints:
            - endpointPattern: "/api/v1/labels"
              method: "POST"
            - endpointPattern: "/api/v1/series"
              method: "POST"
            - endpointPattern: "/api/v1/metadata"
              method: "GET"
            - endpointPattern: "/api/v1/query"
              method: "POST"
            - endpointPattern: "/api/v1/query_range"
              method: "POST"
            - endpointPattern: "/api/v1/label/([a-zA-Z0-9_-]+)/values"
              method: "GET"
```
`allowedEndpoints` is a real whitelist, not decoration - only the listed API paths/methods get proxied through; the six above cover everything a dashboard's queries/variables/autocomplete actually need.

Applied via `PUT /api/v1/globaldatasources/victoriametrics` (updates in place, no need to delete/recreate). Verified through the *actual* path the browser now uses, not just "the API call succeeded":
```bash
curl -X POST "http://<perses-pod-ip>:8080/proxy/globaldatasources/victoriametrics/api/v1/query" -d 'query=up'
# -> real result set, confirming the proxy path itself works end-to-end
```

**Lesson**: testing a `directUrl`-style datasource by curling it from the server/cluster network proves the URL is *reachable from there* - it says nothing about whether the actual client (a browser on the LAN) can reach the same address. Any datasource pointed at a Kubernetes-internal DNS name needs `proxy`, not `directUrl`, full stop - there's no context where a browser will ever resolve `*.svc.cluster.local`.

## Dashboard: "home: Node & k3s Cluster"

Researched what a Kubernetes cluster dashboard should actually cover before just extending the original 6-panel one - the standard framing (USE method for infrastructure: Utilization/Saturation/Errors, applied per the CNCF/general k8s-monitoring guidance) splits into two layers that need *different* metric sources:

- **Resource usage** (node/pod CPU, memory, disk, network) - cAdvisor covers this, already had it.
- **Object state** (pod phase/restarts, deployment replica health, PVC status, node readiness) - cAdvisor has no idea about this at all; it only sees cgroups, not Kubernetes API objects. This needs **kube-state-metrics**, which wasn't deployed on this cluster - added it (`prometheus-community/kube-state-metrics` Helm chart, tight resources: `20m/64Mi` request, `200m/192Mi` limit) and wired it into VictoriaMetrics as a fourth scrape job (plain `static_configs` target, no k8s service-discovery needed for a single well-known ClusterIP).

Final dashboard, 11 `TimeSeriesChart` panels:

| Panel | Source | PromQL |
|---|---|---|
| Node Ready | kube-state-metrics | `kube_node_status_condition{condition="Ready",status="true"}` |
| Pods by Phase | kube-state-metrics | `sum(kube_pod_status_phase{namespace="homelab"}) by (phase)` |
| Pod Restarts (1h) | kube-state-metrics | `sum(increase(kube_pod_container_status_restarts_total{namespace="homelab"}[1h])) by (pod)` |
| Deployment Replicas: Available vs Desired | kube-state-metrics | `kube_deployment_status_replicas_available{namespace="homelab"}` + `kube_deployment_spec_replicas{namespace="homelab"}` |
| PVC Status | kube-state-metrics | `sum(kube_persistentvolumeclaim_status_phase{namespace="homelab"}) by (phase)` |
| Node Memory Usage % | cAdvisor | `container_memory_working_set_bytes{id="/"} / on(instance) machine_memory_bytes * 100` |
| Node CPU Usage % | cAdvisor | `sum(rate(container_cpu_usage_seconds_total{id="/"}[5m])) by (instance) / on(instance) machine_cpu_cores * 100` |
| Top 10 pods by memory | cAdvisor | `topk(10, container_memory_working_set_bytes{namespace="homelab",container!=""})` |
| Top 10 pods by CPU | cAdvisor | `topk(10, rate(container_cpu_usage_seconds_total{namespace="homelab",container!=""}[5m]))` |
| Node Filesystem Usage | cAdvisor | `max(container_fs_usage_bytes{id="/",device="/dev/sda2"}) by (device)` |
| Node Network I/O | cAdvisor | `rate(container_network_receive_bytes_total{id="/"}[5m])` (rx) + transmit (tx) |

`id="/"` is cAdvisor's root-cgroup series - the whole-node aggregate, not any single container. Panel/query/layout schema confirmed against the real dashboard API response after creation (Dashboard → Panel → TimeSeriesChart → TimeSeriesQuery → PrometheusTimeSeriesQuery, with `query` as the actual PromQL field name), not just the docs.

### Two more real PromQL bugs found testing every panel through the actual browser-facing proxy path (not just "the API call succeeded")

1. **Node Memory/CPU % returned empty vectors** - classic PromQL vector-matching failure. `container_memory_working_set_bytes{id="/"}` and `machine_memory_bytes` both genuinely have data, but their full label sets differ (`id`, `boot_id`, `machine_id`, `system_uuid`...) - a bare `/` division requires an *exact* label match on both sides by default, so it silently returns nothing rather than erroring. Fixed with `on(instance)` to match only on the one label both series actually share.
2. **The CPU query broke *again* after adding `on(instance)`** - `sum(rate(...))` with no `by()` clause strips every label from its output, including `instance`, so `on(instance)` then has nothing to match against on the left side either. Needed `by (instance)` inside the `sum()` to preserve exactly that one label through the aggregation, *then* `on(instance)` to match it against the right side. The general lesson: any aggregation (`sum`, `max`, `topk`, etc.) without an explicit `by()` drops all labels - if you need to join the result against another series afterward, you have to deliberately keep whatever label you're joining on.
3. **Node Filesystem Usage returned 182 series**, not the one expected - `container_fs_usage_bytes{id="/"}` genuinely reports once per block device the node can see, and this node has ~20 real iSCSI-backed PVC devices attached (`democratic-csi` provisions one LUN per PVC - matches the `lsblk` output from earlier in the migration, not a bug). Narrowed to `device="/dev/sda2"` (the actual host root disk) since that's what "node filesystem" should mean for this panel - the per-PVC devices are a separate, per-app storage concern already visible in the app-level dashboards on Checkmk.

Every query above was verified for real by curling it through `/proxy/globaldatasources/victoriametrics/api/v1/query` on the actual running Perses pod - the exact path the browser uses - not just checked against VictoriaMetrics directly (that only proves the datasource has the data, not that Perses' proxy layer and the PromQL itself are both correct).

## Exposure and DNS

Caddy route (`hosts/home/proxy.nix`):
```
virtualHosts."perses.lan".extraConfig = ''
  tls internal
  reverse_proxy 10.43.155.107:8080    # Perses' own ClusterIP
'';
```

**Real gotcha, same class as always with this LAN**: Technitium's `.lan` zone isn't a wildcard - every new hostname needs an explicit A record, and I couldn't add it myself. The wholesale-copied Technitium database (from the `warp-vm` → `home` migration, see [[warp-vm-nixos-migration-plan]]) uses `warp-vm`'s *original* admin password, not the agenix bootstrap secret - confirmed this dead-ends the same way it did back in T19. Needed the real password from the user to log in and add:
```bash
TOKEN=$(curl -s 'http://127.0.0.1:5380/api/user/login?user=admin&pass=<real password>&includeInfo=false' | jq -r .token)
curl "http://127.0.0.1:5380/api/zones/records/add?token=$TOKEN&domain=perses.lan&zone=lan&type=A&ipAddress=192.168.50.200&ttl=3600"
```

## Verification (real, not just "pods are Running")

- Caddy route tested with `--resolve perses.lan:443:192.168.50.200` *before* the DNS record existed → real HTTP 200
- After the DNS record landed: plain `dig perses.lan` resolves correctly, plain `curl https://perses.lan/` (no `--resolve` override) → real HTTP 200
- Dashboard confirmed present via `GET /api/v1/projects/default/dashboards` both immediately after creation and again after a full pod restart with the sidecar disabled, confirming persistence is genuinely coming from the SQL database, not the ephemeral provisioning folder

## References

- [Perses installation - Helm charts](https://perses.dev/helm-charts/docs/installation/)
- [Perses dashboard resource schema (`docs/api/dashboard.md`)](https://raw.githubusercontent.com/perses/perses/main/docs/api/dashboard.md)
- [Perses project resource schema (`docs/api/project.md`)](https://raw.githubusercontent.com/perses/perses/main/docs/api/project.md)
- [Dash0 - Perses dashboard source format reference](https://www.dash0.com/docs/dash0/dashboards/reference-dashboard-source-format) (concrete `TimeSeriesChart`/`PrometheusTimeSeriesQuery` YAML example)
- [Perses helm-charts repo](https://github.com/perses/helm-charts)
- Perses' own `values.yaml` (`https://raw.githubusercontent.com/perses/helm-charts/main/charts/perses/values.yaml`) - fetched directly for the exact `database`/`sidecar`/`resources` schema, since the hosted docs pages didn't cover it
- [Prometheus datasource plugin model - Perses](https://perses.dev/plugins/docs/prometheus/model/) - the `directUrl` vs `proxy`/`HTTPProxy` schema, found while fixing the browser `NetworkError` bug
- [Understanding Kubernetes metrics: Best practices for effective monitoring - CNCF](https://www.cncf.io/blog/2026/03/18/understanding-kubernetes-metrics-best-practices-for-effective-monitoring/) - the node/pod/control-plane layering that shaped which panels to add
- [The USE Method - Kubernetes SLIs](https://oneuptime.com/blog/post/2026-02-09-sli-red-use-methods/view) - utilization/saturation/errors framing used to pick the new cluster-health panels
- [kube-state-metrics essential dashboards](https://kubestatemetrics.com/blog/grafana-dashboards/) and the [kube-state-metrics GitHub repo](https://github.com/kubernetes/kube-state-metrics) - confirmed the exact metric names (`kube_pod_status_phase`, `kube_node_status_condition`, etc.)
- [kube-state-metrics Helm chart - prometheus-community](https://artifacthub.io/packages/helm/prometheus-community/kube-state-metrics) - install command and lightweight resource-limit flags
