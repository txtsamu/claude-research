# claude-research

Working notes from Claude Code sessions on the homelab — deployment write-ups, investigations, and troubleshooting logs. Written primarily so a *future* session (human or AI) can pick up context fast without re-deriving it.

## Structure

Flat, no folders. Research says metadata beats hierarchy for a collection this size — a deep PARA/Zettelkasten-style folder tree is overkill for a few dozen docs and just adds navigation cost. Each file has YAML frontmatter instead:

```yaml
---
type: how-to | troubleshooting | investigation
tags: [topic, service, tech]
created: YYYY-MM-DD
last_verified: YYYY-MM-DD   # last time someone confirmed the content still matches reality
status: current | historical | blocked
---
```

- **`type`** (loosely [Diataxis](https://diataxis.fr/)-flavored, adapted for a solo engineering log rather than product docs):
  - `how-to` — did X, here's the exact steps, reusable as a recipe
  - `troubleshooting` — something broke, here's the diagnosis + fix
  - `investigation` — explored whether X was possible / worth doing; may end in "no" or "not yet"
- **`status`** — `current` (believed accurate), `historical` (superseded but kept for context), `blocked` (investigation stalled on an external constraint)
- **`last_verified`** matters more than `created` for infra docs — treat anything not re-verified in a while as a *snapshot*, not live state. Specific values (IPs, ports, versions) can drift.

When adding a new doc: same flat layout, same frontmatter block, descriptive kebab-case filename (`service-what-happened.md`), one topic per file — don't bundle unrelated work into one doc just because it happened the same day.

## Index

### How-to / deployment

| Doc | Tags | Last verified |
|---|---|---|
| [local-lan-domains-caddy-pihole-setup.md](local-lan-domains-caddy-pihole-setup.md) | caddy, pihole, dns, https, podman, mikrotik, brave | 2026-07-13 |
| [oneterm-podman-quadlet-deploy.md](oneterm-podman-quadlet-deploy.md) | oneterm, podman, quadlet, systemd | 2026-06-26 |
| [agentmemory-shared-mcp-multi-host-setup.md](agentmemory-shared-mcp-multi-host-setup.md) | agentmemory, mcp, claude-code, firewalld, homelab, multi-host | 2026-07-31 |
| [oneterm-dark-mode.md](oneterm-dark-mode.md) | oneterm, frontend, vue | 2026-06-26 |
| [cekping-agent-podman-quadlet-deploy.md](cekping-agent-podman-quadlet-deploy.md) | podman, quadlet, systemd | 2026-07-11 |
| [llama-server-gemma4-qat-mtp-swap.md](llama-server-gemma4-qat-mtp-swap.md) | llama-server, gemma4, mtp, qat | 2026-06-24 |
| [gnome-windows7-theme-fedora.md](gnome-windows7-theme-fedora.md) | gnome, gnome-shell, theming, fedora, wayland | 2026-07-17 |
| [cosmic-de-install-fedora43.md](cosmic-de-install-fedora43.md) | cosmic, cosmic-de, fedora, gdm, desktop-environment | 2026-07-23 |
| [flameshot-shortcut-cosmic-fedora43.md](flameshot-shortcut-cosmic-fedora43.md) | flameshot, screenshot, cosmic, keyboard-shortcuts, fedora | 2026-07-23 |
| [immich-pgdata-iscsi-lun-resize.md](immich-pgdata-iscsi-lun-resize.md) | truenas, iscsi, zfs, zvol, thin-provisioning, podman, quadlet, immich, postgres, homelab-vm | 2026-08-23 |
| [talos-kubernetes-cluster-buildout.md](talos-kubernetes-cluster-buildout.md) | kubernetes, talos, proxmox, terraform, bpg-proxmox, metallb, democratic-csi, truenas, iscsi, rancher, cert-manager, ha, homelab-vm, warp-vm, kube-ovn | 2026-08-28 |
| [mikrotik-hardening-dpi-bypass-2026-08-27.md](mikrotik-hardening-dpi-bypass-2026-08-27.md) | mikrotik, routeros, firewall, security, dpi-bypass, hardening | 2026-08-28 |
| [mikrotik-openvpn-warp-relay-bypass-isp-udp-block.md](mikrotik-openvpn-warp-relay-bypass-isp-udp-block.md) | mikrotik, routeros, openvpn, wireguard, cloudflare-warp, digitalocean, isp, dpi, vpn | 2026-08-30 |
| [netbird-selfhosted-podman-quadlet-setup.md](netbird-selfhosted-podman-quadlet-setup.md) | netbird, podman, quadlet, wireguard, traefik, vpn, self-hosted, mesh, exit-node, acme, kubernetes | 2026-08-30 |
| [pangolin-vpz-podman-quadlet-deploy.md](pangolin-vpz-podman-quadlet-deploy.md) | pangolin, podman, quadlet, traefik, gerbil, wireguard, acme, letsencrypt, tunnel, self-hosted, vpz | 2026-08-30 |
| [homelab-cluster-memory-limits-audit.md](homelab-cluster-memory-limits-audit.md) | kubernetes, kubectl, resource-limits, oom, memory, rwo-pvc, rollingupdate, homelab | 2026-08-30 |
| [talos-worker-disk-resize-proxmox.md](talos-worker-disk-resize-proxmox.md) | talos, kubernetes, proxmox, disk-resize, ephemeral-partition, cordon, drain, ovs-ovn, homelab | 2026-08-30 |
| [rancher-upgrade-2.15.1.md](rancher-upgrade-2.15.1.md) | rancher, helm, kubernetes, upgrade, cattle-system, security | 2026-08-30 |
| [android-phone-proxy-via-vpz.md](android-phone-proxy-via-vpz.md) | android, proxy, socks5, http-proxy, freeproxy, vpz, squid, microsocks | 2026-08-30 |
| [technitium-dns-3node-cluster-deployment.md](technitium-dns-3node-cluster-deployment.md) | technitium, dns, podman, quadlet, mikrotik, caddy, talos, pihole-migration, ad-blocking, ha, vpz | 2026-08-31 |
| [pihole-podman-quadlet-config-historical.md](pihole-podman-quadlet-config-historical.md) | pihole, podman, quadlet, dns, ad-blocking, historical | 2026-08-31 |
| [keel-image-auto-update-and-version-pinning.md](keel-image-auto-update-and-version-pinning.md) | keel, kubernetes, kubectl, image-updates, semver, homelab | 2026-08-31 |
| [syncyomi-suwayomi-sync-k8s-deployment.md](syncyomi-suwayomi-sync-k8s-deployment.md) | syncyomi, suwayomi, kubernetes, kubectl, mihon, manga, dns, tls, hostaliases | 2026-08-31 |
| [llama-server-qwen3.6-hauhau-uncensored-swap.md](llama-server-qwen3.6-hauhau-uncensored-swap.md) | llama-server, qwen, moe, rocm, gguf, uncensored, systemd | 2026-08-31 |
| [nas-lvm-thin-proxmox-setup.md](nas-lvm-thin-proxmox-setup.md) | truenas, iscsi, proxmox, lvm-thin, zfs, storage, homelab | 2026-08-31 |
| [talos-worker-storage-migration-nas-lvm-thin.md](talos-worker-storage-migration-nas-lvm-thin.md) | talos, kubernetes, proxmox, storage-migration, lvm-thin, live-migration, cloudinit, iscsi, homelab, warp-vm | 2026-08-31 |
| [homelab-system-namespace-resource-audit.md](homelab-system-namespace-resource-audit.md) | kubernetes, resource-limits, cert-manager, metallb, fleet, capi, democratic-csi, snapshot-controller, rancher, homelab | 2026-08-31 |
| [k8s-deployment-memory-ranking-technique.md](k8s-deployment-memory-ranking-technique.md) | kubernetes, kubectl, memory, rancher, monitoring, homelab, warp-vm | 2026-08-31 |

### Troubleshooting

| Doc | Tags | Last verified |
|---|---|---|
| [vpd-ssh-cloudflared-slow-connect.md](vpd-ssh-cloudflared-slow-connect.md) | ssh, cloudflared, cloudflare-access, pam, ssh-multiplexing | 2026-08-03 |
| [mikrotik-pc-usb-tether-wan-failover.md](mikrotik-pc-usb-tether-wan-failover.md) | mikrotik, routeros, failover, wan-backup, usb-tethering, firewalld, nat, warp | 2026-08-12 |
| [llama-server-rocm-mtp-tuning.md](llama-server-rocm-mtp-tuning.md) | llama-server, rocm, gpu, mtp | 2026-07-01 |
| [arm-cluster-ssh-motd-slow.md](arm-cluster-ssh-motd-slow.md) | ssh, armbian, motd, arm-cluster, dns | 2026-07-22 |
| [fedora-perf-audit-openrgb-i2c-dup-scan.md](fedora-perf-audit-openrgb-i2c-dup-scan.md) | fedora, performance, use-method, sysstat, openrgb, i2c, cosmic-de | 2026-07-26 |
| [llama-server-qwen9b-crash-loop-cpu-heat.md](llama-server-qwen9b-crash-loop-cpu-heat.md) | llama-server, systemd, rocm, cpu-temp, crash-loop, fedora | 2026-07-31 |
| [claude-research-secrets-history-rewrite.md](claude-research-secrets-history-rewrite.md) | git, secrets, git-filter-repo, github, security, privacy | 2026-08-03 |
| [homelab-lvm-thin-reclaim-fstrim.md](homelab-lvm-thin-reclaim-fstrim.md) | proxmox, lvm-thin, xfs, fstrim, storage, podman, homelab-vm | 2026-08-23 |
| [immich-random-stops-automount-root-cause.md](immich-random-stops-automount-root-cause.md) | immich, systemd, automount, nfs, quadlet, podman, forensics, nextcloud, podman-auto-update | 2026-08-23 |
| [pod-internet-egress-isp-ttl-bug.md](pod-internet-egress-isp-ttl-bug.md) | talos, kubernetes, kube-ovn, flannel, cni, mikrotik, routeros, ttl, networking, homelab-vm, fasttrack, tls, warp-vm | 2026-08-30 |
| [suwayomi-k8s-deployment-fixes.md](suwayomi-k8s-deployment-fixes.md) | suwayomi, kubernetes, kubectl, rollout, rwo-pvc, flaresolverr, byparr, cloudflare, socks-proxy, warp-vm, vpz | 2026-08-30 |
| [mikrotik-double-nat-dmz-isp-filtering-investigation.md](mikrotik-double-nat-dmz-isp-filtering-investigation.md) | mikrotik, routeros, nat, dmz, isp, firewall, digitalocean | 2026-08-28 |
| [lan-wide-warp-failover-routing-outage.md](lan-wide-warp-failover-routing-outage.md) | mikrotik, routeros, cloudflare-warp, policy-routing, ip-rule, outage, postmortem | 2026-08-28 |
| [homelab-cloudflared-tunnel-stopped.md](homelab-cloudflared-tunnel-stopped.md) | cloudflared, cloudflare-tunnel, systemd, homelab | 2026-08-28 |
| [mikrotik-isolated-test-mangle-lockout.md](mikrotik-isolated-test-mangle-lockout.md) | mikrotik, routeros, firewall, mangle, policy-routing, lockout | 2026-08-30 |
| [mikrotik-doh-bypasses-local-dns-for-lan-domains.md](mikrotik-doh-bypasses-local-dns-for-lan-domains.md) | mikrotik, routeros, dns, doh, dns-over-https, lan, cloudflare | 2026-08-31 |
| [homelab-stale-dns-hosts-ssh-config-sweep.md](homelab-stale-dns-hosts-ssh-config-sweep.md) | dns, hosts-file, ssh-config, nmcli, networkmanager, homelab, cleanup | 2026-08-31 |
| [fedora-memory-audit-warp-svc-leak-daily-restart.md](fedora-memory-audit-warp-svc-leak-daily-restart.md) | fedora, memory, warp-svc, llama-server, systemd, memory-leak, cloudflare-warp, sudo | 2026-08-31 |
| [rancher-startup-probe-cpu-throttle-restart-loop.md](rancher-startup-probe-cpu-throttle-restart-loop.md) | rancher, kubernetes, cpu-limits, startup-probe, helm, cattle-system, homelab | 2026-08-31 |
| [talos-worker-memory-downsize-qemu-reboot-semantics.md](talos-worker-memory-downsize-qemu-reboot-semantics.md) | talos, proxmox, qemu, memory, reboot, talosctl, kexec, powercycle, homelab, warp-vm | 2026-08-31 |

### Investigations

| Doc | Tags | Status |
|---|---|---|
| [llama-server-dspark-gemma4-draft-investigation.md](llama-server-dspark-gemma4-draft-investigation.md) | llama-server, gemma4, dspark | blocked — upstream Qwen3-only, no Gemma4 support yet |
| [arm-cluster-security-audit.md](arm-cluster-security-audit.md) | security, ssh, arm-cluster, armbian, cloudflared | current — clean, extra SSH keys confirmed legitimate |
| [podman-to-kubernetes-migration-plan.md](podman-to-kubernetes-migration-plan.md) | kubernetes, podman, migration, proxmox, talos, k3s, homelab-vm, democratic-csi | current — migration complete (Waves 1-3 + homelab-vm decommission), now tracking post-decommission fixes |
| [netbird-exit-node-throughput-isp-hop-loss.md](netbird-exit-node-throughput-isp-hop-loss.md) | netbird, wireguard, throughput, packet-loss, isp, mtr, iperf3, exit-node | current — root cause confirmed (ISP-internal hop loss), not pursued further |

## Secrets policy

Never commit real credentials, tokens, or passwords — use placeholders (`<MIKROTIK_PASSWORD>`, `<CLOUDFLARE_API_TOKEN>`, etc.) and point to where the real value actually lives (usually a Hermes skill reference file kept out of this repo). See the "Notes on secrets" section in any doc that touches credentials for the established convention.

This also covers anything that identifies the homelab itself, not just credentials: real hostnames/FQDNs (use a placeholder like `<HOST_HOSTNAME>`), the personal domain, VPS/box usernames, and public IPs. LAN-internal RFC1918 IPs (192.168.x.x) are lower risk and generally OK as-is since they are not internet-routable, but redact anything that resolves or is reachable from the public internet.
