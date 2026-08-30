---
type: how-to
tags: [pangolin, podman, quadlet, traefik, gerbil, wireguard, acme, letsencrypt, tunnel, self-hosted, vpz]
created: 2026-08-30
last_verified: 2026-08-30
status: current
---

# Pangolin (self-hosted tunnel/reverse-proxy) on vpz, coexisting with an existing Traefik

[Pangolin](https://github.com/fosrl/pangolin) is a self-hosted alternative
to Cloudflare Tunnel — a hub-and-spoke reverse proxy where the VPS is the
hub and private networks (home LAN, etc.) connect outbound as spokes via
WireGuard (`Newt` client / `Gerbil` server component). Deployed on the same
`vpz` box already running self-hosted NetBird (see
[netbird-selfhosted-podman-quadlet-setup.md](netbird-selfhosted-podman-quadlet-setup.md)),
domain `tun.<PERSONAL_DOMAIN>`.

## Prerequisite: the port conflict, and the decision it forces

Pangolin's documented architecture: `Gerbil` (WireGuard controller) owns
ports `80`/`443`/`51820`/`21820` directly, and `Traefik` runs *inside*
Gerbil's network namespace (`network_mode: service:gerbil`) rather than
binding ports itself. If your VPS already runs another Traefik/reverse
proxy bound to `80`/`443` (as this one does, for NetBird), you have two
options:

1. Let Pangolin take over `80`/`443`, migrate the other service to be a
   Pangolin-proxied resource instead.
2. Keep the real `80`/`443` owned by the existing proxy; give Pangolin's
   Gerbil alternate host ports; add routes on the existing proxy that
   forward the Pangolin hostname to those alternate ports.

This doc follows **option 2** throughout — non-disruptive to whatever
already owns `80`/`443`. If you don't have anything else on those ports,
skip straight to Pangolin's own official install script instead of this
doc; none of the workarounds below are needed in that case.

## Step 1 — Pull the real reference files before improvising

Don't trust generic blog posts for the exact port/volume shape — pull
Pangolin's actual files straight from its repo:

```bash
gh api repos/fosrl/pangolin/contents/compose.example.yaml --jq '.content' | base64 -d
gh api repos/fosrl/pangolin/contents/config/config.example.yml --jq '.content' | base64 -d
gh api repos/fosrl/pangolin/contents/config/traefik/traefik_config.yml --jq '.content' | base64 -d
gh api repos/fosrl/pangolin/contents/config/traefik/dynamic_config.yml --jq '.content' | base64 -d
```

The compose reference confirms the real shape:

```yaml
gerbil:
  image: fosrl/gerbil:latest
  command:
    - --reachableAt=http://gerbil:3004
    - --generateAndSaveKeyTo=/var/config/key
    - --remoteConfig=http://pangolin:3001/api/v1/
  cap_add: [NET_ADMIN, SYS_MODULE]
  ports:
    - 51820:51820/udp
    - 21820:21820/udp
    - 443:443   # Port for traefik because of the network_mode
    - 80:80     # Port for traefik because of the network_mode

traefik:
  image: traefik:v3.7
  network_mode: service:gerbil
  command: [--configFile=/etc/traefik/traefik_config.yml]
```

Two things this confirms, both load-bearing for the rest of this doc:
- It's a **bridge network with explicit port publishing**, not host
  networking — the host-side port numbers can be remapped
  (`80:80` → `127.0.0.1:8880:80`) without touching anything inside the
  containers or Pangolin's own static config, since the containers
  themselves still believe they're bound to `80`/`443` internally.
- The ACME **challenge type is `httpChallenge` on the `web` (port 80)
  entrypoint**, not `tlsChallenge` — matters a lot in Step 7.

## Step 2 — DNS

Cloudflare (or your DNS provider): A record, name `tun`, content = your
VPS's public IP, **DNS only** (grey cloud, not proxied). Pangolin
terminates its own TLS and needs to see real client connections directly —
a proxying CDN in front of it breaks both the ACME challenge and (if you
add SNI-passthrough routing per Step 7) the routing itself.

## Step 3 — directories and secrets

```bash
sudo mkdir -p /etc/pangolin/config/traefik /etc/pangolin/config/letsencrypt \
             /etc/pangolin/config/db /etc/pangolin/config/logs
SECRET=$(openssl rand -hex 32)
```

## Step 4 — config.yml

`/etc/pangolin/config/config.yml`:

```yaml
gerbil:
    start_port: 51820
    base_endpoint: "tun.<PERSONAL_DOMAIN>"

app:
    dashboard_url: "https://tun.<PERSONAL_DOMAIN>"
    log_level: "info"
    telemetry:
        anonymous_usage: true

domains:
    domain1:
        base_domain: "tun.<PERSONAL_DOMAIN>"

server:
    secret: "<SECRET generated in Step 3>"
    cors:
        origins: ["https://tun.<PERSONAL_DOMAIN>"]
        methods: ["GET", "POST", "PUT", "DELETE", "PATCH"]
        allowed_headers: ["X-CSRF-Token", "Content-Type"]
        credentials: false

flags:
    require_email_verification: false
    disable_signup_without_invite: true
    disable_user_create_org: false
    allow_raw_resources: true
```

Both `tun.<PERSONAL_DOMAIN>` as the dashboard domain *and* base domain —
resource subdomains land as `<name>.tun.<PERSONAL_DOMAIN>`, a fresh zone
segment. Use a different `base_domain` if you'd rather resources live
under your root domain directly.

## Step 5 — traefik_config.yml and dynamic_config.yml

`/etc/pangolin/config/traefik/traefik_config.yml` — stock upstream content,
domain/email filled in:

```yaml
api:
  insecure: true
  dashboard: true
providers:
  http:
    endpoint: http://pangolin:3001/api/v1/traefik-config
    pollInterval: 5s
  file:
    filename: /etc/traefik/dynamic_config.yml
experimental:
  plugins:
    badger:
      moduleName: github.com/fosrl/badger
      version: v1.4.1
log:
  level: INFO
  format: common
  maxSize: 100
  maxBackups: 3
  maxAge: 3
  compress: true
certificatesResolvers:
  letsencrypt:
    acme:
      httpChallenge:
        entryPoint: web
      email: 'you@example.com'
      storage: /letsencrypt/acme.json
      caServer: https://acme-v02.api.letsencrypt.org/directory
entryPoints:
  web:
    address: ':80'
  websecure:
    address: ':443'
    transport:
      respondingTimeouts:
        readTimeout: 30m
    http:
      tls:
        certResolver: letsencrypt
      encodedCharacters:
        allowEncodedSlash: true
        allowEncodedQuestionMark: true
serversTransport:
  insecureSkipVerify: true
ping:
  entryPoint: web
```

`/etc/pangolin/config/traefik/dynamic_config.yml` — also stock, domain
filled in:

```yaml
http:
  middlewares:
    badger:
      plugin:
        badger:
          disableForwardAuth: true
    redirect-to-https:
      redirectScheme:
        scheme: https

  routers:
    main-app-router-redirect:
      rule: "Host(`tun.<PERSONAL_DOMAIN>`)"
      service: next-service
      entryPoints: [web]
      middlewares: [redirect-to-https, badger]

    next-router:
      rule: "Host(`tun.<PERSONAL_DOMAIN>`) && !PathPrefix(`/api/v1`)"
      service: next-service
      entryPoints: [websecure]
      middlewares: [badger]
      tls:
        certResolver: letsencrypt

    api-router:
      rule: "Host(`tun.<PERSONAL_DOMAIN>`) && PathPrefix(`/api/v1`)"
      service: api-service
      entryPoints: [websecure]
      middlewares: [badger]
      tls:
        certResolver: letsencrypt

  services:
    next-service:
      loadBalancer:
        servers:
          - url: "http://pangolin:3002"
    api-service:
      loadBalancer:
        servers:
          - url: "http://pangolin:3000"

tcp:
  serversTransports:
    pp-transport-v1:
      proxyProtocol:
        version: 1
    pp-transport-v2:
      proxyProtocol:
        version: 2
```

## Step 6 — Podman Quadlets

`/etc/containers/systemd/pangolin.network`:
```ini
[Unit]
Description=Pangolin internal bridge network

[Network]
NetworkName=pangolin
```

`/etc/containers/systemd/pangolin-app.container`:
```ini
[Unit]
Description=Pangolin - tunnel server (dashboard + API)
After=network-online.target
Wants=network-online.target

[Container]
Image=docker.io/fosrl/pangolin:latest
ContainerName=pangolin
Network=pangolin.network
Volume=/etc/pangolin/config:/app/config
HealthCmd=curl -f http://localhost:3001/api/v1/
HealthInterval=3s
HealthTimeout=3s
HealthRetries=15

[Service]
Restart=always

[Install]
WantedBy=multi-user.target
```

`/etc/containers/systemd/pangolin-gerbil.container` — the port remap
(`127.0.0.1:8880`/`8443` instead of the documented `80`/`443`) is the whole
point of this file, to coexist with an existing proxy on the real ports:
```ini
[Unit]
Description=Pangolin - Gerbil (WireGuard tunnel controller)
After=network-online.target pangolin-app.service
Wants=network-online.target

[Container]
Image=docker.io/fosrl/gerbil:latest
ContainerName=gerbil
Network=pangolin.network
Volume=/etc/pangolin/config:/var/config
AddCapability=NET_ADMIN
AddCapability=SYS_MODULE
Exec=--reachableAt=http://gerbil:3004 --generateAndSaveKeyTo=/var/config/key --remoteConfig=http://pangolin:3001/api/v1/
PublishPort=51820:51820/udp
PublishPort=21820:21820/udp
PublishPort=127.0.0.1:8880:80
PublishPort=127.0.0.1:8443:443

[Service]
Restart=always

[Install]
WantedBy=multi-user.target
```

`51820`/`21820` publish 1:1 on the real interface (WireGuard needs to be
reachable directly) — check they're free first (`ss -ulnp | grep -E
':51820|:21820'`) if you've ever run a raw WireGuard server on this box
before. `80`/`443` are bound to `127.0.0.1` only — nothing needs to reach
them except the existing proxy forwarding traffic in Step 7, never the
public internet directly.

`/etc/containers/systemd/pangolin-traefik.container` — Quadlet's
equivalent of `network_mode: service:gerbil` is `Network=container:<name>`:
```ini
[Unit]
Description=Pangolin - Traefik (runs in gerbil's netns, per upstream design)
After=network-online.target pangolin-gerbil.service
Requires=pangolin-gerbil.service

[Container]
Image=docker.io/library/traefik:v3.7
ContainerName=pangolin-traefik
Network=container:gerbil
Exec=--configFile=/etc/traefik/traefik_config.yml
Volume=/etc/pangolin/config/traefik:/etc/traefik:ro
Volume=/etc/pangolin/config/letsencrypt:/letsencrypt

[Service]
Restart=always

[Install]
WantedBy=multi-user.target
```

Bring it up, in order (each depends on the previous being healthy/started):

```bash
sudo systemctl daemon-reload
sudo systemctl start pangolin-app
# wait for it to report healthy: podman inspect pangolin --format '{{.State.Health.Status}}'
sudo systemctl start pangolin-gerbil
sudo systemctl start pangolin-traefik
```

## Step 7 — extend the existing Traefik, don't fight it

Add a new file, `/etc/traefik-dynamic/pangolin.yml`, picked up via
Traefik's file provider. On the existing Traefik container's `Exec=`, add:

```
--providers.file.directory=/etc/traefik-dynamic
--providers.file.watch=true
```

and mount that directory in (`Volume=/etc/traefik-dynamic:/etc/traefik-dynamic:ro`).

`/etc/traefik-dynamic/pangolin.yml`:

```yaml
http:
  routers:
    pangolin-http:
      rule: "Host(`tun.<PERSONAL_DOMAIN>`)"
      entryPoints: [web]
      service: pangolin-http-backend
      priority: 1000

  services:
    pangolin-http-backend:
      loadBalancer:
        servers:
          - url: "http://127.0.0.1:8880"

tcp:
  routers:
    pangolin-tls-passthrough:
      rule: "HostSNI(`tun.<PERSONAL_DOMAIN>`)"
      entryPoints: [websecure]
      service: pangolin-tls-backend
      tls:
        passthrough: true

  services:
    pangolin-tls-backend:
      loadBalancer:
        servers:
          - address: "127.0.0.1:8443"
```

- **Port 80**: a plain HTTP forward, no redirect logic of our own here —
  Pangolin's own inner Traefik already handles the browser
  redirect-to-HTTPS itself (the `main-app-router-redirect` from Step 5).
- **Port 443**: raw TLS passthrough by SNI (`tls.passthrough: true`) — the
  outer Traefik never decrypts this traffic; Pangolin's own inner Traefik
  terminates TLS with its own independently-managed Let's Encrypt
  certificate. This is the standard, documented Traefik pattern for
  multiple TLS-terminating backends behind one front door.

**If your existing Traefik doesn't have a global HTTP→HTTPS redirect
configured, you're done — restart it and skip to Step 8.** If it does
(as this one did, needed for its own pre-existing domain), keep reading —
you'll hit the gotcha below.

### Gotcha: the outer entrypoint's global redirect silently eats the ACME challenge

**Symptom**: Let's Encrypt validation fails with
`Invalid response from https://tun.<PERSONAL_DOMAIN>/.well-known/acme-challenge/...: 404`
— even with DNS correct and the router above in place.

**Root cause**: an entrypoint-level static redirect
(`--entrypoints.web.http.redirections.entrypoint.to=websecure`) runs as an
actual competing router at a very high fixed priority by default — it is
**not** a soft fallback that automatically steps aside for ACME challenge
paths belonging to a different, downstream ACME provider (it only
auto-excludes challenges it recognizes as *its own*). Confirmed directly:

```bash
curl -v --resolve tun.<PERSONAL_DOMAIN>:80:<VPZ_IP> \
  http://tun.<PERSONAL_DOMAIN>/.well-known/acme-challenge/test123
# < HTTP/1.1 301 Moved Permanently
# < Location: https://tun.<PERSONAL_DOMAIN>/.well-known/acme-challenge/test123
```

The redirected request then hits Pangolin's **websecure** entrypoint via
the Step 7 SNI-passthrough router — but Pangolin's `httpChallenge` is
scoped only to its **web** (port 80) entrypoint (Step 5), so nothing
answers it there. Hence the 404.

An enormous explicit `priority:` on the `pangolin-http` router (tried
`9223372036854775806` first) did **not** fix this — the redirect still won.

**Real fix**: `--entrypoints.<name>.allowACMEByPass=true` on the outer
Traefik's `web` entrypoint. Per Traefik's own docs, this flag is
purpose-built for exactly this scenario — "useful when you need custom
handling of ACME challenges, for example when using a dedicated service to
solve HTTP-01 or TLS-ALPN-01 challenges." Add it to the existing
container's `Exec=` alongside whatever's already there:

```
--entrypoints.web.allowACMEByPass=true
```

Restart. Re-test the challenge path — should get a real response (or a
404 for a *made-up* test token, which is correct; only a real,
currently-issued token gets a 200) instead of a 301. Then trigger a fresh
cert attempt:

```bash
sudo systemctl restart pangolin-traefik
podman logs -f pangolin-traefik | grep -i acme
# ... Validations succeeded; requesting certificates.
# ... Server responded with a certificate.
```

**Lesson**: fighting an entrypoint redirect with router priority values is
the wrong tool even though a large-enough number might theoretically work —
`allowACMEByPass` is the documented, correct escape hatch, and priority
interactions with the redirect router have been reported unreliable across
Traefik versions in its own GitHub issues.

### Second gotcha while editing the dynamic config: stale bind mount

Editing `/etc/traefik-dynamic/pangolin.yml` via `mv` (moving a freshly
written temp file into place) did **not** propagate into the
already-running container, despite `--providers.file.watch=true` —
confirmed via `podman exec <container> cat /etc/traefik-dynamic/pangolin.yml`
showing stale content. `mv`/`sed -i` change the file's inode, and a running
container's bind mount keeps pointing at the old one. A container restart
re-establishes the mount against the current file — needed anyway here to
pick up the `allowACMEByPass` flag (a static startup option), so it
resolved itself as a side effect. Worth remembering this bites file-provider
dynamic config too, not just direct app config files — if you ever see a
config edit silently not take effect on a bind-mounted file inside a
running container, this is the first thing to check.

## Step 8 — first login

Pangolin logs a one-time setup token on first boot, needed for the initial
admin-account creation page:

```bash
podman logs pangolin | grep -A2 "SETUP TOKEN"
```

Visit `https://tun.<PERSONAL_DOMAIN>/`, enter the token, create the admin
account.

## Verification

- All three services (`pangolin`, `pangolin-gerbil`, `pangolin-traefik`)
  `active`/`healthy`.
- `https://tun.<PERSONAL_DOMAIN>/` — `200`, valid Let's Encrypt certificate
  (`issuer: ... Let's Encrypt`, `SSL certificate verify ok`).
- WireGuard ports `51820`/`21820` (udp) bound and reachable.
- **Confirmed the pre-existing service sharing the same Traefik instance
  stayed fully functional throughout** — checked after every change to the
  shared container (the file-provider addition, and again after the
  `allowACMEByPass` addition). Worth doing the same check yourself after
  each step if you're extending a Traefik instance that's already serving
  something else in production.
