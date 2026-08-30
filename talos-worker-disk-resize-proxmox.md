---
type: how-to
tags: [talos, kubernetes, proxmox, disk-resize, ephemeral-partition, cordon, drain, ovs-ovn, homelab]
created: 2026-08-30
last_verified: 2026-08-30
status: current
---

# Growing a Talos worker node's disk on Proxmox (30GB → 50GB), one node at a time

Triggered by a disk-usage investigation on `ts-worker03` (see the update in
[pod-internet-egress-isp-ttl-bug.md](pod-internet-egress-isp-ttl-bug.md) —
unrelated finding, but happened during the same disk investigation) that
showed `/var` trending toward genuinely tight, unlike the router-level
false-positive `DiskPressure` signal investigated first. Decided to just
grow all three worker nodes rather than keep managing it via image pruning
alone.

## Researched properly before touching anything

Generic blog posts (a batch of near-identical "oneuptime.com" posts, likely
templated/SEO content) suggested a `talosctl upgrade --preserve` reinstall
cycle was required to trigger repartitioning. That seemed like more than
should be necessary just to grow a same-disk partition, so checked
Sidero Labs' own official channels before trusting it:

- Official docs confirm the `EPHEMERAL` partition has `grow: true` by
  default — it "will expand the volume to fill available space after it"
  once the underlying disk is bigger.
- A **Talos maintainer directly, in
  [siderolabs/talos discussion #12695](https://github.com/siderolabs/talos/discussions/12695)**:
  *"Volume expansion (if there's available space) today only works on a
  reboot."*

That settled it: grow the underlying disk in the hypervisor, then a plain
`talosctl reboot` — no reinstall, no `--preserve`, no image swap. This
matches the actual observed result below.

## Prerequisites checked first

```bash
# VMID mapping and current disk config on the Proxmox host
qm list | grep worker
qm config <vmid> | grep scsi0     # confirm storage backend + current size

# thin-pool headroom (need enough for all 3 nodes' growth combined)
pvesm status | grep local-lvm
```

Confirmed `local-lvm` (LVM-thin) had ~107GB free against a planned +20GB×3
= 60GB total growth — comfortable margin. LVM-thin fully supports online
(no VM downtime) resize via `qm resize`.

## Per-node procedure (repeat for each worker, one at a time)

**1. Cordon and drain:**
```bash
kubectl cordon ts-worker01
kubectl drain ts-worker01 --ignore-daemonsets --delete-emptydir-data --timeout=90s
```
Confirm only DaemonSet pods remain before proceeding:
```bash
kubectl get pods -A --field-selector spec.nodeName=ts-worker01 \
  -o custom-columns="NS:.metadata.namespace,NAME:.metadata.name,OWNER:.metadata.ownerReferences[0].kind"
```
Gotcha: a slow-terminating pod (a headless-browser workload, in this case)
can exceed the drain's own `--timeout` and make `kubectl drain` report a
failure even though eviction is still genuinely in progress — check the
specific pod's status (`kubectl get pod <name>`) before assuming something
is actually stuck; it may just need a few more seconds to finish its
graceful shutdown.

**2. Resize the disk on Proxmox:**
```bash
qm resize <vmid> scsi0 50G
```
The "Sum of all thin volume sizes exceeds the size of thin pool" warning
that follows is expected/normal for thin-provisioned storage — it's about
nominal allocation vs. pool capacity, not actual usage, and doesn't block
anything as long as real free space was confirmed beforehand.

**3. Reboot via talosctl:**
```bash
talosctl --talosconfig <path> -n <node-ip> -e <node-ip> reboot
```
A full, clean reboot sequence (`unmountEphemeralPartition` → `kexec` →
back up) — takes a couple of minutes. `talosctl reboot`'s own log stream
can outlast a short client-side timeout; that's just the streamed output
being cut off client-side, not a failure — the reboot itself proceeds
server-side regardless.

**4. Wait for `Ready`, verify the grow, uncordon:**
```bash
kubectl get node ts-worker01 -w   # wait for Ready,SchedulingDisabled
talosctl -n <node-ip> -e <node-ip> mounts | grep sda5
kubectl uncordon ts-worker01
```

Gotcha: a naive wait-loop using `grep -q "Ready"` will false-positive match
on `"NotReady"` too (substring match) — use an exact match against the
full status column (`awk '{print $2}' | grep -qx "Ready,SchedulingDisabled"`)
instead.

## Result

| Node | Before | After |
|---|---|---|
| `ts-worker01` | 27.84GB (74% used) | 49.32GB (42.65% used) |
| `ts-worker02` | 27.84GB | 49.32GB (27.84% used) |
| `ts-worker03` | 27.84GB (75% used) | 49.32GB (44.59% used) |

Confirmed via the same `talosctl mounts` check that a plain reboot really
was sufficient — no reinstall needed, matching the maintainer's answer
exactly.

For reference, the control-plane nodes (`ts-master01/02/03`) run a smaller
~17GB `/var` each (only ~28% used) — they don't need this, since they
mainly run etcd/API-server components rather than application workloads.

## Side effect discovered after all three reboots: ~92 stale `ovs-ovn` DaemonSet pod objects

After the third reboot, `kubectl get pods -A` showed a startling number of
`ovs-ovn` pods (kube-ovn's Open vSwitch DaemonSet) stuck in
`Init:ContainerStatusUnknown` — accumulated across all three reboots.

**Not an actual networking problem** — verified first, before touching
anything:
```bash
kubectl get daemonset -n kube-system ovs-ovn   # DESIRED=6, CURRENT=6
kubectl get pods -n kube-system -l app=ovs -o wide | grep Running
# exactly one genuinely-Running ovs-ovn pod per node, all 6 covered
```

These are orphaned pod *objects* — kubelet loses track of a DaemonSet
pod's status when its node reboots out from under it, and the object
sometimes isn't cleanly garbage-collected afterward, especially across
several reboots in quick succession. The daemonset controller correctly
spawns a fresh, genuinely-`Running` replacement each time; the stale
records just accumulate as clutter (and confusingly deflate the
DaemonSet's own `READY`/`AVAILABLE` counters while they exist).

**Fix**: force-delete the stale ones, verified safe first via the real
running-pod check above:
```bash
kubectl get pods -n kube-system -l app=ovs --no-headers | \
  grep ContainerStatusUnknown | awk '{print $1}' > /tmp/stale.txt
kubectl delete pod -n kube-system $(cat /tmp/stale.txt | tr '\n' ' ') \
  --force --grace-period=0
```
DaemonSet reported `6/6` `READY`/`AVAILABLE` immediately after.

**Lesson**: after any node reboot (planned maintenance or otherwise),
check DaemonSet pod counts across the cluster, not just the node's own
`Ready` status — a rebooted node coming back healthy doesn't guarantee its
DaemonSet pod objects were cleanly reconciled, especially after multiple
reboots close together.
