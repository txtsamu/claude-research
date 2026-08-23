---
type: how-to
tags: [truenas, iscsi, zfs, zvol, thin-provisioning, podman, quadlet, immich, postgres, homelab-vm]
created: 2026-08-23
last_verified: 2026-08-23
status: current
---

# Shrinking an oversized iSCSI-backed zvol LUN under a live Podman-Quadlet Postgres DB

## Symptom

Immich's Postgres data directory on `homelab-vm` (`192.168.50.80`) is backed by a TrueNAS iSCSI LUN, not local disk or NFS. The zvol behind it had been provisioned at **200G**, way oversized for the actual DB. Wanted it capped smaller.

## Diagnosis — is this actually a space problem?

Checked before touching anything:

```sh
# on the NAS (moo@192.168.50.10, sudo)
zfs get all data/immich-pgdata | grep -E 'volsize|reserv|used|refer'
#   used            4.68G
#   referenced      4.68G
#   reservation     none      default
#   refreservation  none      default
#   volsize         200G      local

zpool list
#   data   7.27T  3.05T alloc  4.22T free
```

**No refreservation** → the zvol is thin-provisioned. The 200G `volsize` is only the *logical* size presented to the iSCSI initiator; actual pool consumption was 4.68G, and the pool had 4.22T free regardless. So shrinking it would **not** reclaim any real space — the only reason to do it was capping the LUN so a runaway Postgres bug can't silently balloon toward 200G unnoticed. Worth confirming this before doing surgery on a live production DB for zero space benefit — see `homelab-lvm-thin-reclaim-fstrim.md` for the same "is the size real or thin-provisioning noise" question on a different layer (LVM-thin vs ZFS).

Given the goal was a safety cap, not space reclaim, the safe move is **provision a new smaller LUN, cut over, decommission the old one** — not an in-place `resize2fs`+`zfs set volsize=` shrink on a live device, which risks corruption if anything goes wrong mid-resize.

## Setup at time of migration

- NAS: zvol `data/immich-pgdata`, iSCSI extent `immich-pgdata-extent` (id 1), target `immich-pgdata` (id 1), IQN `iqn.2005-10.org.freenas.ctl:immich-pgdata`, portal id 1 / initiator group id 1, auth NONE.
- `homelab-vm`: iSCSI session to that target → `/dev/sda`, ext4, mounted at `/mnt/immich-pgdata` via `/etc/fstab` (`x-systemd.requires=iscsid.service,x-systemd.requires-mounts-for=/dev/sda`).
- Podman Quadlet `immich-postgres.container`: `Volume=/mnt/immich-pgdata:/var/lib/postgresql/data:Z` — plain bind mount, no LVM/device-mapper indirection to worry about.

## Migration steps

### 1. New zvol + iSCSI LUN on the NAS

```sh
ssh moo@192.168.50.10
sudo zfs create -s -V 30G -b 16K data/immich-pgdata-new   # -s = sparse, matches volblocksize of the original

sudo midclt call iscsi.extent.create '{"type": "DISK", "disk": "zvol/data/immich-pgdata-new", "name": "immich-pgdata-new", "blocksize": 512}'
sudo midclt call iscsi.target.create '{"name": "immich-pgdata-new", "groups": [{"portal": 1, "initiator": 1, "authmethod": "NONE"}]}'
sudo midclt call iscsi.targetextent.create '{"target": 2, "extent": 2, "lunid": 0}'   # ids from the two calls above
```

TrueNAS doesn't let you repoint an existing extent to a different zvol, so the new LUN necessarily gets a new name/IQN (`immich-pgdata-new`) — can't preserve the original `immich-pgdata` name without yet another cutover.

### 2. Attach + format on the initiator

```sh
ssh root@192.168.50.80   # homelab-vm
iscsiadm -m discovery -t sendtargets -p 192.168.50.10
iscsiadm -m node -T iqn.2005-10.org.freenas.ctl:immich-pgdata-new -p 192.168.50.10 --login
# new device shows up as /dev/sdb
mkfs.ext4 -q -L immich-pgdata-new /dev/sdb
mkdir -p /mnt/immich-pgdata-new
mount /dev/sdb /mnt/immich-pgdata-new
```

### 3. Downtime window — stop Postgres, copy, verify

```sh
systemctl stop immich-postgres.service
rsync -aHAX --numeric-ids /mnt/immich-pgdata/ /mnt/immich-pgdata-new/
diff -rq /mnt/immich-pgdata /mnt/immich-pgdata-new   # must be empty (ignoring lost+found)
```

Data was 2.2G at copy time; rsync + diff took seconds. Total Postgres downtime was well under a minute.

### 4. Cut over the mount

```sh
umount /mnt/immich-pgdata-new /mnt/immich-pgdata
blkid /dev/sdb   # get new UUID
```

Edit `/etc/fstab`, replacing the old line's UUID **and** the `requires-mounts-for` target:

```
# before
UUID=<old-uuid> /mnt/immich-pgdata ext4 _netdev,x-systemd.requires=iscsid.service,x-systemd.requires-mounts-for=/dev/sda 0 0

# after
UUID=<new-uuid> /mnt/immich-pgdata ext4 _netdev,x-systemd.requires=iscsid.service,x-systemd.requires-mounts-for=/dev/disk/by-uuid/<new-uuid> 0 0
```

Then:

```sh
systemctl daemon-reload
mount /mnt/immich-pgdata
systemctl start immich-postgres.service
```

### 5. Verify

```sh
journalctl -u immich-postgres.service -n 20 --no-pager   # "database system is ready to accept connections", no errors
curl -s -o /dev/null -w '%{http_code}' http://localhost:2283/api/server/ping   # 200
podman exec immich-postgres psql -U postgres -d immich -c 'SELECT count(*) FROM asset;'   # matches pre-migration count
```

### 6. Decommission the old LUN

Only after the new one is confirmed stable:

```sh
# initiator
iscsiadm -m node -T iqn.2005-10.org.freenas.ctl:immich-pgdata -p 192.168.50.10 --logout
iscsiadm -m node -T iqn.2005-10.org.freenas.ctl:immich-pgdata -p 192.168.50.10 -o delete

# NAS
sudo midclt call iscsi.targetextent.delete 1
sudo midclt call iscsi.target.delete 1
sudo midclt call iscsi.extent.delete 1 false false   # id, remove-underlying-data, force — NOT a JSON array, positional args
sudo zfs destroy data/immich-pgdata
```

## Key findings / gotchas

- **A zvol's `volsize` is not what it costs you.** TrueNAS Scale zvols are thin-provisioned by default (no `refreservation`) — check `zfs get reservation,refreservation` before assuming an oversized LUN is wasting pool space. If there's no reservation, the only reason to shrink is a safety cap, not capacity.
- **In-place shrink (`resize2fs` down + `zfs set volsize=` down) works in principle but is unnecessary risk** for a live production DB when the actual data is small — a new-LUN-and-rsync cutover is safer, fully reversible until the old LUN is destroyed, and barely more work.
- **`x-systemd.requires-mounts-for=/dev/sdX` in fstab is fragile** — `/dev/sdX` device letters depend on iSCSI login/enumeration order, which can change after you remove a LUN (a device that was `/dev/sdb` today may become `/dev/sda` after a reboot once the original LUN is gone). Use the stable `/dev/disk/by-uuid/<uuid>` path instead.
- **`midclt call iscsi.extent.delete` takes positional args, not a JSON array** — `sudo midclt call iscsi.extent.delete 1 false false` works; `sudo midclt call iscsi.extent.delete "[1, false]"` fails with `[EINVAL] id: Input should be a valid integer`.
- **TrueNAS can't repoint an extent to a different zvol** — a "resize" of an iSCSI-backed zvol via new-LUN-cutover always means a new IQN/target name, unless you're willing to do a second cutover just to rename it back.
