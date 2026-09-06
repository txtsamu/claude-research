---
type: troubleshooting
tags: [netbird, reverse-proxy, k3s, kube-router, nftables, cloudflare-tunnel, metallb, vpz, warp-vm]
created: 2026-09-06
last_verified: 2026-09-06
status: current — infra built and one app (nextcloud) verified working end-to-end; rest of the Cloudflare-tunneled apps not yet migrated
---

# NetBird Reverse Proxy as a Cloudflare Tunnel replacement: setup + a real upstream bug

## Goal

Replace the Cloudflare Tunnel fronting the homelab's public apps with NetBird's
built-in Reverse Proxy feature (self-hosted, v0.65+, requires Traefik in front for
TLS passthrough — see the official docs:
[Reverse Proxy](https://docs.netbird.io/manage/reverse-proxy),
[Migration Guide: Enable Reverse Proxy Feature](https://docs.netbird.io/selfhosted/migration/enable-reverse-proxy),
[External Reverse Proxy Setup](https://docs.netbird.io/selfhosted/external-reverse-proxy)).
The self-hosted NetBird stack already runs on `vpz` as rootful Podman quadlets with
Traefik in front — see [[netbird-selfhosted-podman-quadlet-setup]] — so this is
"add one more container + a Traefik dynamic-config file", not a from-scratch
install.

## Infra setup (Podman quadlet, matching the existing style)

Generate a proxy access token from the combined server container:

```bash
sudo podman exec netbird-server /go/bin/netbird-server --config /etc/netbird/config.yaml \
  admin token create --name "netbird-proxy"
```

`/etc/netbird/proxy.env`:

```env
NB_PROXY_DOMAIN=proxy.<PERSONAL_DOMAIN>
NB_PROXY_TOKEN=<REDACTED - nbx_... token from admin token create, shown once>
NB_PROXY_MANAGEMENT_ADDRESS=http://localhost:8081
NB_PROXY_ADDRESS=:9443
NB_PROXY_ACME_CERTIFICATES=true
NB_PROXY_ACME_CHALLENGE_TYPE=tls-alpn-01
NB_PROXY_CERTIFICATE_DIRECTORY=/certs
NB_PROXY_FORWARDED_PROTO=https
NB_PROXY_PROXY_PROTOCOL=true
NB_PROXY_TRUSTED_PROXIES=127.0.0.1/32
NB_PROXY_ALLOW_INSECURE=true
NB_PROXY_HEALTH_ADDRESS=localhost:8090
```

Three things the official docs' generic example doesn't cover, all specific to a
box that already runs other things:

- **`NB_PROXY_ALLOW_INSECURE=true` is required** and easy to miss — without it the
  proxy fails immediately with `create management connection: grpc: the credentials
  require transport level security`, since the management address here is plain
  `http://localhost:8081`, not TLS.
- **Port 8080 conflicts with the netbird-dashboard's own nginx** (it already binds
  host port 8080 for Traefik to reach it) — the proxy's default health-check port
  collides. Moved it via `NB_PROXY_HEALTH_ADDRESS=localhost:8090`.
- **Port 8443 (the docs' example default for `NB_PROXY_ADDRESS`) conflicts with
  Pangolin's remapped HTTPS port** (`gerbil`'s quadlet publishes
  `127.0.0.1:8443:443`, since Pangolin's own Traefik can't have the real 443 —
  NetBird's own Traefik already owns it). Moved the proxy to `:9443` instead, and
  matched that in the Traefik dynamic config below.

`/etc/containers/systemd/netbird-proxy.container`:

```ini
[Unit]
Description=NetBird - Reverse Proxy (exposes internal services publicly)
After=network-online.target netbird-server.service netbird-traefik.service
Requires=netbird-server.service

[Container]
AutoUpdate=registry
Image=docker.io/netbirdio/reverse-proxy:latest
ContainerName=netbird-proxy
Network=host
EnvironmentFile=/etc/netbird/proxy.env
Volume=netbird-proxy-certs.volume:/certs

[Service]
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Traefik dynamic config (`/etc/traefik-dynamic/netbird-proxy.yml` — the existing
Traefik quadlet already watches this directory, so no quadlet edit needed):

```yaml
tcp:
  routers:
    netbird-proxy-passthrough:
      entryPoints: [websecure]
      rule: "HostSNI(`*`) && !HostSNI(`vpn.<PERSONAL_DOMAIN>`)"
      tls: {passthrough: true}
      service: netbird-proxy-tls
      priority: 1
  services:
    netbird-proxy-tls:
      loadBalancer:
        serversTransport: pp-v2
        servers: [{address: "127.0.0.1:9443"}]
  serversTransports:
    pp-v2:
      proxyProtocol: {version: 2}
```

Note `serversTransport`+`serversTransports.proxyProtocol`, not the older
`loadBalancer.proxyProtocol` inline form the netbird docs' docker-compose example
uses — that form is deprecated in current Traefik and logs a warning (still works,
but fix it properly).

**DNS**: `proxy.<PERSONAL_DOMAIN>` A record → vpz's public IP, plus a
`*.proxy.<PERSONAL_DOMAIN>` CNAME to it — both **DNS-only** (grey cloud if using
Cloudflare for the zone), never proxied, since NetBird needs a direct TLS connection
for its own ACME `tls-alpn-01` challenge and TLS passthrough.

## The real bug: NetBird's forward-filter ACL gets clobbered by kube-router

With everything above running and a Reverse-Proxy Service configured (subdomain →
NetBird Network resource covering `192.168.50.0/24`, routed via `warp` as the
NetBird routing peer, `warp` also being the k3s node), traffic through the proxy
consistently hung / timed out reaching the backend (a k3s Service's MetalLB VIP),
even though:

- The NetBird Network resource + routing peer + Access Control policy were all
  correctly configured (verified via dashboard — default "All → All, all
  ports/protocols" policy already present).
- `vpz`'s own routing was fine — NetBird uses a **separate policy-routing table**
  for split-tunnel routes (`ip route show table all`, not the default `main` table;
  `ip rule show` shows an `fwmark`-based rule pointing non-default traffic at it).
  Checking only the main table here is a red herring worth knowing about up front.
- A direct `tcpdump -i wt0 host <VIP>` on warp during a test showed the SYN packets
  **arriving cleanly** from vpz, repeatedly (standard retransmit backoff) — proving
  the tunnel/routing-peer path itself was fine.
- kube-proxy's own DNAT chain (`KUBE-EXT-*` → `KUBE-SVC-*` → `KUBE-SEP-*` → the
  actual `DNAT to:<pod-ip>:<port>` rule) showed matching packet counters incrementing
  on every test — so the VIP→pod-IP translation *was* happening.
- Yet **zero bytes ever reached `cni0`** (checked via `tcpdump -i cni0`) — the
  packet died somewhere between DNAT being applied and actual delivery to the pod.

### Root cause: a mark-bit collision, confirmed as [upstream issue #6022](https://github.com/netbirdio/netbird/issues/6022)

`sudo nft list ruleset` revealed NetBird's own nftables ACL enforcement, separate
from anything iptables/kube-proxy-related:

```
chain netbird-acl-forward-filter {
    type filter hook forward priority filter; policy accept;
    meta mark 0x0001bd20 accept
    iifname "wt0" jump netbird-rt-fwd
    iifname "wt0" drop
}
```

NetBird marks authorized forwarded traffic with `meta mark 0x0001bd20` (bit
`0x10000` = "NetBird says this is fine"). **kube-router's per-pod NetworkPolicy
enforcement chain uses that exact same bit** as its own "policy-permitted" flag, and
unconditionally clears-and-replaces it at the end of every per-pod evaluation
(`MARK and 0xfffeffff` then `MARK or 0x20000`) — regardless of whether kube-router
itself decided to *allow* the packet. So by the time the packet reaches NetBird's own
forward-filter, the mark has silently become `0x0002bd20` instead of `0x0001bd20`,
NetBird's `meta mark` rule no longer matches, and the packet falls through to the
explicit `iifname "wt0" drop` catch-all — dropped by NetBird's *own* firewall, after
having already been legitimately authorized and DNAT'd by Kubernetes.

This is a generic collision class: "any environment combining NetBird with another
netfilter consumer that reuses/clears bits on the per-packet mark" (kube-router,
Calico/Felix, kube-proxy's own `KUBE-MARK-MASQ`, fwmark policy-routing daemons,
etc.) — not specific to this exact setup, per the upstream issue discussion. The
recommended real fix upstream is for NetBird to key off connection-tracking mark
(`ct mark`, set once per connection, immune to other components' per-packet `meta
mark` mutations) instead of `meta mark`.

### Workaround applied (local, not an upstream fix)

Insert an explicit accept for wt0-sourced traffic bound for the pod CIDR, ahead of
NetBird's catch-all drop — safe because kube-router's own per-pod NetworkPolicy
chain *already ran and decided to allow* this exact packet; this only corrects for
the mark being clobbered afterward, it doesn't bypass any actual policy decision:

```bash
sudo nft insert rule ip netbird netbird-acl-forward-filter iifname "wt0" ip daddr 10.42.0.0/16 accept
```

**Not persistent** — NetBird dynamically rebuilds its own `ip netbird` table on
every daemon (re)start/reconnect, wiping manual inserts. Made it durable via a
systemd drop-in (an `ExecStartPost=` hook is the only reliable way to run something
on *every* start of a vendor-managed unit — a separate `BindsTo=`/`After=` unit does
**not** auto-trigger on the target's start, only on its stop, learned the hard way):

`/usr/local/sbin/netbird-k8s-fwd-fix.sh`:
```sh
#!/bin/sh
for i in $(seq 1 30); do
  nft list chain ip netbird netbird-acl-forward-filter >/dev/null 2>&1 && break
  sleep 1
done
nft list chain ip netbird netbird-acl-forward-filter 2>/dev/null | grep -q "10.42.0.0/16" && exit 0
nft insert rule ip netbird netbird-acl-forward-filter iifname "wt0" ip daddr 10.42.0.0/16 accept
```

`/etc/systemd/system/netbird.service.d/k8s-fwd-fix.conf`:
```ini
[Service]
ExecStartPost=/usr/local/sbin/netbird-k8s-fwd-fix.sh
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart netbird.service   # verify the rule reappears afterward
```

Adjust `10.42.0.0/16` to whatever the cluster's actual pod CIDR is (k3s/flannel
default shown here).

## Second issue after the network-level fix: app-level Host header

Once packets reached the pod, Nextcloud rejected with "Access through untrusted
domain" — its `trusted_domains` check saw a Host header it didn't recognize. Two
separate things needed fixing, not just one:

1. Nextcloud's own allowlist:
   ```bash
   kubectl -n homelab exec deploy/nextcloud -c app -- \
     php occ config:system:set trusted_domains 2 --value=<subdomain>.proxy.<PERSONAL_DOMAIN>
   ```
   Needed a pod restart afterward to pick up the change cleanly (opcache/config
   caching in the running Apache/PHP process didn't reload it live).

2. **The Reverse-Proxy Service's own "Pass Host Header" setting** (Service → Advanced
   Settings tab) — off by default, which means NetBird rewrites the Host header to
   the backend's own address before forwarding, so step 1's allowlist entry never
   actually matched what the backend saw. Enabling it forwards the original public
   Host header through, matching what was just added to `trusted_domains`.

## Side effects encountered while debugging (both self-resolved)

- Restarting `netbird.service` on vpz (twice, while testing the workaround's
  persistence) briefly broke a third, unrelated machine's ("fedora") ability to SSH
  to vpz directly. Turned out that machine uses **vpz as a full-tunnel NetBird Exit
  Node** (`0.0.0.0/0` + `::/0` routed through it) — restarting vpz's tunnel flapped
  that machine's entire default route, and since the SSH target (vpz's own public
  IP) was itself being reached *through* the tunnel that terminates at vpz, this was
  a brief circular-dependency outage. Self-resolved once vpz's tunnel restabilized;
  going through a different peer (not depending on vpz's own tunnel) worked the
  whole time. **Lesson: restarting a box's NetBird service that other peers use as
  an Exit Node has a wider blast radius than "just that box".**
- Separately, that same machine's own NetBird client had independently gone through
  a clean auto-update-triggered shutdown (`new version available` in its log,
  `0.77.1` → newer) and gotten stuck fully disconnected rather than reconnecting on
  its own. Fixed with a plain `systemctl restart netbird.service` on that machine.

## Verification

```bash
curl -kv -H "Host: <subdomain>.proxy.<PERSONAL_DOMAIN>" http://<metallb-vip>/
```
run from vpz, bypassing the NetBird PIN/auth gate to isolate network-layer success —
confirmed a real, fast (sub-100ms) HTTP response from the actual backend once both
fixes above were in place, vs. the prior 10-15s hard timeout.

## Status / next steps

Only one app (`nextcloud`, via `cloud.proxy.<PERSONAL_DOMAIN>`) has been fully
verified end-to-end through the real Reverse-Proxy Service + PIN auth flow. The
Cloudflare Tunnel has **not** been touched/retired yet — it's still the live public
path for everything else. Remaining work: repeat the Service-creation step
(dashboard) for each of the other ~18 tunneled apps, pointing at the same
`192.168.50.0/24` subnet resource, enabling "Pass Host Header" from the start this
time, then retire the Cloudflare tunnel hostnames once each is confirmed.
