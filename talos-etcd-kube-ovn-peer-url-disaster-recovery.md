---
type: troubleshooting
tags: [talos, kubernetes, etcd, kube-ovn, disaster-recovery, reboot, proxmox, democratic-csi, registry-mirror, containerd, px1]
created: 2026-09-05
last_verified: 2026-09-05
status: current
---

# A full `px1` reboot took down the whole Talos cluster: etcd peer-URL bug + disaster recovery

Rebooting the Proxmox host `px1` (192.168.50.30) — needed as routine
maintenance after some hostname/package-upgrade work, see
`proxmox-px1-px2-rename-cert-fix.md` — took the entire 6-node Talos cluster
down simultaneously (all 3 control-plane + 3 worker VMs live on that one
host) and etcd failed to reform quorum afterward. Root cause turned out to
be a long-dormant bug from an earlier CNI migration, invisible until this
exact failure mode (full simultaneous reboot) occurred for the first time.
Full recovery took the official etcd disaster-recovery path — no
Kubernetes data was lost.

## Symptom

After `px1` finished rebooting, all 9 guests (including
`talos-cp1/2/3`/`talos-worker1/2/3`) came back up fine at the Proxmox level
(`qm list` showed all `running`, correct PIDs), but:

- `kubectl` against the control-plane VIP (`192.168.50.90`) failed: `dial
  tcp 192.168.50.90:6443: connect: no route to host`
- The VIP itself didn't respond to ping — kube-vip never claimed it
- `talosctl -n <cp-ip> service etcd` showed `HEALTH Fail` / `context
  deadline exceeded` on all 3 control-plane nodes, indefinitely

## Root cause

All 3 control-plane nodes' etcd instances had **each other's peer URLs
permanently baked in wrong** — pointing at Kube-OVN's internal join-subnet
addresses instead of the real LAN IPs:

| Node | Real IP | What the other 2 members had stored for it |
|---|---|---|
| `ts-master01` (cp1) | `192.168.50.91` | `100.64.0.3:2380` |
| `ts-master02` (cp2) | `192.168.50.92` | `100.64.0.4:2380` |
| `ts-master03` (cp3) | `192.168.50.93` | `100.64.0.5:2380` |

Confirmed via etcd's own logs on every node — identical symmetric pattern:

```
{"level":"warn",...,"msg":"prober detected unhealthy status",...,"remote-peer-id":"3e1165a023056544","error":"dial tcp 100.64.0.4:2380: i/o timeout"}
```

...and conclusively proven by the `ovn.kubernetes.io/ip_address: "100.64.0.3"`
annotation already sitting on the `ts-master01` Kubernetes node object —
`100.64.0.3` is genuinely that node's real Kube-OVN join-subnet IP, not a
typo or random value.

**Provenance**: this dates back to the original Flannel→Kube-OVN CNI
migration (see `pod-internet-egress-isp-ttl-bug.md`, gotcha #5 there). That
migration found and fixed **kubelet's** node-IP auto-detection getting
confused by the `ovn0`/join-subnet interface (`InternalIP` silently became
`100.64.0.x`), via:

```yaml
machine:
  kubelet:
    nodeIP:
      validSubnets:
        - 192.168.50.0/24
```

etcd has its **own, separate** advertise-address setting
(`cluster.etcd.advertisedSubnets`) that was never pinned at the time — so
etcd independently locked onto the same wrong addresses and it was never
corrected. This was completely invisible for weeks: a single-node reboot
never breaks anything here, because raft's *existing* live peer connections
just keep working without ever needing to re-resolve an address. It only
surfaces the moment **all 3** control-plane nodes have to freshly dial each
other at once — which is exactly what a full host reboot does, and which
had apparently never happened since the CNI migration until this incident.

## Fix, part 1: prevent recurrence

```yaml
cluster:
  etcd:
    advertisedSubnets:
      - 192.168.50.0/24
```

Applied via `talosctl patch mc --endpoints <ip> --nodes <ip> --patch @file.yaml`
to all 3 control-plane nodes. This is the [Talos-documented mechanism](https://oneuptime.com/blog/post/2026-03-03-set-up-etcd-advertised-subnets-in-talos-linux/view)
for exactly this class of problem — analogous to the kubelet `validSubnets`
fix above, just for etcd specifically. Applied *before* the recovery below
so freshly-(re)joining members pick correct addresses from the start.

## A dead end, documented so it isn't retried

Before reaching for full disaster recovery, tried making the *existing*
(wrong) peer URLs simply reachable again — add the stale `100.64.0.x`
addresses as plain `/32` IP aliases on each node's `eth0` via a Talos
network-config patch (`machine.network.interfaces[0].addresses`), on the
theory that the actual raft/cert data was fine and only the *address* was
wrong.

**This did not reliably work** and was abandoned:
- 2 of 3 nodes' alias addresses never answered ARP at all, despite Talos's
  own `AddressStatus`/`RouteStatus` resources reporting them as correctly
  configured at the kernel level.
- The 1 alias that *did* get a ping reply came back with `ttl=63` — one
  router hop away, not the `ttl=64` a same-subnet ARP-resolved reply should
  show. That strongly suggests some unrelated pre-existing routing (from
  when Kube-OVN's gateway function was fully operational) happened to
  answer for that one address, not that the alias technique itself worked.
- Confirmed via web research: Kube-OVN's join-subnet addresses are meant to
  be managed by its own OVS/OVN dataplane, with return-path routing
  normally requiring either the CNI agent actively running or an explicit
  static route — not just "any host can claim any address in that range via
  a plain kernel interface alias." Kube-OVN itself wasn't even running at
  the time (no pods could schedule without a live API server), so there was
  no dataplane to make the alias behave correctly anyway.

**Lesson**: for a Kube-OVN-related address problem, don't reach for a plain
host-level IP alias as a quick fix — go straight to fixing it at the
correct layer (Talos's `advertisedSubnets`, or Kube-OVN's own config),
even though the alias looks simpler on paper.

## Fix, part 2: etcd disaster recovery

Followed the [official Talos procedure](https://docs.siderolabs.com/talos/v1.9/build-and-extend-talos/cluster-operations-and-maintenance/disaster-recovery)
for "members alive, data intact, but quorum lost." No Kubernetes objects or
workload data were lost — confirmed after recovery by full 12-day-old
node/pod history coming back intact.

```bash
export TALOSCONFIG=/path/to/talosconfig

# 1. Snapshot etcd from ANY one control-plane node (source only — do not wipe this one yet)
talosctl -n <source-ip> etcd snapshot db.snapshot
#   ^ this HUNG INDEFINITELY with no quorum in this instance — apparently needs
#     a metadata call that itself needs consensus. Fallback that worked instead
#     (per the docs' own suggested alternative for an unhealthy cluster):
talosctl -n <source-ip> cp /var/lib/etcd/member/snap/db ./etcd.snapshot
#   ^ NOTE: this creates a *directory* named `etcd.snapshot` containing a file
#     called `db`, not a file at that path directly. Flatten it:
mv etcd.snapshot/db ./etcd.snapshot.flat && rmdir etcd.snapshot && mv etcd.snapshot.flat etcd.snapshot

# 2. Wipe the OTHER two control-plane nodes' etcd/ephemeral state (NOT the source node yet)
talosctl -n <other-ip-1> reset --graceful=false --reboot --system-labels-to-wipe=EPHEMERAL
talosctl -n <other-ip-2> reset --graceful=false --reboot --system-labels-to-wipe=EPHEMERAL
# wait for both to show STATE=Preparing:
talosctl -n <ip> service etcd

# 3. Bootstrap-recover on one of the WIPED (empty) nodes — NOT the snapshot source node
#    (the source node still has its own unwiped data; bootstrap refuses with
#    "rpc error: code = AlreadyExists desc = etcd data directory is not empty"
#    if you target it — this cost one wasted attempt here)
talosctl -n <wiped-ip> bootstrap --recover-from=./etcd.snapshot --recover-skip-hash-check

# 4. Wipe+reboot the ORIGINAL snapshot-source node too, same as step 2 — it still
#    has its old broken-membership data and was never touched by steps 1-3
talosctl -n <source-ip> reset --graceful=false --reboot --system-labels-to-wipe=EPHEMERAL
```

All 3 nodes then rejoin automatically as etcd **learners** — this is normal,
not an error, even though `service etcd` shows `HEALTH Fail` /
`etcdserver: rpc not supported for learner` during this phase. Verify real
progress via:

```bash
talosctl --endpoints <ip1>,<ip2>,<ip3> -n <ip1>,<ip2>,<ip3> etcd status
# compare RAFT APPLIED INDEX across all three — once a learner matches the
# leader's index exactly, it's fully caught up
talosctl -n <any-healthy-ip> etcd members
# LEARNER column flips to false automatically once caught up (took roughly
# 1-2 min per node here, on a small ~50MB/2099-key db; auto-promotion is
# a genuine Talos controller action, no manual `member promote` needed)
```

Total time from first wipe to all-3-healthy: roughly 15-20 minutes for this
cluster size. `talosctl` commands always need explicit `--endpoints <ip> -n
<ip>` even with a configured `TALOSCONFIG` context — omitting `--endpoints`
fails with `error constructing client: failed to determine endpoints` (a
recurring gotcha, also independently hit during the original CNI migration).

## Post-recovery pod cascade (expected, self-heals — but not instantly)

Once etcd/API/kube-vip were back, `kubectl get nodes` showed all 6 `Ready`
(briefly `SchedulingDisabled` too — a transient `talos.dev/cordoned`
annotation from Talos's own reset-cycle handling, cleared on its own, no
manual `kubectl uncordon` needed). But **every single pod across every
namespace** was stuck `ContainerCreating` — two distinct, sequential causes:

1. **Kube-OVN's own control plane was itself broken.** `kube-ovn-controller`,
   `kube-ovn-monitor`, and `ovn-central` pods had stale container references
   from mid-reboot — one `ovn-central` replica's own event history literally
   read `"Pod was rejected as the node is shutting down"` from the exact
   moment it got scheduled during the node reset in step 2/4 above, and was
   never rescheduled. Since Kube-OVN's control plane wasn't running, it
   couldn't service *any* pod's network-attach request — that's why
   literally everything was stuck, not just OVN-related pods. Fix: delete
   the stuck pods so their owning Deployments recreate them clean:
   ```bash
   kubectl -n kube-system delete pod <stale-kube-ovn-controller-pods> \
     <stale-kube-ovn-monitor-pods> <stale-ovn-central-pods> --force --grace-period=0
   ```
   Once the CNI's control plane was healthy again (kube-ovn-controller 3/3,
   ovn-central 3/3 running), the per-node CNI daemon (`kube-ovn-cni`
   DaemonSet, already healthy on all 6 nodes throughout) could actually
   start servicing pod sandbox creation, and dozens of pods began
   transitioning out of `ContainerCreating` within a minute or two.

2. **Stale CSI volume attachments from the ungraceful shutdown.** Pods
   backed by `democratic-csi` (iSCSI, against a TrueNAS backend) hit
   `Multi-Attach error ... Volume is already exclusively attached to one
   node` — a normal consequence of nodes going down without a graceful
   detach. This couldn't self-heal either, because `democratic-csi-controller`
   (the component that reconciles stale `VolumeAttachment` objects) was
   *itself* also stuck in the same Kube-OVN-blocked `ContainerCreating`
   state as everything else — genuinely circular until fix #1 landed. Once
   the CSI controller came up, it cleared every stale attachment and
   reattached correctly on its own — no manual `VolumeAttachment` deletion
   needed, just time (each pod: attach → mount → image pull → start,
   roughly 1-10 min apart depending on image size and pull contention).

Full cluster (89 pods, excluding 2 unrelated pre-existing chronic
crash-loopers unrelated to this incident) took roughly 20-25 minutes after
etcd recovery to fully settle back to all-`Running`.

## Bonus find while investigating slow pulls: the registry mirror was never actually wired up

During the pod-cascade recovery, image pulls were unusually slow (one 10MB
image took 3m12s — roughly 55KB/s). Direct throughput tests
(`ping`/`curl` from `warp-vm`) came back completely normal, ruling out a
recurrence of the known ISP-egress issue (`pod-internet-egress-isp-ttl-bug.md`).

Actual cause: this cluster has `docker-mirror`/`ghcr-mirror` pull-through
cache pods deployed (`registry-mirror` namespace, LoadBalancer IPs
`192.168.50.221`/`.222`, port 5000) — running fine — but **containerd on
every node was never actually told to use them**. Talos's
`machine.registries.mirrors` config section was completely absent from all
6 nodes' machine config, so every pull, always, went straight to the real
upstream registry (`ghcr.io`/`docker.io`) regardless of the mirror pods'
existence. They'd been dead weight since deployment.

Fix, applied to all 6 nodes, no reboot required:

```yaml
machine:
  registries:
    mirrors:
      docker.io:
        endpoints:
          - http://192.168.50.221:5000
      ghcr.io:
        endpoints:
          - http://192.168.50.222:5000
```

Verified working with a fresh (previously-uncached) small image pull —
containerd hit the mirror directly (confirmed via the mirror pod's own
access logs showing the request and its `ghcr.io` proxy-through with
caching), completing in 11s total for a 34MB image.

## Aside: Immich ML removal doesn't shrink the server image

While investigating a slow `immich` pod pull, briefly suspected the
`immich-server` image itself might still bundle ML models even after
`immich-machine-learning` had been removed from the deployment. Checked and
that's not how Immich is packaged: `immich-server` and
`immich-machine-learning` are always separate images —
`ghcr.io/immich-app/immich-server` never bundles ML models regardless of
whether the separate ML deployment exists. The slow pull was purely the
mirror-not-wired-up issue above, affecting every image pull cluster-wide,
not anything Immich-specific.

## Related docs

- `technitium-dns-3node-cluster-deployment.md` — same overall session; a
  stale DNS config on a different host was found and fixed during the same
  audit that led to renaming `px1`/`px2`.
- `proxmox-px1-px2-rename-cert-fix.md` — the Proxmox-side work
  (hostname rename, cert collision, apt upgrade) that led to the `px1`
  reboot which triggered this whole incident.
- `pod-internet-egress-isp-ttl-bug.md` — the original Flannel→Kube-OVN
  migration where the underlying etcd/kubelet node-IP confusion first got
  introduced (kubelet side was fixed then; etcd side was not, until now).
