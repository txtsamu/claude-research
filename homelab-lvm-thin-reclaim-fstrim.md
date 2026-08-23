---
type: troubleshooting
tags: [proxmox, lvm-thin, xfs, fstrim, storage, podman, homelab-vm]
created: 2026-08-23
last_verified: 2026-08-23
status: current
---

# `local-lvm` thin pool was 2.5x fuller than the guest actually needed — `fstrim.timer` was disabled

## Symptom

Wanted to shrink the `homelab-vm` root filesystem from 350G down to 150G to free up space on the Proxmox host (`pve-pc`). `df -h` inside the guest showed:

```
/dev/vda4   349G   81G  269G  24%   /
```

Only 81G actually used, 269G free — so 150G looked like a safe target from inside the guest.

## Diagnosis

### Root is XFS — can't be shrunk in place

```sh
findmnt -no FSTYPE /        # xfs
```

XFS supports `xfs_growfs` but has no shrink operation at all (unlike ext4's `resize2fs`). Shrinking would require booting a rescue image, recreating a smaller filesystem, migrating data with `xfsdump`/`rsync`, then repairing the GPT partition table and bootloader — real downtime and risk for a host running ~45 production containers, just to reclaim host-side space.

### The real question: does the guest's "free" space cost anything on the host?

`homelab-vm` is VM 100 on Proxmox node `pve-pc`, disk backed by **LVM-thin** (`local-lvm`), not a flat qcow2/raw file:

```
# on pve-pc
qm config 100 | grep virtio0
virtio0: local-lvm:vm-100-disk-0,discard=on,size=350G

lvs pve/vm-100-disk-0
  LV            VG  Attr       LSize   Pool Origin Data%
  vm-100-disk-0 pve Vwi-aotz-- 350.00g data        60.36
```

60.36% of a 350G thin volume = **~211G actually allocated in the pool** — far more than the 81G the guest filesystem reports as used. `discard=on` is set on the virtio disk, which should let the guest's TRIM commands punch holes back into the thin pool as blocks are freed. That wasn't happening:

```sh
systemctl is-enabled fstrim.timer   # disabled
systemctl is-active fstrim.timer    # inactive
```

**Root cause**: `fstrim.timer` was disabled inside the guest, so freed blocks were never actually discarded — they stayed allocated in the thin pool indefinitely even though the guest filesystem considered them free. The ~130G gap (211G allocated vs 81G used) was pure trim debt.

## Fix

```sh
# inside the guest (homelab-vm)
fstrim -v /
# /: 348.9 GiB (374653038592 bytes) trimmed

systemctl enable --now fstrim.timer
```

## Verification

```sh
# on pve-pc, before -> after
lvs pve/vm-100-disk-0
#   Data%   60.36  ->  22.85

pvesm status
#   local-lvm used   231.4G -> 93.8G
#   local-lvm avail   149.4G -> 287.0G
```

Reclaimed **~137.6G** on the host with zero downtime and zero guest-side risk — no partition resize, no filesystem rebuild. `fstrim.timer` runs weekly by default going forward, so this shouldn't drift back.

## Key findings / gotchas

- **A thin-provisioned VM disk's "size" is not what costs space on the host** — what matters is how much the thin pool has actually allocated, which only tracks the *filesystem's own free-space view* if TRIM is actually running. `discard=on` on the Proxmox disk is necessary but not sufficient — the guest also needs `fstrim.timer` (or `discard`/`async discard` mount options) actually enabled.
- **Always check `fstrim.timer` status before assuming a VM disk needs to be resized.** This was a 5-minute fix that made an XFS-can't-shrink problem irrelevant.
- **XFS cannot shrink, full stop.** If a genuinely smaller *visible* disk size is ever needed (not just host-side reclaim), the only path is rescue-boot + rebuild-as-ext4 + `lvreduce`, which Proxmox doesn't support via `qm resize` (grow-only) — that's a manual, guest-and-host operation, not a one-liner.
- Proxmox node capacity at the time of this check: `pve-pc` — 16 cores, 62.7GB RAM total, only ~20.5GB in use by the two running VMs (`homelab-vm`, `warp-vm`) — plenty of headroom for future VMs without needing to shrink anything.
