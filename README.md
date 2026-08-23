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
| [talos-kubernetes-cluster-buildout.md](talos-kubernetes-cluster-buildout.md) | kubernetes, talos, proxmox, terraform, bpg-proxmox, metallb, democratic-csi, truenas, iscsi, rancher, cert-manager, ha, homelab-vm, warp-vm | 2026-08-23 |

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

### Investigations

| Doc | Tags | Status |
|---|---|---|
| [llama-server-dspark-gemma4-draft-investigation.md](llama-server-dspark-gemma4-draft-investigation.md) | llama-server, gemma4, dspark | blocked — upstream Qwen3-only, no Gemma4 support yet |
| [arm-cluster-security-audit.md](arm-cluster-security-audit.md) | security, ssh, arm-cluster, armbian, cloudflared | current — clean, extra SSH keys confirmed legitimate |
| [podman-to-kubernetes-migration-plan.md](podman-to-kubernetes-migration-plan.md) | kubernetes, podman, migration, proxmox, talos, k3s, homelab-vm | current — Talos chosen, cluster built (see [talos-kubernetes-cluster-buildout.md](talos-kubernetes-cluster-buildout.md)); Wave 1 not started |

## Secrets policy

Never commit real credentials, tokens, or passwords — use placeholders (`<MIKROTIK_PASSWORD>`, `<CLOUDFLARE_API_TOKEN>`, etc.) and point to where the real value actually lives (usually a Hermes skill reference file kept out of this repo). See the "Notes on secrets" section in any doc that touches credentials for the established convention.

This also covers anything that identifies the homelab itself, not just credentials: real hostnames/FQDNs (use a placeholder like `<HOST_HOSTNAME>`), the personal domain, VPS/box usernames, and public IPs. LAN-internal RFC1918 IPs (192.168.x.x) are lower risk and generally OK as-is since they are not internet-routable, but redact anything that resolves or is reachable from the public internet.
