---
type: investigation
tags: [nixos, warp-vm, migration, k3s, kubernetes, proxmox, mcp, tiktok-bot, technitium, caddy, cloudflared, netbird, democratic-csi, plan, px1]
created: 2026-09-09
status: current
last_verified: 2026-09-09
---

# warp-vm → NixOS migration plan

Goal (user's framing): make `warp-vm` declarative/reproducible by moving it to NixOS, config centralized instead of imperatively hand-built. This doc is the **plan**, built from a live inventory of the VM on 2026-09-09 — not yet executed. Update `status`/`last_verified` as phases land, and treat any IP/version/secret-name below as a snapshot that can drift.

## 0. Current topology

- `px1` (alias `pve-pc`) — Proxmox VE 9.2.11 host, 16c/62.7GiB RAM, HP EliteDesk 705 G4. Already tight on RAM (~80% used before this migration; see [[homelab-k8s-ram-overhead-analysis]]).
- `warp-vm` = Proxmox VMID **101**, 4 vCPU/16GiB RAM (per `qm list` earlier this was 8GB; now shows 16384MB — confirm before rebuild), 100GB disk (`/dev/sda1`, 68G used / 72%), Debian 13 (trixie), static LAN IP **192.168.50.200/24**, gw `192.168.50.1`, single NIC `eth0`.
- It is **not** a spare bastion — it's the single most heavily-loaded host in the homelab: a k3s control-plane + Rancher stack, ~13 user-facing apps, a TikTok/IG/PH bulk-downloader Telegram bot, the evomem knowledge server this very session is capturing to, both Hermes MCP services, the Proxmox MCP server, DNS for the whole LAN (Technitium), the LAN reverse proxy (Caddy), the Cloudflare Tunnel, NetBird mesh client, and multiple SOCKS/TCP relay shims for WARP egress. See [[talos-to-k3s-migration-warp]] and [[tiktok-bot-warp-vm-migration-fixes]] for prior history on this box.

**Practical consequence:** this is not a "reinstall and restore a few dotfiles" migration — it's re-platforming ~20 independent services plus a live single-node k8s cluster with ~13 stateful apps behind an external iSCSI SAN. Plan for a **parallel build + staged cutover**, not an in-place `nixos-infect`.

## 1. Full inventory (source of truth for what must be reproduced)

### 1.1 Bare-metal / systemd services (non-k8s)

| Service | What it is | Runtime | Key config |
|---|---|---|---|
| `technitium.service` | LAN DNS server (replaced Pi-hole) | Podman container (`docker.io/technitium/dns-server:15.4.0`), volume `systemd-technitium-data:/etc/dns` | env `DNS_SERVER_DOMAIN`, `DNS_SERVER_ADMIN_PASSWORD` (**secret**, redacted), `DNS_SERVER_RECURSION=AllowOnlyForPrivateNetworks` |
| `caddy.service` | LAN reverse proxy, `.lan` domains w/ HTTPS | Podman Quadlet (`/etc/containers/systemd/caddy.container`), image `caddy:latest`, network=host | `/root/caddy/Caddyfile` (+ 9 dated `.bak` copies — Caddyfile has been through several manual cutovers, worth diffing before porting) |
| `cloudflared.service` | Cloudflare Tunnel (public exposure layer, see [[homelab-dual-exposure-layer]]) | native binary `/usr/local/bin/cloudflared` | `--token <TUNNEL_TOKEN>` inline in ExecStart — **secret**, redacted; token is per-tunnel, get a fresh one or read it from the CF dashboard, don't hardcode the old one in Nix |
| `netbird.service` | Mesh VPN client | native | `/etc/netbird/install.conf` — re-enroll fresh on new host rather than copy state |
| `microsocks.service` | SOCKS5 proxy, binds `192.168.50.200:1080`, used as WARP egress by cluster apps (crawl4ai, suwayomi, etc. — see [[warp-vm-socks-proxy]]) | native binary, runs as `nobody` | `-i 192.168.50.200 -p 1080` — **IP is hardcoded**, must be updated if the new host's IP changes |
| `socks-relay.service` | `socat` TCP relay, `192.168.50.200:1080` → `192.168.50.41:1080` | native `socat` | forwards to another LAN SOCKS proxy — check if still needed or superseded by `microsocks` above |
| `ovpn-relay.service` | `socat` TCP relay, `192.168.50.200:12443` → a DigitalOcean VPS `:443` (see [[mikrotik-openvpn-warp-relay-bypass-isp-udp-block]]) | native `socat` | target is a **public IP — redact** in any write-up; this is part of the ISP-DPI-bypass OpenVPN relay chain |
| `warp-bypass-route.service` | Custom routing setup for WARP split-tunnel/bypass | shell script `/usr/local/sbin/warp-bypass-setup.sh` | **must pull the actual script content before migrating** — not yet captured in this pass |
| `warp-svc.service` | Cloudflare WARP client daemon | native (`cloudflare-warp` package) | known to leak memory on fedora hosts per [[fedora-memory-audit-warp-svc-leak-daily-restart]] — worth a periodic-restart timer on the NixOS side too |
| `evomem.service` | This session's knowledge server, REST API on :7700 | native binary `/usr/local/bin/evomem` | `--knowledge /root/evomem-kb serve --host 0.0.0.0 --port 7700`; **the knowledge base directory `/root/evomem-kb` is the single most important thing to not lose** — it's the shared memory every Claude Code session (homelab+fedora) auto-captures into |
| `hermes-gateway.service` | Hermes messaging-platform gateway | `/opt/hermes-venv` (Python venv) + Node under `/root/.hermes/node`, source at `/opt/hermes-source` | `WorkingDirectory=/root/.hermes`, `HERMES_HOME=/root/.hermes` — this is an MCP-adjacent piece, see §1.3 |
| `hermes-mcp.service` | Hermes MCP bridge (pre-warmed stdio daemon) | `/usr/bin/python3 /root/.hermes/mcp-daemon.py` | see §1.3 |
| `proxmox-mcp-plus.service` | MCP server exposing Proxmox control to Claude | `/usr/local/bin/proxmox-mcp-plus` | `PROXMOX_MCP_CONFIG=/etc/proxmoxmcp/config.json` — **contains Proxmox API credentials, secret** |
| `camofox-browser.service` | Anti-detection headless browser server, backs tiktok-bot's profile-scraping fallback | Node (`/root/.hermes/node/bin/node server.js`), `/root/camofox-browser` | `CAMOFOX_API_KEY` (**secret**), addon at `/root/camofox-browser/addons/quetta_xpi` |
| `tiktok-bot.service` | TikTok/IG/PornHub bulk-downloader Telegram bot, ~4900 lines, `/opt/tiktok-bot/tiktok_bot.py` | `/opt/hermes-venv` | see §1.4, has a locally-patched f2 import (backup at `tiktok_bot.py.bak-before-f2-disable`) — **this patch must survive the migration, don't re-pull a clean copy of the bot and lose it** |
| `claude-telegram.service` | Claude Code Telegram bot | Poetry venv `/root/.cache/pypoetry/virtualenvs/claude-code-telegram-...` | `/root/claude-telegram-bot` |
| `headroom-proxy.service` | Context-compression proxy | `/opt/headroom-proxy/venv`, runs as `moo` | `HEADROOM_HOST=0.0.0.0` |
| `check-mk-agent-async` / `cmk-agent-ctl-daemon` | Checkmk monitoring agent (see [[caddy-checkmk-monitor-setup]]) | package | reporting to `monitor.lan` on warp k3s |
| `k3s.service` | Kubernetes | see §1.2 | |

Also enabled but not obviously custom: `iscsid`/`open-iscsi`/`rpcbind`/`nfs-blkmap` (needed for democratic-csi iSCSI + the `/mnt/photos` NFS mount from `192.168.50.10`), `incus-startup` (Incus is installed but `incus list` is currently empty — confirm nothing depends on it before dropping).

### 1.2 k3s cluster (single-node, `homelab` namespace + platform)

Node: `warp` itself, `v1.36.4+k3s1`, containerd runtime. This replaced the old 6-VM Talos HA cluster in-place ([[talos-to-k3s-migration-warp]], [[rancher-talos-to-k3s-migration]]) — Talos VMs still exist powered-off on `px1` as rollback.

Platform layer (all namespaces besides `homelab`/`default`): Rancher + Fleet + CAPI + Rancher Turtles, cert-manager, MetalLB, democratic-csi, local-path-provisioner, metrics-server, coredns. 140 CRDs registered (mostly Rancher/Kube-OVN legacy — Kube-OVN itself is **gone** now that this is k3s with flannel, so those CRDs may be orphaned cruft worth *not* carrying forward).

`homelab` namespace workloads (13 apps, all `LoadBalancer` via MetalLB, addresses `192.168.50.221–237`):

| App | Storage | Notes |
|---|---|---|
| bookstack (app+db) | PVC | |
| checkmk | PVC | added 10h ago, newest |
| cekping-agent | — | |
| copyparty | PVC | |
| couchdb | PVC | |
| crawl4ai | — | routes through microsocks for WARP egress |
| forgejo (app+db) | PVC | git server — check for repos not mirrored elsewhere |
| immich | PVC | history of automount issues, see [[immich-random-stops-automount-root-cause]] and [[immich-pgdata-iscsi-lun-resize]] — **treat as the highest-risk stateful migration** |
| nextcloud | PVC | |
| openwebui | PVC | |
| searxng | — | |
| suwayomi + syncyomi | PVC | manga sync pair, [[syncyomi-suwayomi-sync-k8s-deployment]] |
| uptime-kuma | PVC | |

Scaled to 0 replicas currently (exist as manifests, not actively running): `grafana`, `jellyfin`, `oneterm`. Include in manifest export even though idle.

Storage: `democratic-csi` (`org.democratic-csi.iscsi`, default StorageClass `truenas-iscsi`) provisions iSCSI LUNs off an external **TrueNAS NAS** (`192.168.50.10` — same host serving the `/mnt/photos` NFS mount). This is the important structural fact for the migration: **PVC data lives on the NAS, not on the VM's own disk.** `lsblk` shows ~15 iSCSI-attached block devices already mounted under `/var/lib/kubelet/...` — normal steady-state for this setup, not a problem.

### 1.3 MCP surfaces (explicitly called out by user — don't lose these)

- `hermes-mcp.service` + `hermes-gateway.service` — Hermes' own MCP bridge/gateway, config under `/root/.hermes/`.
- `proxmox-mcp-plus.service` — MCP server for Proxmox, config `/etc/proxmoxmcp/config.json` (has Proxmox API creds).
- evomem itself is consumed as an MCP server (`mcp__evomem__*` tools this session uses) — the REST API on :7700 is what backs it; the MCP wiring is on each *client* machine's Claude Code config, but the server-side data (`/root/evomem-kb`) lives on warp.
- Claude Code's own config on warp: `/home/moo/.claude.json` (+ `/home/moo/.claude/` — credentials, sessions, settings) — if warp itself runs Claude Code sessions (it does; evomem captures sessions tagged `homelab`), this is local state to carry over too. `/home/moo/.claude/.credentials.json` is a **secret**.
- Not yet inventoried: whether there's a project- or user-level `.mcp.json` registering *other* MCP servers (only `.claude.json` was found) — worth a `find / -iname ".mcp.json"` pass before cutover.

**Action for this section specifically:** capture the full `/root/.hermes/` tree, `/etc/proxmoxmcp/config.json`, and `/home/moo/.claude.json` verbatim (with secrets stripped to placeholders for anything committed to git) as the reference for rebuilding these three MCP services declaratively.

### 1.4 tiktok-bot specifics

Per [[tiktok-bot-warp-vm-migration-fixes]], this instance has two live local patches that a fresh clone/pull would **not** have:
1. `f2` import wrapped in try/except with a stub `TokenManager` (backup: `/opt/tiktok-bot/tiktok_bot.py.bak-before-f2-disable`).
2. A `pip` corruption fix for `gallery-dl` (stray `~allery_dl-1.32.9.dist-info` cleaned up).

State that must move, not just code: the `WatchDB` (555 entries), per-user `--download-archive` files, `cookies.txt` (session cookies — **secret**), and any Instagram `instagrapi` session files. Locate these under `/opt/tiktok-bot/` (subdirectories weren't enumerated yet — do `ls -la /opt/tiktok-bot` before the cutover and list every stateful file explicitly).

## 2. NixOS target design

Recommend: **new Proxmox VM (new VMID) built from the official NixOS ISO/qcow2, on `px1`, in parallel with the live `warp-vm`** — not an in-place conversion. `px1` is already at ~80% RAM (see [[homelab-k8s-ram-overhead-analysis]]) so check free capacity before sizing the new VM; if headroom is tight, this is also the moment to right-size (does this box really need 16GB, or was that a typo from the 8GB originally provisioned?).

Suggested module layout (flake-based, so this itself becomes the "centralized config" the user wants):

```
warp-nixos/
  flake.nix
  hosts/warp/
    configuration.nix       # networking (static 192.168.50.200/24), users, base packages
    k3s.nix                 # services.k3s + iscsid/rpcbind for democratic-csi
    dns.nix                 # technitium (oci-containers or podman module)
    proxy.nix                # caddy (either services.caddy natively, or oci-containers to keep parity)
    tunnel.nix               # cloudflared (services.cloudflared exists in nixpkgs)
    vpn.nix                  # netbird (services.netbird exists in nixpkgs), warp-svc, socks/relay units
    mcp.nix                  # hermes-gateway, hermes-mcp, proxmox-mcp-plus as systemd units
    tiktok-bot.nix           # camofox-browser + tiktok-bot as systemd units, python env via poetry2nix or a plain venv
    evomem.nix               # evomem server unit + persistent /var/lib/evomem-kb
    secrets.nix               # sops-nix or agenix wiring
  secrets/                    # sops-nix encrypted secrets, safe to commit
```

Key decisions to make before writing Nix:

1. **Secrets management** — currently everything is plaintext in `Environment=` lines in systemd units (DNS admin password, Camofox API key, Cloudflare tunnel token, Proxmox API creds, TikTok cookies). NixOS config is world-readable in the Nix store by default, so this is the point to introduce **sops-nix** or **agenix** rather than carrying the plaintext-env-var pattern forward. This is the single biggest quality improvement available in this migration, worth doing even though it's extra work.
2. **k3s: native `services.k3s` vs. keep Talos-style / stay on Debian for just this node** — nixpkgs has a `services.k3s` module; single-node control-plane should translate cleanly. Rancher/Fleet/cert-manager/MetalLB/democratic-csi are all Helm-installed *inside* the cluster, so they don't need Nix modules at all — just `k3s` up, then re-apply the same Helm releases (ideally via a GitOps tool like Fleet pointing at a git repo, which is already partially in place given Fleet is running).
3. **Podman-quadlet services (technitium, caddy) → NixOS `virtualisation.oci-containers` or native packages.** nixpkgs ships `caddy` natively (`services.caddy`) which would let the Caddyfile become real declarative Nix instead of a container volume mount — recommended over carrying Podman forward for just two containers.
4. **Python services (hermes, tiktok-bot, camofox, headroom-proxy, claude-telegram)** — four different Python venv layouts today (raw venv, poetry, mixed). Decide once: `poetry2nix`/`uv2nix` per-service flake inputs, or keep plain venvs bootstrapped by an `ExecStartPre`. Given these are actively-developed bots (not vendored packages), a pragmatic middle ground — Nix manages Python interpreter + system deps, venv/pip still manages the fast-moving app deps — is likely less migration risk than fully hermetic Nix builds of each bot on day one.

## 3. Data that must be copied (not just config)

| Data | Location on warp | Size/notes | Destination |
|---|---|---|---|
| evomem knowledge base | `/root/evomem-kb` | shared memory for **every** Claude Code session — highest-value data on this box | rsync to new host, same path or update `EVOMEM_ROOT` everywhere it's referenced |
| tiktok-bot state | `/opt/tiktok-bot/{WatchDB,*.txt,cookies.txt,download-archives,...}` | needs explicit enumeration first | rsync |
| Hermes state | `/root/.hermes/` | sessions, MCP daemon state | rsync |
| Caddy TLS data | `/root/caddy/data`, `/root/caddy/config` | ACME certs/keys for `.lan` HTTPS | rsync or just let it re-issue |
| Claude Code state (warp's own) | `/home/moo/.claude/`, `/home/moo/.claude.json` | sessions/creds if warp itself is used as a Claude Code host | rsync, treat `.credentials.json` as secret |
| k8s app data | TrueNAS-backed PVCs via democratic-csi | **stays on the NAS**, does not need copying — only the new node's iSCSI initiator (IQN) needs to be authorized against the same TrueNAS targets, and the `democratic-csi` driver config secrets re-applied | re-point, don't copy |
| Camofox addons | `/root/camofox-browser/addons/quetta_xpi` | | rsync |
| `/mnt/photos` NFS mount | from `192.168.50.10` | external, just remount | fstab/NixOS `fileSystems` entry |

## 4. Suggested phased plan

1. **Freeze & document.** Pull the actual `warp-bypass-setup.sh` content, enumerate `/opt/tiktok-bot/*` fully, diff the 9 Caddyfile `.bak` files down to what's actually live, dump `/root/.hermes/` tree and `/etc/proxmoxmcp/config.json` structure (redacted). Confirm `warp-vm`'s real current RAM allocation (`qm config 101` on px1) since `qm list` showed 16384MB against a memory doc that said 8GB — reconcile before sizing the new VM.
2. **Stand up NixOS skeleton** on a new VM (new VMID on `px1`) — base networking, SSH, users, flake scaffolding. No workloads yet. Validate it can reach the LAN, DNS, and the TrueNAS iSCSI portal.
3. **Migrate infra services one at a time, in dependency order, each verified working before moving to the next:** DNS (technitium) → reverse proxy (caddy) → tunnel (cloudflared) → VPN/relays (netbird, warp-svc, microsocks, socat relays) → evomem → MCP trio (hermes-gateway, hermes-mcp, proxmox-mcp-plus) → camofox + tiktok-bot → claude-telegram → headroom-proxy → checkmk agent. Keep the old warp-vm's copies **enabled but able to be stopped**, not deleted, until each new-host service is confirmed good (this is exactly the "two copies both enabled" bug pattern already seen once with tiktok-bot per [[tiktok-bot-warp-vm-migration-fixes]] — be deliberate about which copy is authoritative at every point, and stop+disable the old one the moment the new one is verified, don't leave both running).
4. **Bring up k3s on the new host**, join/re-authorize against the same TrueNAS iSCSI backend, re-install the platform Helm stack (Rancher, Fleet, cert-manager, MetalLB, democratic-csi), then re-apply/re-deploy the 13 `homelab` app manifests. Since PVC data lives on the NAS, this should mostly be "point new node's CSI driver at the same TrueNAS target IQNs" rather than a data copy — but test this assumption on a throwaway PVC before trusting it for immich/forgejo/nextcloud.
5. **DNS/IP cutover.** Once everything on the new host is verified side-by-side (different temp IP), do the final swap: move `192.168.50.200` to the new box (or repoint DHCP/MikroTik/Caddy/Technitium records — check [[homelab-stale-dns-hosts-ssh-config-sweep]] for the class of gotcha where stale DNS/hosts/SSH-config entries linger after a host swap), update `~/.ssh/config` alias `warp` to the new host if the IP changes, update the **Cloudflare Tunnel** (new tunnel token bound to new host, per [[homelab-dual-exposure-layer]] both the `.lan` Caddy route and the public Cloudflare Tunnel route need repointing or the public domain silently 502s), and re-enroll NetBird fresh rather than copying its identity.
6. **Decommission.** Once the new host has run clean for a few days, shut down (don't delete yet) the old `warp-vm` (VMID 101) as a rollback point, same pattern already used for the Talos VMs. Delete only after a real burn-in period.

## 5. Risks / things that have already bitten this exact stack before

- **Duplicate-service crash loops** if an old copy isn't fully stopped+disabled before the new one starts — already happened once with tiktok-bot (11 days crash-looping, 30k+ restarts) per [[tiktok-bot-warp-vm-migration-fixes]]. Migrate one service at a time, verify, then kill the old copy — don't batch-cutover.
- **Dual exposure layer** (`.lan` Caddy + Cloudflare Tunnel) — per [[homelab-dual-exposure-layer]], forgetting to repoint *both* on cutover leaves the public domain 502ing even though the LAN route works fine.
- **DNS not a wildcard** — per [[pihole-lan-records-not-wildcard]] (now Technitium, same constraint), every `.lan` route needs an explicit A record; nothing auto-resolves.
- **Kube-OVN join-subnet / proxy-trust class of bug** doesn't apply anymore since this is flannel-backed k3s now, not Kube-OVN — but any reverse-proxy trust config (`--xff-src` etc.) should be re-verified against the new node's real LAN IP as peer, since that's the kind of assumption that broke silently before.
- **sed -i on bind-mounted files breaks container mounts silently** ([[sed-i-bind-mount-gotcha]]) — relevant if editing the Caddyfile or any bind-mounted config in place during the transition; use container restart or truncate+write instead.
- **warp-svc memory leak** ([[fedora-memory-audit-warp-svc-leak-daily-restart]]) — carry forward whatever periodic-restart mitigation exists, or add one in the NixOS unit if none exists yet.
- **px1 headroom** — host is already ~80% RAM used; sizing the new VM (especially if larger than the old one) may require freeing capacity first (e.g. the powered-off Talos VMs still reserve no RAM since they're off, but double-check nothing else is competing).

## 6. Open questions for the user

- Target NixOS install method: fresh ISO install into a new Proxmox VM (recommended, cleanest), or `nixos-anywhere`/`nixos-infect` onto a clone of the existing disk (faster but drags along Debian cruft and makes rollback via "just don't touch the old VM" less clean)?
- Keep Podman for technitium/caddy (`virtualisation.oci-containers`, less porting work) or move both to native NixOS services (`services.caddy` exists; Technitium does not have a nixpkgs module, so it'd stay containerized either way)?
- Secrets: sops-nix or agenix? (Both integrate cleanly with flakes; sops-nix is more common for "many small secrets across many services" like this box has.)
- k3s re-platform: keep single-node k3s as-is, or use this migration as the point to reconsider HA/topology given [[homelab-k8s-ram-overhead-analysis]] found the platform overhead (~10GB) already costs ~2× the actual app workload (~5.4GB)?

## Notes on secrets

Every secret found during inventory (Cloudflare tunnel token, Technitium admin password, Camofox API key, Proxmox MCP API credentials, tiktok-bot `cookies.txt`/session files, Claude Code `.credentials.json`) is redacted above and was **not** copied into this file in raw form. Real values live only on `warp-vm` itself; when building the sops-nix/agenix secrets store for the new host, pull them fresh from the running services rather than from this doc.
