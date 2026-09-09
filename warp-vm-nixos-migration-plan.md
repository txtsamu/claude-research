---
type: investigation
tags: [nixos, warp-vm, migration, k3s, kubernetes, proxmox, mcp, tiktok-bot, technitium, caddy, cloudflared, netbird, democratic-csi, plan, px1, wayfinder]
created: 2026-09-09
status: current
last_verified: 2026-09-09
---

# warp-vm → NixOS migration plan

Goal (user's framing): make `warp-vm` declarative/reproducible by moving it to NixOS, config centralized instead of imperatively hand-built. This doc is the **plan**, built from a live inventory of the VM on 2026-09-09 — not yet executed. Update `status`/`last_verified` as phases land, and treat any IP/version/secret-name below as a snapshot that can drift.

**Progress (2026-09-09):** T1 (#9), T2 (#10, agenix), T3 (#11, DNS), T4 (#12, Caddy), T5 (#13, tunnel), T6 (#14, NetBird - WARP dropped, see its resolution comment), T7 (#15, evomem), T8 (#16, MCP trio), T13 (#21, k3s core platform) done and closed — see each issue's resolution comment for exact commands, values, and real bugs hit (stale root Nix eval cache needing `--refresh`, containerd's `/etc/localtime` bind-mount needing `time.timeZone` set, democratic-csi's `/var/iscsi` hostPath, `netbird up`'s daemon-addr default drifting by version, the T1-era virtio_scsi/DNS-resolver fixes). `home` (192.168.50.202) now has: k3s + full platform layer (Rancher/Fleet/cert-manager/MetalLB/democratic-csi, proven against live TrueNAS), Technitium DNS (real zone data ported), Caddy (16 routes ported), a fresh Cloudflare Tunnel (native module needed a real tunnel, not a shared token - see #13), and NetBird mesh membership (fresh peer identity, real P2P connectivity confirmed to warp-vm), and the MCP trio (hermes-gateway / hermes-mcp / proxmox-mcp-plus on uv-built venvs - source rsynced to /opt/hermes-source, /root/.hermes state rsynced, proxmox token in agenix). Every "old service on warp-vm stopped" criterion is deliberately deferred across the board — every client (DNS resolvers, Caddy routes, evomem's hardcoded IP) still points at warp-vm until T19 cutover; stopping any of them now breaks live production for no benefit. Frontier as of this update: T9 camofox (#17), T11 headroom-proxy (#19), T12 checkmk (#20), and T14-T18 app redeploys (#22-26, unblocked by T13 - T14 will need to resolve the deferred MetalLB IP-pool question from T13's resolution comment).

## 0. Current topology

- `px1` (alias `pve-pc`) — Proxmox VE 9.2.11 host, 16c/62.7GiB RAM, HP EliteDesk 705 G4. Already tight on RAM (~80% used before this migration; see [[homelab-k8s-ram-overhead-analysis]]).
- `warp-vm` = Proxmox VMID **101**, **8 vCPU / 16GiB RAM** (confirmed via `qm config 101` — deliberate current allocation, not a stale doc), 100GB disk (`/dev/sda1`, 68G used / 72%), Debian 13 (trixie), static LAN IP **192.168.50.200/24**, gw `192.168.50.1`, single NIC `eth0`.
- **New NixOS host will be named `home`** (new Proxmox VM, new VMID, new hostname — not a rename of `warp-vm` in place). Every "new host" reference below refers to this `home` box; `warp-vm` stays `warp-vm` until decommissioned per §4 step 6.
- It is **not** a spare bastion — it's the single most heavily-loaded host in the homelab: a k3s control-plane + Rancher stack, ~13 user-facing apps, a TikTok/IG/PH bulk-downloader Telegram bot, the evomem knowledge server this very session is capturing to, both Hermes MCP services, the Proxmox MCP server, DNS for the whole LAN (Technitium), the LAN reverse proxy (Caddy), the Cloudflare Tunnel, NetBird mesh client, and multiple SOCKS/TCP relay shims for WARP egress. See [[talos-to-k3s-migration-warp]] and [[tiktok-bot-warp-vm-migration-fixes]] for prior history on this box.

**Practical consequence:** this is not a "reinstall and restore a few dotfiles" migration — it's re-platforming ~20 independent services plus a live single-node k8s cluster with ~13 stateful apps behind an external iSCSI SAN. Plan for a **parallel build + staged cutover**, not an in-place `nixos-infect`.

## 1. Full inventory (source of truth for what must be reproduced)

### 1.1 Bare-metal / systemd services (non-k8s)

| Service | What it is | Runtime | Key config |
|---|---|---|---|
| `technitium.service` | LAN DNS server (replaced Pi-hole) | Podman container (`docker.io/technitium/dns-server:15.4.0`), volume `systemd-technitium-data:/etc/dns` | env `DNS_SERVER_DOMAIN`, `DNS_SERVER_ADMIN_PASSWORD` (**secret**, redacted), `DNS_SERVER_RECURSION=AllowOnlyForPrivateNetworks` |
| `caddy.service` | LAN reverse proxy, `.lan` domains w/ HTTPS | Podman Quadlet (`/etc/containers/systemd/caddy.container`), image `caddy:latest`, network=host | `/root/caddy/Caddyfile`, 18 site blocks live on `warp-vm` (**17 to actually port** — drop `syncyomi.lan`, out of scope as of 2026-09-09) — **confirmed current** against all 8 dated `.bak` copies (all differ from live, none more current; backups are pure cruft, skip them). Fronts more than just k8s `homelab` apps: also the **px1 and px2 Proxmox web UIs directly** (`px1.lan`/`px2.lan` → `:8006`) and the **TrueNAS UI** (`nas.lan`) — port to `services.caddy`, not just the app-namespace subset |
| `cloudflared.service` | Cloudflare Tunnel (public exposure layer, see [[homelab-dual-exposure-layer]]) | native binary `/usr/local/bin/cloudflared` | `--token <TUNNEL_TOKEN>` inline in ExecStart — **secret**, redacted; token is per-tunnel, get a fresh one or read it from the CF dashboard, don't hardcode the old one in Nix |
| `netbird.service` | Mesh VPN client | native | `/etc/netbird/install.conf` — re-enroll fresh on new host rather than copy state |
| `microsocks.service` | SOCKS5 proxy, binds `192.168.50.200:1080`, used as WARP egress by cluster apps (crawl4ai, suwayomi, etc. — see [[warp-vm-socks-proxy]]) | native binary, runs as `nobody` | `-i 192.168.50.200 -p 1080` — **IP is hardcoded**, must be updated if the new host's IP changes |
| `socks-relay.service` | `socat` TCP relay, `192.168.50.200:1080` → `192.168.50.41:1080` | native `socat` | forwards to another LAN SOCKS proxy — check if still needed or superseded by `microsocks` above |
| `ovpn-relay.service` | `socat` TCP relay, `192.168.50.200:12443` → a DigitalOcean VPS `:443` (see [[mikrotik-openvpn-warp-relay-bypass-isp-udp-block]]) | native `socat` | target is a **public IP — redact** in any write-up; this is part of the ISP-DPI-bypass OpenVPN relay chain |
| `warp-bypass-route.service` | Custom routing setup for WARP split-tunnel/bypass | shell script `/usr/local/sbin/warp-bypass-setup.sh` | **captured**: just `ip rule` policy routing (LAN traffic → WARP's routing table 65743, plus one narrow bypass rule for a specific IP) + `iptables-restore`. Ports directly, no redesign needed for `vpn.nix` — just must run *after* `warp-svc` brings up its routing table, same ordering as today |
| `warp-svc.service` | Cloudflare WARP client daemon | native (`cloudflare-warp` package) | known to leak memory on fedora hosts per [[fedora-memory-audit-warp-svc-leak-daily-restart]] — worth a periodic-restart timer on the NixOS side too |
| `evomem.service` | This session's knowledge server, REST API on :7700 | native binary `/usr/local/bin/evomem` | `--knowledge /root/evomem-kb serve --host 0.0.0.0 --port 7700`; **the knowledge base directory `/root/evomem-kb` is the single most important thing to not lose** — it's the shared memory every Claude Code session (homelab+fedora) auto-captures into |
| `hermes-gateway.service` | Hermes messaging-platform gateway | `/opt/hermes-venv` (Python venv) + Node under `/root/.hermes/node`, source at `/opt/hermes-source` | `WorkingDirectory=/root/.hermes`, `HERMES_HOME=/root/.hermes` — this is an MCP-adjacent piece, see §1.3 |
| `hermes-mcp.service` | Hermes MCP bridge (pre-warmed stdio daemon) | `/usr/bin/python3 /root/.hermes/mcp-daemon.py` | see §1.3 |
| `proxmox-mcp-plus.service` | MCP server exposing Proxmox control to Claude | `/usr/local/bin/proxmox-mcp-plus` | `PROXMOX_MCP_CONFIG=/etc/proxmoxmcp/config.json` — **contains Proxmox API credentials, secret** |
| `camofox-browser.service` | Anti-detection headless browser server, backs tiktok-bot's profile-scraping fallback | Node (`/root/.hermes/node/bin/node server.js`), `/root/camofox-browser` | `CAMOFOX_API_KEY` (**secret**), addon at `/root/camofox-browser/addons/quetta_xpi` |
| `tiktok-bot.service` | TikTok/IG/PornHub bulk-downloader Telegram bot, ~4900 lines, `/opt/tiktok-bot/tiktok_bot.py` | `/opt/hermes-venv` | see §1.4, has a locally-patched f2 import (backup at `tiktok_bot.py.bak-before-f2-disable`) — **this patch must survive the migration, don't re-pull a clean copy of the bot and lose it** |
| ~~`claude-telegram.service`~~ | ~~Claude Code Telegram bot~~ | **out of scope, not migrating** — user no longer uses it; stopped + disabled on `warp-vm` 2026-09-09 | — |
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
| suwayomi | PVC | previously paired with syncyomi for sync, see [[syncyomi-suwayomi-sync-k8s-deployment]] — now standalone, migrates alone |
| uptime-kuma | PVC | |

Scaled to 0 replicas: `grafana`, `jellyfin`, `oneterm` (idle, include in manifest export), and as of 2026-09-09 also `syncyomi` — **out of scope, not migrating**, user no longer uses it. PVC left intact (not deleted) in case it's wanted back later.

Storage: `democratic-csi` (`org.democratic-csi.iscsi`, default StorageClass `truenas-iscsi`) provisions iSCSI LUNs off an external **TrueNAS NAS** (`192.168.50.10` — same host serving the `/mnt/photos` NFS mount). This is the important structural fact for the migration: **PVC data lives on the NAS, not on the VM's own disk.** `lsblk` shows ~15 iSCSI-attached block devices already mounted under `/var/lib/kubelet/...` — normal steady-state for this setup, not a problem.

### 1.3 MCP surfaces (explicitly called out by user — don't lose these)

- `hermes-mcp.service` + `hermes-gateway.service` — Hermes' own MCP bridge/gateway, config under `/root/.hermes/`.
- `proxmox-mcp-plus.service` — MCP server for Proxmox, config `/etc/proxmoxmcp/config.json` (has Proxmox API creds).
- evomem itself is consumed as an MCP server (`mcp__evomem__*` tools this session uses) — the REST API on :7700 is what backs it; the MCP wiring is on each *client* machine's Claude Code config, but the server-side data (`/root/evomem-kb`) lives on warp.
- Claude Code's own config on warp: `/home/moo/.claude.json` (+ `/home/moo/.claude/` — credentials, sessions, settings) — if warp itself runs Claude Code sessions (it does; evomem captures sessions tagged `homelab`), this is local state to carry over too. `/home/moo/.claude/.credentials.json` is a **secret**.
- Not yet inventoried: whether there's a project- or user-level `.mcp.json` registering *other* MCP servers (only `.claude.json` was found) — worth a `find / -iname ".mcp.json"` pass before cutover.

**Action for this section specifically:** capture the full `/root/.hermes/` tree, `/etc/proxmoxmcp/config.json`, and `/home/moo/.claude.json` verbatim (with secrets stripped to placeholders for anything committed to git) as the reference for rebuilding these three MCP services declaratively.

### 1.4 tiktok-bot specifics

**Corrected after a full enumeration (2026-09-09) — the picture below supersedes the original draft's assumptions.**

`/opt/tiktok-bot` is a **local git repo** (`.git/` present). This changes the migration approach for the better: clone/pull the code instead of manually reconciling backup files. The f2 fix from [[tiktok-bot-warp-vm-migration-fixes]] is already a **tracked patch**, not a loose manual edit: `patches/f2-device-id-manager-fallback.patch` + `patches/apply.sh`. Migrate by cloning the repo and running `patches/apply.sh`, not by diffing `.py.bak` files.

Five historical `tiktok_bot.py.bak-*` copies exist (before-f2-disable, before-manifest-source-fix, before-photo-typing, before-post-manifest, phbatch) — all superseded by git history now that this is confirmed a repo; safe to leave behind, don't migrate them.

**Actual stateful data to rsync** (not code — code comes via git):

- **7 cookie files, not 1**: `cookies.txt`, `tiktok_cookies.txt`, `user_cookies.txt`, `ph_cookies.txt`, and `cookies/{facebook,instagram,nhentai,patreon,reddit,twitter}_cookies.txt` — all **secrets**.
- **`watchlist.json`** (267KB) — the real persistent watch state. `watchdb.sqlite3` also exists but is **0 bytes**; the "555-entry WatchDB" figure from [[tiktok-bot-warp-vm-migration-fixes]] either lives in `watchlist.json` now or is stale — sanity-check against the running bot before cutover, don't just copy blind.
- **Per-target scrape state**: `scripts/*_capture_state.json`, `*_links.json`, `*_recon.json` (e.g. `liliibunny_*`, `asiatcnn_*`) — live scrape progress per target, not just code.
- Skip: `logs/` (~90 small rotated f2 logs, mostly noise, several exactly 192 bytes), `__pycache__/`.

## 2. NixOS target design

Recommend: **new Proxmox VM (new VMID) on `px1`, installed via `nixos-anywhere` + `disko`, in parallel with the live `warp-vm`** — not an in-place conversion. `nixos-anywhere` kexecs into a NixOS installer and uses `disko` for fully declarative disk partitioning, which fits the "everything centralized in config" goal better than a manual ISO install (partition layout becomes part of the flake, not a one-off click-through) — see the "NixOS + Proxmox: a recipe for a declarative homelab" and "Proxmox to NixOS + Incus" write-ups for the pattern other homelabbers use for exactly this. Either way, make sure `services.qemuGuest.enable = true;` is set so Proxmox integration (clean shutdown, IP reporting) keeps working like it does on the Debian VM today. `px1` is already at ~80% RAM (see [[homelab-k8s-ram-overhead-analysis]]) so check free capacity before sizing the new VM; if headroom is tight, this is also the moment to right-size (does this box really need 16GB, or was that a typo from the 8GB originally provisioned?).

Suggested module layout (flake-based, so this itself becomes the "centralized config" the user wants):

```
warp-nixos/
  flake.nix
  hosts/home/
    configuration.nix       # hostname "home", networking (static 192.168.50.200/24), users, base packages
    disko.nix                # declarative disk layout (nixos-anywhere target)
    k3s.nix                 # services.k3s + services.openiscsi/rpcbind for democratic-csi
    dns.nix                 # services.technitium-dns-server (native nixpkgs module)
    proxy.nix                # services.caddy (native)
    tunnel.nix               # cloudflared (services.cloudflared exists in nixpkgs)
    vpn.nix                  # netbird — hand-written systemd unit around the (stable) netbird package, NOT services.netbird (see §2.5); warp-svc, socks/relay units
    mcp.nix                  # hermes-gateway, hermes-mcp, proxmox-mcp-plus as systemd units
    tiktok-bot.nix           # camofox-browser + tiktok-bot as systemd units, python env via uv2nix or a plain venv
    evomem.nix               # evomem server unit + persistent /var/lib/evomem-kb
    secrets.nix               # sops-nix or agenix wiring
  secrets/                    # encrypted secrets, safe to commit
```

Key decisions to make before writing Nix (verified against current nixpkgs/tooling, 2026-09-09):

1. **Secrets management** — currently everything is plaintext in `Environment=` lines in systemd units (DNS admin password, Camofox API key, Cloudflare tunnel token, Proxmox API creds, TikTok cookies). NixOS config is world-readable in the Nix store by default, so this is the point to introduce **sops-nix** or **agenix** rather than carrying the plaintext-env-var pattern forward. This is the single biggest quality improvement available in this migration, worth doing even though it's extra work. Given the secret count here is modest (~6, spread across independent services, not one big templated config like a mail server), **agenix is the better fit** — no YAML schema or `.sops.yaml` to keep in sync, `secrets.nix` is plain Nix; reach for sops-nix instead only if the secret count grows a lot or a service needs several secrets templated into one generated config file.
2. **k3s: confirmed available.** `services.k3s` is a real, actively maintained nixpkgs module (45 options as of current nixpkgs — `role`, `token`/`tokenFile`, `extraFlags`, `manifests` for auto-deployed addons, `images` for pre-imported containerd images, etc.). Single-node control-plane translates cleanly. Rancher/Fleet/cert-manager/MetalLB/democratic-csi are all Helm-installed *inside* the cluster, so they don't need Nix modules at all — just `k3s` up, then re-apply the same Helm releases (ideally via a GitOps tool like Fleet pointing at a git repo, which is already partially in place given Fleet is running). For the iSCSI initiator side that democratic-csi needs on the node, use `services.openiscsi.enable = true` (the real nixpkgs option — plain `iscsid`/`open-iscsi` aren't separate NixOS services the way they are Debian packages).
3. **Correction from the first draft: Technitium *does* have a native nixpkgs module** (`services.technitium-dns-server`, in `nixos/modules/services/networking/`) — no need to keep it containerized. Use it alongside `services.caddy` (also native) instead of `virtualisation.oci-containers`; this drops Podman from the new host entirely for these two, which is a real win for "everything declarative" since container volume-mounted config (the current Caddyfile-via-bind-mount setup) is exactly the kind of imperative-adjacent pattern this migration is trying to get away from.
4. **Python services (hermes, tiktok-bot, camofox, headroom-proxy, claude-telegram)** — four different Python venv layouts today (raw venv, poetry, mixed). The nixpkgs Python-packaging ecosystem has shifted since poetry2nix was the default answer: **uv2nix is now the maintainer-recommended path for new work** (poetry2nix's own maintainers point new users to it), so plan any packaging effort here around `uv`/`uv2nix` rather than `poetry2nix`, and use plain `uv`-managed venvs (not full hermetic Nix builds) for the actively-developed bots as a pragmatic middle ground — Nix manages the Python interpreter + system deps, `uv` still manages the fast-moving app deps.
5. **NetBird: use the package, skip the `services.netbird` module.** The `netbird` *package* is in stable nixpkgs (25.11), so no unstable pin is needed at all — but the *module* has several open 2026 bugs directly relevant here: it keeps a daemon connecting to NetBird's default cloud management even when a custom management URL is set ([#523384](https://github.com/nixos/nixpkgs/issues/523384) — a real problem since this setup self-hosts its own NetBird management server, not NetBird's cloud), writes secrets to a world-readable config file outside the Nix store ([#371286](https://github.com/NixOS/nixpkgs/issues/371286), undermining the agenix work from §2.1), and has open service-doesn't-start-after-upgrade ([#497484](https://github.com/NixOS/nixpkgs/issues/497484)) and SSH-to-client ([#505846](https://github.com/NixOS/nixpkgs/issues/505846)) bugs. None of these are in the binary itself — write a plain `systemd.services.netbird` unit around `${pkgs.netbird}/bin/netbird up --management-url <self-hosted-url> ...`, matching the hand-written-unit pattern already used for `mcp.nix`/`tiktok-bot.nix`, and mirroring what the Debian box already runs today.

## 3. Data that must be copied (not just config)

| Data | Location on warp | Size/notes | Destination |
|---|---|---|---|
| evomem knowledge base | `/root/evomem-kb` | shared memory for **every** Claude Code session — highest-value data on this box | rsync to new host, same path or update `EVOMEM_ROOT` everywhere it's referenced |
| tiktok-bot code | `/opt/tiktok-bot/` (git repo) | code + the f2 patch | `git clone`, then run `patches/apply.sh` — not rsync |
| tiktok-bot state | 7 cookie files (see §1.4), `watchlist.json`, `scripts/*_{capture_state,links,recon}.json` | all secrets/live scrape state, enumerated 2026-09-09 | rsync |
| Hermes state | `/root/.hermes/` | sessions, MCP daemon state | rsync |
| Caddy TLS data | `/root/caddy/data`, `/root/caddy/config` | ACME certs/keys for `.lan` HTTPS | rsync or just let it re-issue |
| Claude Code state (warp's own) | `/home/moo/.claude/`, `/home/moo/.claude.json` | sessions/creds if warp itself is used as a Claude Code host | rsync, treat `.credentials.json` as secret |
| k8s app data | TrueNAS-backed PVCs via democratic-csi | **stays on the NAS**, does not need copying — only the new node's iSCSI initiator (IQN) needs to be authorized against the same TrueNAS targets, and the `democratic-csi` driver config secrets re-applied | re-point, don't copy |
| Camofox addons | `/root/camofox-browser/addons/quetta_xpi` | | rsync |
| `/mnt/photos` NFS mount | from `192.168.50.10` | external, just remount | fstab/NixOS `fileSystems` entry |

## 4. Suggested phased plan

1. **Freeze & document.** ~~Pull the actual `warp-bypass-setup.sh` content, enumerate `/opt/tiktok-bot/*` fully, diff the 9 Caddyfile `.bak` files down to what's actually live, confirm `warp-vm`'s real RAM allocation.~~ **Done 2026-09-09** — see §0, §1.1, §1.4 and §3 above, findings tracked as resolved tickets on [the wayfinder map](https://github.com/txtsamu/claude-research/issues/1). Still outstanding: dump `/root/.hermes/` tree and `/etc/proxmoxmcp/config.json` structure (redacted).
2. **Stand up NixOS skeleton** on a new VM (new VMID on `px1`, hostname `home`) — base networking, SSH, users, flake scaffolding. No workloads yet. Validate it can reach the LAN, DNS, and the TrueNAS iSCSI portal.
3. **Migrate infra services one at a time, in dependency order, each verified working before moving to the next:** DNS (technitium) → reverse proxy (caddy) → tunnel (cloudflared) → VPN/relays (netbird, warp-svc, microsocks, socat relays) → evomem → MCP trio (hermes-gateway, hermes-mcp, proxmox-mcp-plus) → camofox + tiktok-bot → claude-telegram → headroom-proxy → checkmk agent. Keep the old warp-vm's copies **enabled but able to be stopped**, not deleted, until each new-host service is confirmed good (this is exactly the "two copies both enabled" bug pattern already seen once with tiktok-bot per [[tiktok-bot-warp-vm-migration-fixes]] — be deliberate about which copy is authoritative at every point, and stop+disable the old one the moment the new one is verified, don't leave both running).
4. **Bring up k3s on the new host**, join/re-authorize against the same TrueNAS iSCSI backend, re-install the platform Helm stack (Rancher, Fleet, cert-manager, MetalLB, democratic-csi), then re-apply/re-deploy the 13 `homelab` app manifests. Since PVC data lives on the NAS, this should mostly be "point new node's CSI driver at the same TrueNAS target IQNs" rather than a data copy — but test this assumption on a throwaway PVC before trusting it for immich/forgejo/nextcloud.
5. **DNS/IP/hostname cutover.** Once everything on `home` is verified side-by-side (different temp IP), do the final swap: move `192.168.50.200` to `home` (or repoint DHCP/MikroTik/Caddy/Technitium records — check [[homelab-stale-dns-hosts-ssh-config-sweep]] for the class of gotcha where stale DNS/hosts/SSH-config entries linger after a host swap). Decide explicitly what happens to the `warp` name/alias: either add `home` as a new `~/.ssh/config` entry and retire the `warp` alias once `warp-vm` is decommissioned, or repoint the existing `warp` alias at `home`'s IP — pick one and update every place the old hostname is hardcoded (Technitium A records, Caddy upstream refs, `microsocks`/relay bind IPs in §1.1, monitoring configs in Checkmk). Update the **Cloudflare Tunnel** (new tunnel token bound to `home`, per [[homelab-dual-exposure-layer]] both the `.lan` Caddy route and the public Cloudflare Tunnel route need repointing or the public domain silently 502s), and re-enroll NetBird fresh under the `home` identity rather than copying `warp-vm`'s.
6. **Decommission.** Once `home` has run clean for a few days, shut down (don't delete yet) the old `warp-vm` (VMID 101) as a rollback point, same pattern already used for the Talos VMs. Delete only after a real burn-in period.

## 5. Risks / things that have already bitten this exact stack before

- **Duplicate-service crash loops** if an old copy isn't fully stopped+disabled before the new one starts — already happened once with tiktok-bot (11 days crash-looping, 30k+ restarts) per [[tiktok-bot-warp-vm-migration-fixes]]. Migrate one service at a time, verify, then kill the old copy — don't batch-cutover.
- **Dual exposure layer** (`.lan` Caddy + Cloudflare Tunnel) — per [[homelab-dual-exposure-layer]], forgetting to repoint *both* on cutover leaves the public domain 502ing even though the LAN route works fine.
- **DNS not a wildcard** — per [[pihole-lan-records-not-wildcard]] (now Technitium, same constraint), every `.lan` route needs an explicit A record; nothing auto-resolves.
- **Kube-OVN join-subnet / proxy-trust class of bug** doesn't apply anymore since this is flannel-backed k3s now, not Kube-OVN — but any reverse-proxy trust config (`--xff-src` etc.) should be re-verified against the new node's real LAN IP as peer, since that's the kind of assumption that broke silently before.
- **sed -i on bind-mounted files breaks container mounts silently** ([[sed-i-bind-mount-gotcha]]) — relevant if editing the Caddyfile or any bind-mounted config in place during the transition; use container restart or truncate+write instead.
- **warp-svc memory leak** ([[fedora-memory-audit-warp-svc-leak-daily-restart]]) — carry forward whatever periodic-restart mitigation exists, or add one in the NixOS unit if none exists yet.
- **px1 headroom** — host is already ~80% RAM used; sizing the new VM (especially if larger than the old one) may require freeing capacity first (e.g. the powered-off Talos VMs still reserve no RAM since they're off, but double-check nothing else is competing).

## 6. Decisions (locked 2026-09-09)

All three were open questions in the original draft; resolved via a wayfinder session and tracked on [the map (issue #1)](https://github.com/txtsamu/claude-research/issues/1) — closed decision tickets linked below for full rationale.

- **Install method: [`nixos-anywhere` + `disko`](https://github.com/txtsamu/claude-research/issues/2)**, confirmed over a manual ISO install or `nixos-infect` (community consensus was already against `nixos-infect` — no declarative disk partitioning, relies on lustrate).
- `services.caddy` and `services.technitium-dns-server` confirmed native nixpkgs modules — plan drops Podman for these two.
- **Secrets: [`agenix`](https://github.com/txtsamu/claude-research/issues/3)**, confirmed over sops-nix, for this box's secret count (see §2.1).
- **k3s topology: [keep single-node](https://github.com/txtsamu/claude-research/issues/4)**, confirmed as-is rather than using this migration to also reconsider HA/topology (that's a separate, later effort if pursued at all).

## 7. Verification pass (2026-09-09)

Checked the tooling assumptions above against current docs/discourse before finalizing:

- `services.k3s` — real, current nixpkgs module. [MyNixOS reference](https://mynixos.com/nixpkgs/options/services.k3s)
- `services.caddy`, `services.cloudflared` — real, stable, straightforward. [cloudflared module source](https://github.com/NixOS/nixpkgs/blob/release-26.05/nixos/modules/services/networking/cloudflared.nix)
- **NetBird — package is stable, module is not recommended (revised 2026-09-09).** The `netbird` package itself is in stable nixpkgs 25.11, but `services.netbird` carries several open bugs relevant to a self-hosted-management setup like this one (keeps connecting to NetBird's default cloud management even with a custom URL set, world-readable secrets, service-doesn't-start-after-upgrade). Plan now uses the package directly with a hand-written systemd unit instead of the module — see §2.5. [default-cloud-connection bug](https://github.com/nixos/nixpkgs/issues/523384), [world-readable secrets](https://github.com/NixOS/nixpkgs/issues/371286), [service doesn't start](https://github.com/NixOS/nixpkgs/issues/497484), [SSH-to-client failure](https://github.com/NixOS/nixpkgs/issues/505846)
- `services.technitium-dns-server` — **real, corrects the first draft's claim that Technitium has no module.** [module source](https://github.com/NixOS/nixpkgs/blob/7eee17a8a5868ecf596bbb8c8beb527253ea8f4d/nixos/modules/services/networking/technitium-dns-server.nix)
- `services.openiscsi` — real, confirmed as the option democratic-csi node initiators need. [NixOS Discourse thread](https://discourse.nixos.org/t/how-setup-iscsi/42129/2)
- `nixos-anywhere` over `nixos-infect` — current community consensus, kexec+disko vs. lustrate-based conversion. [nixos-anywhere no-os howto](https://github.com/nix-community/nixos-anywhere/blob/main/docs/howtos/no-os.md), [HN thread on nixos-infect maturity](https://news.ycombinator.com/item?id=38242334)
- `agenix` vs `sops-nix` — both current and maintained; agenix favored for simpler/fewer-secret setups, sops-nix for templated multi-secret configs. [NixOS Discourse overview](https://discourse.nixos.org/t/handling-secrets-in-nixos-an-overview-git-crypt-agenix-sops-nix-and-when-to-use-them/35462)
- `uv2nix` over `poetry2nix` — poetry2nix's own maintainers now point new users to uv2nix. [poetry2nix repo](https://github.com/nix-community/poetry2nix), [uv2nix announcement](https://discourse.nixos.org/t/uv2nix-build-develop-python-projects-using-uv-with-nix/58563)
- Proxmox+NixOS pattern (disko + `services.qemuGuest.enable`) matches other homelab write-ups doing this exact px→NixOS move. [NixOS + Proxmox declarative homelab](https://medium.com/@joshleecreates/nixos-proxmox-a-recipe-for-a-declarative-homelab-84d4a02360b6), [Proxmox to NixOS + Incus](https://www.nijho.lt/post/proxmox-to-nixos/)

## Notes on secrets

Every secret found during inventory (Cloudflare tunnel token, Technitium admin password, Camofox API key, Proxmox MCP API credentials, tiktok-bot `cookies.txt`/session files, Claude Code `.credentials.json`) is redacted above and was **not** copied into this file in raw form. Real values live only on `warp-vm` itself; when building the sops-nix/agenix secrets store for the new host, pull them fresh from the running services rather than from this doc.
