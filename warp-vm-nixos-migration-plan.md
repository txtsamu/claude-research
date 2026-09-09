---
type: investigation
tags: [nixos, warp-vm, migration, k3s, kubernetes, proxmox, mcp, tiktok-bot, technitium, caddy, cloudflared, netbird, democratic-csi, plan, px1, wayfinder]
created: 2026-09-09
status: current
last_verified: 2026-09-10
---

# warp-vm → NixOS migration

**Status: complete.** `home` (192.168.50.200) is the LAN's canonical host — DNS, reverse proxy, the public Cloudflare Tunnel, the k3s cluster and every app on it, the MCP trio, evomem, and every other service that used to run on `warp-vm`. `warp-vm` (Proxmox VMID 101) is powered off, kept as a rollback point for at least one month (user's decision, 2026-09-10) before any deletion decision.

This doc now describes the **final architecture** first, then the ticket-by-ticket history of how it got there, then the original pre-execution plan (§5 onward) kept for reference. For lessons learned / what to do differently next time, see [[warp-vm-nixos-migration-retrospective]] — that's the "how to do better" doc, this one is "what is true now and how we got here."

All 20 tickets (T1-T20, GitHub issues [#9-#28](https://github.com/txtsamu/claude-research/issues?q=is%3Aissue+9..28) in txtsamu/claude-research) are closed. Each issue's own resolution comment has the exact commands/values for its ticket — this doc summarizes, it doesn't replace them.

## Final architecture (as of 2026-09-10)

`home` — NixOS, flake at [github.com/txtsamu/home-nixos](https://github.com/txtsamu/home-nixos), Proxmox VMID 102 on `px1`, static IP `192.168.50.200/24` (took over `warp-vm`'s original IP in T19's cutover).

**Native NixOS services** (`hosts/home/*.nix` in the flake):
- `dns.nix` — Technitium DNS (`services.technitium-dns-server`), zone data copied wholesale from `warp-vm`
- `proxy.nix` — Caddy (`services.caddy`), reverse-proxies every `.lan` domain
- `tunnel.nix` — Cloudflare Tunnel (`services.cloudflared`), tunnel ID `83033670-...` named "home" in the dashboard, ingress config remote-managed via the Cloudflare API
- `vpn.nix` — NetBird, hand-written unit around the `netbird` package (not `services.netbird` — see §7's tooling notes for why)
- `k3s.nix` — k3s single-node cluster (`--disable-network-policy`, `--kube-proxy-arg=proxy-mode=nftables`, NFS client support, `/var/iscsi` for democratic-csi) + the Rancher/Fleet/cert-manager/MetalLB/democratic-csi platform layer, Helm-installed inside the cluster
- `evomem.nix` — evomem knowledge server, data on a dedicated TrueNAS iSCSI LUN (`/root/evomem-kb`, `/dev/sdb`)
- `mcp.nix` — hermes-gateway, hermes-mcp, proxmox-mcp-plus (hand-copied `/opt/hermes-venv` + `/opt/hermes-source`, not the official `hermes-agent` NixOS module — see the retrospective's §6 for why)
- `camofox.nix` — Camoufox anti-detection browser server, wrapped in `pkgs.steam-run` (NixOS-FHS fix)
- `tiktok-bot.nix` — the TikTok/IG/PornHub Telegram bot, own dedicated venv
- `headroom-proxy.nix` — context-compression proxy for Claude Code
- `checkmk-agent.nix` — host-monitoring agent reporting to the Checkmk server (itself running as a k3s app)
- `secrets.nix` — agenix, secrets encrypted at rest, safe to commit to the public flake repo

**k3s apps** (`homelab` namespace, MetalLB pool `192.168.50.240-252`): bookstack, checkmk, copyparty, couchdb, crawl4ai, openwebui, searxng, uptime-kuma, suwayomi, forgejo, nextcloud, immich, cekping-agent — 13 apps, all with live data verified (357,039 real asset rows in immich's postgres alone).

**Not migrated, deliberately out of scope**: jellyfin, grafana, oneterm (bastion), syncyomi — all already non-functional on `warp-vm`'s original cluster before this migration started, or explicitly dropped (syncyomi, decided in T4). Their `.lan` and `.ssamu.id` DNS entries were deliberately left pointing at now-dead backends rather than either fixed or cleaned up, in case they're revived later.

**Known, accepted tradeoffs** (not bugs, decisions):
- `home`'s memory runs hot — Checkmk flags it CRIT (157% of physical RAM committed across all containers). Honest cost of consolidating everything onto one 16GB box; worth a capacity look before adding more workloads.
- hermes-gateway uses a hand-rolled NixOS packaging instead of the project's own official module (Tier 2/best-effort per Hermes' own docs) — works, but more exposed to future FHS/dependency drift than the officially-supported path.
- `warp-svc`, `warp-bypass-setup.sh`, `microsocks`, `socks-relay`, `ovpn-relay` (the whole WARP-egress relay stack) — confirmed dropped, not ported (T6). NetBird replaced it.

## Ticket history

T1-T2 (#9-#10): provisioning + agenix secrets skeleton. T3-T8 (#11-#16): DNS, Caddy, Cloudflare Tunnel, NetBird, evomem, MCP trio — each verified working side-by-side with `warp-vm`'s originals, `warp-vm`'s copies deliberately left running until the T19 cutover (every client hardcoded warp-vm's IP directly, no hostname indirection to repoint early). T9-T10 (#17-#18): camofox-browser + tiktok-bot, the two riskiest hand-rolled Python services — tiktok-bot in particular recovered 1,361 lines of uncommitted local fixes with zero VCS backup before they could have been lost to a plain `git clone`. T11-T12 (#19-#20): headroom-proxy, checkmk agent. T13 (#21): k3s + the full platform layer stood up fresh, re-authorized against the same TrueNAS iSCSI backend (no data copy needed — PVC data lives on the NAS). T14-T18 (#22-#26): the 13 apps redeployed one at a time, each with `warp-vm`'s copy genuinely stopped (not deferred — RWO iSCSI storage makes running two copies against the same backing volume actively dangerous) immediately after the new copy was verified.

**T19 (#27) — the cutover** — the highest-risk single ticket: moved the shared LAN IP itself. Found and handled, in order: `home`'s own Caddy config was still on pre-migration IPs (deferred here deliberately since T14); DNS needed no changes (the whole zone had been copied wholesale from `warp-vm` back in T3, already pointing at the target IP); a live, never-inventoried workload turned up mid-cutover (`cekping-agent`, an external ping-monitoring client with zero prior mention anywhere in this migration) and was migrated on the spot rather than allowed to break silently; the whole WARP-egress relay stack (confirmed dead weight since T6) was finally stopped for real; Checkmk's host entries were corrected; and — caught by the user, not by the work itself — Proxmox's own cloud-init VM config still had the temp IP, which would have silently reintroduced it on any future re-provision.

**Post-T19, same-day incident** — a real regression (not caught before closing T19): changing `home`'s interface IP never triggered a `k3s` restart, so the Kubernetes Node object kept the stale IP, which broke MetalLB's speaker and cascaded into every migrated `.lan` route going down plus several platform pods CrashLoopBackOff-ing. Fixed with `systemctl restart k3s`. In the same incident: `rancher.lan` (pointed at the now-dead `warp-vm` Rancher, repointed to `home`'s own), three of hermes-gateway's stdio MCP integrations (`camofox`/`evomem`/`crawl4ai`, three separate root causes), Telegram support (a real T8 gap — the `messaging` dependency extras were never installed), and — found afterward, at the user's prompting — 11 real `.ssamu.id` production hostnames that had silently been dead since `warp-vm`'s original tunnel died in the cutover, root-caused via the Cloudflare API and fixed by rebuilding the ingress config on the live tunnel and repointing DNS. The dead tunnel was deleted afterward.

**T20 (#28) — decommission.** Closed with the user's own retention policy: `warp-vm` stays powered off on `px1` for at least one month before any deletion decision, satisfying the ticket's "shut down, not deleted, deletion deferred" criteria directly.

Full details, exact commands, and exact values for every one of the above are in each ticket's own resolution comment — this section is the index, not the source of truth.

## Open items / flagged for the user's attention

- **4 forgejo repos have no GitHub mirror** (`capstone_project_documents`, `novia-app`, `novia-model`, `novia-web-api`, found in T16) — worth a deliberate backup decision before `warp-vm` is ever deleted.
- **`home`'s memory overcommit** (157% CRIT per Checkmk) — not urgent, but a real capacity constraint on this box as-is.
- **`hermes` CLI isn't on the interactive `moo` user's PATH on `home`** — works fine as root/via full path, minor convenience gap only.
- A handful of pre-existing/out-of-scope apps stay broken by design: jellyfin, grafana, oneterm (bastion), syncyomi (`.lan` and `.ssamu.id` both) — not a byproduct of this migration, already non-functional before it started.

## Retention / decommission plan

`warp-vm` (VMID 101) stays powered off on `px1`, not deleted, for **at least one month from 2026-09-10** (the user's stated policy). Revisit deletion after that window — at minimum, confirm the forgejo-mirror decision above has been made first, since some of those repos' only copy may be on `warp-vm`'s disk.

---

## Original pre-execution plan (2026-09-09, kept for historical reference)

Everything below this line was written *before* execution, as the initial inventory and design. It's kept verbatim as a record of what was planned and why — cross-reference against "Final architecture" and "Ticket history" above for what actually happened, which sometimes differed from what's described here (e.g. the phased plan's step ordering, or the exact NixOS module choices for hermes/tiktok-bot, which ended up hand-rolled rather than uv2nix-built as originally suggested).

### 0. Original topology (warp-vm, pre-migration)

- `px1` (alias `pve-pc`) — Proxmox VE 9.2.11 host, 16c/62.7GiB RAM, HP EliteDesk 705 G4. Already tight on RAM (~80% used before this migration; see [[homelab-k8s-ram-overhead-analysis]]).
- `warp-vm` = Proxmox VMID **101**, **8 vCPU / 16GiB RAM** (confirmed via `qm config 101` — deliberate current allocation, not a stale doc), 100GB disk (`/dev/sda1`, 68G used / 72%), Debian 13 (trixie), static LAN IP **192.168.50.200/24**, gw `192.168.50.1`, single NIC `eth0`.
- It was **not** a spare bastion — it was the single most heavily-loaded host in the homelab: a k3s control-plane + Rancher stack, ~13 user-facing apps, a TikTok/IG/PH bulk-downloader Telegram bot, the evomem knowledge server, both Hermes MCP services, the Proxmox MCP server, DNS for the whole LAN (Technitium), the LAN reverse proxy (Caddy), the Cloudflare Tunnel, NetBird mesh client, and multiple SOCKS/TCP relay shims for WARP egress. See [[talos-to-k3s-migration-warp]] and [[tiktok-bot-warp-vm-migration-fixes]] for prior history on this box.

### 1. Full inventory (source of truth for what had to be reproduced)

#### 1.1 Bare-metal / systemd services (non-k8s)

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
| `evomem.service` | Knowledge server, REST API on :7700 | native binary `/usr/local/bin/evomem` | `--knowledge /root/evomem-kb serve --host 0.0.0.0 --port 7700`; **the knowledge base directory `/root/evomem-kb` is the single most important thing to not lose** — it's the shared memory every Claude Code session (homelab+fedora) auto-captures into |
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

#### 1.2 k3s cluster (single-node, `homelab` namespace + platform)

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

#### 1.3 MCP surfaces (explicitly called out by user — don't lose these)

- `hermes-mcp.service` + `hermes-gateway.service` — Hermes' own MCP bridge/gateway, config under `/root/.hermes/`.
- `proxmox-mcp-plus.service` — MCP server for Proxmox, config `/etc/proxmoxmcp/config.json` (has Proxmox API creds).
- evomem itself is consumed as an MCP server (`mcp__evomem__*` tools) — the REST API on :7700 is what backs it; the MCP wiring is on each *client* machine's Claude Code config, but the server-side data (`/root/evomem-kb`) lives on warp.
- Claude Code's own config on warp: `/home/moo/.claude.json` (+ `/home/moo/.claude/` — credentials, sessions, settings) — if warp itself runs Claude Code sessions (it does; evomem captures sessions tagged `homelab`), this is local state to carry over too. `/home/moo/.claude/.credentials.json` is a **secret**.

#### 1.4 tiktok-bot specifics

`/opt/tiktok-bot` was a **local git repo** (`.git/` present). The f2 fix from [[tiktok-bot-warp-vm-migration-fixes]] was already a **tracked patch**: `patches/f2-device-id-manager-fallback.patch` + `patches/apply.sh`.

**Actual stateful data that needed rsyncing** (not code — code came via git):
- 7 cookie files (all **secrets**): `cookies.txt`, `tiktok_cookies.txt`, `user_cookies.txt`, `ph_cookies.txt`, and `cookies/{facebook,instagram,nhentai,patreon,reddit,twitter}_cookies.txt`
- `watchlist.json` (267KB) — the real persistent watch state
- Per-target scrape state: `scripts/*_capture_state.json`, `*_links.json`, `*_recon.json`

### 2. NixOS target design (as planned)

Recommended: new Proxmox VM (new VMID) on `px1`, installed via `nixos-anywhere` + `disko`, in parallel with the live `warp-vm` — not an in-place conversion, matching the "parallel build + staged cutover" pattern this migration actually followed.

Key decisions made before writing Nix (see §6/§7 below for the research behind each):
1. **Secrets: agenix**, not sops-nix — modest secret count, no templated multi-secret configs needed.
2. **k3s: `services.k3s`**, a real nixpkgs module. Rancher/Fleet/cert-manager/MetalLB/democratic-csi installed via Helm *inside* the cluster, not as Nix modules. `services.openiscsi` for the iSCSI initiator side.
3. **Technitium and Caddy: native nixpkgs modules** (`services.technitium-dns-server`, `services.caddy`), dropping Podman for both.
4. **Python services (hermes, tiktok-bot, camofox, headroom-proxy): plain `uv`-managed venvs**, not full uv2nix hermetic builds — a pragmatic middle ground given how actively these bots change. (In practice this meant hand-copying the venvs from `warp-vm` rather than building fresh via `uv2nix` — see the retrospective for the tradeoffs this created.)
5. **NetBird: package only, not `services.netbird`** — the module had several 2026-era open bugs (default cloud-management connection, world-readable secrets, service-doesn't-start-after-upgrade) irrelevant to the plain package.

### 3. Data that had to be copied (not just config)

| Data | Location on warp | Destination |
|---|---|---|
| evomem knowledge base | `/root/evomem-kb` | Moved to a dedicated TrueNAS iSCSI LUN on `home`, not a straight rsync-to-same-path — an enhancement beyond the original plan, done mid-T7 at the user's request |
| tiktok-bot code | `/opt/tiktok-bot/` (git repo) | `git clone` + `patches/apply.sh` |
| tiktok-bot state | 7 cookie files, `watchlist.json`, per-target scrape state | rsync |
| Hermes state | `/root/.hermes/` | rsync |
| Caddy TLS data | `/root/caddy/data`, `/root/caddy/config` | Let it re-issue on `home` instead (ACME certs are cheap to regenerate) |
| k8s app data | TrueNAS-backed PVCs via democratic-csi | **Stayed on the NAS** — only the new node's iSCSI initiator needed authorizing against the same TrueNAS targets, confirmed no data copy was actually needed |
| Camofox addons | `/root/camofox-browser/addons/quetta_xpi` | rsync |
| `/mnt/photos` NFS mount | from `192.168.50.10` | NixOS `fileSystems` entry |

### 4. Suggested phased plan (as planned — see "Ticket history" above for what actually happened)

1. Freeze & document the full inventory (§1 above).
2. Stand up a NixOS skeleton on a new VM — base networking, SSH, users, flake scaffolding, no workloads yet.
3. Migrate infra services one at a time, in dependency order, each verified working before moving to the next, keeping `warp-vm`'s copies running until each is confirmed good.
4. Bring up k3s on the new host, re-authorize against the same TrueNAS iSCSI backend, re-deploy the platform Helm stack and the 13 app manifests.
5. DNS/IP/hostname cutover — move the shared LAN IP itself once everything is verified side-by-side.
6. Decommission — shut down (don't delete) the old VM as a rollback point once the new one has run clean.

### 5. Risks identified up front (and whether they actually materialized)

- **Duplicate-service crash loops** if an old copy isn't fully stopped+disabled before the new one starts — the exact failure mode already seen once with tiktok-bot pre-migration (11 days crash-looping, 30k+ restarts per [[tiktok-bot-warp-vm-migration-fixes]]). *Did not recur* during this migration — the one-app-at-a-time discipline held.
- **Dual exposure layer** (`.lan` Caddy + Cloudflare Tunnel) — forgetting to repoint both on cutover. *Did happen*, in a delayed form: T5 only ever verified the tunnel side with a throwaway hostname, and the real hostnames silently broke a full day later when the old tunnel died — see the retrospective's §3.
- **DNS not a wildcard** — every `.lan` route needs an explicit A record. Not an issue in practice since the whole zone was copied wholesale rather than rebuilt by hand.
- **sed -i on bind-mounted files breaks container mounts silently** — *did happen*, once, during T17's Caddyfile edit on `warp-vm`; recovered via `systemctl restart caddy.service`.
- **px1 headroom** (already ~80% RAM used pre-migration) — not directly hit, but `home`'s own memory overcommit (157% CRIT per Checkmk) is the same underlying capacity pressure surfacing on the new box instead.

### 6. Decisions (locked 2026-09-09, before execution)

- **Install method: [`nixos-anywhere` + `disko`](https://github.com/txtsamu/claude-research/issues/2)**, over a manual ISO install or `nixos-infect`.
- **Secrets: [`agenix`](https://github.com/txtsamu/claude-research/issues/3)**, over sops-nix.
- **k3s topology: [keep single-node](https://github.com/txtsamu/claude-research/issues/4)**, not a separate HA/topology reconsideration.

### 7. Tooling verification pass (2026-09-09, before execution)

- `services.k3s`, `services.caddy`, `services.cloudflared`, `services.technitium-dns-server`, `services.openiscsi` — all confirmed real, current, maintained nixpkgs modules/options.
- **NetBird — package stable, module not recommended.** Several open 2026 bugs in `services.netbird` (default-cloud-management connection even with a custom URL set, world-readable secrets, service-doesn't-start-after-upgrade, SSH-to-client failures) made a hand-written unit around the plain package the safer choice.
- `nixos-anywhere` over `nixos-infect` — current community consensus (kexec+disko vs. lustrate-based conversion).
- `agenix` vs `sops-nix` — both current/maintained; agenix favored for this box's modest, non-templated secret count.
- `uv2nix` over `poetry2nix` — poetry2nix's own maintainers now point new users to uv2nix (though in practice, T8's actual Python services ended up hand-copied rather than uv2nix-built — see the retrospective).

## Notes on secrets

Every secret found during the original inventory (Cloudflare tunnel token, Technitium admin password, Camofox API key, Proxmox MCP API credentials, tiktok-bot cookies/session files, Claude Code credentials) was redacted in this doc and never committed in raw form. Real values live in `home`'s agenix-encrypted secrets store now, pulled fresh from the running services during migration rather than copied from this doc.
