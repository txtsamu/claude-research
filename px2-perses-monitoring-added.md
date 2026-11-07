---
type: how-to
tags: [perses, victoriametrics, vmagent, proxmox, px2, node-exporter, blackbox, dashboard, k3s, home, monitoring, pve-exporter]
created: 2026-11-07
last_verified: 2026-11-07
status: current
---

# Adding px2 (Proxmox, 192.168.50.50) to the Perses dashboards

Follow-up to [[perses-dashboards-audit-and-expansion-2026-11-05]] and [[perses-dashboard-victoriametrics-datasource]]. px2 (formerly `pve-nas`, see [[proxmox-px1-px2-rename-cert-fix]]) had no metrics at all: it was not in the `node`, `pve`, `blackbox-icmp` or `blackbox-http` jobs. px1 was the only Proxmox host on the "06 · Proxmox VE" dashboard.

## Status

| Part | State |
|---|---|
| node_exporter on px2 (host metrics) | done, scraped as `job=node, host=px2` |
| ICMP + HTTPS(:8006) probes | done (`job=blackbox-icmp name=px2`, `job=blackbox-http name=proxmox-px2`) |
| Perses: Hosts dashboard, Services & Probes, Overview | px2 shows up (variables are auto-discovered; Overview ICMP regexes edited) |
| Perses: Proxmox dashboard host section for px2 | done (8 panels) |
| PVE API metrics for px2 (guests, storage, node, version) | done after the user approved the token; second exporter `pve-exporter-px2`, job `pve` with `host=px2` |
| Proxmox dashboard pve_* panels | made host-aware (px1 + px2 together), see "PVE metrics for px2" |

## Time estimate

Estimates (no timestamps were recorded), about 25 min for the first part (node, probes, dashboards) plus about 15 min for the PVE token, exporter and dashboard fix.

| Step | Time | Kind |
|---|---|---|
| Recon in claude-research, VM series and k8s configs | ~10 min | estimate |
| `apt install prometheus-node-exporter` on px2 | under 1 min | estimate |
| `vmagent-home` rollout after the ConfigMap edit | ~20 s | measured (rollout status) |
| First node series visible in VM after the restart | ~1 min | estimate |
| First ICMP probe sample visible after the restart | ~2-3 min | estimate (the polling loop needed several tries) |
| Dashboards: script, push, verify | ~5 min | estimate |
| PVE token + exporter rollout (~1 min) + scrape job restart (~20 s) + first `pve_up` sample (~1 min) | ~5 min | estimate |
| pve panel host-awareness fix, test, screenshots | ~10 min | estimate |

## What was found

- px1's scraping lives in two places. The helm release `vmsingle` (values `server.scrape.config` plus `extraScrapeConfigs`) holds `node`, `cloudflared`, `pve`, `blackbox-*`. The ConfigMap `vmagent-home-config` (ns `homelab`, Deployment `vmagent-home`, remote-writes to vmsingle) holds the add-on jobs from the 2026-11-06 follow-up.
- Helm is not usable from `home` for changes (`helm repo list` is empty, the chart would have to be re-added), so px2 was added through `vmagent-home-config`, the same non-helm pattern as CoreDNS/MetalLB/cert-manager. The cost: px2's targets are not in the vmsingle helm values, so a future `helm upgrade` does not remove them but anyone reading only the values file will not see px2. Moving them into the values file is optional cleanup.
- Dashboards: Hosts and Overview use a `host` variable from `node_uname_info`, so px2 appears by itself. Services & Probes uses `probe_success{job="blackbox-http"}` for its variable. Only the Overview ICMP panels had hard-coded name lists (`...|fedora|px1|arm1|...`). The Proxmox dashboard's "Host (px1 node_exporter)" section has `host="px1"`, `device="nvme0n1"`, `eno1` hard-coded.
- px2 hardware differs from px1: no NVMe; disks are `sdf` (111.8 GB SSD) and `sdg` (465.8 GB HDD) plus LVM `dm-0/dm-1`; NIC `eno1` (also `vmbr0`) is the only one with link; hwmon chips `coretemp`, `acpitz`, `hp`. px2 has the PVE firewall off, so port 9100 was reachable without any change.

## Steps (in order)

1. Install node_exporter on px2 (same package and default `ARGS=""` as px1):
   ```bash
   ssh root@px2 'DEBIAN_FRONTEND=noninteractive apt-get install -y prometheus-node-exporter
     systemctl enable --now prometheus-node-exporter
     curl -s localhost:9100/metrics | grep -c ^node_'      # 2632 series
   curl -s -o /dev/null -w '%{http_code}\n' http://192.168.50.50:9100/metrics   # 200 from fedora
   ```
2. Back up and edit the vmagent config. Prometheus-style configs reject a duplicate `job_name`, so px2 is **appended to the existing `node` job's `static_configs`**, and the two probe jobs get new names (`blackbox-icmp-px2`, `blackbox-http-px2`) with `job` set back to `blackbox-icmp` / `blackbox-http` by a relabel rule (so existing dashboard queries keep matching):
   ```bash
   ssh home 'kubectl -n homelab get cm vmagent-home-config -o yaml' > vmagent-home-config.backup.yaml
   ssh home 'kubectl -n homelab get cm vmagent-home-config -o jsonpath="{.data.scrape\.yml}"' > scrape.before.yml
   python3 - <<'EOF'
   import yaml
   d = yaml.safe_load(open('scrape.before.yml'))
   for j in d['scrape_configs']:
       if j['job_name'] == 'node':
           j['static_configs'].append({'targets': ['192.168.50.50:9100'], 'labels': {'host': 'px2'}})
   def probe(name, module, target, label):
       return {'job_name': name, 'metrics_path': '/probe', 'params': {'module': [module]},
         'relabel_configs': [
           {'source_labels': ['__address__'], 'target_label': '__param_target'},
           {'source_labels': ['__param_target'], 'target_label': 'instance'},
           {'replacement': 'blackbox-exporter.homelab.svc.cluster.local:9115', 'target_label': '__address__'},
           {'replacement': name.rsplit('-px2', 1)[0], 'target_label': 'job'}],
         'static_configs': [{'targets': [target], 'labels': {'name': label}}]}
   d['scrape_configs'] += [probe('blackbox-icmp-px2', 'icmp', '192.168.50.50', 'px2'),
                           probe('blackbox-http-px2', 'http_any', 'https://192.168.50.50:8006', 'proxmox-px2')]
   yaml.safe_dump(d, open('scrape.after.yml', 'w'), sort_keys=False)
   EOF
   scp scrape.after.yml home:/tmp/scrape.px2.yml
   ssh home 'kubectl -n homelab create cm vmagent-home-config --from-file=scrape.yml=/tmp/scrape.px2.yml --dry-run=client -o yaml | kubectl apply -f - \
     && kubectl -n homelab rollout restart deploy/vmagent-home && kubectl -n homelab rollout status deploy/vmagent-home --timeout=90s'
   ```
   vmagent does not reload the file by itself here, hence the rollout restart. Rollback: `kubectl apply -f vmagent-home-config.backup.yaml` (strip `resourceVersion`/`uid` if apply complains) and restart the deployment.
3. Verify through the Perses proxy (it only accepts POST; GET returns 403):
   ```bash
   curl -sk https://perses.lan/proxy/globaldatasources/victoriametrics/api/v1/query --data-urlencode 'query=up{host="px2"}'
   curl -sk ... --data-urlencode 'query=probe_success{name=~"px2|proxmox-px2"}'
   ```
   Targets can also be listed from inside the pod: `kubectl -n homelab exec deploy/vmagent-home -- wget -qO- http://127.0.0.1:8429/api/v1/targets`. The ICMP series took longer to show up than the node series; poll instead of assuming failure.
4. Dashboards, with a script that GETs the **live** dashboard, saves a backup, edits and PUTs (`add_px2.py`, helper `pl.py` from the earlier session):
   - Proxmox (`proxmox`): copy the 8 host panels `hcpu hload hmem hnet hdisk hutil htemp hroot` to `h2*` with `px1`→`px2`; `device="nvme0n1"` → `device=~"sdf|sdg"` with legends `{{device}} read/write/busy %`; new Grid "Host (px2 node_exporter)" appended after the px1 one; dashboard title "06 · Proxmox VE (px1, px2)".
   - Overview (`homelab-overview`): `fedora|px1|arm1` → `fedora|px1|px2|arm1` in the two ICMP panels (`hosts`, `lat`).
5. Test every new query through the proxy: all 16 panel queries return data (e.g. `h2disk` 2 series, `h2temp` 8 series); Overview ICMP lists now include `px2`; `node_uname_info` has hosts `arm1-4, fedora, home, nas, px1, px2`; the Services & Probes variable lists `proxmox-px2`.

## PVE metrics for px2 (done after the user approved the token)

The `pve-exporter` Deployment (`prompve/prometheus-pve-exporter:3.10.2`, ns `homelab`) reads **one** set of credentials from Secret `pve-exporter` (`PVE_USER=monitor@pve`, token name `vm`) and px1 is scraped through it via the `pve` job (`__param_target` relabel). px2 is a standalone node, so px1's token is not valid there. The first attempt to create the token was blocked by the session's auto-mode classifier ("access added as a means"); it was done after the user said "go ahead and create the PVE token on px2".

1. On px2: same user and role as px1 (`monitor@pve`, `PVEAuditor` on `/`, token `vm` with `--privsep 0`). The token value went straight from the ssh output into a Kubernetes Secret and the temp files were shredded (never printed):
   ```bash
   ssh root@px2 'pveum user add monitor@pve --comment "Perses/VM read-only" && pveum acl modify / --users monitor@pve --roles PVEAuditor && pveum user token add monitor@pve vm --privsep 0 --output-format json' > tok.json
   # extract .value to a file, scp to home, then:
   kubectl -n homelab create secret generic pve-exporter-px2 --from-literal=PVE_USER=monitor@pve \
     --from-literal=PVE_TOKEN_NAME=vm --from-literal=PVE_VERIFY_SSL=false --from-file=PVE_TOKEN_VALUE=/tmp/px2tokval
   shred -u tok.json /tmp/px2tokval
   ```
2. Second exporter (`pve-exporter-px2.yaml`: Deployment + ClusterIP Service on 9221, same image and resources as the px1 one, `envFrom` the new Secret). Test from a throwaway pod: `curl "http://pve-exporter-px2.homelab.svc.cluster.local:9221/pve?target=192.168.50.50&cluster=1&node=1"` returned `pve_up{id="node/px2"} 1.0` and the 3 guests.
3. Scrape job `pve-px2` added to `vmagent-home-config` (same restart procedure as step 2 above): `metrics_path: /pve`, params `cluster=1`, `node=1`, relabel `__address__` -> `__param_target`, then `__address__` -> `pve-exporter-px2.homelab.svc.cluster.local:9221`, and `job` set to `pve`; static target `192.168.50.50` with label `host: px2`. Result: `pve_up` has 8 series for px1 and 5 for px2.
4. **Dashboard fix that was necessary**: both hosts have `qemu/100` (px1 `tiny11`, px2 `utility-01`), so every join `... * on (id) group_left (name) pve_guest_info` became ambiguous (VictoriaMetrics did not error but matching by `id` alone is wrong). `fix_pve_hosts.py` rewrote all pve panels of the Proxmox dashboard: `on (id)` -> `on (host, id)`, legends now carry the host (`utility-01 (px2)`, `px1 cpu`, ...), and the two tables (`gtab`, `stortab`) got a `Host` column with transforms `MergeIndexedColumns id`, `MergeIndexedColumns host`, `JoinByColumnValue [id, host]`. The Overview stat row was raised from height 4 to 7 because two hosts per tile were cut off.
5. Verified: every non-host panel query returns series for both hosts with 0 duplicate (host,id,name,storage) combinations; headless Chromium screenshots of Overview, Storage and the px2 host section show no "No data" and both hosts in the guest inventory, storage pools, charts and stat tiles. Playwright was run from the existing `agent-1/venv` (`shot_px.py`).

Gotcha: do not join on `id` alone in any new pve panel, since Proxmox VMIDs repeat across standalone hosts.

## Side findings

- `up{job="metallb"}` had a 0: the hard-coded controller target `10.42.0.173:7472` was stale (the controller pod restarted, it is now `10.42.0.40`). Fixed 2026-11-07 on request: `kubectl -n metallb-system get pod -l component=controller -o jsonpath='{.items[0].status.podIP}'`, replaced the IP in `vmagent-home-config` (`sed`, diff showed one line), applied and restarted `vmagent-home`; `up{instance="10.42.0.40:7472"}` = 1. The old `10.42.0.173` series keeps a last sample of 0 and ages out of instant queries after a few minutes. That static IP would break on every controller restart, so the same day it was replaced with pod service discovery (the fix the classifier denied on 2026-11-06; it was done after the user asked again, with a narrower RBAC than the first draft):

1. RBAC, namespaced to `metallb-system` only (`vmagent-metallb-sd-rbac.yaml`): ServiceAccount `vmagent-home` (ns homelab), `Role vmagent-pod-reader` (get/list/watch `pods`) and a RoleBinding, both in `metallb-system`. The earlier draft was a ClusterRole bound in three namespaces; kube-system and cert-manager are not needed for MetalLB. Check: `kubectl auth can-i list pods -n metallb-system --as=system:serviceaccount:homelab:vmagent-home` = yes, `-n kube-system` = no.
2. `kubectl -n homelab patch deploy vmagent-home --type merge -p '{"spec":{"template":{"spec":{"serviceAccountName":"vmagent-home"}}}}'` (backup `vmagent-home-deploy.backup3.yaml`). Before this the Deployment used the `default` account.
3. Scrape config: removed the static `component=controller` target from job `metallb` (the speaker stays static on `192.168.50.200:7472`) and added job `metallb-controller` with `kubernetes_sd_configs: [{role: pod, namespaces: {names: [metallb-system]}}]`, `keep` rules for `app=metallb`, `component=controller` and **container port name `monitoring`**, and relabels `job=metallb`, `component=controller` so the dashboard queries are unchanged. Gotcha: without the port-name `keep`, the pod's second port (webhook 9443) produced a duplicate target and vmagent logged `skipping duplicate scrape target with identical labels` every 30 s.
4. Verified: vmagent targets API shows `metallb controller 10.42.0.40:7472 up` and `metallb speaker ... up`, 0 duplicate/forbidden/error lines in the vmagent log, `up{job="metallb"}` = 2 series, both 1. **Not tested**: restarting the controller to prove the target follows the new pod IP (that restarts MetalLB's controller, so it was left alone); discovery by label makes it follow by design.
5. Rollback: restore `vmagent-home-config.backup4.yaml` and `vmagent-home-deploy.backup3.yaml` (strip `resourceVersion`/`uid`), `kubectl delete -f vmagent-metallb-sd-rbac.yaml`, restart `vmagent-home`.

Files: `scrape.before3.yml`, `scrape.after3.yml`, `scrape.before4.yml`, `scrape.after5.yml` (final), `vmagent-home-config.backup3.yaml`, `backup4.yaml`, `vmagent-metallb-sd-rbac.yaml`.

## Files

`~/sessions/2026-11-05-perses-dashboards-review/px2/`: `vmagent-home-config.backup.yaml`, `scrape.before.yml`, `scrape.after.yml`, `add_px2.py`, `q.sh` (instant-query helper), `pve-exporter-px2.yaml`, `fix_pve_hosts.py`, `shot_px.py`, `scrape.before2.yml` / `scrape.after2.yml`, `vmagent-home-config.backup2.yaml`, `proxmox.before-px2.json` / `proxmox.after-px2.json` / `proxmox.before-pvehost.json` / `proxmox.after-pvehost.json` / `proxmox.before-tiles.json`, `overview.before-px2.json` / `overview.after-px2.json` (rollback: PUT the `before` files to `/api/v1/projects/default/dashboards/<name>`).

## References

- Earlier docs this builds on: [[perses-dashboards-audit-and-expansion-2026-11-05]], [[perses-dashboard-victoriametrics-datasource]], [[proxmox-px1-px2-rename-cert-fix]]
- No external sources were used.
