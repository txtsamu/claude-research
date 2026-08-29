---
type: how-to
tags: [netbird, podman, quadlet, wireguard, traefik, vpn, self-hosted, mesh, exit-node, acme, kubernetes]
created: 2026-08-30
last_verified: 2026-08-30
status: current
---

# Self-hosted NetBird via rootful Podman Quadlets, with a WireGuard exit node

## Why NetBird instead of raw WireGuard/OpenVPN

Direct site-to-site WireGuard from the MikroTik to a VPS worked against one
VPS and failed against another, and OpenVPN direct hit active ISP MITM
before being routed around via a Cloudflare WARP relay (full story in
[mikrotik-openvpn-warp-relay-bypass-isp-udp-block.md](mikrotik-openvpn-warp-relay-bypass-isp-udp-block.md)).
Both of those are single static tunnels — brittle against a double-NAT home
connection and offering nothing for enrolling more than one or two peers.

NetBird replaces that with a managed mesh: ICE/STUN-based NAT traversal with
automatic relay fallback, a real peer/policy/route model, and a dashboard —
while still ultimately running plain kernel WireGuard underneath
(interface `wt0`). Self-hosting it (rather than using NetBird's cloud SaaS)
keeps everything on infrastructure already controlled, and doubles as a
managed drop-in replacement for the raw `wg0` tunnel that used to run
directly on the VPS (that tunnel has since been decommissioned — see
[Update below](#update-2026-08-30-old-raw-wireguard-server-decommissioned)
in the OpenVPN doc).

## Architecture

- **`vpz`** (VPS, IDCloudHost, Debian 13) — runs the NetBird server
  (management + signal + relay, unified single binary/image) *and* enrolls
  as a mesh peer itself. Also configured as the network's **exit node**
  (advertises `0.0.0.0/0`/`::/0`).
- **`wg-bypass` VM** (Proxmox VM, Debian 13, on the home LAN,
  `192.168.50.57`) — a mesh peer. Kernel WireGuard interface `wt0`,
  MTU 1280 (NetBird's default, conservative for relay-compatibility).
- **Phone** — enrolled as a third peer via the official NetBird mobile app,
  for remote access.

All three currently sit in NetBird's single default `All` group under one
default accept-all policy — fine for a handful of trusted personal devices;
would need real group/policy segmentation before adding anything less
trusted.

## Prerequisites

- A VPS (or any box) with a public IP and root/sudo access.
- A subdomain pointed at it. Used `vpn.<PERSONAL_DOMAIN>` here.
- rootful Podman + `podman-docker`/`podman-compose` compatibility shims —
  only needed transiently, to let NetBird's official Docker-oriented
  installer script generate a correct default config, which then gets
  hand-translated into native Quadlets (this repo doesn't use Docker or
  docker-compose in the final deployment).

## Step 1 — DNS

In the DNS dashboard (Cloudflare, in this case): add an `A` record,
name `vpn`, content = the VPS's public IP, **proxy status = DNS only**
(grey cloud, not orange). Must not be proxied — Traefik terminates TLS
itself via ACME TLS-ALPN-01, and NetBird's own relay/signal traffic rides
the same hostname on raw TCP/443, neither of which works behind Cloudflare's
proxy without extra configuration this deployment doesn't use.

## Step 2 — bootstrap config with NetBird's official installer

Ran the upstream `getting-started.sh` installer once (embedded-IdP variant,
not the Zitadel one — no external IdP needed for a handful of personal
devices) under the `podman-docker`/`podman-compose` shim, purely to get a
correct `docker-compose.yml` + `config.yaml` + `dashboard.env` +
nginx config with all the right defaults, secrets, and API wiring. Then
stopped that compose stack entirely and hand-ported the pieces into native
Quadlets below — faster and less error-prone than deriving NetBird's full
config schema from scratch, without actually running anything under Docker
long-term.

## Step 3 — Podman Quadlets

All files live in `/etc/containers/systemd/` on the VPS (root-owned,
rootful Podman). Quadlet auto-generates and wires up the matching
`<name>.service` unit on `systemctl daemon-reload` — the `[Install]` block
inside the `.container`/`.volume` file itself controls boot-start; there is
no separate `systemctl enable` step for Quadlet-generated units.

**`Network=host` (no bridge) throughout, by design** — chosen explicitly
over the more common per-container-network + published-ports setup. Traefik
listens on host `:80`/`:443` directly, and the backend containers bind their
own ports on `127.0.0.1` directly on the host.

### `netbird-data.volume` / `netbird-letsencrypt.volume`

Plain named volumes, nothing container-specific:
```ini
[Unit]
Description=NetBird server data (sqlite DB, keys)

[Volume]
```
(same shape for `netbird-letsencrypt.volume`, description changed to
"Traefik Let's Encrypt certificate storage")

### `netbird-traefik.container`

```ini
[Unit]
Description=NetBird - Traefik reverse proxy (ACME TLS)
After=network-online.target
Wants=network-online.target

[Container]
Image=docker.io/library/traefik:v3.6
ContainerName=netbird-traefik
Network=host
Volume=/run/podman/podman.sock:/var/run/docker.sock:ro
Volume=netbird-letsencrypt.volume:/letsencrypt

Exec=--log.level=INFO \
     --accesslog=true \
     --providers.docker=true \
     --providers.docker.exposedbydefault=false \
     --providers.docker.endpoint=unix:///var/run/docker.sock \
     --entrypoints.web.address=:80 \
     --entrypoints.websecure.address=:443 \
     --entrypoints.websecure.allowACMEByPass=true \
     --entrypoints.websecure.transport.respondingTimeouts.readTimeout=0 \
     --entrypoints.websecure.transport.respondingTimeouts.writeTimeout=0 \
     --entrypoints.websecure.transport.respondingTimeouts.idleTimeout=0 \
     --entrypoints.web.http.redirections.entrypoint.to=websecure \
     --entrypoints.web.http.redirections.entrypoint.scheme=https \
     --certificatesresolvers.letsencrypt.acme.email=<ACME_EMAIL> \
     --certificatesresolvers.letsencrypt.acme.storage=/letsencrypt/acme.json \
     --certificatesresolvers.letsencrypt.acme.tlschallenge=true \
     --serverstransport.forwardingtimeouts.responseheadertimeout=0s \
     --serverstransport.forwardingtimeouts.idleconntimeout=0s

[Service]
Restart=always

[Install]
WantedBy=multi-user.target
```

The `/run/podman/podman.sock` → `/var/run/docker.sock` mount is what lets
Traefik's stock **Docker** provider drive label-based routing on top of a
real **Podman** engine — Podman's socket is Docker-API-compatible, no
Traefik config changes needed beyond pointing at the right socket path.

The zeroed-out response/write/idle timeouts on `websecure` matter
specifically for NetBird's relay/signal traffic, which holds long-lived
streaming connections through Traefik — the default finite timeouts would
periodically kill those.

### `netbird-server.container`

```ini
[Unit]
Description=NetBird - combined server (Management + Signal + Relay + STUN)
After=network-online.target netbird-traefik.service

[Container]
Image=docker.io/netbirdio/netbird-server:latest
ContainerName=netbird-server
Network=host
# STUN (3478/udp), management/API, and metrics all bind directly on the host
# via listenAddress/stunPorts in config.yaml - no port publishing needed.
Volume=netbird-data.volume:/var/lib/netbird
Volume=/etc/netbird/config.yaml:/etc/netbird/config.yaml:ro
Exec=--config /etc/netbird/config.yaml

Label=traefik.enable=true
Label="traefik.http.routers.netbird-grpc.rule=Host(`vpn.<PERSONAL_DOMAIN>`) && (PathPrefix(`/signalexchange.SignalExchange/`) || PathPrefix(`/management.ManagementService/`) || PathPrefix(`/management.ProxyService/`))"
Label=traefik.http.routers.netbird-grpc.entrypoints=websecure
Label=traefik.http.routers.netbird-grpc.tls=true
Label=traefik.http.routers.netbird-grpc.tls.certresolver=letsencrypt
Label=traefik.http.routers.netbird-grpc.service=netbird-server-h2c
Label=traefik.http.routers.netbird-grpc.priority=100
Label="traefik.http.routers.netbird-backend.rule=Host(`vpn.<PERSONAL_DOMAIN>`) && (PathPrefix(`/relay`) || PathPrefix(`/ws-proxy/`) || PathPrefix(`/api`) || PathPrefix(`/oauth2`))"
Label=traefik.http.routers.netbird-backend.entrypoints=websecure
Label=traefik.http.routers.netbird-backend.tls=true
Label=traefik.http.routers.netbird-backend.tls.certresolver=letsencrypt
Label=traefik.http.routers.netbird-backend.service=netbird-server
Label=traefik.http.routers.netbird-backend.priority=100
Label=traefik.http.services.netbird-server.loadbalancer.server.url=http://127.0.0.1:8081
Label=traefik.http.services.netbird-server-h2c.loadbalancer.server.url=h2c://127.0.0.1:8081

[Service]
Restart=always

[Install]
WantedBy=multi-user.target
```

Two separate routers because the gRPC endpoints (management/signal) need
HTTP/2 cleartext (`h2c://`) to the backend while the REST API/relay/OAuth
endpoints are plain HTTP/1.1 — same container, same port, two Traefik
service definitions pointing at it with different backend protocols.

**Gotcha — Quadlet `Label=` truncates at the first space.** Quadlet passes
`Label=` values through systemd's unit-file tokenizer, which is
whitespace-delimited — an unquoted label containing a Traefik rule (which
has spaces around `&&`/`||`) silently truncates at the first space, and
Traefik never sees the full routing rule. Fix: wrap the entire `key=value`
string in double quotes, as shown on the two multi-clause rules above.
Confirmed by inspecting the actual label systemd generated
(`podman inspect netbird-server`) and cross-checking against Traefik's own
`/api/http/routers` endpoint, temporarily exposed via
`--api.insecure=true` + a spare `--entrypoints.traefik.address=:8082`
(removed again once confirmed fixed — don't leave the insecure API
exposed).

**Gotcha — host-network containers don't auto-register an IP with
Traefik's Docker provider.** With `Network=host`, Traefik's usual
"detect the container's own IP" auto-discovery has nothing to detect (no
container-private IP exists). Every host-network service needs an explicit
`traefik.http.services.<name>.loadbalancer.server.url=` label pointing at
`127.0.0.1:<port>` instead.

### `netbird-dashboard.container`

```ini
[Unit]
Description=NetBird - UI dashboard
After=network-online.target netbird-traefik.service

[Container]
Image=docker.io/netbirdio/dashboard:latest
ContainerName=netbird-dashboard
Network=host
EnvironmentFile=/etc/netbird/dashboard.env
Volume=/etc/netbird/dashboard-nginx.conf:/etc/nginx/http.d/default.conf:ro

Label=traefik.enable=true
Label=traefik.http.routers.netbird-dashboard.rule=Host(`vpn.<PERSONAL_DOMAIN>`)
Label=traefik.http.routers.netbird-dashboard.entrypoints=websecure
Label=traefik.http.routers.netbird-dashboard.tls=true
Label=traefik.http.routers.netbird-dashboard.tls.certresolver=letsencrypt
Label=traefik.http.routers.netbird-dashboard.service=dashboard
Label=traefik.http.routers.netbird-dashboard.priority=1
Label=traefik.http.services.dashboard.loadbalancer.server.url=http://127.0.0.1:8080

[Service]
Restart=always

[Install]
WantedBy=multi-user.target
```

Lower `priority` than the server's routers (`1` vs `100`) so the more
specific API/gRPC path rules win on the same hostname, and everything else
falls through to the dashboard SPA.

### `/etc/netbird/config.yaml`

```yaml
server:
  listenAddress: ":8081"
  exposedAddress: "https://vpn.<PERSONAL_DOMAIN>:443"
  stunPorts:
    - 3478
  metricsPort: 9090
  healthcheckAddress: ":9000"
  logLevel: "info"
  logFile: "console"

  authSecret: "<REDACTED - random, generated by installer>"
  dataDir: "/var/lib/netbird"

  auth:
    issuer: "https://vpn.<PERSONAL_DOMAIN>/oauth2"
    signKeyRefreshEnabled: true
    sessionCookieEncryptionKey: "<REDACTED - random, generated by installer>"
    dashboardRedirectURIs:
      - "https://vpn.<PERSONAL_DOMAIN>/nb-auth"
      - "https://vpn.<PERSONAL_DOMAIN>/nb-silent-auth"
    cliRedirectURIs:
      - "http://localhost:53000/"

  reverseProxy:
    trustedHTTPProxies:
      - "127.0.0.1/32"

  store:
    engine: "sqlite"
    encryptionKey: "<REDACTED - random, generated by installer>"
```

All three secrets were randomly generated by the installer script itself —
no need to hand-pick anything here, just don't lose them (they live in
`/etc/netbird/config.yaml` on the VPS, outside this repo).

### `/etc/netbird/dashboard.env`

```ini
NETBIRD_MGMT_API_ENDPOINT=https://vpn.<PERSONAL_DOMAIN>
NETBIRD_MGMT_GRPC_API_ENDPOINT=https://vpn.<PERSONAL_DOMAIN>
AUTH_AUDIENCE=netbird-dashboard
AUTH_CLIENT_ID=netbird-dashboard
AUTH_CLIENT_SECRET=
AUTH_AUTHORITY=https://vpn.<PERSONAL_DOMAIN>/oauth2
USE_AUTH0=false
AUTH_SUPPORTED_SCOPES=openid profile email groups
AUTH_REDIRECT_URI=/nb-auth
AUTH_SILENT_REDIRECT_URI=/nb-silent-auth
NGINX_SSL_PORT=443
LETSENCRYPT_DOMAIN=none
```

`AUTH_CLIENT_SECRET` empty is correct — the embedded IdP uses PKCE, no
client secret needed for the dashboard's own OIDC flow.

### `/etc/netbird/dashboard-nginx.conf`

Mostly the dashboard image's stock nginx config (security headers, a long
CSP allowlist for the various analytics/CDN domains the upstream dashboard
optionally talks to, WASM MIME type handling) — the one deliberate change
from the shipped default is the listen port, **`80` → `8080`**, since `80`
is already claimed by Traefik on the shared host network.

## Step 4 — bring it up

```bash
sudo systemctl daemon-reload
sudo systemctl start netbird-traefik netbird-server netbird-dashboard
```

Verify: `podman ps` shows all three `Up`; `https://vpn.<PERSONAL_DOMAIN>/`
serves the dashboard over a valid Let's Encrypt cert; dashboard login (OIDC
against the embedded IdP) succeeds.

## Step 5 — enroll peers

Setup key created once via the dashboard (Team → Setup Keys), reusable
across multiple peers. On each device:

```bash
curl -fsSL https://pkgs.netbird.io/install.sh | sh
sudo netbird up --management-url https://vpn.<PERSONAL_DOMAIN> --setup-key <setup-key>
```

(Phone used the official NetBird mobile app instead, with the same
management URL + setup key entered manually in its enrollment screen.)

Enrolled so far: `vpz` itself, the `wg-bypass` VM, and a phone — three
peers, all in the default `All` group, `netbird status` on each confirms
`Management: Connected` / `Signal: Connected`.

**Gotcha — enrolling the server itself as a peer can transiently break
its own reachability.** The first `netbird up` on `vpz` briefly broke
SSH/HTTPS to the box (recovered via the hosting provider's web console,
`sudo netbird down`). A second attempt right after worked cleanly with
immediate reachability confirmed — root cause not fully pinned down (a
second device's exit-node experiment running at the same moment is one
plausible explanation), but worth doing enrollment of a box you're
`ssh`'d into via its normal path with an out-of-band console open as a
safety net, just in case.

## Step 6 — exit node

Dashboard → **Network Routes** → Add Route:
- Network: `0.0.0.0/0` (add a second route the same way for `::/0` if v6
  matters)
- Routing peer: `vpz`
- Masquerade: on (so egress traffic looks like it's coming from `vpz`,
  not tunneled straight through with the client's original source IP)

The existing default accept-all policy already covers this route for every
peer in the `All` group — no separate policy object needed in a
single-group setup like this one. Same thing via the REST API:

```bash
curl -s https://vpn.<PERSONAL_DOMAIN>/api/routes \
  -H "Authorization: Token <PAT_TOKEN>" -H "Accept: application/json"
```
returns the route object (`network_id: "Exit Node (vpz)"`, `network:
"0.0.0.0/0"`, `masquerade: true`, `peer: <vpz's-peer-id>`).

On any client peer:
```bash
sudo netbird routes list                              # shows available/selected state
sudo netbird routes select "Exit Node (vpz)"           # enable — default route flips to via wt0
sudo netbird routes deselect "Exit Node (vpz)"         # disable — reverts to the normal gateway
```
(`netbird routes select --all=false` does **not** work as a deselect
shortcut — it errors `unknown flag: --all`; use `deselect` with the
explicit network ID instead.)

Verified working: `curl ifconfig.me` from the `wg-bypass` VM returns the
VPS's public IP once selected, and its own real page-load traffic (not just
`ifconfig.me`) succeeds normally through it. Throughput through this exit
node turned out to be bottlenecked by something entirely outside this
setup — see
[netbird-exit-node-throughput-isp-hop-loss.md](netbird-exit-node-throughput-isp-hop-loss.md).

## Current state / where this is headed

- Mesh P2P connectivity between `vpz` and the `wg-bypass` VM: reliable,
  confirmed direct (not relayed) in normal conditions.
- Exit-node routing: functionally correct, but throughput-limited by an
  ISP-internal hop unrelated to this stack (see the linked investigation) —
  currently left **deselected** on the VM (its default state) since
  there's no benefit to leaving it on for that box's own traffic.
- **The original goal of routing the entire home LAN's traffic through this
  setup (household-wide default route via the MikroTik) was abandoned.**
  Repeated partial failures at that scope (see
  [lan-wide-warp-failover-routing-outage.md](lan-wide-warp-failover-routing-outage.md)
  for the WARP-relay-era version of the same class of problem, and two
  separate MikroTik lockouts from mis-scoped test routing rules during this
  buildout) made the risk/benefit case weak for a household-wide change.
  Pivoted instead to narrower, lower-blast-radius uses of the same NetBird
  mesh:
  - Remote peer access (phone, laptop) to the Talos Kubernetes cluster
    (`192.168.50.0/24` on `px1`) — not yet built. Talos is an immutable OS,
    so a NetBird client can't run directly on a cluster node; the plan is
    either a NetBird **network route** (not exit node — a specific-subnet
    route) advertised by a peer that already sits on that LAN (the
    `wg-bypass` VM is the obvious candidate, already enrolled), or an
    in-cluster NetBird pod acting as a routing peer.
  - Selective per-workload egress via `vpz` for specific cluster services
    that need a non-home-IP egress (mirroring the existing pattern where
    `warp-vm`'s WARP-routed SOCKS proxy already serves this role for a
    couple of podman-hosted apps) — not yet built, scoped to specific
    workloads only rather than blanket cluster-wide egress.
