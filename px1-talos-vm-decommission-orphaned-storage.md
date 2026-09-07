---
type: troubleshooting
tags: [proxmox, talos, lvm-thin, iscsi, storage, cleanup, px1, warp-vm]
created: 2026-09-07
last_verified: 2026-09-07
status: current
---

# Deleting the leftover Talos VMs on `px1` left orphaned cloudinit disks behind

## Context

Follow-up to [[talos-to-k3s-migration-warp]]: the `homelab` namespace had already been fully migrated from the 6-node Talos cluster to k3s on `warp-vm`, with the old Talos VMs kept powered off on `px1` as a rollback safety net. Once the k3s cluster had been running cleanly for a while, the rollback option was no longer needed, so the Talos VMs and their template were deleted outright.

## VMs removed

```
qm list   # before
      VMID NAME                 STATUS     MEM(MB)    BOOTDISK(GB)
       101 warp-vm              running    16384            100.00
       111 talos-cp1            stopped    4096              20.00
       112 talos-cp2            stopped    4096              20.00
       113 talos-cp3            stopped    4096              20.00
       114 talos-worker1        stopped    6144              50.00
       115 talos-worker2        stopped    6144              50.00
       116 talos-worker3        stopped    6144              50.00
      9000 talos-1.13.9-template stopped    2048               4.15
```

```sh
for id in 111 112 113 114 115 116 9000; do qm destroy $id --purge; done
```

`qm list` afterward showed only `101 warp-vm`, and `pvesm status` showed `local-lvm` usage drop to ~0.01% as expected.

## The gotcha: `qm destroy --purge` doesn't catch disks outside the VM's current config

A routine storage audit afterward (`pvesm status` + `cat /etc/pve/storage.cfg` + `lvs <vg>` on every backing VG, cross-checked against the config) turned up three stray LVs still sitting in `local-lvm` (`pve/data` thinpool) for VMs that no longer existed:

```
lvs pve
  LV               VG  Attr       LSize   Pool Origin Data%
  vm-111-cloudinit pve Vwi-a-tz--   4.00m data        9.38
  vm-112-cloudinit pve Vwi-a-tz--   4.00m data        9.38
  vm-113-cloudinit pve Vwi-a-tz--   4.00m data        9.38
```

`qm destroy --purge` only removes disks that are listed in the VM's config *at the time of deletion*. These three cloudinit disks appear to be stale duplicates from an earlier point in each VM's life (before their cloudinit disk was moved to a different storage) — orphaned, unreferenced by any config, and left behind silently. `destroy`'s own log output ("Logical volume ... successfully removed") only reports on what it actually found in the config, so it gives no signal that anything was skipped.

## Fix

```sh
lvremove -f pve/vm-111-cloudinit pve/vm-112-cloudinit pve/vm-113-cloudinit
```

`lvs pve` afterward showed only the thinpool itself plus `vm-101-cloudinit` (warp-vm, still running) — clean.

## Side finding: `nas-lvm-base` is not orphaned, don't touch it

While auditing `/etc/pve/storage.cfg`, `nas-lvm-base` (`iscsi`, `content none`) looked at first glance like dead weight since it holds no VM images directly. It isn't orphaned — it's the iSCSI login to the TrueNAS box that exposes the LUN as `/dev/sda` on `px1`, and `nas-lvm-thin` (`vg-nas-lvm` / thinpool `nas-thin`) is the LVM-thin storage built on top of that same block device:

```sh
pvs
#   PV             VG         Fmt  Attr PSize    PFree
#   /dev/nvme0n1p3 pve        lvm2 a--  <475.94g 804.00m
#   /dev/sda       vg-nas-lvm lvm2 a--  1023.99g  51.20g

iscsiadm -m session
#   tcp: [1] 192.168.50.10:3260,1 iqn.2005-10.org.freenas.ctl:proxmox-lvm (non-flash)
```

`content none` on an iSCSI storage entry is the expected pattern when it exists purely to establish the session/LUN for a derived LVM-thin storage — not a sign of an unused or misconfigured entry.

## Key findings / gotchas

- **After any `qm destroy`, check `lvs <vg>` on every storage backing that node for leftover LVs matching the destroyed VMID** — destroy is not guaranteed to find disks that exist outside the VM's current config (e.g. left behind by a prior storage migration for that VM).
- **`content none` on an `iscsi` storage entry usually means it's a dependency, not dead config** — check whether another storage (typically `lvmthin`) is built on the same underlying PV/device before assuming it's unused.
- Trivial in this case (4MB × 3 = 12MB), but worth doing as routine hygiene after any VM deletion, especially bigger ones.
