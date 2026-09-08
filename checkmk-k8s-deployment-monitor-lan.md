---
type: how-to
tags: [checkmk, kubernetes, k3s, homelab, monitoring, caddy, technitium, truenas, firewalld]
created: 2026-09-08
last_verified: 2026-09-09
status: current
---

# Deploying checkmk on k3s, exposed at monitor.lan, agents on the LAN fleet

## What was deployed

Checkmk Raw Edition (`docker.io/checkmk/check-mk-raw:2.3.0-latest`, site
id `cmk`) as a plain `Deployment` in the `homelab` namespace on `warp-vm`'s
k3s cluster — same per-app-YAML convention as the rest of
`/home/moo/talos-cluster/homelab-apps/` on `warp-vm` (manifest:
`checkmk.yaml` in that directory).

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: checkmk-data
  namespace: homelab
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 5Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: checkmk
  namespace: homelab
  labels: {app: checkmk}
spec:
  replicas: 1
  strategy: {type: Recreate}
  selector: {matchLabels: {app: checkmk}}
  template:
    metadata:
      labels: {app: checkmk, spread-group: homelab-app}
    spec:
      enableServiceLinks: false
      topologySpreadConstraints:
        - {maxSkew: 1, topologyKey: kubernetes.io/hostname, whenUnsatisfiable: ScheduleAnyway,
           labelSelector: {matchLabels: {spread-group: homelab-app}}}
      # checkmk's site user is uid/gid 1000 inside the image
      securityContext: {fsGroup: 1000}
      containers:
        - name: checkmk
          image: docker.io/checkmk/check-mk-raw:2.3.0-latest
          env:
            - {name: CMK_SITE_ID, value: "cmk"}
            - {name: TZ, value: "Asia/Jakarta"}
            - name: CMK_PASSWORD
              valueFrom: {secretKeyRef: {name: checkmk-secret, key: CMK_PASSWORD}}
          ports:
            - {name: web, containerPort: 5000}
            - {name: agent-receiver, containerPort: 8000}
          volumeMounts:
            - {name: data, mountPath: /omd/sites}
            - {name: tmp, mountPath: /omd/sites/cmk/tmp}
          resources:
            requests: {cpu: 250m, memory: 512Mi}
            limits: {cpu: "2", memory: 2Gi}
      volumes:
        - {name: data, persistentVolumeClaim: {claimName: checkmk-data}}
        - {name: tmp, emptyDir: {medium: Memory}}
---
apiVersion: v1
kind: Service
metadata: {name: checkmk, namespace: homelab}
spec:
  type: LoadBalancer
  selector: {app: checkmk}
  ports:
    - {name: web, port: 5000, targetPort: 5000}
    - {name: agent-receiver, port: 8000, targetPort: 8000}
```

The `data` PVC mounts the *whole* `/omd/sites` directory (not just the
site subfolder) and `tmp` is a `Memory`-medium `emptyDir` layered over
`/omd/sites/cmk/tmp` — this mirrors the official docker-run recommendation
(`-v monitoring:/omd/sites --tmpfs /omd/sites/cmk/tmp:uid=1000,gid=1000`)
rather than inventing a k8s-native equivalent.

`CMK_PASSWORD` is read by the image's entrypoint **only on first boot**,
before the site exists — set the k8s Secret *before* the pod starts
initializing (i.e. right after `kubectl apply`, while the pod is still
`Pending`/pulling the image) if you want a specific password instead of
the auto-generated one printed to logs. Changing the Secret after the
site has already initialized does nothing; you'd need `docker exec ...
htpasswd`/`cmk-passwd` equivalent instead.

Storage class used: `truenas-iscsi` (the cluster's default,
`org.democratic-csi.iscsi`), same as every other homelab-apps PVC.

## Exposure: MetalLB → Caddy → Technitium

Service is `type: LoadBalancer`; MetalLB (`homelab-pool`,
`192.168.50.220-192.168.50.239`, `autoAssign: true`) picked
**`192.168.50.221`** automatically — ports 5000 (web) and 8000
(agent-receiver, unused for now, reserved for future TLS/push-mode
agents).

Caddy block added on `warp-vm` (`/root/caddy/Caddyfile`, rootful-Podman
Quadlet, `Network=host`):
```caddyfile
monitor.lan {
	tls internal
	redir / /cmk/ permanent
	reverse_proxy 192.168.50.221:5000
}
```
The `redir` is needed because checkmk's own root path (`/`) just shows a
plain site-listing page, not the actual UI — the real app lives under
`/<site-id>/`, here `/cmk/`. Reload without downtime:
```bash
podman exec caddy caddy reload --config /etc/caddy/Caddyfile
```

DNS: added `monitor.lan → 192.168.50.200` (Caddy's own host, which then
proxies internally to the real backend — same pattern as every other
`.lan` app) via the Technitium API. See
[technitium-lan-secondary-zone-real-replication.md](technitium-lan-secondary-zone-real-replication.md)
for why a *new* record needed to be added to more than one node at the
time, and the real fix for that.

## Agent rollout (classic pull mode, LAN-only scope)

checkmk dials out to each monitored host's TCP/6556 — no inbound
connectivity needed to the checkmk pod itself for this mode. Packages are
served straight from the site, no separate download needed:
```
http://192.168.50.221:5000/cmk/check_mk/agents/check-mk-agent_2.3.0p49-1_all.deb   (public, no auth)
http://192.168.50.221:5000/cmk/check_mk/agents/check-mk-agent-2.3.0p49-1.noarch.rpm
```

Installed successfully on: `warp` (192.168.50.200), `fedora` (.20, RPM —
`dnf install -y ./check-mk-agent-*.rpm`), `arm1`–`arm4` (.40–.43,
Armbian/Ubuntu — installer falls back to "legacy systemd setup" instead
of the newer `cmk-agent-ctl` daemon path, still works fine), `px1` (.30,
Debian 13). All via `apt-get install -y ./check-mk-agent_*.deb` /
`dnf install -y ./check-mk-agent-*.rpm` (dependency resolution needs the
package-manager wrapper, not bare `dpkg -i`/`rpm -i`).

**Fedora needed a firewall hole**: `firewalld` blocks 6556 by default.
```bash
sudo firewall-cmd --permanent --add-port=6556/tcp && sudo firewall-cmd --reload
```
No other host in this fleet runs a local firewall that got in the way.

### `nas` initially could NOT get the agent — it's a TrueNAS SCALE appliance

`/etc/os-release` reports plain Debian 12, which is misleading — TrueNAS
SCALE hard-blocks `apt`/`dpkg`:
```
Package management tools are disabled on TrueNAS appliances.
Attempting to update TrueNAS with apt or methods other than the TrueNAS
web interface can result in a nonfunctional system.
```
**Update 2026-09-09**: fixed via TrueNAS's own Docker/Apps subsystem —
running the same agent package version as a container, sharing the
host's PID/network namespaces, with a non-obvious `/.dockerenv` gotcha
that silently swaps checkmk's agent to container-scoped (wrong) metrics
if you don't strip it. See
[checkmk-agent-containerized-truenas-host-metrics.md](checkmk-agent-containerized-truenas-host-metrics.md)
for the full writeup — `nas` now reports real `Memory`/`CPU
load`/`Uptime` (filesystem/ZFS pool visibility is still a known gap, not
chased further).

### Hosts skipped entirely this pass

- `homelab` (192.168.50.80) and `px2` (192.168.50.50) were unreachable
  (`no route to host`) at deploy time — `homelab` is the old Talos node
  scaled to 0 (see the Talos→k3s migration doc); add them the same way
  once back up.
- Remote/Cloudflare-tunneled hosts (`vps`, `zenx`, `bri`, `lab-boer`,
  `vpsamu`, `vpd`, `vpz`) were deliberately excluded — pull mode can't
  dial into them; they'd need push-mode/TLS agent registration
  (`cmk-agent-ctl register`) instead, not attempted here.

## Registering hosts + service discovery, via the REST API

```
BASE=http://192.168.50.221:5000/cmk/check_mk/api/1.0
AUTH="cmkadmin:<CHECKMK_ADMIN_PASSWORD>"
```

Create a host:
```bash
curl -sk -u "$AUTH" -X POST "$BASE/domain-types/host_config/collections/all" \
  -H "Content-Type: application/json" \
  -d '{"host_name":"warp","folder":"/","attributes":{"ipaddress":"192.168.50.200","tag_agent":"cmk-agent"}}'
```

Bulk discovery across all hosts at once (returns a background job to
poll):
```bash
curl -sk -u "$AUTH" -X POST "$BASE/domain-types/discovery_run/actions/bulk-discovery-start/invoke" \
  -H "Content-Type: application/json" \
  -d '{"hostnames":["warp","fedora","arm1","arm2","arm3","arm4","px1"],"mode":"fix_all","do_full_scan":true,"bulk_size":10,"ignore_errors":true}'
# poll GET .../objects/discovery_run/bulk_discovery until extensions.state == "finished"
```

Activate changes — **requires an `If-Match: *` header**, otherwise a
`428 Precondition required`:
```bash
curl -sk -u "$AUTH" -X POST "$BASE/domain-types/activation_run/actions/activate-changes/invoke" \
  -H "Content-Type: application/json" -H "If-Match: *" \
  -d '{"redirect":false,"sites":["cmk"],"force_foreign_changes":true}'
```

Result on first run: 7 hosts, 295 services discovered and activated in
one shot (`warp` alone contributed 149 — one `Filesystem` service per
mount, including every containerd/kubelet iSCSI mountpoint on that node,
which is why the count looks high).

## The "Checkmk dashboard" being empty is expected, not a bug

`Monitor > System > Checkmk dashboard` (`dashboard.py?name=checkmk_overview`
-ish; exact view name not confirmed) shows health of *the checkmk server
itself* — its own CPU/RAM, `omd status` helper processes — not your
monitored fleet. It's empty unless the checkmk server/pod is itself added
as a monitored host (self-monitoring), which wasn't done here. The actual
per-host view is:
```
https://monitor.lan/cmk/check_mk/view.py?view_name=allhosts     # All hosts
https://monitor.lan/cmk/check_mk/dashboard.py?name=main         # Main dashboard
```
Click a hostname to drill into its `CPU load` / `CPU utilization` /
`Memory` / `Filesystem ...` / `Interface N` services and their graphs.

## Login

`cmkadmin` / `<CHECKMK_ADMIN_PASSWORD>` — set to match the Technitium DNS
admin password by request (both stored the normal out-of-band way, not
reproduced here — see the repo's secrets policy). Set via the k8s Secret
`checkmk-secret` (`homelab` namespace, key `CMK_PASSWORD`) before first
boot, per the note above.
