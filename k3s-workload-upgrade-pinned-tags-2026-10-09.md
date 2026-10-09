---
type: how-to
tags: [k3s, home, upgrade, helm, democratic-csi, truenas, nextcloud, immich, forgejo, snapshotter, api-key-rotation, version-pinning, subagents]
created: 2026-10-09
last_verified: 2026-10-09
status: current
---

# k3s workload upgrade to latest pinned versions (2026-10-09)

Goal (user rule, from now on): every container image uses an explicit latest **version tag**, never `latest` or a floating tag. Upgrade all k3s workloads except `kube-system` and k3s itself. Done with three parallel subagents (infra, file/data apps, other apps) plus manual follow-ups. Databases and caches stayed on their current **major** (a major bump needs dump/restore); only patch/minor bumps were allowed.

kubectl on home is `sudo k3s kubectl` (no standalone kubectl). Images were changed live (`kubectl set image`, or Helm for chart-managed releases), so any manifest source still shows the old tags.

## Result

| Workload | Old | New | How |
|---|---|---|---|
| cert-manager (3 deployments) | v1.21.1 | v1.21.2 | Helm `--reuse-values` |
| VictoriaMetrics (vmsingle) | v1.151.0 | v1.153.0 | Helm, chart kept at 0.46.0, only `server.image.tag` |
| perses-mariadb | `mariadb:11` | `mariadb:11.8.9` (same version, now pinned) | `set image` |
| democratic-csi controller + node | `:latest` | `:v1.9.5` | Helm (see below) |
| BookStack | 26.05.20260608 | v26.09.1-ls287 | `set image` |
| copyparty | 1.20.21 | 1.20.25 | `set image` |
| Nextcloud | 33.0.8 | 34.0.4 (one major step) | `set image`, occ upgrade ran at pod start |
| Immich server | v3.2.4 | v3.3.1 | `set image` |
| Forgejo | 16.0.3 | 16.0.5 | `set image` |
| Open WebUI | v0.11.3 | v0.11.4 | `set image` |
| Uptime Kuma | 2.5.3 | 2.5.5 | `set image` |
| CouchDB init (busybox) | 1.37.0 | 1.38.0 | `set image` |
| Suwayomi / FlareSolverr | v2.3.2359 / v3.5.0 | v2.4.2366 / v3.5.2 | tags only, Deployment stays at 0 replicas |
| route-manager, vm-bot | built this session | 0.2.0 / 0.1.0 | own images, imported with `k3s ctr` |

Already latest, unchanged: kubewall 0.0.23, kube-state-metrics v2.20.0, perses v0.54.0.

Not applied on purpose:
- **MetalLB** v0.15.2: v0.16 changes CRDs, RBAC and metrics; bumping only images is unsafe because the Layer2 speaker serves every LoadBalancer IP. Needs a deliberate manifest upgrade.
- **Database/cache majors**: Postgres (Nextcloud, Forgejo 16; Immich image on 14 with vectorchord 0.4.3), Redis 7.4, Valkey 9.1.2, MariaDB 11.8, CouchDB 3.5.2 (3.5.3 is RC only).
- **Nextcloud 35**: a further major step; drops PHP 8.2.
- **searxng, crawl4ai**: scaled to 0 earlier because the user does not need them; left out.
- **cekping-agent** is still `:latest`: its running digest (`sha256:7384164758bc...`) matches only the `latest` tag; no numbered registry tag has the same digest, so pinning a version would silently change the build. Option: pin by digest `repo@sha256:...` (immutable, same image).

## Safety steps that mattered

- Backups before any stateful change, in `/root/k3s-upgrade-backups-2026-10-09/` on home: Nextcloud `pg_dump`, Immich `pg_dumpall` (1.7 GB), Forgejo `pg_dumpall` + `/data`, CouchDB / Open WebUI / Uptime Kuma data tarballs, old Deployment YAML, VictoriaMetrics snapshot, perses-mariadb dump (`/home/moo/perses-mariadb-backup-20261009.sql`). BookStack's MariaDB only got a crash-consistent file copy of the data dir: logical dumps kept stalling (256Mi limit + slow iSCSI), and the partial `bookstack-db.sql` there is **not** usable.
- Pre-pull images on home before rolling (`sudo k3s ctr images pull ...` or `crictl pull`) so a bad pull cannot take a workload down.
- One workload at a time, `rollout status`, then a functional check (HTTP status, `/api/v1/version`, `occ status`, `/api/server/ping`).
- Final state check: no non-running pods, 23/23 PVs Bound, all VolumeAttachments attached.

## democratic-csi (holds all deployment data) — handled separately

All PVs are `Retain`; StorageClass `truenas-iscsi` reclaims with `Delete` for new volumes only. Controller uses RollingUpdate.

1. **Aborted sidecar bump.** An agent started bumping `csi-attacher` v4.4.0 -> v4.13.0 before it was told this component is safety-critical. The new pod never became Ready; `helm rollback democratic-csi 1` restored the original. The old controller pod served the whole time and the node pod was never touched. Rule given to the agent afterwards: do democratic-csi last, pin-only, never jump sidecar minors without a compatibility reason, never touch PVCs/PVs/StorageClasses/TrueNAS.
2. **Read the 470 restarts correctly.** The controller pod showed 470 restarts, but that is the sum over six containers (12+3+128+83+123+121), all from one event at 2026-09-28 04:28 (driver socket down -> sidecars got 502 and restarted). Nothing had restarted for 11 days. It is not a crash loop.
3. **Real problem: csi-snapshotter log spam.** `failed to list *v1.VolumeSnapshotContent: the server could not find the requested resource` (~7,700 lines/day) because the VolumeSnapshot CRDs were not installed. Fix, additive and no pod restart:

   ```bash
   B=https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/v8.2.1/client/config/crd   # match the sidecar (v8.2.1)
   for f in snapshot.storage.k8s.io_volumesnapshotclasses snapshot.storage.k8s.io_volumesnapshotcontents snapshot.storage.k8s.io_volumesnapshots; do curl -fsSL $B/$f.yaml -o /tmp/$f.yaml; done
   sudo k3s kubectl apply --server-side -f /tmp/snapshot.storage.k8s.io_volumesnapshot{classes,contents,s}.yaml
   ```
   Errors dropped to 0. This only stops the errors: real snapshots would also need the cluster-wide snapshot-controller (not installed).
4. **Pin `latest` -> `v1.9.5`.** The running `latest` image (built 2026-01-07) matches no tag; v1.9.5 is about two hours older. Pre-pull, dry-run, then upgrade through Helm so a later `helm upgrade` does not revert it:

   ```bash
   # helm config/cache under ~/.config/helm and ~/.cache/helm on home are root-owned: point Helm at temp dirs
   export HELM_CACHE_HOME=/tmp/hc HELM_CONFIG_HOME=/tmp/hf HELM_DATA_HOME=/tmp/hd; mkdir -p /tmp/hc /tmp/hf /tmp/hd
   sudo k3s ctr images pull ghcr.io/democratic-csi/democratic-csi:v1.9.5
   R="--repo https://democratic-csi.github.io/charts/ --version 0.15.1"
   helm -n democratic-csi upgrade democratic-csi democratic-csi $R --reuse-values \
     --set controller.driver.image.tag=v1.9.5 --set node.driver.image.tag=v1.9.5 --dry-run=client | grep -E '^\s+image:'
   helm -n democratic-csi upgrade democratic-csi democratic-csi $R --reuse-values \
     --set controller.driver.image.tag=v1.9.5 --set node.driver.image.tag=v1.9.5 --atomic --timeout 5m
   ```
   Result: controller 6/6, node 4/4, 0 restarts, 23 PVs Bound, VolumeAttachments attached (a fresh attach for Immich worked on the new controller).
5. **Mistake and key rotation.** While diffing the deployed manifest I printed the whole Helm manifest, which includes the `democratic-csi-driver-config` Secret with the TrueNAS API key (`httpConnection.apiKey`). The key was rotated the same day, using the old key to mint a new one, then Helm to roll it out, then deleting the old key:

   ```bash
   # TrueNAS 25.10: list keys (metadata only), create a new one for the same user, verify it, roll out via Helm, delete the old one
   curl -sk -H "Authorization: Bearer $OLD" https://192.168.50.10/api/v2.0/api_key
   curl -sk -X POST -H "Authorization: Bearer $OLD" -H 'content-type: application/json' \
     -d '{"name":"democratic-csi-2026-10","username":"root"}' https://192.168.50.10/api/v2.0/api_key      # response .key is shown once
   curl -sk -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $NEW" https://192.168.50.10/api/v2.0/system/version   # 200
   printf 'driver:\n  config:\n    httpConnection:\n      apiKey: %s\n' "$NEW" > /dev/shm/dcsi-key.yaml   # umask 077, removed right after
   helm -n democratic-csi upgrade democratic-csi democratic-csi $R --reuse-values -f /dev/shm/dcsi-key.yaml --atomic --timeout 5m
   curl -sk -X DELETE -H "Authorization: Bearer $NEW" https://192.168.50.10/api/v2.0/api_key/id/1
   ```
   Rotate through Helm, not by patching the Secret: the Secret is rendered from the release values, so a later `helm upgrade --reuse-values` would restore the old key. The Helm values changing also changes the pod-template checksum, which restarts the pods. The old key text still sits in Helm release revisions 1-4 and in the session transcript (now revoked). The key belongs to `root`; a dedicated limited TrueNAS user would be tighter.

## Incidents and gotchas

- **Forgejo outage (~10 min).** The first rollout stalled pulling `codeberg.org/forgejo/forgejo:16.0.5` (~20 KB/s) and was rolled back; the Recreate strategy left a stuck Terminating pod, so Forgejo was down until it was force-deleted. Fix: pull from the official mirror `data.forgejo.org/forgejo/forgejo:16.0.5` and tag it locally as the codeberg name (pull policy is IfNotPresent, so a future node re-pull would hit codeberg again).
- **No `openssl` on home.** `NEW=$(openssl rand -hex 32)` gave an empty value and the app (which requires a long token) refused to start; with `Recreate` the app was down until a real token was set. Use `tr -dc a-f0-9 </dev/urandom | head -c 64` and check the length first.
- **Nextcloud disabled apps** during the upgrade: `admin_audit`, `encryption`, `suspicious_login`, `twofactor_nextcloud_notification`, `user_ldap` (Nextcloud turns off apps that are incompatible with the new version; not checked whether they were disabled before).
- **Open WebUI v0.11.4 behaviour changes:** cookie forwarding is off by default (new "Forward cookies" switch), the Integrations tab is hidden unless an admin enables it, links render only for web/mail/phone schemes, some Python packages were dropped from the image.
- **Suwayomi v2.4.2366** migrates `extensionRepos` to `extensionStores` and needs a one-time full sync when it is next scaled up.
- **Immich v3.3.x:** OAuth claims sync on every login; people-sharing edits apply to all users with access by default.
- `/root/k8s-manifests` on home contains only `immich.yaml` and two checkmk files from September; it does not hold the current manifests, so tags there are stale (Immich especially).

## References

- Helm chart repo used for democratic-csi: <https://democratic-csi.github.io/charts/> (chart 0.15.1)
- VolumeSnapshot CRDs: [kubernetes-csi/external-snapshotter v8.2.1 `client/config/crd`](https://github.com/kubernetes-csi/external-snapshotter/tree/v8.2.1/client/config/crd)
- Forgejo official mirror registry: `data.forgejo.org/forgejo/forgejo`
- Per-project release notes were read by the subagents (cert-manager, VictoriaMetrics, MetalLB, Nextcloud, Immich, Forgejo, Open WebUI, Suwayomi); no single source URL list was kept.
