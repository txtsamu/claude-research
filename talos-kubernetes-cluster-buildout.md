---
type: how-to
tags: [kubernetes, talos, proxmox, terraform, bpg-proxmox, metallb, democratic-csi, truenas, iscsi, rancher, cert-manager, ha, homelab-vm, warp-vm, kube-ovn]
created: 2026-08-23
last_verified: 2026-08-24
status: current
---

# Building a 3-master/3-worker Talos Kubernetes cluster on Proxmox

Full build of a learning-focused Talos K8s cluster on `pve-pc`, done to learn Kubernetes + HA architecture mechanics hands-on before migrating services off `homelab-vm`'s Podman setup — see [[podman-to-kubernetes-migration-plan]] for the service inventory and migration-wave plan (that doc covers *what* gets migrated and in what order; this one covers the cluster itself).

**Update 2026-08-24**: the CNI was later switched from Flannel (as originally built below) to **Kube-OVN**, as part of chasing a pod-to-internet connectivity bug — see [[pod-internet-egress-isp-ttl-bug]] for the full investigation and the actual root cause (which turned out to be unrelated to the CNI). The rest of this doc still accurately describes the original build; the CNI section is superseded by that investigation doc.

## Decisions made

| Decision | Choice | Why |
|---|---|---|
| Distro | **Talos** | Immutable, API-driven, no SSH — closer to real production clusters than k3s; pairs with learning IaC/GitOps |
| Topology | **3 control-plane + 3 worker** | Odd control-plane count for etcd quorum practice; 3 workers so scheduling/spread is actually meaningful |
| Sizing | Started **minimum viable** (2 vCPU / 2GiB RAM/node), ended at **2 vCPU / 4GiB** after two real memory-pressure incidents (see gotchas) | Learning-first sizing was right for bare cluster mechanics; real platform workloads needed more |
| Bastion | **A dedicated management VM** (already existed, repurposed) | Single management box — `talosctl`/`kubectl`/`terraform` live only there, not on the Proxmox host or the user's own machine |
| Talos version | **v1.13.9** (current stable at build time) | Ships Kubernetes 1.36.3 |
| Terraform provider | **`bpg/proxmox`** | Actively maintained, more control than wrapper modules — worth the extra manifest writing for the learning goal |
| Storage | **iSCSI on TrueNAS SCALE via `democratic-csi`** | TrueNAS SCALE manages iSCSI through its own API rather than raw `targetcli`; `democratic-csi` talks to that API to provision a zvol + LUN per PVC dynamically |
| LoadBalancer | **MetalLB** (L2 mode) | Talos ships vanilla k8s — no cloud provider on bare metal means `type: LoadBalancer` Services never get an external IP without something to hand one out |

## Cluster topology

3 control-plane + 3 worker VMs, all on RFC1918 LAN addresses, plus a control-plane VIP for HA API access. Final sizing: 2 vCPU / 4GiB RAM / 20GiB disk per node (12 vCPU / 24GiB / 120GiB total).

Talos's officially documented minimum is 2 vCPU / 2GiB / 10GiB — that's genuinely enough to *boot* a healthy cluster and learn etcd/quorum mechanics, but not enough once real platform workloads (Rancher, MetalLB, a CSI driver, cert-manager) land on top. Both control-plane and worker nodes needed the RAM doubled after hitting actual `NotReady` incidents from memory exhaustion (see gotchas below) — this wasn't scope creep, it was discovered the hard way.

### Why a VIP matters for HA

Talos supports a natively-managed virtual IP shared across control-plane nodes (`machine.network.interfaces[].vip` in the machine config — no `kube-vip` sidecar needed). Without it, `talosctl`/`kubectl` would point at one CP node's static IP, and losing *that specific node* would look like a full outage even though etcd is still quorate on the other two. The VIP is what actually makes the control plane HA from the client's point of view, not just internally.

One caveat learned the hard way: **the VIP only proxies the Kubernetes API port (6443)** — it does not double as a general-purpose front door for arbitrary NodePort/LoadBalancer traffic. Its job is API HA, nothing else.

### Why 3 control-plane nodes, not more

etcd quorum = `floor(n/2)+1`. With 3 nodes, quorum is 2 — the cluster tolerates losing **any 1** control-plane node. Going to 5 would tolerate losing 2, but doubles the resource cost for a fault-tolerance level that doesn't matter here: all 6 nodes are VMs on the **same physical Proxmox host**, so losing the physical host takes down the whole cluster regardless of etcd node count. 3 is the standard minimum for meaningful quorum practice without wasting resources on a guarantee the hardware topology can't back up.

## Provisioning mechanics

1. **Proxmox API token** — dedicated token created for Terraform (privilege-separated), granted `PVEAdmin` on `/`.
2. **Talos image** — pulled via the Talos Image Factory with a custom schematic baking in the `iscsi-tools`, `util-linux-tools`, and `qemu-guest-agent` system extensions (Talos ships none of these by default; `iscsi-tools` specifically is required for `democratic-csi` to mount volumes later). Imported as a Proxmox VM template (thin-provisioned disk, discard+ssd flags, cloud-init drive for per-clone config injection, serial console).
3. **Terraform** (`bpg/proxmox` provider) clones the template into the 6 VMs with static IPs, uploading each node's final Talos machine config as a Proxmox "snippet" wired in as cloud-init user-data.
4. **Talos machine config** — `talosctl gen config` for the base controlplane/worker configs (with the VIP set), then `talosctl machineconfig patch` per node for hostname, static IP, install disk, and DNS.
5. **Apply + bootstrap** — since the config is injected via cloud-init at first boot (Talos's `nocloud` platform reads it directly, no separate `apply-config` step needed), the nodes come up already configured. `talosctl bootstrap` against one CP node initializes etcd, then `talosctl kubeconfig` pulls cluster access.
6. **Storage** — `democratic-csi` (iSCSI driver) deployed via Helm, pointed at a dedicated TrueNAS API key and a fresh parent dataset (kept separate from any existing hand-managed zvols on the NAS).
7. **Rancher UI** — Helm + `cert-manager` prerequisite, exposed via a MetalLB LoadBalancer IP, 2 replicas for actual redundancy.
8. **MetalLB** — Helm install, L2Advertisement mode (no BGP router on this LAN), with the BGP/FRR subsystem explicitly disabled since it's unused overhead (see gotchas).

## Gotchas hit along the way

Several real bugs surfaced getting from "VMs running" to "cluster healthy and stable" — the most useful part of this doc if this ever needs repeating.

### 1. Talos hostname conflict — multi-document config

Talos v1.13's config is multi-document — a separate `HostnameConfig` document (default `auto: stable`) exists independently of `machine.network.hostname`. Setting `machine.network.hostname` directly in the main config collides with the still-active `auto: stable` default, and the node rejects the entire config with `static hostname is already set in v1alpha1 config`, looping forever in maintenance mode with no network ever coming up.

**Fix**: patch the `HostnameConfig` document directly instead of the legacy field:

```yaml
apiVersion: v1alpha1
kind: HostnameConfig
hostname: my-node-name
auto: off
```

(A Proxmox cloud-init meta-data `local-hostname` collision was suspected first, since the symptom looked similar — that was a dead end; overriding meta-data to a bare `instance-id` didn't fix anything.)

### 2. Wrong DNS IP from a stale reference

Nameservers were initially pointed at an old/wrong IP for the LAN's Pi-hole instance (a stale SSH config alias). Nodes booted but spammed `dns-resolve-cache` timeouts and stalled on `k8s.NodeApplyController`. Lesson: verify infra references (SSH aliases, notes, memory) against the live host rather than trusting them blindly — a quick `ssh <alias>` sanity check before baking an IP into 6 node configs would have caught it immediately.

### 3. Terraform snippet uploads need SSH, not just the API token

The `bpg/proxmox` Terraform provider uploads Talos machine-config snippets to the Proxmox node over **SSH**, not through the API token — there's no pure-API path for that content type (Proxmox "snippets" storage). Needed a dedicated SSH key from the bastion VM, authorized for `root` on the Proxmox host, wired into the provider's `ssh {}` config block.

### 4. `iscsi-tools` binary path moved and moved back

Talos v1.12.5 briefly relocated the `iscsi-tools` extension's binaries from `/usr/local/sbin` into the extension's own container rootfs, breaking CSI drivers that expect the old host path. This was reverted in a later patch. **Don't trust blog posts on the exact path for your Talos version** — verify live on your own nodes (`talosctl list /usr/local/sbin`) before baking a path into a CSI driver's config.

### 5. `democratic-csi` requires `detachedSnapshotsDatasetParentName` even without snapshots

Omitting `zfs.detachedSnapshotsDatasetParentName` from the driver config crashes it outright (`Cannot read properties of undefined (reading 'replace')`) even if you never intend to use volume snapshots. Set it to a real (even if unused) parent dataset.

### 6. Talos's default PodSecurity policy blocks privileged CSI/LB pods

Talos enforces `pod-security.kubernetes.io/enforce=baseline` cluster-wide by default. Both `democratic-csi`'s node daemonset and MetalLB's speaker daemonset need privileged host access (hostPID, hostNetwork, hostPath mounts) and get silently rejected under `baseline`. Fix is a namespace label:

```sh
kubectl label namespace <ns> pod-security.kubernetes.io/enforce=privileged
```

### 7. MetalLB's default config nearly took the cluster down

Installing MetalLB with its default Helm values (`frrk8s.enabled: true`, `speaker.tolerateMaster: true`) pushed 4 of 6 nodes to `NotReady`. Root cause: genuine control-plane memory exhaustion — the control-plane nodes were down to under 150MB available RAM each. Two compounding issues: MetalLB's daemonsets target *all* nodes including control-plane by default, and it deploys a full BGP/FRR stack (5 extra containers per node) even for a pure-L2 setup that will never use BGP. Fixed with:

```sh
helm upgrade metallb metallb/metallb -n metallb-system \
  --set frrk8s.enabled=false \
  --set speaker.tolerateMaster=false
```

This drops the unneeded BGP stack entirely and keeps load-balancer pods off control-plane nodes (matching the placement already used for the CSI driver). The cluster self-recovered within about a minute — etcd quorum itself was never actually lost, only kubelet↔apiserver heartbeats were affected.

### 8. Rolling node changes properly requires cordon/drain — learned by skipping it

Early node RAM bumps (all 3 control-plane nodes, plus the first worker) were done with a bare `qm stop` / `qm start` at the hypervisor level, without `kubectl cordon`/`drain` first. This is fine for the control-plane role itself (they don't run arbitrary workloads), but doing it to a worker left a multi-container pod (`democratic-csi-controller`) in a real `CrashLoopBackOff` for about a minute — the abrupt restart meant Flannel hadn't regenerated its per-node subnet config file yet, so the pod's network sandbox kept failing to recreate. It self-healed with no lasting damage, but only because no pod had a volume actively mounted at that exact moment — a `VolumeAttachment` could easily have gotten stuck in a worse-timed version of this.

**Correct sequence for any future node resize/reboot** (control-plane or worker):

```sh
kubectl cordon <node>
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data --timeout=90s
# ...do the actual VM-level change (qm set/stop/start, etc.)...
# wait for the node to reappear Ready
kubectl uncordon <node>
```

### 9. Renaming a node's hostname creates a brand-new Kubernetes Node object

Nodes were later renamed to a cleaner naming scheme. Applying a `HostnameConfig` change live (`talosctl apply-config --mode=reboot`) works cleanly and needs no VM recreation — but since a kubelet's identity *is* its hostname, Kubernetes registers the renamed node as an entirely new `Node` object. The old-named entry doesn't rename in place; it goes stale (`NotReady`) forever unless explicitly deleted:

```sh
kubectl delete node <old-name>
```

Do this once the new-named entry is confirmed `Ready`, one node at a time, checking etcd quorum between each — the same rolling discipline as any other node-at-a-time change.

## HA exercises worth doing on a cluster like this

The actual point of building it this way — worth doing deliberately rather than skipping straight to workloads:

1. `talosctl -n <cp-ip> etcd status` — see the quorum.
2. Reboot one control-plane node — confirm `kubectl` against the VIP never blips.
3. Power off a 2nd control-plane node simultaneously — confirm quorum is lost and the cluster goes read-only until it's back.
4. Cordon/drain a worker mid-workload — watch pods reschedule onto the others.
5. Deliberately corrupt/lose a control-plane node's disk and practice the etcd member-remove + rejoin recovery flow.

Rolling the RAM upgrades one node at a time, confirming quorum survived each step, ended up being a live rehearsal of exercise #2 — a good illustration that routine maintenance operations and HA drills are often the same procedure.

## Notes on secrets

Real values for the Proxmox API token, TrueNAS API key, and Rancher bootstrap password are not recorded in this doc — they live in the cluster's own secret store / the Proxmox and TrueNAS admin UIs. Retrieve the Rancher bootstrap password (if not yet changed) via:

```sh
kubectl -n cattle-system get secret bootstrap-secret -o go-template='{{.data.bootstrapPassword|base64decode}}'
```
