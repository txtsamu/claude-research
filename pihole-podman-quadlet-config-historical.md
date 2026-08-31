---
type: how-to
tags: [pihole, podman, quadlet, dns, ad-blocking, historical]
created: 2026-08-31
last_verified: 2026-08-31
status: historical
---

# Pi-hole on `warp-vm`: final config before decommission (historical reference)

Pi-hole ran as the household's primary DNS server on `warp-vm`
(192.168.50.200) for months, as a rootful Podman Quadlet deployment.
**Decommissioned 2026-08-31** in favor of a 3-node Technitium DNS
deployment — see
[technitium-dns-3node-cluster-deployment.md](technitium-dns-3node-cluster-deployment.md)
for why and how. Kept here as a reference in case the config is ever
needed again (e.g. to spin Pi-hole back up, or just to remember what was
running).

The service was **stopped, not deleted**, on `warp-vm` as a rollback
window — check current state before assuming any of this still applies.

## Deployment

Podman Quadlet, `/etc/containers/systemd/`:

`pihole.pod`:
```ini
[Pod]
PodName=pihole
Network=host

[Install]
WantedBy=multi-user.target
```

`pihole.container`:
```ini
[Unit]
Description=PiHole DNS
After=pihole-pod.service network-online.target

[Container]
AutoUpdate=registry
Image=docker.io/pihole/pihole:latest
ContainerName=pihole
Pod=pihole.pod
Volume=pihole-data.volume:/etc/pihole:Z
Volume=pihole-dnsmasq.volume:/etc/dnsmasq.d:Z
Environment=TZ=Asia/Jakarta
Environment=FTLCONF_LOCAL_IPV4=192.168.50.200
Environment=PIHOLE_DNS_=1.1.1.1;8.8.8.8
Environment=DNSMASQ_LISTENING=single
Environment=FTLCONF_dns_listeningMode=BIND
Environment=FTLCONF_dns_interface=eth0
Environment=FTLCONF_webserver_port=8081

[Service]
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`pihole-data.volume` / `pihole-dnsmasq.volume`: plain named volumes, no
special config.

Web console served internally on `127.0.0.1:8081`, reverse-proxied by
Caddy as `pihole.lan` (that Caddy block was removed along with the
Technitium cutover).

**No DHCP role** — the MikroTik router handled DHCP for the whole
network; Pi-hole was DNS-only (`allow-remote-requests: no` was never
relevant here since it only had to answer LAN clients directly assigned to
it via DHCP's DNS-server option).

## DNS config (from `pihole.toml`)

Upstream forwarders — plain UDP, no DoH/DoT:
```
upstreams = [
  "1.1.1.1",
  "1.0.0.1",
]
```

4 active blocklists (same set carried over to Technitium):
```
https://blocklistproject.github.io/Lists/ads.txt
https://blocklistproject.github.io/Lists/redirect.txt
https://raw.githubusercontent.com/ABPindo/indonesianadblockrules/master/subscriptions/abpindo.txt
https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts
```

Custom `.lan` host records (`dns.hosts` array), all → `192.168.50.200`
except `nas.lan` → `192.168.50.10`:
```
jellyfin.lan, nextcloud.lan, immich.lan, vaultwarden.lan, grafana.lan,
uptime.lan, bastion.lan, bookstack.lan, pihole.lan, openwebui.lan,
copyparty.lan, mihon.lan, 9router.lan, rancher.lan, proxmox.lan, nas.lan,
test.<PERSONAL_DOMAIN>
```
Two of these (`vaultwarden.lan`, `9router.lan`) were found to have no
matching Caddy route at all during the pre-migration audit — likely
already-dead entries from services that no longer exist — and were not
carried forward to Technitium.

Editing this config directly with tools like `sed -i` is unsafe: the file
is bind-mounted into the container as a single file, and `sed -i`'s
default rename-swap behavior silently breaks the mount (see the
`sed-i-bind-mount-gotcha` memory note). Always edit via `podman exec` +
`pihole-FTL --config <key> <value>`, or `tee`/`cp` (which write in place)
rather than `sed -i` or `mv`, when touching config files bind-mounted this
way.

## Restoring this setup, if ever needed

1. Confirm nothing else is bound to `192.168.50.200:53` first — Pi-hole
   (FTL) binds that specific address explicitly, which silently takes
   priority over any wildcard (`0.0.0.0:53`) listener already running
   there (this exact interaction is what caused the Technitium migration's
   biggest testing trap — see the "Discovered while wiring this up"
   section of the Technitium doc).
2. `systemctl start pihole.service` — Quadlet units and volumes are
   already in place, nothing to redeploy.
3. Re-point MikroTik's DHCP DNS list and the router's own `/ip dns
   servers` back if a full rollback (not just a temporary check) is
   intended.
