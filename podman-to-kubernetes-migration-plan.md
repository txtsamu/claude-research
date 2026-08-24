---
type: investigation
tags: [kubernetes, podman, migration, proxmox, talos, k3s, homelab-vm, democratic-csi]
created: 2026-08-23
last_verified: 2026-08-24
status: current — Wave 1 + Wave 2 fully deployed, migrated, and cut over (both Caddy and Cloudflare Tunnel); homelab-vm podman containers for these apps stopped
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

- [x] Actual traffic cutover: `uptime.lan` → done 2026-08-24. Final data re-sync (podman → k8s PVC, same tar/kubectl-cp procedure as the initial migration) to catch any drift since 2026-08-23, then `uptime-kuma` Service converted `ClusterIP` → `LoadBalancer` (MetalLB, `192.168.50.223`), then Caddy's `uptime.lan` repointed at that IP. Podman-side `uptime-kuma-app.service` stopped (not removed — kept for rollback per the "don't decommission until proven stable" rule). Verified for real: `uptime.lan` returns 302 with the podman container inactive, so nothing else could be serving it. The other 4 Wave 1 apps were never in Caddy to begin with (confirmed with the user) — out of scope for this cutover, staying internal-only.
  - **Real gotcha hit**: GNU `sed -i` on a config file that's bind-mounted into a running container (Caddy's Podman Quadlet mounts `/root/caddy/Caddyfile` as a single-file bind mount) silently breaks the mount — `sed -i` writes a new file and `rename()`s it over the original, swapping the inode; the container keeps its bind mount on the old, now-detached inode, so it keeps serving stale content forever with zero error, and `caddy reload` reports success while doing nothing (it re-reads the same stale path inside the container's own mount namespace, which never changed). Cost real debugging time (502s that looked like a network/reachability problem, not a stale-config problem) before catching it with a live-marker test (write a unique string on the host, `podman exec cat` from inside — didn't show up). **Fix**: `systemctl restart caddy.service` to force a fresh bind mount. **For next time**: restart the container after any `sed -i` edit to a bind-mounted single file, or avoid `sed -i` for these entirely and use an in-place truncate+write instead (e.g. Python's `open(path, 'w').write(...)`, which does not rename the inode — this is exactly why the same-day dangling-routes cleanup earlier in this doc *did* survive its own reload without a restart, since that edit used Python's write, not `sed -i`).
- [x] Clean up the dangling `9router.lan` / `vaultwarden.lan` Caddy routes → done 2026-08-24. Both blocks removed from `/root/caddy/Caddyfile` (backed up first as `Caddyfile.bak.20260824`), config validated + reloaded live via `podman exec caddy caddy reload`, zero downtime for the other routes. Verified: both dead hostnames now refuse the TLS connection (no matching site), `uptime.lan`/`jellyfin.lan` unaffected.
- [ ] Decide when it's safe to stop/remove the `homelab-vm` podman containers for these 5 services (only after the above cutover + a stability-watch period, per the original "don't decommission until proven stable" rule)

## Cloudflare Tunnel: the other exposure layer (2026-08-24)

Discovered mid-cutover that `homelab-vm` has **two independent exposure layers per service**, not one: the internal Caddy `*.lan` reverse proxy (LAN-only) *and* a Cloudflare Tunnel (`px1`, tunnel ID `968b7dea-aade-4f0a-9393-71ff3b283744`, account `5e3e62b41620c6d3525989b70f1031c1`, zone `<PERSONAL_DOMAIN>` = `7937113d9d879e43f9e5ec5b7e9e0193`) publishing 15 public `*.<PERSONAL_DOMAIN>` hostnames, all pointing at `localhost:<port>` on `homelab-vm` (cloudflared runs natively there via a token-based/remote-config connector — no local `config.yml`, ingress rules live entirely at Cloudflare's edge, managed via their API). Full API pattern (auth, token recovery, ingress PUT semantics, hostname add/remove order) is documented in Hermes' own `cloudflare-tunnel-api` skill (`/root/.hermes/skills/devops/cloudflare-tunnel-api/`) — reused directly rather than re-deriving it.

**Real regression caught and fixed**: `up.<PERSONAL_DOMAIN>` (Uptime Kuma's public hostname) was still pointing at `localhost:3001` — the podman container stopped during the Wave 1 Caddy cutover — so the public domain had been silently `502`ing since that cutover, missed because only the internal `uptime.lan` route was checked at the time. Fixed by repointing `up.<PERSONAL_DOMAIN>`'s ingress rule to `http://192.168.50.223:3001` (the same k8s MetalLB LoadBalancer IP `uptime.lan` already uses). Verified `302` afterward, spot-checked other hostnames untouched.

**Also cleaned up**: `vault.<PERSONAL_DOMAIN>` → `localhost:8880`, a dangling route to the already-decommissioned Vaultwarden (same story as the `vaultwarden.lan` Caddy route cleaned up earlier). Removed the DNS CNAME first, then the ingress rule (correct order — DNS before ingress, per the Hermes skill's documented removal procedure, avoids a dangling CNAME pointing at a tunnel that no longer serves that host). Verified `530` (Cloudflare's "no DNS record" response) afterward.

**Lesson for every remaining cutover, Wave 1's leftover 4 apps included and all of Wave 2**: repointing Caddy's `.lan` route is **not sufficient** — the matching `*.<PERSONAL_DOMAIN>` Cloudflare Tunnel ingress rule (if one exists for that service) must be repointed too, or the public domain silently breaks while the internal one looks fine. Current `*.<PERSONAL_DOMAIN>` -> `localhost:port` map relevant to future waves:

| Hostname | Port | Service |
|---|---|---|
| `book.<PERSONAL_DOMAIN>` | 8810 | BookStack (Wave 2) |
| `grafana.<PERSONAL_DOMAIN>` | 3000 | Grafana (Wave 2) |
| `jelly.<PERSONAL_DOMAIN>` | 8096 | Jellyfin (Wave 2) |
| `ai.<PERSONAL_DOMAIN>` | 8080 | Open WebUI (Wave 2) |
| `copy.<PERSONAL_DOMAIN>` | 3923 | copyparty (Wave 2) |
| `mihon.<PERSONAL_DOMAIN>` | 4567 | Suwayomi (Wave 2) |
| `obsidian.<PERSONAL_DOMAIN>` | 5984 | CouchDB/Obsidian LiveSync (Wave 2) |

(`agent.<PERSONAL_DOMAIN>`/8642 = headroom-proxy, `git.<PERSONAL_DOMAIN>`/3500 = Forgejo, `bas.<PERSONAL_DOMAIN>`/8666 = OneTerm, `photos.<PERSONAL_DOMAIN>`/2283 = Immich, `cloud.<PERSONAL_DOMAIN>`/8181 = Nextcloud, `warp.<PERSONAL_DOMAIN>` = SSH to warp-vm — all out of current migration scope, listed here only for completeness of the tunnel inventory.)

## Wave 2: deployed, data migrated, verified (2026-08-24)

All 7 recoverable-stateful apps (Grafana, Jellyfin, BookStack [app+db], Suwayomi, copyparty, CouchDB, Open WebUI) are deployed to the `homelab` namespace with real migrated data and confirmed healthy. Same discipline as Wave 1: deploy fresh first, verify pod health, migrate real data (stop podman source -> tar -> load into PVC via a helper pod -> restart podman source -> scale k8s deployment back up), verify the migrated data actually loaded (not just "pod is Running"). No Caddy/tunnel cutover yet -- podman instances stay authoritative for traffic until that happens per-service.

### Storage

7 Secrets (real credentials carried over, same as Wave 1's handling) + 8 `truenas-iscsi` PVCs, sized off actual usage with headroom: grafana-data 2Gi, bookstack-db-data 3Gi, bookstack-app-data 1Gi, copyparty-config 512Mi, jellyfin-config **4Gi (bumped from 1Gi -- see gotcha below)**, openwebui-data 3Gi, suwayomi-data 5Gi, couchdb-data 2Gi. Plus one NFS-backed PV/PVC (`photos-nfs`, RWX) pointed directly at the existing TrueNAS export (`192.168.50.10:/mnt/data/photos`) -- reused as-is for Jellyfin (read-only) and copyparty (read-write), no data copy needed for photos at all, per the plan's own "reuse NFS exports" recommendation.

### Gotchas hit deploying these 7

1. **Secret volumes are always read-only -- breaks anything that needs to write into the same directory.** CouchDB's entrypoint writes its own generated `docker.ini` into `/opt/couchdb/etc/local.d/` alongside the mounted config; mounting the config Secret directly there gave `Read-only file system`. Fixed with an init container that copies the Secret's file into a writable `emptyDir`, which is what actually gets mounted.
2. **Non-root images need `fsGroup`, not just PVC access.** Grafana (uid 472) and Suwayomi (uid 1000) both crashed with `Permission denied` writing to their PVCs -- freshly-provisioned iSCSI volumes are root-owned by default. Fixed with `securityContext.fsGroup` matching each image's UID.
3. **Same stuck-rollout deadlock as the `ovn-central` incident, twice.** After patching `fsGroup`, the new pod landed on a different node than the still-crashing old one and couldn't attach its RWO volume until the old pod released it -- but the old ReplicaSet just kept recreating broken replicas every time the pod was deleted directly. Fixed both times by scaling the *old ReplicaSet* to 0, not deleting the pod.
4. **Real bug in the doc's own domain redaction: don't redact live config.** `<PERSONAL_DOMAIN>` placeholder (correct for this doc) accidentally ended up literally set as `APP_URL`/`GF_SERVER_ROOT_URL` in the actual deployed BookStack and Grafana manifests -- `<` and `>` aren't valid URI host characters, and BookStack hard-failed on it (`Invalid URI: Host is malformed`). Redaction belongs in published docs, never in live config values. Fixed by setting the real domain directly in the cluster manifests (which aren't published/git-tracked).
5. **Jellyfin hard-requires 2GiB free on its data directory regardless of actual usage.** The 1Gi PVC (sized off the source's ~600KB actual config size) was too small purely because of this fixed minimum-free-space check -- `InvalidOperationException: insufficient free space`. `truenas-iscsi` supports online expansion (`allowVolumeExpansion: true`); patched the PVC to 4Gi, restarted the pod to complete the filesystem resize (`FileSystemResizePending` condition requires a pod restart to finish, not just the PVC patch).
6. **A cross-host dependency broke silently: `firewalld` on `homelab-vm` doesn't allow-list every port.** Open WebUI reaches `headroom-proxy` (LLM API proxy, port 8642) and the podman SearXNG (web-search backend, port 8888) -- both previously worked via `127.0.0.1` since Open WebUI ran on the same host. Now that it's on a different host (the cluster), both were blocked by `homelab-vm`'s `firewalld public` zone, which only allow-lists a specific port list (matches the pattern of the other already-open service ports). Opened `8642/tcp` and `8888/tcp` to match.
7. **`/tmp` on `warp-vm` is a small (987M) `tmpfs`, not disk-backed.** A large data-migration tarball (Open WebUI's ~1GB) failed mid-transfer once earlier tarballs filled it. Switched to a disk-backed path (`~/sync-tmp` on `warp-vm`'s actual 9.7G root disk) for anything of meaningful size, and clean up after each service's migration completes rather than letting tarballs accumulate.
8. **A separate, real, cluster-wide bug found and fixed along the way: stale CoreDNS network state.** Both CoreDNS pods had been running ~6h without restart and had Kube-OVN pod IPs (`10.244.6.x`/`10.244.5.x`) that weren't reachable from worker nodes -- worker-to-worker pod traffic was fine, but worker-to-(these specific long-lived master-hosted pods) was completely broken, breaking **all DNS resolution from every worker-hosted pod**, not just the app that surfaced it (Suwayomi, via `UnknownHostException` downloading its web assets). Root cause looks like stale OVN port-binding state left over from one of the day's several node reboots that a live pod's binding was never reprogrammed against. Fixed by deleting the CoreDNS pods (Deployment recreated them with fresh, correctly-routed IPs); verified both internal (`kubernetes.default`) and external (`github.com`) resolution afterward.

### Still-unresolved, recurring pattern worth flagging on its own

Independent of the DNS bug above (confirmed fixed), a **separate** issue kept recurring across multiple apps and destinations during Wave 2: outbound requests to specific external hosts intermittently hang or get dropped with no clean error -- `github.com` (Suwayomi's WebUI asset zip stalled indefinitely on one attempt), `huggingface.co` (Open WebUI's embedding-model download, several retries before eventually succeeding), and this is the same family of symptom as the still-unresolved SearXNG search-engine timeout issue from the Wave 1 verification pass (`html.duckduckgo.com`, `www.bing.com`, `www.google.com/search`). Working theory remains unconfirmed (possibly PMTUD/fragmentation-related given the ISP's already-flaky TTL history, possibly something narrower) -- not blocking (retries and pre-existing cached data got every app running fine in the end), but real enough to have hit 4 separate destinations now. Worth a dedicated investigation pass rather than continuing to patch around it per-app.

### Data migration: all 7 verified with real content, not just "pod is Running"

- **CouchDB**: real `_dbs.couch`/`_nodes.couch`/`shards/` loaded; confirmed via real auth-enforcement (`not a server admin`, not admin-party) and `All system databases exist` in logs (vs. the fresh-instance `database_does_not_exist` warnings seen before migration).
- **Grafana**: `grafana.db` (1.5MB) extracted unchanged; confirmed via matching file size post-startup (Grafana didn't recreate it) and no fresh-bootstrap log lines. Login still uses the *source* instance's actual current admin password (not the `GF_SECURITY_ADMIN_PASSWORD` env var, which only seeds a brand-new database) -- expected Grafana behavior, not a bug.
- **BookStack**: DB (306MB) + app config (104KB) migrated; confirmed via `Nothing to migrate` (Laravel found the schema already current) and `HTTP 302` after the `APP_URL` fix above.
- **copyparty**: config (security salts, TLS cert, session DB) migrated; confirmed it picked up the existing `up2k.db` index (163KB) on the shared photos NFS mount, proving it's reading the same live data with its index intact -- no photo data copy needed at all.
- **Jellyfin**: config (28KB) migrated; confirmed via identical `ServerId` before/after and `HTTP 200` health check post-resize-fix.
- **Open WebUI**: data (1.1GB: `webui.db`, `vector_db`, `uploads`, `cache`) migrated; confirmed via `HTTP 200` health check once startup completed (delayed by the HuggingFace flakiness noted above, not a migration problem).
- **Suwayomi**: library data (1.7GB: `database.mv.db`, `downloads`, `extensions`, `backups`) migrated; confirmed via `HTTP 200`. Bonus: the source instance's data already included a downloaded `webUI/` directory, so migrating it sidestepped the GitHub-download-stall issue entirely for this app.

### MetalLB pool expanded (2026-08-24)

Flagged proactively (user asked directly), then fixed same-day: the `192.168.50.220-229` pool (10 IPs) had 4 already used (Rancher `.220`, 2 registry mirrors `.221`/`.222`, Uptime Kuma `.223`) -- only 6 free, but Wave 2 needs 7 more LoadBalancer IPs at cutover time (`bookstack-db` stays `ClusterIP`-only, internal). Expanded the `IPAddressPool` (`homelab-pool` in `metallb-system`) from `192.168.50.220-229` to `192.168.50.220-239` (10 -> 20 IPs) via `kubectl patch`. `.230-.239` verified free first via ping sweep; checked against the MikroTik's DHCP pool (`/ip pool print` shows it technically spans the whole `.3-.254` range) -- same accepted risk profile as the original `.220-.229` pick, empirically safe since DHCP leases have stayed in the low range in practice. 16 IPs now available (was 6); confirmed the 4 existing assignments were untouched by the patch.

## Wave 2 Caddy/Tunnel cutover (2026-08-24)

All 7 Wave 2 apps fully cut over -- both exposure layers (Caddy `.lan` + Cloudflare Tunnel `.<PERSONAL_DOMAIN>`) repointed at the k8s cluster, podman-side containers stopped (not removed), data re-synced one final time immediately before each cutover to catch any drift since the earlier migration pass. Same per-service discipline as `up.<PERSONAL_DOMAIN>` in Wave 1: assign a MetalLB LoadBalancer IP, repoint Caddy, repoint the tunnel, verify both, *then* stop podman.

| App | LoadBalancer IP | `.lan` | `.<PERSONAL_DOMAIN>` |
|---|---|---|---|
| Grafana | `.224` | `grafana.lan` | `grafana.<PERSONAL_DOMAIN>` |
| BookStack (app only; db stays ClusterIP-internal) | `.225` | `bookstack.lan` | `book.<PERSONAL_DOMAIN>` |
| copyparty | `.226` | `copyparty.lan` | `copy.<PERSONAL_DOMAIN>` |
| Jellyfin | `.227` | `jellyfin.lan` | `jelly.<PERSONAL_DOMAIN>` |
| Open WebUI | `.228` | `openwebui.lan` | `ai.<PERSONAL_DOMAIN>` |
| Suwayomi | `.229` | `mihon.lan` | `mihon.<PERSONAL_DOMAIN>` |
| CouchDB | `.230` | *(none -- never had a Caddy route)* | `obsidian.<PERSONAL_DOMAIN>` |

MetalLB pool usage after this: 11 of 20 IPs assigned (`.220` Rancher, `.221`/`.222` registry mirrors, `.223` Uptime Kuma, `.224`-`.230` this wave) -- 9 free for future waves.

Also added a genuinely new route while in here: **`rancher.lan`**, proxying to Rancher's existing LoadBalancer IP (`.220`) over HTTPS with `tls_insecure_skip_verify` (Rancher's self-signed cert, same established pattern as the existing `nas.lan` block) -- Rancher had a LoadBalancer IP since the original cluster buildout but was never given a `.lan` hostname until now.

### Real bug found and fixed: copyparty CORS-check false-positive behind the LoadBalancer

**Symptom**: every HTTPS request through either exposure layer (`copyparty.lan` *and* `copy.<PERSONAL_DOMAIN>`) got `403 rejected by cors-check (see fileserver log)` on login/upload, despite `Origin`, `Host`, and `X-Forwarded-Proto` headers all being verifiably correct (confirmed via raw `tcpdump` capture of the actual proxied request).

**Root cause** (found by reading copyparty's actual source, `httpcli.py`, after multiple guessed fixes failed): copyparty only trusts `X-Forwarded-Proto` (and thus only correctly infers `https`) when the *direct TCP peer* IP is within `--xff-src`. That peer IP, confirmed via raw `/proc/net/tcp6` inspection on the pod during a live request, was `100.64.0.6` -- **Kube-OVN's "join" subnet** (`100.64.0.0/16`, its internal inter-node transit network for routing LoadBalancer traffic through the distributed OVN gateway) -- not Caddy's or cloudflared's real LAN IP, and *not affected by the Service's `externalTrafficPolicy` setting* (confirmed by testing both `Local` and `Cluster` -- same peer either way). Since `100.64.0.0/16` wasn't in the configured `--xff-src` (which only had RFC1918 ranges), the peer was untrusted, `X-Forwarded-Proto` got ignored, and copyparty silently defaulted to assuming the request arrived over plain HTTP -- producing exactly the Origin/protocol mismatch its CORS check exists to catch.

**Fix**: added `100.64.0.0/16` to `--xff-src`, alongside the existing RFC1918 ranges. Also added `--xf-proto-fb=https` as defense-in-depth (assume https if the header is ever fully absent -- not what fixed this specific bug, but a sane default given every real path to this pod is already HTTPS-terminated).

**Verification method worth noting**: copyparty's own `--ihead=*` and `--log-conn` debug flags produced *zero* extra log output for the failing requests despite reproducing the 403 repeatedly (both via `curl` and via a real headless-browser session through the actual production path) -- logging wasn't the way in here. What actually worked: (1) `tcpdump -A` capture of Caddy's outbound request to confirm headers were correct, ruling out the proxy layer; (2) reading copyparty's real source to find the exact peer-trust code path; (3) `/proc/net/tcp6` on the pod itself, decoded by hand (kernel's little-endian-per-32-bit-word IPv6 hex format) to get the ground-truth peer IP. Also used the `camofox-browser` service (native, port 9377, REST API) already running on `homelab-vm` for an authentic browser-based reproduction (real Firefox engine, real CORS enforcement) rather than trusting a synthetic `curl -H Origin` approximation -- this is what confirmed the bug was real and not a curl artifact, and gave the exact same "welcome back" / "rejected by cors-check" page states a real user would see.

**Broader implication for this cluster**: *any* app doing IP-based reverse-proxy trust decisions (not just CORS -- rate limiting, access logging, IP allowlists) needs `100.64.0.0/16` in its trusted-proxy config if it's reachable via a MetalLB LoadBalancer Service on this Kube-OVN cluster, regardless of `externalTrafficPolicy`. Worth checking for on any future app that does this kind of check.

## Pi-hole `.lan` records are NOT a wildcard -- real gotcha caught on `rancher.lan` (2026-08-24)

Added `rancher.lan` to Caddy (proxying to Rancher's existing LoadBalancer IP), but it was unreachable from a real browser: `ERR_NAME_NOT_RESOLVED`. Wrongly assumed all session that Pi-hole resolves `*.lan` via a wildcard -- it doesn't. Pi-hole v6 (`/etc/pihole/pihole.toml`, `dns.hosts` array, inside the `pihole` podman container on `homelab-vm`) maintains an **explicit, manually-added list** of individual `IP hostname` records, one per `.lan` site (`jellyfin.lan`, `grafana.lan`, `bookstack.lan`, etc.) -- `rancher.lan` was simply never added when the Caddy route was created.

**Fix**: added `"192.168.50.80 rancher.lan"` to the `hosts` array in `pihole.toml` (backed up first as `pihole.toml.bak.rancher-lan-fix`), `pihole reloaddns` (not `restartdns` -- that subcommand doesn't exist in this version) to apply without a full restart. Verified via a real LAN client (`warp-vm`): DNS resolves, `HTTP 200` end-to-end over HTTPS.

**Every future new `.lan` Caddy route needs a matching Pi-hole entry added by hand** -- this is not automatic. Also noticed while in here: `vaultwarden.lan` and `9router.lan` are still in Pi-hole's list even though their Caddy routes were removed earlier this session ([[pod-internet-egress-isp-ttl-bug]]-adjacent cleanup) -- dangling DNS entries now (resolve to `192.168.50.80` but nothing serves them there), left alone since cleanup wasn't specifically requested for the DNS side.

## Next: Wave 3

Critical stateful tier (Nextcloud, Immich, Forgejo, Vaultwarden's eventual replacement) -- only after a full backup/restore drill has been proven in the new cluster at least once, per the original plan. Not started.
