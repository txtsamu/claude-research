---
type: how-to
tags: [talos, kubernetes, proxmox, storage-migration, lvm-thin, live-migration, cloudinit, iscsi, homelab, warp-vm]
created: 2026-08-31
last_verified: 2026-08-31
status: current
---

# Live-migrating Talos worker VM disks from `local-lvm` to NAS-backed `nas-lvm-thin`

Follow-up to [nas-lvm-thin-proxmox-setup.md](nas-lvm-thin-proxmox-setup.md) —
once the new NAS-backed storage existed, moved the 3 Talos worker node
disks onto it to relieve `local-lvm` pressure (was at 64.9% used, workers
alone accounted for 150G of the 210G total across all 6 Talos nodes).

## Scope decision: workers only, not control-plane

All 6 Talos VM disks (3 control-plane + 3 worker, mapped via
`~/talos-cluster/terraform/nodes.tf` on `warp-vm`: VMIDs 111-113 =
control-plane, 114-116 = workers) were on `local-lvm`. Moved **workers
only**:

- etcd (running on control-plane nodes) is documented as latency-sensitive
  to disk fsync — moving it to network-attached iSCSI storage trades real
  risk (leader elections from slow fsync) for freed local space.
- Workers are also where most of the space actually lived (150G of the
  210G total — worker disks had drifted to 50G/8vCPU/8GiB each vs.
  control-plane's 20G/2vCPU/4GiB, well past what `nodes.tf` still declares
  — Terraform state here is stale, not authoritative for live sizing).

## Mechanism: `qm disk move`, not cordon+drain

`qm disk move <vmid> scsi0 <target-storage> --delete 1` does a **live
QEMU block-mirror** — VM keeps running throughout, near-zero downtime, old
copy deleted automatically after the mirror completes and switches over.

Deliberately **skipped `kubectl cordon`/`drain`** for this — this cluster
runs real single-replica services (Nextcloud, Immich, Forgejo, Rancher,
etc.), and draining would force unnecessary pod restarts for zero benefit:
the live block-mirror is transparent to the running guest OS, kubelet, and
every pod on it. Cordoning is the right call for a *reboot* (see the
memory-downsize doc below) but actively counterproductive for a live
disk move.

```sh
ssh root@192.168.50.30   # pve-pc
qm disk move 114 scsi0 nas-lvm-thin --delete 1   # ~15min for a 50G disk over 1GbE, ~50MB/s
```

Verified zero disruption after each move: node stayed `Ready` with `AGE`
unchanged (proves no reboot happened) and pod `RESTARTS` counts unchanged
(proves nothing got evicted) — stronger proof than trusting Proxmox's own
"successfully rolled out" message.

## Gotcha: `qm disk move` doesn't touch the cloudinit (`ide2`) disk

Each Talos node also has a tiny 4MB `ide2` cloudinit seed disk (generated
by the `bpg/proxmox` Terraform provider's `initialization` block, from
Terraform-uploaded snippets referenced via `cicustom`). Moving `scsi0`
leaves `ide2` behind on `local-lvm` — trivial in space (4MB×3) but
inconsistent.

**First attempt, wrong**: assumed `qm set <vmid> --ide2 none,media=cdrom`
would just *eject* the media (detach, keep the volume). It doesn't for a
Proxmox-owned disk — it **deletes** the underlying volume outright. Lost
the (already-migrated) `nas-lvm-thin` cloudinit copies this way.

**Recovery — and it's genuinely fine, because `cicustom` survives**:
the actual cloud-init *source* (`cicustom: meta=local:snippets/<name>-meta.yaml,user=local:snippets/<name>.yaml`,
Terraform-uploaded snippets on `local` storage) is a separate, persistent
config key from `ide2` — deleting the generated ISO doesn't touch it.
Regenerate cleanly:
```sh
qm set 114 --ide2 nas-lvm-thin:cloudinit,media=cdrom   # allocates a NEW volume on the given storage
qm cloudinit update 114                                 # rebuilds the ISO content from cicustom
```
Verified via `qm agent 114 ping` throughout — VM never actually noticed
any of this (cdrom media changes on a running VM don't affect an
already-booted guest).

**Then**: the *original* `local-lvm` cloudinit LVs (from before the whole
detour) were still sitting there, held open by the running QEMU process's
old `ide2` attachment (`lvremove` failed: `"in use"`). The live media
swap above (ejecting to a genuinely new volume, not just re-pointing to
the same one) is what actually released that old handle —
`lvs -o lv_active` flipped from `active` (with the running-VM 'o' open
flag) to a state `lvremove -f` could finally clear.

**Lesson**: on a running Proxmox VM, `--ide2 none,media=cdrom` is a
*delete*, not an eject, for any Proxmox-managed volume. If the goal is
genuinely detaching-without-deleting, don't use `none` — go straight to
pointing `ide2` at the new location/allocation.

Exact cleanup commands, once the old `local-lvm` volumes were confirmed
inactive:
```sh
lvs -o lv_name,lv_active pve | grep -E "vm-11[456]-cloudinit"   # confirm no 'o' (open) flag first
lvremove -f pve/vm-114-cloudinit pve/vm-115-cloudinit pve/vm-116-cloudinit
```

## Result

| Node | VMID | Disk | Cloudinit |
|---|---|---|---|
| ts-worker01 | 114 | ✅ `nas-lvm-thin`, 50G | ✅ `nas-lvm-thin`, regenerated |
| ts-worker02 | 115 | ✅ `nas-lvm-thin`, 50G | ✅ `nas-lvm-thin`, regenerated |
| ts-worker03 | 116 | ✅ `nas-lvm-thin`, 50G | ✅ `nas-lvm-thin`, regenerated |

`local-lvm` usage: 64.9% → 38.1% used. `nas-lvm-thin`: 15.4% used, 862G
free. Control-plane (111-113) untouched, still on `local-lvm` by design.
