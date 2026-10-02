---
type: how-to
tags: [truenas, nas, zfs, iscsi, democratic-csi, k3s, cleanup, talos]
created: 2026-10-03
last_verified: 2026-10-03
status: current
---

# Finding and deleting unused zvols/datasets on the TrueNAS box (`nas`)

Deleted 38 unused zvols/datasets from pool `data` (TrueNAS 25.10, ZFS 2.3.4): 6 orphaned k3s PVC zvols, a leftover Immich pgdata zvol, and the whole old Talos cluster's iSCSI tree. Pool ALLOC went from 3.54T to 3.50T.

## How "unused" was decided

1. List datasets by size: `ssh moo@nas 'zfs list -o name,used,avail,refer,mountpoint,mounted -S used'`.
2. List the iSCSI objects and what is connected. `midclt` is the TrueNAS API CLI:
   ```bash
   sudo midclt call iscsi.extent.query       # extents -> zvol path
   sudo midclt call iscsi.target.query
   sudo midclt call iscsi.targetextent.query # target <-> extent mappings
   sudo midclt call iscsi.global.sessions    # who is connected right now
   sudo midclt call sharing.nfs.query; sudo midclt call sharing.smb.query
   ```
3. Cross-check against the live consumer. For k3s on `home`: `kubectl get pv -o custom-columns=PV:.metadata.name,CLAIM:.spec.claimRef.name`, then compare the PV names to the `pvc-*` zvols under `data/k8s-warp-iscsi`. Six zvols had no PV (0bb2d139, 38ed55a1, 5184673f, 646c6d2a, 734def57, f16b9850; ~176 MB).
4. Check for other consumers: snapshot tasks, replication and cloud sync (`pool.snapshottask.query`, `replication.query`, `cloudsync.query`) were all empty. Origins (clones) were empty.

Kept on purpose: `proxmox-lvm` (192G, live iSCSI session from the Proxmox host 192.168.50.30), `evomem-kb` (session from home), the 17 live warp PVC zvols, and the NFS/SMB datasets (photos, nextcloud, vm, immich-upload, obsidian-livesync-backup).

## What was deleted

- 6 orphaned `data/k8s-warp-iscsi/pvc-*` zvols.
- `data/immich-pgdata-new` (2.3G zvol from Aug 23, with an extent and target but no session; Immich uses PVC d641e76a now).
- `data/k8s-talos-iscsi` (24 zvols, 2 snapshots, ~14.7G) and `data/k8s-talos-iscsi-snapshots`. This is the old Talos cluster's storage, previously kept as a rollback after the k3s migration, so the rollback option is gone.

Left alone: `/mnt/data/immich-upload-backups-tmp` and `/mnt/data/logs` are plain directories on `data`, not datasets, and tiny.

## Deletion order

Done through the TrueNAS API so the iSCSI config is cleaned up as well, not with a bare `zfs destroy`, which would leave dangling extents and targets. Before running, a dry-run script checked that each zvol had exactly one extent and one dedicated target, that no target had a live session, and that no target held extents outside the plan.

```python
# per zvol (script ran on nas, via sudo midclt call)
iscsi.targetextent.delete <id> true
iscsi.target.delete <id> true
iscsi.extent.delete <id> false true      # remove=false, force=true
pool.dataset.delete data/k8s-warp-iscsi/pvc-...
pool.dataset.delete data/k8s-talos-iscsi '{"recursive": true}'
```

## Verification afterwards

`zpool list data` ONLINE; 17 warp zvols; 19 extents (17 PVCs + evomem-kb + proxmox-lvm); 18 sessions (16 warp + evomem-kb + proxmox-lvm, the same as before); on `home`, k3s active and no non-Running pods.

## Gotcha

`rtk` output filtering mangled a `grep` over the file listings, so the first orphan comparison looked wrong. Reading the saved files directly gave the correct result.
