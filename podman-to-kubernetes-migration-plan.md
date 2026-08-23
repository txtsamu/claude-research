---
type: investigation
tags: [kubernetes, podman, migration, proxmox, talos, k3s, homelab-vm, democratic-csi]
created: 2026-08-23
last_verified: 2026-08-24
status: current — Wave 1 deployed and verified on the Talos cluster; Caddy/DNS cutover not done yet, homelab-vm podman instances still authoritative for traffic
---

# Migrating `homelab-vm`'s Podman services to Kubernetes, for learning

## Goal

User wants to move (some/all of) the Podman Quadlet services currently running on `homelab-vm` to a Kubernetes deployment, primarily to **learn and practice managing Kubernetes** in the homelab — not because Podman is failing at anything.

## Current state (updated 2026-08-24)

`homelab-vm` (Proxmox VM 100 on `pve-pc`) runs Podman containers via Quadlet. Rough inventory by risk tier (corrected against the live host on 2026-08-24 — the original inventory below had drifted):

- **Critical / stateful, hard to lose**: Forgejo (git server), Nextcloud, Immich, OneTerm (+ its mysql/redis/guacd/acl sidecars).
- **Stateful but recoverable**: Grafana, Jellyfin, BookStack, Suwayomi, copyparty, CouchDB (Obsidian LiveSync), Open WebUI.
- **Stateless / disposable**: SearXNG, Uptime Kuma, cekping-agent, FlareSolverr, crawl4ai — this is Wave 1, see below.
- **Infra that resists containerized k8s networking**: Pi-hole (wants port 53/67 + host networking for DNS/DHCP), Caddy (current reverse proxy in front of everything).
- **Removed, no longer in scope**: ~~Vaultwarden~~ and ~~9router~~ — user confirmed both were intentionally decommissioned (not a silent outage, as first suspected when their Caddy routes were found dangling with nothing listening behind them). Vaultwarden's replacement (Passbolt) is a future, separate project. Their dead `*.lan` Caddy routes are still in the Caddyfile and worth cleaning up whenever convenient.
- **Found running but missing from the original inventory**: `openwebui`, `mihon` (Suwayomi's Caddy alias), `virtualmin`, `proxcenter` — the original service list wasn't exhaustive; noting here so a future pass doesn't miss them when scoping Wave 2/3.
- **Not containerized, out of migration scope entirely**: `cloudflared`, `evomem`, `hermes-gateway`/`hermes-mcp`, `headroom-proxy`, `camofox-browser`, `proxmox-mcp-plus`, `claude-telegram`, `tiktok-bot` — native host systemd services, nothing to move.

Nextcloud/Immich/photo data lives on NFS exports (`/mnt/nextcloud`, `/mnt/immich-upload`, `/mnt/photos`, `/mnt/obsidian-livesync`) from a separate NAS host — not local to `homelab-vm`.

Proxmox host capacity (`pve-pc`): 16 cores / 62.7GB RAM, only ~20.5GB RAM in use by the two existing VMs; `local-lvm` has 287G free after the fstrim fix in [[homelab-lvm-thin-reclaim-fstrim]] — comfortably enough room to stand up a K8s cluster as new VMs without touching `homelab-vm`.

## Recommended approach (not yet started)

1. **Build a separate cluster on new VMs — don't convert `homelab-vm` in place.** Zero blast radius on the currently-running services while learning.
2. **Distro choice is the open fork** — see below.
3. **Reuse the existing NFS exports as PVs** (NFS CSI driver, or `nfs-subdir-external-provisioner`) instead of copying Nextcloud/Immich data — makes eventual cutover a config change, not a data migration.
4. **Migrate in three waves**, cheapest/safest first:
   - Wave 1 — stateless containers (SearXNG, Uptime Kuma, cekping-agent, 9router, FlareSolverr, crawl4ai): learn Deployments/Services/Ingress with nothing to lose.
   - Wave 2 — recoverable stateful (Grafana, Jellyfin, BookStack, Suwayomi, copyparty): learn PVCs/StatefulSets, still low stakes.
   - Wave 3 — critical stateful (Nextcloud, Immich, Forgejo, Vaultwarden): only after a full backup/restore drill has been proven in the new cluster at least once.
   - Pi-hole: leave on Podman/host networking unless/until `hostNetwork` + MetalLB (L2 announce) is specifically wanted — not worth the pain for a DNS server that needs to survive cluster hiccups.
5. **Keep `homelab-vm` running throughout.** Point Caddy at whichever backend (Podman container or k8s Ingress) is currently authoritative per-service during the transition; don't decommission a Podman service until its k8s replacement has run stable for a while.

## Decision resolved: Talos

Talos was chosen — immutable/API-driven, pairs the K8s learning goal with IaC/GitOps practice, more transferable to real production clusters than k3s's fast-but-opaque bootstrap. Full build (3 control-plane + 3 worker, Terraform + `bpg/proxmox`, `democratic-csi` for iSCSI storage, MetalLB for LoadBalancer IPs, Rancher for the UI) is documented in [[talos-kubernetes-cluster-buildout]] — cluster is live and verified end-to-end as of 2026-08-23.

## Wave 1: deployed and verified (2026-08-24)

All 5 real Wave-1 candidates are running on the Talos cluster in a dedicated `homelab` namespace: **Uptime Kuma, SearXNG, cekping-agent, FlareSolverr, Crawl4AI**. `9router` dropped (decommissioned, see above).

### Which to prioritize, and why

Checked actual signals before deciding an order, rather than treating all 5 as equally low-stakes:

- **Restart counts**: all 5 showed `NRestarts=0` on their systemd units — none crash-looping, stability wasn't a differentiator.
- **Resource usage**: all trivially light (13-208MB RAM, <2% CPU) via `podman stats` — no capacity pressure either.
- **Actual traffic**: checked the Caddyfile — **only Uptime Kuma is reverse-proxied and exposed** (`uptime.lan`). SearXNG/cekping-agent/FlareSolverr/Crawl4AI aren't in Caddy at all.

Uptime Kuma went first: it's the only one with confirmed real usage, and it doubles as the observability tool for watching the rest of the migration as it happens.

### Storage: NAS-backed via `democratic-csi`, prepared ahead of deployment

Checked each service's actual podman quadlet for real persistent state before assuming anything:

| Service | Real persistent data? | Volume/mount found |
|---|---|---|
| Uptime Kuma | **Yes** — 382MB (SQLite DB, monitor history, uploads) | `Volume=uptime-kuma-data.volume:/app/data` |
| SearXNG | Minimal — a single ~600-byte `settings.yml`, data dir empty | `/opt/searxng/settings.yml` + `/opt/searxng/data` bind mounts |
| Crawl4AI | Empty (outputs dir exists but unused) | `Volume=crawl4ai-data.volume:/var/lib/crawl4ai/outputs` |
| cekping-agent | **None** — no `Volume=` lines at all | — |
| FlareSolverr | **None** — no `Volume=` lines at all | — |

Created a `homelab` namespace and 3 `truenas-iscsi`-backed PVCs ahead of deploying anything (`uptime-kuma-data` 2Gi, `searxng-data` 1Gi, `crawl4ai-data` 1Gi) — every PVC on that StorageClass is a real dynamically-provisioned zvol on TrueNAS via `democratic-csi`, satisfying "use NAS, not local storage, and persistent" directly. All bound successfully on first try.

### Resource sizing

Based on actual `podman stats` idle readings, padded for realistic peak load — flaresolverr and crawl4ai both run full headless Chromium instances, which spike far above their idle baseline during real work:

| Service | Request (CPU/Mem) | Limit (CPU/Mem) |
|---|---|---|
| uptime-kuma | 50m / 128Mi | 300m / 512Mi |
| searxng | 20m / 64Mi | 300m / 256Mi |
| cekping-agent | 10m / 32Mi | 100m / 128Mi |
| flaresolverr | 100m / 256Mi | 1000m / 1Gi |
| crawl4ai | 100m / 256Mi | 1500m / 1.5Gi |

Total requested (~280m CPU / ~736Mi RAM) was trivial against cluster headroom — no node resize needed for Wave 1, unlike the earlier Rancher/MetalLB/CSI capacity incidents.

### Gotchas hit deploying these 5

1. **Secrets found in plaintext quadlet configs** — `cekping-agent`'s API token, and `crawl4ai`'s API token + a DeepSeek LLM API key (in an `EnvironmentFile=`), plus SearXNG's session `secret_key` (embedded in `settings.yml`). All moved into Kubernetes `Secret` objects (`stringData`/`envFrom`), not plain manifests.
2. **`FlareSolverr` shares Suwayomi's pod on `homelab-vm`** (`Pod=suwayomi.pod` in the quadlet) — Suwayomi (Wave 2, not migrated) reaches it over localhost as a Cloudflare-bypass helper. Deployed FlareSolverr's k8s manifest, but this does **not** cut over the podman side — Suwayomi's config would need repointing at the new Service first, or this genuinely waits for Suwayomi's own Wave 2 migration. Flagging so nobody deletes homelab-vm's FlareSolverr container thinking Wave 1 is a clean cutover.
3. **Talos's default `baseline` PodSecurity policy again** — `cekping-agent` needs `NET_RAW` (matching `AddCapability=NET_RAW` in its quadlet), which `baseline` blocks. Same fix as `democratic-csi`/MetalLB: `kubectl label namespace homelab pod-security.kubernetes.io/enforce=privileged`.
4. **Kubernetes' Docker-links-style env var injection collided with Crawl4AI's own config convention.** Kubernetes auto-injects `<SERVICE>_PORT` env vars (Docker-links legacy behavior) into every pod in a namespace for every Service present — `CRAWL4AI_PORT=tcp://10.100.40.42:11235` for the `crawl4ai` Service. Crawl4AI's own app reads an env var literally named `CRAWL4AI_PORT` to pick its listen port, and the auto-injected one silently won, breaking gunicorn (`'tcp://...' is not a valid port number`). Fixed with `enableServiceLinks: false` on the pod spec — added to all 5 deployments preemptively, not just the one that broke, since any of them could collide with some other service's naming later.
5. **Podman `Tmpfs=` vs Kubernetes `emptyDir` are not equivalent.** Crawl4AI's original quadlet used `ReadOnly=true` + `Tmpfs=/home/appuser` for hardening. Mirroring that with `readOnlyRootFilesystem: true` + an `emptyDir` at `/home/appuser` broke it: Podman's tmpfs mount preserves the image's existing files at that path (copy-up semantics), but Kubernetes' `emptyDir` always starts genuinely empty, fully hiding the image's baked-in Playwright/Chromium browser cache that lived under `/home/appuser/.cache/ms-playwright/`. Playwright then failed to find its browser binary at all. Fix: dropped `readOnlyRootFilesystem` for this one container and removed the `/tmp`/`/home/appuser` mounts entirely, letting them stay part of the normal writable container layer — same effective behavior as the original.

### Data migration: Uptime Kuma done, others trivially already in sync

SearXNG and Crawl4AI had no real data to move (confirmed empty on both the source and freshly-provisioned destination). Uptime Kuma's 382MB was migrated for real:

1. Stopped `uptime-kuma-app.service` on `homelab-vm` briefly for a clean, consistent copy (SQLite, avoid copying mid-write) — `tar czf` the volume (382MB → 104MB compressed), immediately restarted the source so `uptime.lan` kept working via Caddy throughout (a few seconds of downtime total).
2. Scaled the k8s Deployment to 0 to release the RWO PVC, launched a throwaway `busybox` pod with the same PVC mounted, `kubectl cp`'d the tarball in and extracted it there, deleted the helper pod, scaled the real Deployment back to 1.
3. Verified for real, not just "pod is Running": the new pod's logs show `Load JWT secret from database` and no `No user, need setup` prompt — confirms it loaded the actual migrated DB, not a fresh empty one.

**Important caveat going forward**: both the `homelab-vm` podman instance and the new k8s instance now hold independent copies of the data as of the copy timestamp. Caddy/DNS still point traffic at the podman instance — nothing has been cut over yet. Any changes made on the podman side from this point on (new monitors, edits) will **not** appear on the k8s side until either a re-sync or the actual cutover happens. Avoid making changes on the old instance if avoidable, and do a final re-sync immediately before whenever the real cutover happens.

### Update 2026-08-24: found and fixed a real ISP-level bug blocking internet-dependent apps

SearXNG (live search results), cekping-agent (`cekping.id:50051`), Crawl4AI (crawling external sites), and FlareSolverr were all deployed and `Running`, but couldn't actually reach the internet — not a bug in these apps or their manifests. Root cause turned out to be an ISP/modem issue (delivering replies with an already near-exhausted TTL, breaking any traffic needing an extra internal hop) that had nothing to do with Kubernetes, Talos, or the CNI — full investigation and fix in [[pod-internet-egress-isp-ttl-bug]]. Along the way, the cluster's CNI was also switched from Flannel to Kube-OVN (a legitimate improvement either way, given KubeVirt is a future goal here, but it did not actually fix this particular bug — the ISP-side TTL fix did). All 4 of these services should now have real internet connectivity — worth re-verifying their actual functionality (not just pod health) now that the fix is in.

### Still open before Wave 1 is truly "done"

- [ ] Actual traffic cutover: repoint Caddy's `uptime.lan` (and decide an access story for the other 4, none of which were externally exposed to begin with) at the new cluster — not done, both stacks are running in parallel right now
- [x] Clean up the dangling `9router.lan` / `vaultwarden.lan` Caddy routes → done 2026-08-24. Both blocks removed from `/root/caddy/Caddyfile` (backed up first as `Caddyfile.bak.20260824`), config validated + reloaded live via `podman exec caddy caddy reload`, zero downtime for the other routes. Verified: both dead hostnames now refuse the TLS connection (no matching site), `uptime.lan`/`jellyfin.lan` unaffected.
- [ ] Decide when it's safe to stop/remove the `homelab-vm` podman containers for these 5 services (only after the above cutover + a stability-watch period, per the original "don't decommission until proven stable" rule)

## Next: Wave 2

Recoverable stateful tier (Grafana, Jellyfin, BookStack, Suwayomi, copyparty, CouchDB, Open WebUI) — not started. Expect this to need real node capacity planning (unlike Wave 1's trivial footprint) given the CP/worker RAM incidents already hit once during cluster buildout and once during platform-tool installation.
