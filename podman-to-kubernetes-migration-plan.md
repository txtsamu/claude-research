---
type: investigation
tags: [kubernetes, podman, migration, proxmox, talos, k3s, homelab-vm]
created: 2026-08-23
last_verified: 2026-08-23
status: current — Talos chosen, cluster built and live (see [[talos-kubernetes-cluster-buildout]]); Wave 1 migration not started yet
---

# Migrating `homelab-vm`'s Podman services to Kubernetes, for learning

## Goal

User wants to move (some/all of) the Podman Quadlet services currently running on `homelab-vm` to a Kubernetes deployment, primarily to **learn and practice managing Kubernetes** in the homelab — not because Podman is failing at anything.

## Current state (as of 2026-08-23)

`homelab-vm` (Proxmox VM 100 on `pve-pc`) runs ~45 Podman containers via Quadlet. Rough inventory by risk tier:

- **Critical / stateful, hard to lose**: Vaultwarden (password vault), Forgejo (git server), Nextcloud, Immich.
- **Stateful but recoverable**: Grafana, Jellyfin, BookStack, Suwayomi, copyparty, OneTerm (+ its mysql/redis/guacd/acl sidecars).
- **Stateless / disposable**: SearXNG, Uptime Kuma, cekping-agent, 9router, FlareSolverr, crawl4ai.
- **Infra that resists containerized k8s networking**: Pi-hole (wants port 53/67 + host networking for DNS/DHCP), Caddy (current reverse proxy in front of everything).

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

**Next step**: start Wave 1 (stateless containers — SearXNG, Uptime Kuma, cekping-agent, 9router, FlareSolverr, crawl4ai) — not started yet as of this doc's last verification.
