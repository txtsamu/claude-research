---
type: how-to
tags: [kubernetes, talos, k3s, migration, metallb, democratic-csi, cloudflare-tunnel, warp-vm, proxmox]
created: 2026-09-06
last_verified: 2026-09-06
status: current — homelab namespace fully cut over, Talos scaled to 0 and kept as rollback
---

# Migrating the `homelab` namespace from Talos to k3s on warp

## Goal

Retire the 6-node Talos cluster (3 control-plane + 3 worker, on `px1`) in favor of a
single-node k3s cluster installed directly on `warp` (192.168.50.200), migrating all
18 app Deployments in the `homelab` namespace with the Cloudflare tunnel kept working
throughout — ideally with **zero tunnel reconfiguration**.

## Key design decision: reuse the exact same MetalLB IPs

Recon on the Talos side found: no Ingress objects anywhere, every app is a bare
`Deployment` + `LoadBalancer` `Service`, IPs handed out by MetalLB L2 mode from a
single pool (`homelab-pool`, 192.168.50.220-239). The Cloudflare tunnel (`cloudflared`,
native systemd service on warp itself, dashboard-managed, no local `config.yml`)
almost certainly points its ingress rules at these internal IPs directly.

**If k3s's MetalLB reuses the identical IP range and each service keeps its original
IP, the tunnel needs zero changes.** This was confirmed true end-to-end after cutover —
verified by fetching the public hostnames externally post-migration.

## Phase 0 — grow warp's disk

warp-vm is Proxmox VMID 101 on `px1`, disk `scsi0` on `nas-lvm-thin`. Started at 40G,
grew to 100G total across three rounds during the migration as image pulls repeatedly
pushed it into kubelet eviction territory (immich, nextcloud, rancher are all large
images). Online resize, no VM downtime:

```bash
# on px1
qm resize 101 scsi0 +30G

# on the guest (warp) — cloud-init image, has x-systemd.growfs in fstab
echo 1 | sudo tee /sys/class/block/sda/device/rescan
sudo growpart /dev/sda 1
sudo resize2fs /dev/sda1
```

Check `df -h /` before starting any migration involving Immich/Nextcloud/Rancher-sized
images — 30-40G of headroom is not enough for the whole run.

## Phase 1 — install k3s + supporting infra

```bash
curl -sfL https://get.k3s.io | sudo INSTALL_K3S_EXEC="--disable traefik --disable servicelb --write-kubeconfig-mode 644" sh -
```

- `traefik` disabled — no Ingress objects exist, pure dead weight.
- `servicelb` disabled — MetalLB owns LoadBalancer IPs instead.

Install `open-iscsi` + `nfs-common` (warp is plain Debian, no Talos-style `nsenter`
workaround needed):

```bash
sudo apt-get install -y open-iscsi nfs-common cloud-guest-utils
sudo systemctl enable --now iscsid
```

**MetalLB**, same IP range as Talos:

```bash
kubectl --context=k3s apply -f https://raw.githubusercontent.com/metallb/metallb/v0.15.2/config/manifests/metallb-native.yaml
```
```yaml
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata: {name: homelab-pool, namespace: metallb-system}
spec:
  addresses: ["192.168.50.220-192.168.50.239"]
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata: {name: homelab-l2, namespace: metallb-system}
spec: {ipAddressPools: ["homelab-pool"]}
```

**democratic-csi**, same TrueNAS backend, but a **distinct ZFS dataset parent**
(`data/k8s-warp-iscsi` vs Talos's `data/k8s-talos-iscsi`) so dynamically-provisioned
zvols never collide between the two clusters:

```yaml
driver:
  config:
    driver: freenas-api-iscsi
    httpConnection:
      host: 192.168.50.10
      apiKey: "<REDACTED - TrueNAS API key>"
    iscsi:
      targetPortal: 192.168.50.10:3260
      namePrefix: csi-warp-
      targetGroups: [{targetGroupAuthType: None, targetGroupInitiatorGroup: 1, targetGroupPortalGroup: 1}]
    zfs:
      datasetParentName: data/k8s-warp-iscsi
      detachedSnapshotsDatasetParentName: data/k8s-warp-iscsi-snapshots
node:
  hostPID: true
  driver: {iscsiDirHostPath: /var/iscsi}
storageClasses:
  - {name: truenas-iscsi, defaultClass: true, reclaimPolicy: Delete, volumeBindingMode: Immediate, parameters: {fsType: ext4}}
```

**Gotcha**: the node pod fails with `hostPath type check failed: /var/iscsi is not a
directory` on first install — `mkdir -p /var/iscsi` on the host first, k3s doesn't
create it. Verified the whole stack end-to-end with a throwaway PVC + pod before
migrating anything real.

**k3s also creates its own `local-path` StorageClass and marks it default** —
unset that (`storageclass.kubernetes.io/is-default-class: "false"`) to avoid two
default SCs.

Copy secrets/configmaps up front (cheap, no traffic impact) and recreate the 3
static NFS PVs (immich/nextcloud/photos, all pointing at `192.168.50.10`) — no data
copy needed since that data lives off-cluster already:

```bash
kubectl --context=talos -n homelab get secrets -o json \
  | jq 'del(.items[].metadata.resourceVersion, .items[].metadata.uid, .items[].metadata.creationTimestamp, .items[].metadata.ownerReferences, .items[].metadata.managedFields, .items[].metadata.annotations)' \
  | kubectl --context=k3s apply -f -
# same for configmaps, excluding kube-root-ca.crt
```

## Phase 2 — per-app cutover procedure

Both clusters' kubeconfigs live in **one file** on warp (`talos` and `k3s` contexts) —
this makes cross-cluster data copy trivial:

```bash
kubectl --context=talos -n homelab scale deploy <app> --replicas=0   # stop writes
# create PVC on k3s from the sanitized old-PVC spec, then:
kubectl --context=talos -n homelab exec mover-src -- tar cf - -C /data . \
  | kubectl --context=k3s -n homelab exec -i mover-dst -- tar xf - -C /data
```

Apply the app's Deployment + a **ClusterIP-only** Service first on k3s, verify
internally (pod Ready, `wget` from a throwaway busybox pod against the ClusterIP),
*then* cut the public IP over:

```bash
kubectl --context=talos -n homelab delete svc <app>          # releases the IP/ARP claim
kubectl --context=k3s -n homelab patch svc <app> --type=merge \
  -p '{"metadata":{"annotations":{"metallb.io/loadBalancerIPs":"<original-ip>"}},"spec":{"type":"LoadBalancer"}}'
kubectl --context=talos -n homelab scale deploy <app> --replicas=0   # rollback-ready, not deleted
```

MetalLB has no way to "pin" a specific IP at Service-creation time other than this
annotation (or the deprecated `spec.loadBalancerIP` field) — the original IPs were
just auto-assigned in creation order, recorded only in `status.loadBalancer.ingress`.

Multi-port services (forgejo, oneterm) need `name:` on each port in the sanitized
Service manifest — Kubernetes rejects a multi-port Service without it.

Migrated in risk-ordered waves: stateless apps first, then stateful-recoverable,
then critical (forgejo/nextcloud/immich) last, `jellyfin`/`oneterm` migrated but left
at 0 replicas (matching their already-paused state on Talos).

## Gotchas hit along the way

**k3s/flannel PMTUD blackhole** — pods could hang indefinitely (not fail fast) on
outbound HTTPS to some external hosts serving large TLS responses, despite flannel's
interface MTUs (1450) being set correctly. This is a missing MSS-clamp problem, not
an MTU problem — fixed cluster-wide:

```bash
sudo iptables -t mangle -A POSTROUTING -o eth0 -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
sudo apt-get install -y iptables-persistent   # DEBIAN_FRONTEND=noninteractive, then netfilter-persistent save
```
Symptom to watch for: a pod hangs on startup, `/proc/net/tcp` inside it shows an
`ESTABLISHED` connection with a climbing retransmit count and no error — that's this,
not an app bug.

**SOCKS-proxy colocation** — an app's `HTTP_PROXY=socks5://192.168.50.200:1080` (a
microsocks-via-Cloudflare-WARP proxy, set up so LAN hosts get reliable outbound
internet on a double-NAT ISP path) hung on startup once that app's pod ran ON warp
itself — the proxy target became the same host. Fixed for `openwebui` by dropping the
proxy env vars (its actual outbound targets don't need WARP). `flaresolverr`
(suwayomi's sidecar) still has this same proxy setting and genuinely needs it —
untested under real load post-migration; if suwayomi scraping ever hangs, check this
first. (Testing tip: `kubectl exec` into a container that lacks `wget`/`curl` silently
does nothing useful — always verify against the Service from a throwaway busybox pod,
not from inside the target container.)

## Verification

- Per app: pod Ready, internal ClusterIP responds, public hostname via the tunnel
  loads correctly.
- End of migration: `kubectl --context=k3s -n homelab get svc` IPs match the original
  Talos assignment 1:1; Talos-side deployments all at 0 replicas, PVCs/data untouched
  for rollback.
- Confirmed the "no tunnel changes needed" design by fetching two public hostnames
  externally after cutover — both resolved through the unmodified tunnel straight to
  the new k3s-hosted pods.

## Open / follow-up

- Talos cluster itself not yet decommissioned — kept live, fully scaled down, as a
  rollback path.
- Disk on warp needs monitoring — three growth rounds in one session, single-node
  clusters concentrate all image-pull weight on one disk.
