---
type: troubleshooting
tags: [truenas, zfs, arc, iscsi, scst, proxmox, vzdump, backup, warp-vm, px1]
created: 2026-09-08
last_verified: 2026-09-08
status: current
---

# warp-vm (101) manual backup hangs/fails — TrueNAS iSCSI SCST buffer allocation starved by ZFS ARC

## Symptom

Ran a manual `vzdump` backup of VM 101 (warp) from px1 (Proxmox). The VM felt "stuck"
during the backup window, then the job aborted. After the abort, `qm status 101`
showed `running` again — the VM itself recovered, but every backup attempt at that
disk fails the same way.

## Diagnosis

### 1. Proxmox side (px1)

Recent vzdump task log (`pvesh get /nodes/px1/tasks/<UPID>/log`):

```
INFO: starting new backup job: vzdump 101 --storage nas-vm --compress zstd ...
...
ERROR: job failed with err -5 - Input/output error
INFO: aborting backup job
INFO: resuming VM again
ERROR: Backup of VM 101 failed - job failed with err -5 - Input/output error
TASK ERROR: job errors
```

VM 101's disk (`vg-nas-lvm-vm--101-disk--0`) lives on `nas-lvm-thin`, an LVM-thin pool
built on top of an **iSCSI LUN** (`/dev/sda` on px1) from TrueNAS (`192.168.50.10`,
target `iqn.2005-10.org.freenas.ctl:proxmox-lvm`). The backup target itself
(`nas-vm`, NFSv4.2, also on the same TrueNAS box) is a separate share — the failure
is on the *source* disk read path, not the backup write path.

`dmesg -T` on px1 at the exact failure timestamps:

```
[Tue Sep  8 02:12:12 2026] sd 16:0:0:0: [sda] tag#35 timing out command, waited 180s
[Tue Sep  8 02:12:12 2026] sd 16:0:0:0: [sda] tag#35 FAILED Result: hostbyte=DID_OK driverbyte=DRIVER_OK cmd_age=180s
[Tue Sep  8 02:12:12 2026] I/O error, dev sda, sector 384521728 op 0x0:(READ) ...
```

Same pattern repeated at 02:32:52 (this backup's abort) and the previous day
(2026-09-07 02:14, during an earlier automatic/manual attempt) — this is a
**recurring** failure, not a one-off. iSCSI session itself stayed `LOGGED_IN`
throughout (`iscsiadm -m session -P3`) — the initiator side is fine; the target
just stopped answering reads within the 180s SCSI command timeout.

### 2. TrueNAS side (nas / 192.168.50.10, SCALE 25.10.4)

`zpool status` — pool `data` (RAIDZ2, 4 disks) fully healthy, zero read/write/cksum
errors, last scrub clean (2026-08-16). Disks are not the problem.

The real cause was in `journalctl -k` on TrueNAS at the exact same timestamps:
tens of thousands of lines like:

```
kernel: [2793]: scst: Allocation of sgv_pool_obj failed (size 8388608)
kernel: [2793]: scst: Unable to allocate or build requested buffer (size 8388608), sending BUSY or QUEUE FULL status
```

SCST (the Linux iSCSI target TrueNAS SCALE uses) couldn't allocate 8MB
scatter-gather buffers for the read burst the backup generated, so it told px1
"busy" — repeatedly, for the full 180s the initiator waits — hence the timeout/abort
on the Proxmox side.

`free -h` on TrueNAS at the time: 29GiB total RAM, ZFS ARC (`c` / `size` in
`/proc/spl/kstat/zfs/arcstats`) sized to ~20GiB actual / ~28GiB max (`zfs_arc_max`
was `0`, i.e. default — TrueNAS SCALE's default is roughly half-to-most of RAM
depending on version), leaving only ~3.7GiB free / ~7.2GiB "available". Under the
extra read pressure of a backup, SCST couldn't find enough free, non-fragmented
memory for its buffer pool → allocation failures → BUSY responses → px1 timeouts.

This matches a documented TrueNAS SCALE community case exactly:
[NVMe/TCP instability, moved to iSCSI/SCST, now SGV allocation failures](https://forums.truenas.com/t/nvme-tcp-instability-moved-to-iscsi-scst-now-sgv-allocation-failures/67381) —
same `sgv_pool_obj` error, traced to **ZFS ARC memory pressure causing kernel
memory *compaction* failures** (high-order/contiguous allocations fail even when
"free" memory looks adequate — `/proc/buddyinfo` and `compact_stall`/`compact_fail`
counters are the real signal, not `free -h` alone). Their fix: cap ARC to 16GiB on
a 32GiB box; problem stopped reproducing under repeated backup/migration load.

## Fix

Capped ZFS ARC on the TrueNAS box to leave SCST reliable headroom, via a
**persisted** middleware tunable (survives reboot, unlike editing
`/sys/module/zfs/parameters/zfs_arc_max` directly or the old pre-init-script
method from earlier SCALE releases):

```bash
# TrueNAS SCALE — persistent, applies immediately (it's a job)
midclt call tunable.create '{
  "type": "ZFS",
  "var": "zfs_arc_max",
  "value": "12884901888",
  "comment": "Cap ARC to 12GiB so SCST iSCSI target has memory headroom for sgv_pool buffer allocs during heavy reads",
  "enabled": true
}'
```

(`tunable.*`, not `system.tunable.*` — the latter doesn't exist on this version.
`tunable.tunable_type_choices` confirms `SYSCTL` / `UDEV` / `ZFS` as the three
types; `ZFS` is for zfs.ko module parameters like `zfs_arc_max`, applied under
`/sys/module/zfs/parameters/`.)

12GiB on this 29GiB box (vs. the forum case's 16GiB on 32GiB) — proportionally a
bit more conservative since this box's only job is storage (no TrueNAS "Apps"/k3s
configured, confirmed via `midclt call app.query '[]'` → `[]` and
`docker.status` → `UNCONFIGURED`, so there's no middleware auto-adjustment of
ARC max to worry about — that override only kicks in when Apps has memory
reserved).

Verified applied:

```
$ cat /sys/module/zfs/parameters/zfs_arc_max
12884901888
$ grep -E '^(c |c_max) ' /proc/spl/kstat/zfs/arcstats
c                               4    12884901888
c_max                           4    12884901888
```

`free -h` before → after: `3.7Gi free / 7.2Gi available` → `10Gi free / 13Gi
available`.

## Not yet verified

Did **not** re-run the backup to confirm the SCST allocation failures stop
reproducing under real load — should do a follow-up `vzdump 101` and check
`journalctl -k` on TrueNAS for `sgv_pool_obj` during it. If it recurs even at
12GiB, the forum thread's advice is to watch `/proc/buddyinfo` and
`compact_stall`/`compact_fail`/`compact_success` (`/proc/vmstat`) under load
rather than just `free -h` — fragmentation, not raw free memory, is the actual
constraint on high-order allocations.

## Useful commands

```bash
# px1 (Proxmox) — see task history / logs
pvesh get /nodes/px1/tasks --limit 10
pvesh get /nodes/px1/tasks/<UPID>/log

# px1 — iSCSI session health
iscsiadm -m session -P3

# px1 — kernel-level I/O errors on the LUN
dmesg -T | grep -iE 'sd 16|I/O error'

# TrueNAS — pool health
zpool status -x

# TrueNAS — SCST buffer allocation failures (the actual smoking gun)
journalctl -k --since '<window>' | grep -iE 'scst.*alloc'

# TrueNAS — ARC size vs. cap
grep -E '^(c |c_max|size) ' /proc/spl/kstat/zfs/arcstats

# TrueNAS — list/inspect persisted tunables
midclt call tunable.query '[]'
```

## Related

See also [`nas-lvm-thin-proxmox-setup.md`](nas-lvm-thin-proxmox-setup.md) for how
this iSCSI LUN + LVM-thin storage was originally set up, and
[`immich-pgdata-iscsi-lun-resize.md`](immich-pgdata-iscsi-lun-resize.md) for
another iSCSI/ZFS interaction on the same TrueNAS box.
