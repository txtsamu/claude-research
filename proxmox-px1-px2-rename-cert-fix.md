---
type: how-to
tags: [proxmox, hostname-rename, pmxcfs, tls, ssl-cert, dns, apt, storage-cfg, caddy, px1, px2]
created: 2026-09-05
last_verified: 2026-09-05
status: current
---

# Renaming two standalone Proxmox hosts (`pve-nas`→`px2`, `pve-pc`→`px1`) + fallout fixes

Two independent (non-clustered) Proxmox VE hosts had drifted from their intended
`px1`/`px2` naming convention: `192.168.50.30` was still actually named `pve-pc`
(only ever called "px1" informally/in SSH config), and `192.168.50.50` was
`pve-nas`. Renamed both properly, which surfaced three unrelated pre-existing
issues along the way — documenting all of it since the rename touches genuinely
fragile pmxcfs internals.

## Background: how each host was found

- `192.168.50.50` (`pve-nas`) — a routine "why is DNS not working here" check
  found `/etc/resolv.conf` was a **plain static file** (not managed by
  NetworkManager/systemd-resolved) still pointing at `192.168.50.16`, a
  Pi-hole box decommissioned during the Technitium migration (see
  `technitium-dns-3node-cluster-deployment.md`). This host was never in that
  migration's original inventory, so the cleanup swept every host it *knew
  about* and missed this one — worth remembering for any future DNS cutover:
  audit for standalone/static `resolv.conf` files outside the usual
  DHCP/NetworkManager-managed fleet, they don't show up in the obvious list.
  Fixed: rewrote it to the 3 Technitium nodes + `1.1.1.1` fallback.
- `192.168.50.30` (`pve-pc`) — found while renaming `pve-nas`; this host runs
  9 live guests, including the entire Talos Kubernetes cluster
  (`talos-cp1/2/3`, `talos-worker1/2/3`), `warp-vm`, and `wg-bypass` — i.e.
  it's the opposite of an idle box, so its rename had to be done live with
  zero acceptable downtime.

## The rename procedure (standalone node, official method + the parts the wiki glosses over)

Official reference: <https://pve.proxmox.com/wiki/Renaming_a_PVE_node>. It
explicitly says this "must be done on an empty node" and is "not recommended"
otherwise — done anyway here since neither host could be trivially emptied,
following the same steps the wiki describes for handling existing VMs/CTs
(recreate the `/etc/pve/nodes/<name>/` folder structure, copy files per
level, since **pmxcfs refuses to `mv`/rename a non-empty directory** — only
individual file moves work).

Per node (ran identically on both `pve-nas`→`px2` and `pve-pc`→`px1`):

```bash
# 1. hostname
hostnamectl set-hostname px2

# 2. /etc/hosts — rewrite in place (see the sed -i gotcha note if this file
#    were ever bind-mounted into a container; it's a plain host file here so
#    a direct edit is fine)
#    192.168.50.50 pve.ssamu.id pve-nas  ->  192.168.50.50 px2.<PERSONAL_DOMAIN> px2

# 3. restart pmxcfs so it picks up the new local hostname
systemctl restart pve-cluster

# 4. create the new node dir, migrate files ONE AT A TIME (not `mv olddir newdir`)
mkdir -p /etc/pve/nodes/px2/qemu-server /etc/pve/nodes/px2/lxc
mv /etc/pve/nodes/pve-nas/qemu-server/*.conf /etc/pve/nodes/px2/qemu-server/
mv /etc/pve/nodes/pve-nas/lxc/*.conf         /etc/pve/nodes/px2/lxc/       # if any
for f in config lrm_status ssh_known_hosts; do
  [ -f /etc/pve/nodes/pve-nas/$f ] && mv /etc/pve/nodes/pve-nas/$f /etc/pve/nodes/px2/$f
done
# priv/ is usually empty on a standalone node — don't bother copying, regen certs instead (step 6)

# 5. fix any node-restricted storage.cfg entries
sed -i "s/nodes pve-nas/nodes px2/" /etc/pve/storage.cfg

# 6. regenerate the node's own TLS cert (old one has the wrong CN)
pvecm updatecerts -f

# 7. drop the now-empty old node dir, restart services
rm -rf /etc/pve/nodes/pve-nas
systemctl restart pvedaemon pveproxy pvestatd
```

**On the 9-VM host (`pve-pc`), all 9 guests (including the live Talos
cluster) stayed running throughout** — verified by PID continuity in `qm
list` before/after. pmxcfs config operations and `systemctl restart
pve*` don't touch already-running QEMU processes; the risk is purely to
management-plane operations mid-move, not to the guests themselves.

The official wiki also mentions two things not needed here: `/etc/mailname`
(didn't exist on either host) and migrating `/var/lib/rrdcached/db/pve2-{node,storage}/<old-name>/`
history (neither host had accumulated any RRD history yet — a fresh-ish
install). Check both on a more mature host before assuming they're
irrelevant.

A reboot is recommended by the wiki to fully settle everything; it's optional
if you've confirmed services are already running correctly under the new
name (which they were here) — do it at a convenient time rather than
mid-procedure.

### Fleet cleanup check

Worth checking whether any other host's `/etc/hosts` hardcodes the old name —
none did here (verified across `nas`, `warp-vm`, `arm1-4`, and the other
Proxmox host), so nothing else needed updating.

## Fallout #1: `local-lvm2` storage entry pointed at a non-existent LVM thin pool

While testing on `px2`, `qm destroy <vmid>` failed with:

```
TASK ERROR: no such logical volume pve2/data
```

Root cause: `/etc/pve/storage.cfg` had an **enabled** `lvmthin` storage
(`local-lvm2`, `vgname pve2`, `thinpool data`) that never corresponded to
anything on this host's actual disk layout — the only real VG here is `pve`
(root + swap, plain LVM, no thin pool, 0 free space). `qm destroy` scans
every *enabled* storage for orphaned volumes belonging to the VMID as part
of cleanup, and dies as soon as it hits a storage backed by a VG that
doesn't exist — completely unrelated to whether the VM being destroyed
actually has any disks on that storage (in this case it had none at all).

No VM/CT config on the host referenced `local-lvm` or `local-lvm2`, so the
fix was just to mark it disabled:

```
lvmthin: local-lvm2
	disable 1
	thinpool data
	vgname pve2
	content rootdir,images
```

After that, `pvesm status` came back clean and `qm destroy` completed
normally.

## Fallout #2: two Proxmox hosts sharing the exact same self-signed CA

After the rename, `px1`'s web UI threw Firefox's
`SEC_ERROR_REUSED_ISSUER_AND_SERIAL` — an error Firefox does **not** allow
adding a manual exception for (unlike a normal self-signed warning), since
it specifically flags a genuine issuer+serial collision as a possible
spoofing attempt.

Root cause, confirmed by comparing files directly:

```bash
md5sum /etc/pve/pve-root-ca.pem /etc/pve/priv/pve-root-ca.key   # on both hosts
# identical MD5 on BOTH the cert AND the private key, on both px1 and px2
```

`px1` and `px2` were provisioned from a common template/clone rather than
independently initialized, so they share the literal same
"PVE Cluster Manager CA" identity (same CA UUID in the cert's `OU`, same
private key). Each node's local `pve-root-ca.srl` (next-serial counter) is
tracked independently, but since both had been regenerated a similar number
of times, they landed on the identical next serial (`03`) — combined with
the identical issuer, that's an exact collision.

Fix (only needed on one of the two — the browser already trusted the
other's existing cert fine):

```bash
rm -f /etc/pve/pve-root-ca.pem /etc/pve/priv/pve-root-ca.key /etc/pve/priv/pve-root-ca.srl
rm -f /etc/pve/nodes/px1/pve-ssl.key /etc/pve/nodes/px1/pve-ssl.pem
pvecm updatecerts -f     # generates a brand-new, independent CA + node cert
systemctl restart pveproxy
```

Verified: new CA `OU` UUID is completely different from `px2`'s, fresh
random serial, no more collision.

**Note for later**: `px2` still carries the original shared-CA identity. Not
broken today (browsers already trust its current cert), but if this template
is ever cloned again, the new clone will collide with `px2` the same way —
worth giving `px2` its own independent CA too at some point, same procedure.

## Fallout #3: getting genuinely browser-trusted HTTPS for the Proxmox UIs

Chose the low-effort option consistent with the rest of this homelab's
`.lan` setup (Caddy + `tls internal`, already used for every other
self-hosted service here) over a real Let's Encrypt cert via Proxmox's
built-in ACME (DNS-01) — that remains the better option if a fully
warning-free experience *at the raw `IP:8006` level* is ever wanted, since
the Caddy route only fixes the new `.lan` hostname, not direct IP access.

Added to `/root/caddy/Caddyfile` on `warp-vm` (`local_certs` global option
already present, so `tls internal` reuses Caddy's own already-trusted local
CA — no new per-device trust setup needed):

```caddyfile
px1.lan {
	tls internal
	reverse_proxy https://192.168.50.30:8006 {
		header_up Host {host}
		transport http {
			tls_insecure_skip_verify
		}
	}
}

px2.lan {
	tls internal
	reverse_proxy https://192.168.50.50:8006 {
		header_up Host {host}
		transport http {
			tls_insecure_skip_verify
		}
	}
}
```

(`px1.lan` replaced a pre-existing `proxmox.lan` block that already pointed
at `.30` — renamed to match the new naming scheme rather than kept as an
alias.)

Then added matching `A` records (`px1.lan`/`px2.lan` → `192.168.50.200`,
same convention as every other Caddy-fronted `.lan` site) via the Technitium
HTTP API on all 3 DNS nodes:

```bash
TOK=$(curl -s "http://<node-ip>:5380/api/user/login?user=admin&pass=<TECHNITIUM_ADMIN_PASSWORD>" | jq -r .token)
curl -s -H "Authorization: Bearer $TOK" -G "http://<node-ip>:5380/api/zones/records/add" \
  --data-urlencode "domain=px1.lan" --data-urlencode "zone=lan" \
  --data-urlencode "type=A" --data-urlencode "ipAddress=192.168.50.200"
# repeat per node (192.168.50.200/.42/.40), per hostname
```

### Gotcha: `sed -i` on the live Caddyfile broke the running container's bind mount

Mid-edit, `sed -i 's/^proxmox\.lan {/px1.lan {/'` was used on
`/root/caddy/Caddyfile` — `sed -i` does a write-new-file-then-rename under
the hood, which **swaps the inode**. The Caddy container's bind mount stays
attached to the *old* inode, so the running container silently kept serving
stale content (confirmed via `podman exec caddy cat /etc/caddy/Caddyfile`
showing the pre-edit version) even though the file on the host looked
correct. A second full-file rewrite via `tee`/`cat >` (same inode, in
place) fixed the *host* file but the container was by then permanently
detached from that path — required `podman restart caddy` (Quadlet/systemd
auto-recreated it cleanly) to reattach. **Lesson, worth repeating**: never
`sed -i` a file that's bind-mounted into a running container; always
truncate-and-rewrite in place (`cat > file <<EOF ... EOF` or `tee`), or
restart the container after any edit if unsure which method was used.

## Fallout #4: `px2` was also just behind on updates

Separately noticed `px2` was on `pve-manager 9.1.7` vs `px1`'s `9.2.6` —
turned out to be no actual blocker (no held packages, no apt pinning, 85GB
free disk, no broken dpkg state), just that `apt update` had been run
regularly (refreshing package lists) but `apt full-upgrade` never had. One
run brought it to `9.2.11` (ahead of `px1`), including a ZFS stack bump
(`2.3.4-pve1` → `2.4.4-pve1`) that pulls in new kernel modules — the
existing kernel modules keep running until a reboot, harmless here since
this host doesn't actually use ZFS for any of its storage (root is LVM,
other storage is plain `dir`), but worth a reboot at a convenient time
to fully settle the new module set.
