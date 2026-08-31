---
type: how-to
tags: [technitium, dns, podman, quadlet, mikrotik, caddy, talos, pihole-migration, ad-blocking, ha]
created: 2026-08-31
last_verified: 2026-08-31
status: current
---

# Migrating from Pi-hole to a 3-node Technitium DNS deployment

Replaced a single-point-of-failure Pi-hole (on `warp-vm`) with three
independent [Technitium DNS Server](https://technitium.com/dns/) v15.4.0
instances — `warp-vm`, `arm3`, `arm1` — so `.lan` resolution and ad-blocking
survive any one of those hosts going down.

## Why Technitium, and why 3 independent nodes instead of its Clustering feature

Technitium is a full self-contained recursive+authoritative DNS server
(web console, DoH/DoT/DNSSEC, blocklists) rather than a filter-in-front-of-
another-resolver like Pi-hole+dnsmasq. It ships official multi-arch Docker
images (`amd64`, `arm64`, `arm/v7`) at ~100MB, comfortably light enough for
Raspberry Pi Zero 2W-class hardware, so an ARM SBC board is a fine host for
it.

Technitium v14 (Nov 2025) added a native **Clustering** feature — one
primary node, N secondaries, config/zone auto-sync via a special
`cluster-catalog` zone. **It does not work reliably as of v15.4.0** — see
the "Clustering bug" section below. After losing real time to it, the
deployment instead runs **three fully independent Technitium instances**
with identical manually-applied config (same records, same blocklists, same
settings). The trade-off: future `.lan` record changes must be pushed to
all three nodes individually rather than syncing automatically.

## Architecture

| Node | IP | Role |
|---|---|---|
| `warp-vm` | 192.168.50.200 | Primary reference node, also runs Caddy (reverse-proxies all `.lan` HTTPS sites) |
| `arm3` | 192.168.50.42 | ARM SBC, independent instance |
| `arm1` | 192.168.50.40 | ARM SBC, independent instance |

Two other ARM boards were tried and rejected for this deployment:
- `arm4` (192.168.50.43): Technitium bound port 53 cleanly but never
  answered *any* query, even locally via `127.0.0.1`, even after clean
  restarts. Same host had shown an unrelated, unexplained
  `systemd-resolved` stub-listener hang earlier the same day. Root cause
  not found — treated as a pre-existing host-level anomaly and excluded.
  Service stopped/disabled there (`systemctl disable technitium.service`).
- `arm2` (192.168.50.41): Technitium bound `[::]:53` only, then dropped to
  no listener at all after an endpoint-setting change. This host already
  runs a Cloudflare WARP client (`warp-svc`) bound to `127.0.2.2`/
  `127.0.2.3:53` — suspected interference, not confirmed. Also excluded;
  service stopped/disabled.

## Deployment: Podman Quadlet (per node)

Same rootful-Podman-Quadlet pattern used elsewhere in this homelab.

`/etc/containers/systemd/technitium-data.volume`:
```ini
[Volume]
```

`/etc/containers/systemd/technitium.container`:
```ini
[Unit]
Description=Technitium DNS Server
After=network-online.target

[Container]
AutoUpdate=registry
Image=docker.io/technitium/dns-server:15.4.0
ContainerName=technitium-dns
Network=host
Volume=technitium-data.volume:/etc/dns:Z
Environment=DNS_SERVER_DOMAIN=<node-label, e.g. dns-warp-vm>
Environment=DNS_SERVER_ADMIN_PASSWORD=<TECHNITIUM_ADMIN_PASSWORD>
Environment=DNS_SERVER_RECURSION=AllowOnlyForPrivateNetworks

[Service]
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl start technitium.service   # NOT `enable` — see gotcha below
```

`Network=host` is required — the DNS ports need to bind directly on the
host's LAN-facing IP, not a container-NAT'd address.

### Gotcha 1: `systemctl enable` fails on a fresh Quadlet unit

```
Failed to enable unit: Unit /run/systemd/generator/technitium.service is transient or generated
```
Harmless — the `[Install]` block in the `.container` file is already
handled by the Quadlet generator. Just `systemctl start`; no separate
`enable` step needed (or possible).

### Gotcha 2: env-var bootstrap config doesn't fully activate the DNS listener

On a couple of nodes, `ss -tulnp` after a fresh env-var-bootstrapped start
showed **no listener on port 53 at all**, despite `Environment=` variables
being correctly written into the config and the service reporting "started
successfully" with no errors. Re-applying the exact same value via the
Settings API (`/api/settings/set?dnsServerLocalEndPoints=0.0.0.0:53,[::]:53`)
immediately triggered a proper bind. Cause not confirmed — looks like the
first-boot env-var config write doesn't always trigger the listener-start
codepath the way an explicit settings save does. **After first boot,
always touch `/api/settings/set` once (even with existing values) and
verify `ss -tulnp | grep :53` before trusting a fresh node.**

## Docker environment variables reference

Full list: `DockerEnvironmentVariables.md` in the
[TechnitiumSoftware/DnsServer](https://github.com/TechnitiumSoftware/DnsServer)
repo. The ones used here:

| Variable | Value used | Notes |
|---|---|---|
| `DNS_SERVER_DOMAIN` | per-node label | only affects self-identification, not required to be a real domain |
| `DNS_SERVER_ADMIN_PASSWORD` | generated, then changed | only read on first boot when no config exists yet |
| `DNS_SERVER_RECURSION` | `AllowOnlyForPrivateNetworks` | prevents the node becoming an open resolver |

## Configuration, via the HTTP API (port 5380, plain HTTP — 5380 is *not* TLS)

Login:
```bash
curl -s "http://<node-ip>:5380/api/user/login?user=admin&pass=<pw>" \
  | jq -r .token
```
All subsequent calls: `-H "Authorization: Bearer <token>"`.

### Forwarders + blocklists (applied identically to all 3 nodes)
```bash
curl -s -H "Authorization: Bearer $TOK" -G \
  "http://<ip>:5380/api/settings/set" \
  --data-urlencode "forwarders=1.1.1.1,1.0.0.1" \
  --data-urlencode "forwarderProtocol=Udp" \
  --data-urlencode "allowRecursion=true" \
  --data-urlencode "allowRecursionOnlyForPrivateNetworks=true" \
  --data-urlencode "blockListUrls=https://blocklistproject.github.io/Lists/ads.txt,https://blocklistproject.github.io/Lists/redirect.txt,https://raw.githubusercontent.com/ABPindo/indonesianadblockrules/master/subscriptions/abpindo.txt,https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts" \
  --data-urlencode "blockListUpdateIntervalHours=24" \
  --data-urlencode "blockingType=AnyAddress"
```
`blockListUpdateIntervalHours=24` = daily auto-refresh of all 4 lists.
`blockingType=AnyAddress` returns `0.0.0.0`/`::` for a blocked domain
(matches prior Pi-hole convention); the alternative `NxDomain` is also
valid, just a different response style — both actually block the request.
Confirmed live: `dig doubleclick.net` returns an `EDE 15 (Blocked)` extended
error citing the exact matching blocklist URL, and the Dashboard API
(`/api/dashboard/stats/get?type=lastHour`) reports `blockListZones: 397186`
domains loaded from the 4 lists combined.

### The `lan` zone (created independently, identically, on each node)
```bash
curl -s -H "Authorization: Bearer $TOK" -G "http://<ip>:5380/api/zones/create" \
  --data-urlencode "zone=lan" --data-urlencode "type=Primary"

curl -s -H "Authorization: Bearer $TOK" -G "http://<ip>:5380/api/zones/records/add" \
  --data-urlencode "domain=jellyfin.lan" --data-urlencode "zone=lan" \
  --data-urlencode "type=A" --data-urlencode "ipAddress=192.168.50.200"
# ... repeated per record
```
Records carried over 1:1 from the old Pi-hole `dns.hosts` list (all →
`192.168.50.200` except `nas.lan` → `192.168.50.10`): `jellyfin`,
`nextcloud`, `immich`, `grafana`, `uptime`, `bastion`, `bookstack`,
`openwebui`, `copyparty`, `mihon`, `rancher`, `proxmox`, `dns` (Technitium's
own dashboard, added after cutover — see below), `nas`. `pihole.lan` was
removed post-decommission. Two genuinely dead entries (`vaultwarden.lan`,
`9router.lan` — DNS existed but no Caddy route at all) were dropped during
the pre-migration audit, not carried over.

A separate narrow zone was created for one non-`.lan` host record from the
old Pi-hole config, to avoid the internal zone shadowing the rest of the
real public domain:
```bash
curl -s -H "Authorization: Bearer $TOK" -G "http://<ip>:5380/api/zones/create" \
  --data-urlencode "zone=test.<PERSONAL_DOMAIN>" --data-urlencode "type=Primary"
```

### Changing the admin password
```bash
curl -s -H "Authorization: Bearer $TOK" -G \
  "http://<ip>:5380/api/user/changePassword" \
  --data-urlencode "pass=<old>" --data-urlencode "newPass=<new>"
```
Real password not reproduced here — see the credential normally shared
out-of-band, same convention as other services in this repo.

## The Clustering bug (why native sync was abandoned)

Traced end-to-end before giving up on it — documented in case a future
Technitium version is worth retrying:

1. `POST /api/admin/cluster/init` on the primary, `POST
   /api/admin/cluster/initJoin` on each secondary (with
   `ignoreCertificateErrors=true` — required, join uses a self-signed
   cert). Join succeeds; `configLastSynced` gets an initial timestamp.
2. The `cluster-catalog.<cluster-domain>` zone on secondaries shows
   `"syncFailed": true, "soaSerial": 0` immediately and permanently, even
   after manual `resync`.
3. First real clue: any ongoing (post-join) call to the primary's
   registered hostname URL (`https://<node>.<cluster-domain>:53443/`) —
   e.g. `Leave Cluster` — fails with
   `RemoteCertificateNameMismatch, RemoteCertificateChainErrors`. The
   `ignoreCertificateErrors=true` override from the join handshake is
   **not persisted** for any subsequent inter-node call.
4. Root cause of the mismatch: Technitium's self-signed cert is generated
   from the container's OS-level hostname at first boot (`CN=dns-warp-vm`),
   but cluster-init later renames the node's registered identity to
   `<label>.<cluster-domain>` (`dns-warp-vm.dnscluster.internal`) —
   permanent mismatch. Regenerating the cert (delete
   `/etc/dns/self-signed-cert.pfx` + restart) doesn't help — it just
   regenerates from the OS hostname again (`CN=warp-vm`), still wrong.
   Fix attempted: hand-generated a proper cert per node
   (`openssl req -x509 ... -addext "subjectAltName=DNS:<name>,IP:<ip>"`),
   installed via `webServiceTlsCertificatePath`. This fixed the TLS
   handshake itself (`RemoteCertificateNameMismatch` → resolved) but **not**
   the underlying sync.
5. Deeper cause: `Get Cluster State` on a secondary shows the primary as
   `"state": "Unreachable"` permanently — because the cluster's own
   hostname-based node addressing is circular: resolving
   `dns-warp-vm.<cluster-domain>` requires querying the very
   `<cluster-domain>` zone that lives *only* on the primary, and that
   zone's own glue `A` record for its own name returns **NXDOMAIN even
   though the record demonstrably exists** (confirmed via the zone-records
   API while the live `dig` query against the same server for the same
   name returns NXDOMAIN). This looks like a genuine bug in how Technitium
   v15.4.0 serves its own auto-generated, DNSSEC-signed
   (`SignedWithNSEC`), delete-protected "Cluster Primary zone" — it could
   not be unsigned to rule out a DNSSEC/NSEC-chain inconsistency
   (`Cannot unsign the Cluster Primary zone` — API refuses).

Given the heartbeat, config-sync, *and* catalog zone-transfer channels all
ultimately depend on this broken self-resolution, clustering was abandoned
cluster-wide (`cluster.config` deleted directly from each node's `/etc/dns`
volume + service restart resets a node to standalone) in favor of the
three-independent-instances model described above.

## Discovered while wiring this up: Pi-hole's specific-IP bind was masking Technitium

**Important trap, worth re-reading if this is ever repeated.** Pi-hole
(FTL) on `warp-vm` binds `192.168.50.200:53` explicitly; Technitium (via
`Network=host`) binds the wildcard `0.0.0.0:53`. On Linux, a
specific-address bind takes priority over a wildcard bind for traffic to
that exact address — so with both services running, **every `dig
@192.168.50.200` query was still answered by Pi-hole**, the whole time
Technitium was being built out and "verified" on that host. The two
processes silently coexist rather than erroring on a port conflict, which
is what made this easy to miss.

Caught by adding a record that existed *only* in Technitium's zone and
observing it didn't resolve via `192.168.50.200` until Pi-hole was
actually stopped:
```bash
# added only to Technitium's API — then:
dig +short technitium-only-test.lan @192.168.50.200   # → empty (Pi-hole answering)
systemctl stop pihole.service
dig +short technitium-only-test.lan @192.168.50.200   # → 10.10.10.10 (Technitium now answering)
```
All API-driven configuration (zones, records, settings, password) was
unaffected by this — those calls go over port 5380, which Pi-hole never
touched. Only the actual DNS-port resolution testing was compromised.
**Lesson: when two DNS daemons might coexist on one host, don't trust
`dig`-based verification without confirming which process actually
answered** (a record unique to the new service is the simplest check).

## Cutover

Ran gradual: stood up and fully verified all 3 nodes with Pi-hole still
live as a fallback, then flipped once confident.

### MikroTik
```
/ip dhcp-server network set [find] dns-server=192.168.50.200,192.168.50.42,192.168.50.40,1.1.1.1,1.0.0.1
/ip dns set servers=192.168.50.200,192.168.50.42,192.168.50.40,1.1.1.1,1.0.0.1
```
The pre-existing `.lan` DoH-bypass static-forward rule (see
`mikrotik-doh-bypasses-local-dns-for-lan-domains.md`) still points at
`192.168.50.200` — unchanged, still valid since that node is part of the
new set.

### Every host's own resolver (not just DHCP-derived — several had static overrides)
Updated to list all 3 nodes + one public fallback, via `nmcli con mod
<conn> ipv4.dns '192.168.50.200,192.168.50.42,192.168.50.40,1.1.1.1'` (Linux
NetworkManager hosts) or a direct `/etc/resolv.conf` rewrite (hosts without
NetworkManager). Two real pre-existing bugs found and fixed along the way,
unrelated to Technitium itself:
- `arm2`, `arm3`, `arm4` were statically pointed at a long-dead Pi-hole
  box (`.50`) via `nmcli ipv4.dns` — a leftover from before that box was
  decommissioned, never cleaned up.
- `px1` (the Proxmox host) had `nameserver 192.168.50.80` (a different,
  also-dead old Pi-hole install) as its *only* local nameserver, with just
  `1.1.1.1` as fallback — meaning it had likely never resolved `.lan` names
  correctly at all until this fix.

### Talos Kubernetes cluster (via `talosctl`/`kubectl` from `warp-vm`)
CoreDNS's `Corefile` forwards `. { forward . /etc/resolv.conf }` — i.e. it
uses whatever the node itself resolves with. So the only change needed was
the node-level `machine.network.nameservers`, not CoreDNS's own config:
```yaml
# dns-patch.yaml
machine:
  network:
    nameservers:
      - 192.168.50.200
      - 192.168.50.42
      - 192.168.50.40
      - 1.1.1.1
```
```bash
export TALOSCONFIG=/home/moo/talos-cluster/talosconfig/talosconfig
for node in 192.168.50.91 192.168.50.92 192.168.50.93 192.168.50.94 192.168.50.95 192.168.50.96; do
  talosctl patch mc --endpoints $node --nodes $node -p @dns-patch.yaml
done
```
Applied live, no reboot required on any of the 6 nodes (3 control-plane +
3 workers). Gotcha: `talosctl patch mc` needs `--endpoints` explicitly —
omitting it (even with a configured context) fails with `error
constructing client: failed to determine endpoints`. `talosctl get
resolvers` afterward showed the new IPs merged alongside the old
DHCP-sourced ones (not a bug — the resource aggregates DHCP-provided and
statically-configured nameservers separately; the old DHCP-sourced entries
clear on the next lease renewal). Verified working with a live in-cluster
`kubectl run --rm -it --image=busybox -- nslookup github.com`.

### Caddy
Added a `dns.lan` site pointing at Technitium's own web console
(`warp-vm`, same host as Caddy):
```caddyfile
dns.lan {
	tls internal
	reverse_proxy 127.0.0.1:5380
}
```
`pihole.lan`'s block (`reverse_proxy 127.0.0.1:8081`) was removed once
Pi-hole was stopped, along with its DNS record on all 3 nodes.

### Pi-hole itself
Stopped (`systemctl stop pihole.service`), **not deleted** — kept as a
rollback window. See `pihole-podman-quadlet-config-historical.md` for its
final config, in case it's ever needed for reference or restore.

## Verification checklist used throughout

```bash
for ip in 192.168.50.200 192.168.50.42 192.168.50.40; do
  dig +short jellyfin.lan @$ip        # .lan record
  dig +short doubleclick.net @$ip     # ad-block → 0.0.0.0
  dig +short github.com @$ip          # normal forwarding
done
# Caddy still routes correctly regardless of which node answered:
curl -sk "https://grafana.lan" --resolve "grafana.lan:443:$(dig +short grafana.lan @<any-node>)"
```
