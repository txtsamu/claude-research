---
type: troubleshooting
tags: [talos, proxmox, qemu, memory, reboot, talosctl, kexec, powercycle, homelab, warp-vm]
created: 2026-08-31
last_verified: 2026-08-31
status: current
---

# `talosctl reboot` (any mode) does not apply a Proxmox VM memory resize — only a hypervisor-level `qm reboot` does

Downsized the 3 Talos worker VMs from 8GB → 6GB RAM each (VMIDs 114-116)
after confirming real usage was well under 6GB (`kubectl top nodes`:
2.5-3.1Gi actual vs. 8Gi capacity) even though scheduled *requests* were
tighter, especially on `ts-worker03` (4944Mi requested, 66% of capacity —
flagged as worth watching post-resize, ~80% of the new 6GB).

## Why this doc exists: the reboot mechanism genuinely doesn't work the way it looks like it should

Instinct: change `qm set --memory`, then reboot the VM somehow, done.
Two `talosctl`-driven reboot attempts both **appeared to succeed** (clean
log output, node came back `Ready`) while **silently not applying the new
memory value at all**. This is the actual gotcha worth documenting — the
failure mode gives no error, just a `Ready` node still on the old capacity.

## What was tried, in order

**1. Default `talosctl reboot`** — uses **kexec** by default:
```sh
talosctl -e 192.168.50.91 -n 192.168.50.94 reboot
```
Log shows a `phase: kexec` step. kexec re-executes a new kernel *within
the same running process's memory space* — it does not restart the
underlying QEMU process, so Proxmox never re-reads the VM's hardware
config. Confirmed after this: `kubectl get node ts-worker01 -o
jsonpath='{.status.capacity.memory}'` → still `8108200Ki`, unchanged.

**2. `talosctl reboot -m powercycle`** — explicitly bypasses kexec:
```sh
talosctl -e 192.168.50.91 -n 192.168.50.94 reboot -m powercycle
```
Full boot sequence this time (including a `memorySizeCheck` phase, which
looked promising), node came back `Ready`. **Still didn't work** —
capacity unchanged again. Confirmed why, directly on Proxmox:
```sh
qm config 114 --current | grep memory   # -> memory: 8192  (the OLD value — a *pending* change)
ps -o pid,etime,cmd -p $(cat /var/run/qemu-server/114.pid) | head -2
# PID 3029362, ELAPSED 7-12:56:02 (SEVEN DAYS) — the QEMU process had never restarted, across BOTH reboot attempts
# -m 8192 baked into the running process's own launch command line
```
"Powercycle" mode still only triggers an ACPI-level reset *inside* the
guest/QEMU — QEMU's own `system_reset` resets virtual hardware state
without killing and relaunching the process itself, so it never re-reads
the Proxmox config file either.

## What actually worked

A **Proxmox-level** `qm reboot` — unlike anything triggered from inside
the guest, Proxmox's own reboot implementation for a VM really does stop
and relaunch the QEMU process:
```sh
ssh root@192.168.50.30
qm set 114 --memory 6144
qm reboot 114
```
Confirmed: new PID, `ELAPSED 00:04`, `-m 6144` in the process's own
command line this time. Node came back with `capacity: 6043812Ki`.

## Takeaway

**Any Talos-side reboot mechanism (`talosctl reboot`, default or
`-m powercycle`) operates entirely within the guest/QEMU-process
boundary and cannot apply a pending Proxmox VM hardware change.** Only a
reboot issued from the Proxmox management layer itself (`qm reboot`, or
equivalently a full `qm stop` + `qm start`) actually restarts the QEMU
process and re-reads `qm.conf`. This applies to *any* hardware-level
change that only takes effect at QEMU launch (memory size being the one
hit here) — worth checking `qm config <vmid> --current` vs. the base
config after any such change to see whether it's still "pending."

Contrast with disk *resizing* — see
[talos-worker-disk-resize-proxmox.md](talos-worker-disk-resize-proxmox.md) —
where a plain `talosctl reboot` (kexec, default mode) *was* sufficient.
The distinction: growing a disk just needs the guest kernel to notice a
bigger block device on its next partition scan (a guest-OS-level
operation, which kexec's fresh kernel boot does trigger) — it doesn't
require QEMU itself to re-initialize the device from a changed `-drive`
argument the way memory size requires a changed `-m` argument at process
launch.

## Procedure used (repeated per node, one at a time)

Cordon+drain **was** the right call here (unlike the live disk-move in
[talos-worker-storage-migration-nas-lvm-thin.md](talos-worker-storage-migration-nas-lvm-thin.md)) —
a real reboot is unavoidable for a memory resize, so draining first
avoids pods getting stuck in `Unknown` state while the node is briefly
gone, rather than a clean reschedule:

```sh
kubectl cordon ts-worker01
kubectl drain ts-worker01 --ignore-daemonsets --delete-emptydir-data --timeout=180s
```
```sh
ssh root@192.168.50.30 'qm set 114 --memory 6144 && qm reboot 114'
```
```sh
ssh root@192.168.50.30 "ps -o pid,etime,cmd -p \$(cat /var/run/qemu-server/114.pid) | head -2; qm config 114 --current | grep memory"   # verify BEFORE waiting on kubectl
```
```sh
kubectl wait node/ts-worker01 --for=condition=Ready --timeout=180s
kubectl get node ts-worker01 -o jsonpath='capacity: {.status.capacity.memory}{"\n"}allocatable: {.status.allocatable.memory}{"\n"}'
kubectl uncordon ts-worker01
```

Order: lightest-loaded node first (`ts-worker01`, lowest scheduled
requests) → heaviest last (`ts-worker03`) — maximizes headroom on the
*other* two nodes to absorb each drain's rescheduled pods.

**Gotcha**: `kubectl wait --for=condition=Ready --timeout=180s` timed out
once on `ts-worker03` even though the node actually *was* `Ready` by the
time the command returned (`kubectl get node` immediately after showed
`Ready,SchedulingDisabled`, fresh heartbeat) — just a timing race between
the wait's own poll and the node's actual transition, not a real failure.
Don't trust a `wait` timeout alone as proof of a hung node; check current
status directly.

**Transient side effect after `ts-worker01`'s reboot**: a freshly
rescheduled `fleet-agent` pod briefly failed sandbox creation
(`dial unix /run/openvswitch/kube-ovn-daemon.sock: connect: no such file
or directory`) because it landed on `ts-worker01` in the same narrow
window its own `kube-ovn-cni` DaemonSet pod was still in `Init:0/2` after
its own post-reboot restart. Self-resolved in under a minute once
`kube-ovn-cni` finished initializing — kubelet retries sandbox creation
automatically. Not a real problem, just a reboot/CNI-readiness race
worth recognizing rather than intervening on.

## Result

| Node | Before | After |
|---|---|---|
| ts-worker01 | 8Gi (8108200Ki) | **6Gi** (6043812Ki) |
| ts-worker02 | 8Gi | **6Gi** (6043808Ki) |
| ts-worker03 | 8Gi | **6Gi** (6043808Ki) |

Total worker capacity 24Gi → 18Gi. `ts-worker03` worth re-checking later —
was already the most heavily-requested node pre-resize (4944Mi, 66% of
old 7.73Gi capacity); at 6Gi that's ~80% of allocatable requested, leaving
comparatively little schedulable headroom there specifically for new
pods (though real usage has plenty of room).

Also note: these VM sizes are now further drifted from
`~/talos-cluster/terraform/nodes.tf` on `warp-vm` (already stale before
this — that file still says `memory = 2048`/`cores = 2` per node, live
values were already 4096/8192-and-8-cores before today). Not reconciled
as part of this work.
