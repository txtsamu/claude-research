---
type: how-to
tags: [perses, victoriametrics, dashboard, promql, k3s, home, monitoring, node-exporter, snmp, blackbox, zfs, proxmox, helm, oomkilled, subagents]
created: 2026-11-05
last_verified: 2026-11-05
status: current
---

# Perses dashboards on `home`: audit every panel, fix bad data presentation, extend all 8 dashboards

Follow-up to [[perses-dashboard-victoriametrics-datasource]] (which built the first dashboard and the VictoriaMetrics datasource) and [[home-k8s-resource-rightsizing-victoriametrics]]. By 2026-11-05 Perses (v0.55.0, chart `perses-0.24.0`, ns `homelab` on k3s host `home`) held 8 dashboards, all stored **only in the MariaDB database** (no ConfigMaps, no files, no repo). Request: make every dashboard more complete and re-check that each panel presents its data correctly.

## Time estimate

Measured (agent durations from the run, wall clock ~30 min end to end):

| Step | Time | Kind |
|---|---|---|
| Recon, backups, harness | ~10 min | estimate |
| 4 subagents in parallel (2 dashboards each) | 18.3, 24.1, 26.3, 29.3 min | measured |
| `helm upgrade` of vmsingle (pod rollout) | ~20 s | measured |
| Lead verification + rename + this doc | ~15 min | estimate |

## Result

| Order / title | ID (URL slug, unchanged) | Panels before → after |
|---|---|---|
| 01 · Homelab Overview | `homelab-overview` | 15 → 28 |
| 02 · Services & Uptime Probes | `services-probes` | 12 → 21 |
| 03 · Hosts (CPU, Memory, Disk, Network) | `hosts-node-exporter` | 22 → 39 |
| 04 · Kubernetes (k3s) Cluster | `node-and-cluster` | 11 → 36 → 105 (follow-up 2026-11-06) |
| 05 · NAS Storage (TrueNAS & ZFS) | `nas-storage` | 19 → 42 |
| 06 · Proxmox VE (px1) | `proxmox` | 16 → 30 |
| 07 · Network & Router (MikroTik) | `network-router` | 20 → 36 |
| 08 · Cloudflare Tunnels & Monitoring Stack | `tunnels-and-stack` | 15 → 36 |

111 → 268 panels. Final check: 0 empty, 0 NaN, 0 error, 0 missing-legend-label queries across all 8 (details in Verification).

**Ordering trick:** Perses has an immutable ID (`metadata.name`, used in URLs) and a display title (`spec.display.name`); the dashboard list sorts by title. Rename by changing only the title and PUT-ing back, with a `NN · ` numeric prefix for a fixed order (overview → services → hosts → cluster → storage → virtualization → network → monitoring stack).

## Recipe

All commands from the Fedora desktop; the Perses API is unauthenticated on the LAN (`perses.lan` through Caddy, `-k` for the internal TLS cert).

### 1. Snapshot and back up first (dashboards live only in the DB)

```bash
D=~/sessions/2026-11-05-perses-dashboards-review; mkdir -p $D/{data,backups}; cd $D
curl -sk -o data/dash-default.json https://perses.lan/api/v1/projects/default/dashboards
for n in $(jq -r '.[].metadata.name' data/dash-default.json); do
  jq ".[]|select(.metadata.name==\"$n\")" data/dash-default.json > backups/$n.before.json; done
# full DB dump for rollback
ssh moo@home 'kubectl -n homelab exec deploy/perses-mariadb -- sh -c "mariadb-dump -uperses -p\"\$MARIADB_PASSWORD\" perses"' > backups/perses-db-before.sql
```
Rollback of one dashboard: `curl -sk -X PUT https://perses.lan/api/v1/projects/default/dashboards/<name> -H 'Content-Type: application/json' -d @backups/<name>.before.json`.

Gotcha: the project is called `default` (an old session note said `homelab`), `jq` is not installed on `home`, so pull JSON down and use jq locally. A local `curl` may be wrapped by the RTK hook and print truncated output, so write to a file with `-o` before parsing.

### 2. A harness that tests every panel through the browser-facing proxy

The same lesson as the datasource doc: checking VictoriaMetrics directly proves nothing about what Perses shows. `check_panels.py` fetches the live dashboard, substitutes dashboard variables with `.*`, and runs each panel query as an instant **and** a 1h range query through `POST /proxy/globaldatasources/victoriametrics/api/v1/{query,query_range}`. Per query it prints series count, min/max, and flags `EMPTY`, `NaN`, `MANY-SERIES` (>25), `LEGEND-LABEL-MISSING` (a `{{label}}` in `seriesNameFormat` that the result lacks) and `NO-seriesNameFormat(multi)`. A "gentle" copy sleeps 0.6-0.8 s between queries and retries 5xx (see the OOM section). Known false positive: Perses built-in `$__range` is not substituted, so `increase(...[$__range])` returns HTTP 400 in the harness; test those with a concrete range like `[6h]`.

### 3. Delegate: one subagent per pair of dashboards

Four agents, each owning two dashboards, each told to (A) audit, (B) fix, (C) add panels, verify every new query via the proxy before saving, keep scripts in its own subdir, PUT in small increments and re-GET, and take headless-browser screenshots. Dashboard JSON is built with Python scripts and sent with `PUT /api/v1/projects/default/dashboards/<name>` (Perses validates the spec schema on PUT; a bad panel spec is rejected with the reason).

Do not guess panel spec fields. The agents pulled the CUE schemas from `github.com/perses/plugins` (note `main` can be newer than the installed v0.55.0, so only fields the API accepts are safe) and copied working shapes from existing dashboards.

### 4. Raise VictoriaMetrics' resources (the agents' concurrent queries OOM-killed it)

Symptoms: panels blank with `no such host` / proxy HTTP 500 for several minutes; `kubectl describe` shows `OOMKilled`, exit 137, at 21:49 WIB. vmsingle ran at 384Mi memory / 500m CPU limit, working set 360-380Mi.

```bash
ssh moo@home
helm -n homelab get values vmsingle > ~/vmsingle-values-backup-20261105.yaml
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
# the repo index on home was stale (no 0.50.0 entry) but the exact chart tgz is cached for root:
sudo -E helm -n homelab upgrade vmsingle /root/.cache/helm/repository/victoria-metrics-single-0.50.0.tgz \
  --reuse-values --set server.resources.limits.memory=768Mi \
  --set server.resources.limits.cpu=1000m --set server.resources.requests.memory=256Mi
```
Result: Helm revision 9, pod Ready in ~20 s, 69 targets up, 3-day-old data still queryable. Rollback `sudo -E helm -n homelab rollback vmsingle 8`. Do not `kubectl patch` the StatefulSet: the next `helm upgrade` would revert it. Plain `helm` as the `moo` user fails with `permission denied` on `~/.config/helm/repositories.yaml`; use sudo.

### 5. Rename with ordered titles

```bash
for n in ...; do
  curl -sk -o $n.json https://perses.lan/api/v1/projects/default/dashboards/$n
  jq --arg t "NN · Title" '.spec.display.name=$t' $n.json > $n.new.json
  curl -sk -X PUT https://perses.lan/api/v1/projects/default/dashboards/$n -H 'Content-Type: application/json' -d @$n.new.json   # 200
done
```

## Real bugs found in the existing panels (with root cause)

Data was wrong or misleading, not merely incomplete:

- **"NAS pool used" showed 0.0004%.** It queried `node_filesystem_*{host="nas",mountpoint="/mnt/data"}`, which is the near-empty **root ZFS dataset** (7 MB used; its size equals pool free space). node_exporter exposes no zpool size. Fix: sum the used space of every dataset under `data` and add the pool's free space (avail of root dataset `data`):
  `100 * S / (S + max(node_filesystem_avail_bytes{host="nas",fstype="zfs",device="data"}))` with `S = sum(max by (device)(node_filesystem_size_bytes{host="nas",fstype="zfs",device=~"data(/.*)?"} - node_filesystem_avail_bytes{same selector}))`. Gives 48.5%; ground truth on the NAS (`zpool list` CAP 49%, RAIDZ2 on 4x2TB, raw 7.27T) says ~3 points higher because zvols and snapshots are invisible to node_exporter. Related fixes on nas-storage: "Pool size" was free space, "Pool usage over time" plotted a 7 MB series.
- **"Services up" stat was red at 18/18**: fixed thresholds of 20/22 were wrong. Now `100 * avg(probe_success{job="blackbox-http"})`.
- **1/0 status values printed as raw numbers** (`probe_success`, `up`, `pve_up`, `ifOperStatus`, SMART health). Now value mappings (UP/DOWN, RUNNING/STOPPED, PASSED/FAILED, ONLINE/OFFLINE) and coloured backgrounds.
- **Clipped stat tiles**: 8 series in a height-4 tile showed 3. Fix: `seriesColumns` + taller tiles.
- **Duplicate legend names** ("arm1 sent" x4, four series called "rx"): the query was per connection/interface but the legend only used `{{host}}`. Fix: `sum by (host)` / `sum by (interface)`.
- **Mixed scales on one axis** (57 °C and 23.8 V; 14k open files and 1-4 running procs): split into separate panels.
- **Filesystem panels**: ZFS dataset used% is meaningless (~0%) and bind mounts (`/nix/store`, btrfs `/home`, `/var/log.hdd`) duplicate real mounts: 57 series. Restrict to real fstypes and exclude those mountpoints.
- **Disk throughput double counted** whole disks + partitions on arm1-4 (mmcblk). Exclude partitions/zram/loop; "disk busy" drew 55 lines, now `max by (host)`.
- **Temperature legends were raw hwmon ids** and included a bogus -55 °C sensor: join `node_hwmon_chip_names` for driver names.
- **Sentinel/dead targets plotted as 0**: dead ping addresses showed 0 s latency. Fix: `... and on(name) (probe_success{job="blackbox-icmp"} == 1)`.
- **TLS expiry `> 0`** hid already-expired certs.
- **`== bool 1` on `ifOperStatus`** reported an empty SFP cage (status 6, notPresent) as DOWN.
- **Wrong container regex** in "Monitoring pods memory" (`victoria-metrics|...`; real container names are `vmsingle|vmagent|vmalert|alertmanager`).
- **Hard-coded `namespace="homelab"` and `device="/dev/sda2"`** in node-and-cluster: now a `$namespace` variable and node_exporter `{host="home",mountpoint="/"}`.
- **Constant-value time series** (Node Ready, PVC phase, replicas: 26x2 flat lines, 25 flat restart lines) replaced by stats, tables and totals.
- **Units**: rates shown as `decimal`, packets/s, requests/s, bytes vs bits (`rate(ifHCInOctets[..])*8` with `bits/sec`), seconds for power-on hours.

## What was added (highlights)

- **Overview**: alerts firing and over time (`ALERTS` series written by vmalert), load per core, uptime, fullest filesystems, NAS pool/SMART/disk temps, pods running/unhealthy.
- **Services**: summary stats (down counts, soonest cert expiry, avg/slowest HTTP), 7d availability, HTTP time by phase, failing probes over time, `service` variable.
- **Hosts**: summary table (8 queries merged with `MergeColumns` + `JoinByColumnValue`), failed systemd units, swap, OOM kills, IOPS/latency, TCP retransmits, conntrack, inodes, PSI.
- **Cluster**: workloads not ready, last OOMKilled/termination reason, CPU requests/limits vs usage, throttling, PVC usage, k3s API/kine/scheduler panels, `$namespace`.
- **NAS**: pool health, datasets table/pie, disks table (model/serial/temp/health), ARC hit ratio and contents, dataset IO, `disk` variable, 7 collapsible sections.
- **Proxmox**: guest inventory table, storage pool table/gauges, px1 host section (CPU, load, NVMe, temps).
- **Network**: interface table via one `or`-union query with `label_replace(...,"metric",...)` + `PivotByLabel`, port state history, errors/discards, router health, gear table, internet loss/HTTPS/DNS probe time, `interface` variable.
- **Stack**: cloudflared versions/re-registrations, scrape tables, VictoriaMetrics health (disk, churn, query rate/latency, memory vs limit, unclean-shutdown stat), monitoring-pods table, `job` variable.

## Findings worth acting on (not dashboard bugs)

- `home`: 2 kernel OOM kills in the last hour (428 since boot), swapping in, memory limits ~126% of allocatable. vmsingle and forgejo-db were OOMKilled; vmsingle and immich are CPU-throttled ~22%.
- arm1 root filesystem is 90.7% full (eMMC); the DiskFull alert only covers arm4.
- Failed systemd units: cloudflared on px1 and arm1, motd-news on arm2/3/4, netfilter-persistent on arm2.
- NAS drive `sde` (boot SSD) has 1 historic UDMA CRC error; everything else healthy.
- cloudflared version skew: px1 2026.8.2 vs arm1 2026.3.0; `quic_*` metrics exist only on arm1.
- Not available without new exporters: vmalert/alertmanager/vmagent self-metrics and netbird (agents found no scrape job), Proxmox backup age (pve-exporter only gives `pve_not_backed_up_total`), MikroTik CPU/memory (SNMP modules lack it), exact zpool alloc/cap. Perses `bits/sec` is base 2 (1 Gbit/s shows "954 Mib/s"); Perses time-series legends cannot scroll, so 16-23 series panels truncate the legend (hover works).

## Side effect to know about

One agent installed Playwright in a venv for screenshots and `playwright install` deleted the old shared browsers (`chromium-1208`, `chromium_headless_shell-1208`, `firefox-1509`, `webkit-2248`) from `~/.cache/ms-playwright` on the Fedora desktop. Anything else using those builds needs `playwright install` again. The same agent also made read-only `ssh` calls to the NAS (`zpool list`, `zfs list`) to confirm the pool figure.

## Follow-up 2026-11-06: dashboard 04 (Kubernetes) extended from 36 to 105 panels

Request: "more complete, include common errors and things I might have missed, check available metrics". Done inline (single dashboard, not delegated).

### Method (recipe)

1. **Inventory what exists, not what you assume.** Pull metric names per scrape job through the proxy and diff against the tokens the dashboard already uses:
   ```bash
   curl -sk -X POST https://perses.lan/proxy/globaldatasources/victoriametrics/api/v1/query \
     --data-urlencode 'query=count by (__name__)({job="kubernetes-nodes"})' -o names.json
   jq -r '.data.result[].metric.__name__' names.json | sort > names-kubernetes-nodes.txt   # also kubernetes-nodes-cadvisor, kube-state-metrics
   jq -r '.. | .query? // empty' dashboard.json | grep -o -E '[a-zA-Z_:][a-zA-Z0-9_:]*' | sort -u > used.txt
   grep -v -x -F -f used.txt names-kube-state-metrics.txt     # = unused KSM metrics
   ```
   Result: 715 kubelet/k3s names, 85 cAdvisor, 149 kube-state-metrics; only ~37 used before.
2. **Check ambiguous metrics by value before building on them**: `k3s_certificate_expiration_seconds` is *seconds remaining* (~26.5M = 307 days), not a timestamp; `container_pressure_*` exists at pod level (`pod!=""`) as well as cgroup level, so aggregate with `max by (namespace,pod)` not `sum` (pod cgroup + container cgroups would double count).
3. **Build with a script** (`k8s_extend.py`: GET dashboard, add panels with helper functions, rebuild `layouts`, PUT) and **test every new query** (`testq.py`: instant + 3h range through the proxy, flags EMPTY/NaN/missing legend label) *before* pushing. 73 built, 4 returned nothing and were dropped.
4. **Push, re-run the harness on the live dashboard** (105 panels, only intentional empty table flagged), then screenshot.

### What was added (69 panels, 11 sections)

- **Common errors & problem pods**: containers waiting, running-not-Ready, Pending, Failed/evicted, Unschedulable, restarts (15m), OOM kills (1h, cAdvisor `container_oom_events_total`), cordoned nodes, namespaces Terminating, containers without memory/CPU limit, BestEffort pods; problem timeline; containers closest to memory limit %; waiting-reason table (CrashLoopBackOff / ImagePullBackOff...); last-exit-code table (137 killed/OOM, 143 SIGTERM...); restarts last 24h.
- **Rollouts, scheduling & lifecycle**: Deployments mid-rollout (`metadata_generation != observed_generation`), unavailable replicas, paused deployments, DaemonSet unavailable/misscheduled, StatefulSets not updated, pods started <1h, scheduler attempts by result, scheduler queues, QoS classes, youngest pods.
- **Pod pressure, I/O & network errors**: PSI memory/CPU/IO per pod, network errors/drops, disk I/O by pod, threads/FDs, node memory composition.
- **Storage (appended)**: PVs not Bound, PVCs predicted full in 24h (`predict_linear`), VolumeAttachments not attached, PV capacity, PVC free bytes, PVC inode %, container log size, volume operations/h.
- **Kubelet & runtime health**: soonest k3s cert expiry, node evictions, runtime op errors, pod start errors, PLEG relist p99, runtime latency p99, REST client non-2xx.
- **k3s control plane & API server (appended)**: in-flight requests, API priority & fairness queue, 5xx / post-timeout / TLS handshake / datastore errors, authentication results, stored objects by kind, workqueue retries and wait p99, k3s goroutines & FDs.
- **Networking**: LoadBalancer IPs assigned / without IP, Services, kube-proxy pending changes, Services by type.
- **Inventory & coverage**: Kubernetes version, nodes, node age, pods total, node table, object counts, and a Markdown "Not monitored yet" panel.

Sections reordered: Cluster health → Common errors → Rollouts → Node capacity → Workloads → Pressure/I-O → Storage → Kubelet → Control plane → Networking → Inventory.

### Gotchas found

- The `kubernetes-nodes` / cadvisor scrape jobs use `labelmap` relabeling, so **every series carries ~20 node labels**. Always aggregate (`sum by`, `max by`) or use `defaultColumnHidden: true` on tables; otherwise legends and tables are unreadable.
- **Dropped (query returned nothing)**: `kubelet_pod_start_sli_duration_seconds` p99/p50 (histogram too sparse over 1h), `container_fs_usage_bytes{container!=""}` (cAdvisor only reports fs usage at cgroup level here), `kubeproxy_sync_proxy_rules_duration_seconds` and `kubeproxy_network_programming_duration_seconds` p99 (no observations in window). Re-try with another window or label filter if needed.
- **Intentionally empty-when-healthy**: the "Containers waiting - reason" table (KSM only emits `waiting_reason` while a container is waiting). All count tiles use `or vector(0)` so they show 0.
- **Not scraped, so no panels** (listed on the dashboard): CoreDNS, MetalLB, cert-manager, kube-ovn, Traefik, Kubernetes Warning events; kube-state-metrics emits no Job/CronJob/HPA/ResourceQuota series here. `kube_lease_renew_time` still lists stale Rancher leases (`cattle-controllers`) left from the Rancher decommission, so no lease panel was built.
- **Screenshots of Perses lie for lazy panels**: panels are only rendered when scrolled into the viewport, so a `full_page` Playwright screenshot shows empty sections. Scroll each section into view (`page.get_by_text("<section title>", exact=True).scroll_into_view_if_needed()`, wait ~6 s) and take a viewport screenshot instead. Removing panels leaves layout holes: widen the neighbours (`x`/`width`) and PUT again.
- Running a local helper script with `python3 -I` breaks `from pl import *` (isolated mode drops the script directory from `sys.path`); use `-I` only for scripts that read untrusted data.

### Files

`~/sessions/2026-11-05-perses-dashboards-review/lead/`: `k8s_extend.py` (builder), `testq.py` (query tester), `k8s.before-extend.json` (rollback: PUT this file), `k8s.final-live.json` (pushed, version 9), `shot_sections.py` (section screenshots), `testq-1.txt` (test output).

## Verification

- Harness over all 8 live dashboards (gentle copy): 0 `EMPTY`, 0 `NaN`, 0 `LEGEND-LABEL-MISSING`. The only `ERROR`s were the two `$__range` panels (harness artifact; with `[6h]` they return 19.6 GB and 2.26 GB). `MANY-SERIES` only on pivot tables and on panels where the harness substitutes `.*` for `$disk`.
- Each agent screenshotted its dashboards with headless Chromium (Playwright in a per-agent venv) and looked at them: no "No data", no error banners, no overlap. Not verified: clicking every variable dropdown (spot-checked `?var-disk=sda`, `guest`, `namespace` via proxy), the last small layout tweaks after the final screenshots, other browsers.
- After the rename: all 8 PUTs returned 200 and the list sorts 01-08.

## References

- [Perses plugins repo (CUE schemas for Table, StatChart, GaugeChart, BarChart, TimeSeriesChart, StatusHistoryChart)](https://github.com/perses/plugins)
- [Perses plugin documentation](https://perses.dev/plugins/docs/)
- [Perses dashboard resource schema](https://raw.githubusercontent.com/perses/perses/main/docs/api/dashboard.md)
- Earlier docs this builds on: [[perses-dashboard-victoriametrics-datasource]], [[home-k8s-resource-rightsizing-victoriametrics]]
