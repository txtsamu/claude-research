---
type: how-to
tags: [truenas, iscsi, proxmox, lvm-thin, zfs, storage, homelab]
created: 2026-08-31
last_verified: 2026-08-31
status: current
---

# Adding 1TB of TrueNAS-backed LVM-thin storage to Proxmox (`pve-pc`)

`pve-pc`'s only VM-disk storage was `local-lvm` on the single local NVMe
(476GB total, was down to ~127GB free). Needed more room without adding
local disks — the NAS (`192.168.50.10`, TrueNAS SCALE 25.10) had 4.29TB
free on pool `data`.

## Why LVM-thin-on-iSCSI, not the TrueNAS Proxmox plugin

Two ways to get NAS-backed VM storage into Proxmox:

1. **iSCSI zvol + LVM-thin on top** — TrueNAS exports a raw block device,
   Proxmox layers its own LVM-thin pool on it. Snapshots/clones are
   Proxmox-native LVM-thin operations.
2. The official [truenas-proxmox-plugin](https://github.com/truenas/truenas-proxmox-plugin)
   — manages zvols directly from Proxmox via the TrueNAS API, its own
   storage plugin type (not `lvmthin`), thin provisioning via ZFS instead.

Went with #1 because the goal was specifically LVM-thin (Proxmox-native
snapshots/clones, standard `lvmthin` storage type) — the plugin route
would work but produces a different storage type entirely, not literal
`lvmthin`. Also confirmed: **LVM-thin cannot be cluster-shared** in
Proxmox, but that's a non-issue since `pve-pc` is single-node.

## Setup — NAS side

Reused the existing iSCSI portal (id 1) and initiator group (id 1,
"allow-all-lan") already serving other iSCSI consumers (k8s CSI PVCs,
an Immich Postgres LUN — see
[immich-pgdata-iscsi-lun-resize.md](immich-pgdata-iscsi-lun-resize.md)).

```sh
ssh moo@192.168.50.10
sudo zfs create -s -V 1T -b 16K data/proxmox-lvm   # -s sparse, matches existing block-size convention

sudo midclt call iscsi.extent.create '{"type": "DISK", "disk": "zvol/data/proxmox-lvm", "name": "proxmox-lvm", "blocksize": 512}'
sudo midclt call iscsi.target.create '{"name": "proxmox-lvm", "groups": [{"portal": 1, "initiator": 1, "authmethod": "NONE"}]}'
sudo midclt call iscsi.targetextent.create '{"target": <extent_id>, "extent": <target_id>, "lunid": 0}'

# base IQN, needed to build the full target IQN on the Proxmox side
sudo midclt call iscsi.global.config   # -> basename: iqn.2005-10.org.freenas.ctl
```
Full IQN: `iqn.2005-10.org.freenas.ctl:proxmox-lvm`.

## Setup — Proxmox side

```sh
ssh root@192.168.50.30   # pve-pc
systemctl enable --now iscsid          # was installed (open-iscsi) but inactive

iscsiadm -m discovery -t sendtargets -p 192.168.50.10   # sanity check the target is visible

pvesm add iscsi nas-lvm-base --portal 192.168.50.10 \
  --target iqn.2005-10.org.freenas.ctl:proxmox-lvm --content none
```

`pvesm add iscsi ...` triggers Proxmox to log in to the target itself —
no manual `iscsiadm ... --login` needed. Find the resulting block device:

```sh
pvesm list nas-lvm-base
# nas-lvm-base:0.0.0.scsi-<naa-id>   raw   images   1099511627776
ls -la /dev/disk/by-id/ | grep <naa-id>   # -> ../../sda
```

Then build the actual LVM-thin pool on that LUN:

```sh
pvcreate /dev/disk/by-id/scsi-<naa-id>
vgcreate vg-nas-lvm /dev/disk/by-id/scsi-<naa-id>
lvcreate -l 95%FREE --type thin-pool --thinpool nas-thin vg-nas-lvm   # 5% held back per Proxmox's own recommendation
```

**Gotcha**: default thin-pool creation warns about 512KiB chunk-size
zeroing slowing down writes ("Consider disabling zeroing (-Zn)"). Since
the backing device is a *fresh* sparse zvol (already zero), zeroing is
redundant — safe to disable for better write throughput over iSCSI:
```sh
lvchange --zero n vg-nas-lvm/nas-thin
```
Only safe to skip zeroing because the LUN is fresh/never-written; wouldn't
do this on a thin pool reused from another purpose.

Register with Proxmox:
```sh
pvesm add lvmthin nas-lvm-thin --thinpool nas-thin --vgname vg-nas-lvm \
  --content images,rootdir --nodes pve-pc
```

## Verification

```sh
pvesm alloc nas-lvm-thin 9999 vm-9999-disk-test 256M   # allocate
lvs vg-nas-lvm                                          # confirm it landed
pvesm free nas-lvm-thin:vm-9999-disk-test               # clean up
```

Real end-to-end test (create + verify + delete a thin LV through `pvesm`,
not just `pvesm status` reporting green) rather than trusting the storage
"active" status alone.

## Result

```
nas-lvm-thin   lvmthin   active   1019789312 KiB total   0 used   0.00%
```
~972.5GiB usable after the 5% thin-pool headroom. Shows up in the Proxmox
UI (Datacenter → Storage) as `nas-lvm-thin`, selectable for VM disks.

## Caveats to keep watching

- **Thin-on-thin**: the zvol is ZFS-sparse *and* the LVM pool on top is
  thin — actual NAS pool usage (`zpool list` on `192.168.50.10`) won't
  match what Proxmox reports until real data lands. Watch the NAS side
  independently, don't trust Proxmox's own usage number as the full
  picture.
- **Single iSCSI path, no multipath** — a network blip to the NAS stalls
  any VM disk living on `nas-lvm-thin`. Fine for this homelab; wouldn't
  put the most latency-critical workload here (see the etcd-latency
  reasoning in
  [talos-worker-storage-migration-nas-lvm-thin.md](talos-worker-storage-migration-nas-lvm-thin.md)
  for why control-plane nodes specifically were kept off this storage).
- `nas-lvm-base` (the raw iSCSI passthrough entry) reports `0 KiB` in
  `pvesm status` — expected, not a bug. It's a transport layer; the real
  volumes live one layer up in `nas-lvm-thin`. Don't remove it — deleting
  it breaks `nas-lvm-thin`, whose VG lives on that iSCSI LUN.
