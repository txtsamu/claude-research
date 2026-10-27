# claude-research

Working notes from Claude Code sessions on the homelab — deployment write-ups, investigations, and troubleshooting logs. Written primarily so a *future* session (human or AI) can pick up context fast without re-deriving it.

## Structure

Flat, no folders. Research says metadata beats hierarchy for a collection this size — a deep PARA/Zettelkasten-style folder tree is overkill for a few dozen docs and just adds navigation cost. Each file has YAML frontmatter instead:

Another code folder: **`kt0211l-flasher/`** holds the Linux flasher (`ktflash_kt0211l.py`, tests, README) for KTMicro KT02H20/KT0211L dongles, documented in `fission-rational-hifi-firmware-upgrade-linux-flasher-ktmicro-kt0211l.md`.

One exception: **`samsung-tv-kants2-exploit/`** holds the buildable exploit sources for the KantS2 TV root chain (`hr.c`, the `.NET` payloads, the kernel-dump scanners, the launcher/debloat scripts). Code cannot live in a flat markdown archive.

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

**If the write-up involved any web research** (an official docs page, a GitHub issue/PR, a changelog, a forum/Discourse thread, a blog post — anything found via search rather than derived on-box), end the doc with a `## References` section linking every source that actually contributed, not just a summary of "I searched and found a fix." A future session hitting the same problem should be able to jump straight to the primary source instead of re-searching from scratch.

Each index table below has a **Last verified** column and is sorted by it, **newest first**. Insert new rows at the top of their table, not the bottom, and re-sort if a `last_verified` bump moves an existing doc out of place.

## Index

### Recent (last 15, newest first)

One combined view across all three tables below, so the latest work is visible at a glance without checking each section separately. Full history lives in the categorized tables.

| Date | Doc | Type |
|---|---|---|
| 2026-10-27 | [8bitdo-ultimate-2c-wireless-linux-web-firmware-update.md](8bitdo-ultimate-2c-wireless-linux-web-firmware-update.md) | how-to |
| 2026-10-27 | [fission-rational-hifi-firmware-upgrade-linux-flasher-ktmicro-kt0211l.md](fission-rational-hifi-firmware-upgrade-linux-flasher-ktmicro-kt0211l.md) | how-to |
| 2026-10-27 | [ktmicro-dsp-dongles-fission-ja11-chu2-same-chip-comparison-and-otg.md](ktmicro-dsp-dongles-fission-ja11-chu2-same-chip-comparison-and-otg.md) | investigation |
| 2026-10-27 | [moondrop-chu2-dsp-ktmicro-peq-match-tin-hifi-c7.md](moondrop-chu2-dsp-ktmicro-peq-match-tin-hifi-c7.md) | how-to |
| 2026-10-26 | [fiio-ja11-peq-match-tin-hifi-c7-hidraw.md](fiio-ja11-peq-match-tin-hifi-c7-hidraw.md) | how-to |
| 2026-10-26 | [tanchjim-fission-ktmicro-dsp-peq-match-tin-hifi-c7.md](tanchjim-fission-ktmicro-dsp-peq-match-tin-hifi-c7.md) | how-to |
| 2026-10-25 | [samsung-tv-t6500-root-and-persistence.md](samsung-tv-t6500-root-and-persistence.md) | investigation |
| 2026-10-25 | [samsung-tv-t6500-debloat-and-launcher.md](samsung-tv-t6500-debloat-and-launcher.md) | troubleshooting |
| 2026-10-25 | [samsung-tv-t6500-sideload-and-apps.md](samsung-tv-t6500-sideload-and-apps.md) | how-to |
| 2026-10-25 | [samsung-tv-t6500-power-states-and-remote-control.md](samsung-tv-t6500-power-states-and-remote-control.md) | investigation |
| 2026-10-23 | [xiaomi-fm-radio-backup-and-cross-device-install.md](xiaomi-fm-radio-backup-and-cross-device-install.md) | how-to |
| 2026-10-23 | [redmi-10-magisk-root-swap-zram-and-modules.md](redmi-10-magisk-root-swap-zram-and-modules.md) | investigation |
| 2026-10-23 | [redmi-10-miui125-adb-debloat-telemetry-ads.md](redmi-10-miui125-adb-debloat-telemetry-ads.md) | how-to |
| 2026-10-22 | [firefox-audio-pinned-to-onboard-sink-wireplumber-restore-target.md](firefox-audio-pinned-to-onboard-sink-wireplumber-restore-target.md) | troubleshooting |
| 2026-10-22 | [poweramp-pauses-when-switching-apps-audio-focus.md](poweramp-pauses-when-switching-apps-audio-focus.md) | troubleshooting |
| 2026-10-22 | [truenas-music-dedupe-and-tag-cleanup.md](truenas-music-dedupe-and-tag-cleanup.md) | how-to |
| 2026-10-22 | [immich-lan-unreachable-oom-crashloop-and-stale-caddy-ca.md](immich-lan-unreachable-oom-crashloop-and-stale-caddy-ca.md) | troubleshooting |
| 2026-10-21 | [immich-effect-v4-stage2-services.md](immich-effect-v4-stage2-services.md) | how-to |
| 2026-10-21 | [immich-effect-v4-stage2-services.md](immich-effect-v4-stage2-services.md) | immich, fork, effect, effect-ts, nestjs, services, subagents, vitest, podman | 2026-10-21 |
| [immich-effect-v4-stage1-repositories.md](immich-effect-v4-stage1-repositories.md) | how-to |
| 2026-10-21 | [immich-fork-memory-usage-analysis.md](immich-fork-memory-usage-analysis.md) | investigation |
| 2026-10-21 | [immich-strip-ai-machine-learning-fork.md](immich-strip-ai-machine-learning-fork.md) | how-to |
| 2026-10-20 | [kt02h20-jcally-dac-ja11-firmware-flash-protocol.md](kt02h20-jcally-dac-ja11-firmware-flash-protocol.md) | investigation |
| 2026-10-23 | [diskos-stock-plus-round-screen-features-and-flash.md](diskos-stock-plus-round-screen-features-and-flash.md) | how-to |
| 2026-10-22 | [diskos-usb-dac-exit-deadlock-roles-and-volume-fix.md](diskos-usb-dac-exit-deadlock-roles-and-volume-fix.md) | troubleshooting |
| 2026-10-22 | [snowsky-disc-usb-dac-uac2-android-and-firmware-decompile.md](snowsky-disc-usb-dac-uac2-android-and-firmware-decompile.md) | investigation |
| 2026-10-20 | [diskos-disc-hotload-watchdog-snowsky-logo-hang.md](diskos-disc-hotload-watchdog-snowsky-logo-hang.md) | troubleshooting |
| 2026-10-20 | [gigabyte-b650m-k-argb-fan-no-light-openrgb-gbrgb.md](gigabyte-b650m-k-argb-fan-no-light-openrgb-gbrgb.md) | troubleshooting |
| 2026-10-19 | [mikrotik-dhcp-public-dns-fallback-lan-nxdomain.md](mikrotik-dhcp-public-dns-fallback-lan-nxdomain.md) | troubleshooting |
| 2026-10-19 | [ingenic-x2000-swb-reboot-to-usb-boot.md](ingenic-x2000-swb-reboot-to-usb-boot.md) | investigation |
| 2026-10-19 | [snowsky-disc-music-sync-from-nas.md](snowsky-disc-music-sync-from-nas.md) | how-to |
| 2026-10-19 | [diskos-usb-audio-reverse-engineering-mq-player.md](diskos-usb-audio-reverse-engineering-mq-player.md) | investigation |
| 2026-10-19 | [pipewire-native-sample-rate-usb-dac-cosmic-volume-keys.md](pipewire-native-sample-rate-usb-dac-cosmic-volume-keys.md) | how-to |
| 2026-10-19 | [fiio-snowsky-disc-diskos-flash-fedora.md](fiio-snowsky-disc-diskos-flash-fedora.md) | how-to |
| 2026-10-19 | [redmi-note-12-pro-hyperos2-adb-debloat.md](redmi-note-12-pro-hyperos2-adb-debloat.md) | how-to |
| 2026-10-19 | [iqoo-z11-usb-audio-output-flags-bitperfect-hires.md](iqoo-z11-usb-audio-output-flags-bitperfect-hires.md) | investigation |
| 2026-10-19 | [iqoo-vivo-otg-keepalive-not-possible-without-root.md](iqoo-vivo-otg-keepalive-not-possible-without-root.md) | investigation |
| 2026-10-19 | [iqoo-originos6-adb-debloat-uad-list.md](iqoo-originos6-adb-debloat-uad-list.md) | how-to |
| 2026-10-18 | [tiktok-bot-anoa-browser-backend-vs-camofox.md](tiktok-bot-anoa-browser-backend-vs-camofox.md) | how-to |
| 2026-10-18 | [technitium-samsung-tv-ad-telemetry-block-advanced-blocking.md](technitium-samsung-tv-ad-telemetry-block-advanced-blocking.md) | how-to |
| 2026-10-14 | [bitchord-android-usb-exclusive-mode-uac-driver.md](bitchord-android-usb-exclusive-mode-uac-driver.md) | how-to |

### How-to / deployment

| Doc | Tags | Last verified |
|---|---|---|
| [fission-rational-hifi-firmware-upgrade-linux-flasher-ktmicro-kt0211l.md](fission-rational-hifi-firmware-upgrade-linux-flasher-ktmicro-kt0211l.md) | tanchjim, fission, ktmicro, kt0211l, firmware, flash, rea, ghidra, reverse-engineering, fedora | 2026-10-27 |
| [moondrop-chu2-dsp-ktmicro-peq-match-tin-hifi-c7.md](moondrop-chu2-dsp-ktmicro-peq-match-tin-hifi-c7.md) | moondrop, chu-ii-dsp, ktmicro, dsp, peq, hidraw, squig-link, iem, eq, tin-hifi | 2026-10-27 |
| [fiio-ja11-peq-match-tin-hifi-c7-hidraw.md](fiio-ja11-peq-match-tin-hifi-c7-hidraw.md) | fiio, ja11, ktmicro, dsp, peq, hidraw, squig-link, iem, eq, tin-hifi | 2026-10-26 |
| [tanchjim-fission-ktmicro-dsp-peq-match-tin-hifi-c7.md](tanchjim-fission-ktmicro-dsp-peq-match-tin-hifi-c7.md) | tanchjim, fission, ktmicro, dsp, peq, hid, squig-link, iem, eq, fedora | 2026-10-26 |
| [samsung-tv-t6500-sideload-and-apps.md](samsung-tv-t6500-sideload-and-apps.md) | samsung, tizen, tv, sideload, sdb, tizen-studio, fedora, clean-home, youtube, tizentube, ad-block | 2026-10-25 |
| [samsung-tv-t6500-power-states-and-remote-control.md](samsung-tv-t6500-power-states-and-remote-control.md) | samsung, tizen, kants2, t6500, power, standby, wol, ex-link, mdc, suspend, sdb | 2026-10-25 |
| [xiaomi-fm-radio-backup-and-cross-device-install.md](xiaomi-fm-radio-backup-and-cross-device-install.md) | android, xiaomi, redmi, fm-radio, adb, wireless-debugging, apk-backup | 2026-10-23 |
| [redmi-10-miui125-adb-debloat-telemetry-ads.md](redmi-10-miui125-adb-debloat-telemetry-ads.md) | android, xiaomi, redmi, miui, adb, debloat, telemetry, ads | 2026-10-23 |
| [diskos-stock-plus-round-screen-features-and-flash.md](diskos-stock-plus-round-screen-features-and-flash.md) | fiio, snowsky-disc, diskos, lvgl, round-display, flash, usbboot | 2026-10-23 |
| [immich-effect-v4-stage1-repositories.md](immich-effect-v4-stage1-repositories.md) | immich, fork, effect, effect-ts, nestjs, kysely, subagents, git-subtree | 2026-10-21 |
| [immich-strip-ai-machine-learning-fork.md](immich-strip-ai-machine-learning-fork.md) | immich, fork, machine-learning, postgres, migration, pnpm, podman | 2026-10-21 |
| [fiio-snowsky-disc-diskos-flash-fedora.md](fiio-snowsky-disc-diskos-flash-fedora.md) | fiio, snowsky-disc, diskos, dap, ingenic, mask-rom, flashing, squashfs, udev, fedora, usb-dac, usb-audio | 2026-10-19 |
| [snowsky-disc-music-sync-from-nas.md](snowsky-disc-music-sync-from-nas.md) | fiio, snowsky-disc, rsync, nas, fat32, fsck, dedup, flac | 2026-10-19 |
| [pipewire-native-sample-rate-usb-dac-cosmic-volume-keys.md](pipewire-native-sample-rate-usb-dac-cosmic-volume-keys.md) | pipewire, fedora, cosmic, usb-dac, sample-rate, bit-perfect, volume-keys | 2026-10-19 |
| [redmi-note-12-pro-hyperos2-adb-debloat.md](redmi-note-12-pro-hyperos2-adb-debloat.md) | android, xiaomi, redmi, hyperos, adb, debloat, uad-ng, mediatek | 2026-10-19 |
| [iqoo-originos6-adb-debloat-uad-list.md](iqoo-originos6-adb-debloat-uad-list.md) | android, iqoo, vivo, originos, adb, debloat, uad-ng | 2026-10-19 |
| [tiktok-bot-anoa-browser-backend-vs-camofox.md](tiktok-bot-anoa-browser-backend-vs-camofox.md) | tiktok-bot, home, anoa, camofox, scraping, cdp, gallery-dl | 2026-10-18 |
| [technitium-samsung-tv-ad-telemetry-block-advanced-blocking.md](technitium-samsung-tv-ad-telemetry-block-advanced-blocking.md) | technitium, dns, blocklist, samsung, smart-tv, advanced-blocking, hagezi | 2026-10-18 |
| [bitchord-android-usb-exclusive-mode-uac-driver.md](bitchord-android-usb-exclusive-mode-uac-driver.md) | android, bitchord, usb-dac, bit-perfect, uac, usbfs, media3, redmi, mediatek, android-sdk | 2026-10-14 |
| [k3s-workload-upgrade-pinned-tags-2026-10-09.md](k3s-workload-upgrade-pinned-tags-2026-10-09.md) | k3s, home, upgrade, helm, democratic-csi, truenas, nextcloud, immich, forgejo, snapshotter, api-key-rotation, version-pinning, subagents | 2026-10-09 |
| [telegram-bot-proxmox-windows-vm-power.md](telegram-bot-proxmox-windows-vm-power.md) | telegram, bot, proxmox, px1, windows, vm, effect-v4, k3s, home, api-token, pveum, tls-pinning | 2026-10-09 |
| [route-manager-effect-v4-caddy-lan-routes.md](route-manager-effect-v4-caddy-lan-routes.md) | effect-ts, effect-v4, caddy, nixos, home, k3s, technitium, dns, route-manager, systemd-path | 2026-10-09 |
| [immich-pgdata-iscsi-lun-resize.md](immich-pgdata-iscsi-lun-resize.md) | truenas, iscsi, zfs, zvol, thin-provisioning, podman, quadlet, immich, postgres, homelab-vm | 2026-10-05 |
| [talos-to-k3s-migration-warp.md](talos-to-k3s-migration-warp.md) | kubernetes, talos, k3s, migration, metallb, democratic-csi, cloudflare-tunnel, warp-vm, proxmox | 2026-10-05 |
| [truenas-nas-unused-zvol-cleanup.md](truenas-nas-unused-zvol-cleanup.md) | truenas, nas, zfs, iscsi, democratic-csi, k3s, cleanup, talos | 2026-10-03 |
| [immich-upgrade-k8s-home.md](immich-upgrade-k8s-home.md) | immich, kubernetes, k3s, home, upgrade, postgres, valkey, deployment, homelab | 2026-10-03 |
| [immich-upgrade-v3-2-4-home.md](immich-upgrade-v3-2-4-home.md) | immich, kubernetes, k3s, home, upgrade, postgres, kubectl | 2026-10-02 |
| [home-nixos-merge-and-deploy-prs-2-and-4.md](home-nixos-merge-and-deploy-prs-2-and-4.md) | nixos, home, flake, github, rebase, systemd-hardening, flake-lock, deploy, ci | 2026-10-02 |
| [technitium-cloudflare-doh-forwarder.md](technitium-cloudflare-doh-forwarder.md) | technitium, dns, doh, dns-over-https, cloudflare, google, quad9, home, privacy, forwarder | 2026-09-26 |
| [mikrotik-hardening-round2-2026-09-24.md](mikrotik-hardening-round2-2026-09-24.md) | mikrotik, routeros, hardening, security, firewall, ssh, mac-server, services, hex-s | 2026-09-24 |
| [comfyui-qwen-image-2-1-gguf-fedora-comfy-lan.md](comfyui-qwen-image-2-1-gguf-fedora-comfy-lan.md) | comfyui, qwen-image, gguf, rocm, gfx1101, fedora, caddy, technitium, nixos, openwebui, image-generation | 2026-09-21 |
| [mikrotik-config-backup-private-github.md](mikrotik-config-backup-private-github.md) | mikrotik, routeros, backup, github, git, security | 2026-09-21 |
| [bonsai-27b-prismml-ternary-gguf-deploy.md](bonsai-27b-prismml-ternary-gguf-deploy.md) | llama-server, llama.cpp, prismml, gguf, ternary, quantization, rocm, hip, gfx1101, openwebui, qwen, huggingface | 2026-09-21 |
| [amdgpu-power-cap-floor-compute-profile.md](amdgpu-power-cap-floor-compute-profile.md) | rocm, rocm-smi, amdgpu, gpu, power, gfx1101, fedora | 2026-09-21 |
| [home-directory-cleanup-evomem-bridge-hook-coupling.md](home-directory-cleanup-evomem-bridge-hook-coupling.md) | fedora, home, cleanup, evomem, claude-code, hooks | 2026-09-21 |
| [tiny11core-windows-vm-proxmox-px1.md](tiny11core-windows-vm-proxmox-px1.md) | proxmox, px1, windows, tiny11, iso, sourceforge, aria2, ovmf, tpm, nas-lvm-thin, rtk, static-ip, technitium, dns, control-panel | 2026-09-21 |
| [rancher-full-decommission-k3s-home.md](rancher-full-decommission-k3s-home.md) | rancher, fleet, rancher-turtles, capi, k3s, kubernetes, cleanup, home, caddy, technitium | 2026-09-17 |
| [kubewall-lighter-rancher-dashboard-deploy.md](kubewall-lighter-rancher-dashboard-deploy.md) | kubewall, kubernetes, k3s, dashboard, helm, caddy, technitium, dns, home, rancher-alternative | 2026-09-17 |
| [perses-dashboard-victoriametrics-datasource.md](perses-dashboard-victoriametrics-datasource.md) | perses, victoriametrics, dashboard, kubernetes, k3s, mariadb, home, monitoring, caddy, technitium, kube-state-metrics, promql | 2026-09-17 |
| [nixos-home-python-venv-uv-port.md](nixos-home-python-venv-uv-port.md) | nixos, uv, python, venv, home, hermes, proxmox-mcp-plus, mcp, migration, systemd | 2026-09-17 |
| [k3s-swap-nixos-correct-setup.md](k3s-swap-nixos-correct-setup.md) | k3s, kubernetes, swap, nixos, memory, kubelet, home | 2026-09-10 |
| [checkmk-k8s-deployment-monitor-lan.md](checkmk-k8s-deployment-monitor-lan.md) | checkmk, kubernetes, k3s, homelab, monitoring, caddy, technitium, truenas, firewalld | 2026-09-09 |
| [checkmk-agent-containerized-truenas-host-metrics.md](checkmk-agent-containerized-truenas-host-metrics.md) | checkmk, truenas, scale, docker, containers, monitoring, package-management-blocked | 2026-09-09 |
| [evomem-mcp-connect-pi.md](evomem-mcp-connect-pi.md) | evomem, mcp, pi, coding-agent, knowledge-base, homelab, nixos, memory | 2026-09-09 |
| [wine-standalone-exe-steam-proton-shortcut.md](wine-standalone-exe-steam-proton-shortcut.md) | wine, wine-wow64, fedora, proton, steam, non-steam-game, pulseaudio, alsa, mmdevapi, gaming, python-vdf | 2026-09-08 |
| [openrgb-rc3-update-fedora.md](openrgb-rc3-update-fedora.md) | openrgb, fedora, rpm, versioning | 2026-09-06 |
| [rancher-talos-to-k3s-migration.md](rancher-talos-to-k3s-migration.md) | rancher, kubernetes, talos, k3s, migration, cert-manager, metallb, caddy, cattle-system | 2026-09-06 |
| [vpz-netbird-update-podman-autoupdate-rollout.md](vpz-netbird-update-podman-autoupdate-rollout.md) | netbird, podman, quadlet, auto-update, vpz, pangolin, technitium | 2026-09-06 |
| [technitium-dns-3node-cluster-deployment.md](technitium-dns-3node-cluster-deployment.md) | technitium, dns, podman, quadlet, mikrotik, caddy, talos, pihole-migration, ad-blocking, ha, vpz | 2026-08-31 |
| [pihole-podman-quadlet-config-historical.md](pihole-podman-quadlet-config-historical.md) | pihole, podman, quadlet, dns, ad-blocking, historical | 2026-08-31 |
| [keel-image-auto-update-and-version-pinning.md](keel-image-auto-update-and-version-pinning.md) | keel, kubernetes, kubectl, image-updates, semver, homelab | 2026-08-31 |
| [syncyomi-suwayomi-sync-k8s-deployment.md](syncyomi-suwayomi-sync-k8s-deployment.md) | syncyomi, suwayomi, kubernetes, kubectl, mihon, manga, dns, tls, hostaliases | 2026-08-31 |
| [llama-server-qwen3.6-hauhau-uncensored-swap.md](llama-server-qwen3.6-hauhau-uncensored-swap.md) | llama-server, qwen, moe, rocm, gguf, uncensored, systemd | 2026-08-31 |
| [nas-lvm-thin-proxmox-setup.md](nas-lvm-thin-proxmox-setup.md) | truenas, iscsi, proxmox, lvm-thin, zfs, storage, homelab | 2026-08-31 |
| [talos-worker-storage-migration-nas-lvm-thin.md](talos-worker-storage-migration-nas-lvm-thin.md) | talos, kubernetes, proxmox, storage-migration, lvm-thin, live-migration, cloudinit, iscsi, homelab, warp-vm | 2026-08-31 |
| [homelab-system-namespace-resource-audit.md](homelab-system-namespace-resource-audit.md) | kubernetes, resource-limits, cert-manager, metallb, fleet, capi, democratic-csi, snapshot-controller, rancher, homelab | 2026-08-31 |
| [k8s-deployment-memory-ranking-technique.md](k8s-deployment-memory-ranking-technique.md) | kubernetes, kubectl, memory, rancher, monitoring, homelab, warp-vm | 2026-08-31 |
| [mikrotik-openvpn-warp-relay-bypass-isp-udp-block.md](mikrotik-openvpn-warp-relay-bypass-isp-udp-block.md) | mikrotik, routeros, openvpn, wireguard, cloudflare-warp, digitalocean, isp, dpi, vpn | 2026-08-30 |
| [netbird-selfhosted-podman-quadlet-setup.md](netbird-selfhosted-podman-quadlet-setup.md) | netbird, podman, quadlet, wireguard, traefik, vpn, self-hosted, mesh, exit-node, acme, kubernetes | 2026-08-30 |
| [pangolin-vpz-podman-quadlet-deploy.md](pangolin-vpz-podman-quadlet-deploy.md) | pangolin, podman, quadlet, traefik, gerbil, wireguard, acme, letsencrypt, tunnel, self-hosted, vpz | 2026-08-30 |
| [homelab-cluster-memory-limits-audit.md](homelab-cluster-memory-limits-audit.md) | kubernetes, kubectl, resource-limits, oom, memory, rwo-pvc, rollingupdate, homelab | 2026-08-30 |
| [talos-worker-disk-resize-proxmox.md](talos-worker-disk-resize-proxmox.md) | talos, kubernetes, proxmox, disk-resize, ephemeral-partition, cordon, drain, ovs-ovn, homelab | 2026-08-30 |
| [rancher-upgrade-2.15.1.md](rancher-upgrade-2.15.1.md) | rancher, helm, kubernetes, upgrade, cattle-system, security | 2026-08-30 |
| [android-phone-proxy-via-vpz.md](android-phone-proxy-via-vpz.md) | android, proxy, socks5, http-proxy, freeproxy, vpz, squid, microsocks | 2026-08-30 |
| [talos-kubernetes-cluster-buildout.md](talos-kubernetes-cluster-buildout.md) | kubernetes, talos, proxmox, terraform, bpg-proxmox, metallb, democratic-csi, truenas, iscsi, rancher, cert-manager, ha, homelab-vm, warp-vm, kube-ovn | 2026-08-28 |
| [mikrotik-hardening-dpi-bypass-2026-08-27.md](mikrotik-hardening-dpi-bypass-2026-08-27.md) | mikrotik, routeros, firewall, security, dpi-bypass, hardening | 2026-08-28 |
| [agentmemory-shared-mcp-multi-host-setup.md](agentmemory-shared-mcp-multi-host-setup.md) | agentmemory, mcp, claude-code, firewalld, homelab, multi-host | 2026-07-31 |
| [cosmic-de-install-fedora43.md](cosmic-de-install-fedora43.md) | cosmic, cosmic-de, fedora, gdm, desktop-environment | 2026-07-23 |
| [flameshot-shortcut-cosmic-fedora43.md](flameshot-shortcut-cosmic-fedora43.md) | flameshot, screenshot, cosmic, keyboard-shortcuts, fedora | 2026-07-23 |
| [gnome-windows7-theme-fedora.md](gnome-windows7-theme-fedora.md) | gnome, gnome-shell, theming, fedora, wayland | 2026-07-17 |
| [local-lan-domains-caddy-pihole-setup.md](local-lan-domains-caddy-pihole-setup.md) | caddy, pihole, dns, https, podman, mikrotik, brave | 2026-07-13 |
| [cekping-agent-podman-quadlet-deploy.md](cekping-agent-podman-quadlet-deploy.md) | podman, quadlet, systemd | 2026-07-11 |
| [oneterm-podman-quadlet-deploy.md](oneterm-podman-quadlet-deploy.md) | oneterm, podman, quadlet, systemd | 2026-06-26 |
| [oneterm-dark-mode.md](oneterm-dark-mode.md) | oneterm, frontend, vue | 2026-06-26 |
| [llama-server-gemma4-qat-mtp-swap.md](llama-server-gemma4-qat-mtp-swap.md) | llama-server, gemma4, mtp, qat | 2026-06-24 |

### Troubleshooting

| Doc | Tags | Last verified |
|---|---|---|
| [samsung-tv-t6500-debloat-and-launcher.md](samsung-tv-t6500-debloat-and-launcher.md) | samsung, tizen, tv, sdb, debloat, kants2, uep, cold-boot, persistence, clean-launcher, tvunlock02, app-list, home-key, uid-5001, t6500, blocked | 2026-10-25 |
| [diskos-usb-dac-exit-deadlock-roles-and-volume-fix.md](diskos-usb-dac-exit-deadlock-roles-and-volume-fix.md) | fiio, snowsky-disc, diskos, usb-dac, uac2, deadlock, usb-role, volume | 2026-10-22 |
| [firefox-audio-pinned-to-onboard-sink-wireplumber-restore-target.md](firefox-audio-pinned-to-onboard-sink-wireplumber-restore-target.md) | pipewire, wireplumber, firefox, usb-dac, fiio-ja11, stream-restore, fedora | 2026-10-22 |
| [poweramp-pauses-when-switching-apps-audio-focus.md](poweramp-pauses-when-switching-apps-audio-focus.md) | android, iqoo, poweramp, adb, audio-focus, usb-dac, fingerprint, instagram | 2026-10-22 |
| [diskos-disc-hotload-watchdog-snowsky-logo-hang.md](diskos-disc-hotload-watchdog-snowsky-logo-hang.md) | fiio, snowsky-disc, diskos, disco, hot-load, watchdog, fiio_init | 2026-10-20 |
| [gigabyte-b650m-k-argb-fan-no-light-openrgb-gbrgb.md](gigabyte-b650m-k-argb-fan-no-light-openrgb-gbrgb.md) | openrgb, gigabyte, b650m-k, rgb-fusion, it5702, hidraw, argb, reverse-engineering, systemd | 2026-10-20 |
| [mikrotik-dhcp-public-dns-fallback-lan-nxdomain.md](mikrotik-dhcp-public-dns-fallback-lan-nxdomain.md) | mikrotik, routeros, dhcp, dns, technitium, lan, nxdomain, immich | 2026-10-19 |
| [kubewall-caddy-kwall-lan-route.md](kubewall-caddy-kwall-lan-route.md) | kubewall, caddy, nixos, home, k3s, tls, dns, kwall-lan | 2026-10-09 |
| [px1-talos-vm-decommission-orphaned-storage.md](px1-talos-vm-decommission-orphaned-storage.md) | proxmox, talos, lvm-thin, iscsi, storage, cleanup, px1, warp-vm | 2026-10-05 |
| [wifi-buffering-quic-channel-congestion-altos-ax3000.md](wifi-buffering-quic-channel-congestion-altos-ax3000.md) | wifi, altos-ax3000, mikrotik, quic, buffering, streaming, channel, dfs, 5ghz, isp, mtu, bufferbloat, nethome | 2026-09-24 |
| [pod-internet-egress-isp-ttl-bug.md](pod-internet-egress-isp-ttl-bug.md) | talos, kubernetes, kube-ovn, flannel, cni, mikrotik, routeros, ttl, networking, homelab-vm, fasttrack, tls, warp-vm | 2026-09-21 |
| [home-oom-cascade-cloudflared-outage.md](home-oom-cascade-cloudflared-outage.md) | home, k3s, oom, cloudflared, cloudflare-tunnel, kubernetes, memory, fedora | 2026-09-21 |
| [llama-server-lan-unreachable-firewalld-port.md](llama-server-lan-unreachable-firewalld-port.md) | llama-server, openwebui, firewalld, fedora, networking, k3s | 2026-09-21 |
| [claude-research-secrets-history-rewrite.md](claude-research-secrets-history-rewrite.md) | git, secrets, git-filter-repo, github, security, privacy, gitleaks | 2026-09-18 |
| [hermes-update-broken-git-and-nixos-uv.md](hermes-update-broken-git-and-nixos-uv.md) | hermes, hermes-agent, nixos, uv, git, home, proxmox, migration, systemd | 2026-09-18 |
| [agenix-technitium-admin-password-fix.md](agenix-technitium-admin-password-fix.md) | agenix, nixos, technitium, secrets, home | 2026-09-18 |
| [caddy-internal-ca-cert-mismatch-after-host-migration.md](caddy-internal-ca-cert-mismatch-after-host-migration.md) | caddy, tls, pwa, android, certificate, home, warp-vm, migration | 2026-09-10 |
| [netbird-stale-peer-blocked-by-reverse-proxy-reference.md](netbird-stale-peer-blocked-by-reverse-proxy-reference.md) | netbird, self-hosted, reverse-proxy, peer-management, vpz, home, warp-vm | 2026-09-10 |
| [technitium-lan-secondary-zone-real-replication.md](technitium-lan-secondary-zone-real-replication.md) | technitium, dns, zone-transfer, axfr, notify, secondary-zone, warp-vm, arm1, arm3, checkmk | 2026-09-09 |
| [truenas-scst-arc-memory-backup-timeout.md](truenas-scst-arc-memory-backup-timeout.md) | truenas, zfs, arc, iscsi, scst, proxmox, vzdump, backup, warp-vm, px1 | 2026-09-08 |
| [immich-bull-queue-leftover-cleanup.md](immich-bull-queue-leftover-cleanup.md) | immich, redis, bullmq, job-queue, kubernetes, homelab | 2026-09-06 |
| [pihole-technitium-port53-conflict-warp.md](pihole-technitium-port53-conflict-warp.md) | dns, pihole, technitium, warp-vm, iptables, port-conflict | 2026-09-06 |
| [netbird-reverse-proxy-k3s-forward-filter-drop.md](netbird-reverse-proxy-k3s-forward-filter-drop.md) | netbird, reverse-proxy, k3s, kube-router, nftables, cloudflare-tunnel, metallb, vpz, warp-vm | 2026-09-06 |
| [proxmox-px1-px2-rename-cert-fix.md](proxmox-px1-px2-rename-cert-fix.md) | proxmox, hostname-rename, pmxcfs, tls, ssl-cert, dns, apt, storage-cfg, caddy, px1, px2 | 2026-09-05 |
| [talos-etcd-kube-ovn-peer-url-disaster-recovery.md](talos-etcd-kube-ovn-peer-url-disaster-recovery.md) | talos, kubernetes, etcd, kube-ovn, disaster-recovery, reboot, proxmox, democratic-csi, registry-mirror, containerd, px1 | 2026-09-05 |
| [mikrotik-doh-bypasses-local-dns-for-lan-domains.md](mikrotik-doh-bypasses-local-dns-for-lan-domains.md) | mikrotik, routeros, dns, doh, dns-over-https, lan, cloudflare | 2026-08-31 |
| [homelab-stale-dns-hosts-ssh-config-sweep.md](homelab-stale-dns-hosts-ssh-config-sweep.md) | dns, hosts-file, ssh-config, nmcli, networkmanager, homelab, cleanup | 2026-08-31 |
| [fedora-memory-audit-warp-svc-leak-daily-restart.md](fedora-memory-audit-warp-svc-leak-daily-restart.md) | fedora, memory, warp-svc, llama-server, systemd, memory-leak, cloudflare-warp, sudo | 2026-08-31 |
| [rancher-startup-probe-cpu-throttle-restart-loop.md](rancher-startup-probe-cpu-throttle-restart-loop.md) | rancher, kubernetes, cpu-limits, startup-probe, helm, cattle-system, homelab | 2026-08-31 |
| [talos-worker-memory-downsize-qemu-reboot-semantics.md](talos-worker-memory-downsize-qemu-reboot-semantics.md) | talos, proxmox, qemu, memory, reboot, talosctl, kexec, powercycle, homelab, warp-vm | 2026-08-31 |
| [suwayomi-k8s-deployment-fixes.md](suwayomi-k8s-deployment-fixes.md) | suwayomi, kubernetes, kubectl, rollout, rwo-pvc, flaresolverr, byparr, cloudflare, socks-proxy, warp-vm, vpz | 2026-08-30 |
| [mikrotik-isolated-test-mangle-lockout.md](mikrotik-isolated-test-mangle-lockout.md) | mikrotik, routeros, firewall, mangle, policy-routing, lockout | 2026-08-30 |
| [mikrotik-double-nat-dmz-isp-filtering-investigation.md](mikrotik-double-nat-dmz-isp-filtering-investigation.md) | mikrotik, routeros, nat, dmz, isp, firewall, digitalocean | 2026-08-28 |
| [lan-wide-warp-failover-routing-outage.md](lan-wide-warp-failover-routing-outage.md) | mikrotik, routeros, cloudflare-warp, policy-routing, ip-rule, outage, postmortem | 2026-08-28 |
| [homelab-cloudflared-tunnel-stopped.md](homelab-cloudflared-tunnel-stopped.md) | cloudflared, cloudflare-tunnel, systemd, homelab | 2026-08-28 |
| [homelab-lvm-thin-reclaim-fstrim.md](homelab-lvm-thin-reclaim-fstrim.md) | proxmox, lvm-thin, xfs, fstrim, storage, podman, homelab-vm | 2026-08-23 |
| [immich-random-stops-automount-root-cause.md](immich-random-stops-automount-root-cause.md) | immich, systemd, automount, nfs, quadlet, podman, forensics, nextcloud, podman-auto-update | 2026-08-23 |
| [mikrotik-pc-usb-tether-wan-failover.md](mikrotik-pc-usb-tether-wan-failover.md) | mikrotik, routeros, failover, wan-backup, usb-tethering, firewalld, nat, warp | 2026-08-12 |
| [vpd-ssh-cloudflared-slow-connect.md](vpd-ssh-cloudflared-slow-connect.md) | ssh, cloudflared, cloudflare-access, pam, ssh-multiplexing | 2026-08-03 |
| [llama-server-qwen9b-crash-loop-cpu-heat.md](llama-server-qwen9b-crash-loop-cpu-heat.md) | llama-server, systemd, rocm, cpu-temp, crash-loop, fedora | 2026-07-31 |
| [fedora-perf-audit-openrgb-i2c-dup-scan.md](fedora-perf-audit-openrgb-i2c-dup-scan.md) | fedora, performance, use-method, sysstat, openrgb, i2c, cosmic-de | 2026-07-26 |
| [arm-cluster-ssh-motd-slow.md](arm-cluster-ssh-motd-slow.md) | ssh, armbian, motd, arm-cluster, dns | 2026-07-22 |
| [llama-server-rocm-mtp-tuning.md](llama-server-rocm-mtp-tuning.md) | llama-server, rocm, gpu, mtp | 2026-07-01 |

### Investigations

| Doc | Tags | Status | Last verified |
|---|---|---|---|
| [ktmicro-dsp-dongles-fission-ja11-chu2-same-chip-comparison-and-otg.md](ktmicro-dsp-dongles-fission-ja11-chu2-same-chip-comparison-and-otg.md) | ktmicro, helios, fission, ja11, chu2-dsp, uac, otg, xiaomi, hidraw | current | 2026-10-27 |
| [samsung-tv-t6500-root-and-persistence.md](samsung-tv-t6500-root-and-persistence.md) | samsung, tizen, tv, root, kants2, uep, kernel-exploit, armv7l, dotnet-launcher, remotepc, cifs, smack, ghidra, persistence, raw-block | current: merges the full root journey (negative compat probe -> Remote PC/CIFS -> archive-root -> dotnet-launcher invocation solved from source -> kernel-exploit survey -> UEP bypass, 152ms fast path -> boot-persistent root via raw-block profile.d patch); the one open thread is a custom launcher as Home target (see the debloat-and-launcher doc), blocked on setuid(5001) | 2026-10-25 |
| [redmi-10-magisk-root-swap-zram-and-modules.md](redmi-10-magisk-root-swap-zram-and-modules.md) | android, redmi, miui, magisk, root, swap, zram, lmkd | current: root over adb works (Magisk 30.7); swap already on as 2.2 GB lz4 zram, swappiness 100, MIUI writeback loop device; magisk-swapspace installed but inactive; encore module flagged for removal | 2026-10-23 |
| [snowsky-disc-usb-dac-uac2-android-and-firmware-decompile.md](snowsky-disc-usb-dac-uac2-android-and-firmware-decompile.md) | fiio, snowsky-disc, usb-dac, uac2, android, ghidra, reverse-engineering, firmware | current | 2026-10-22 |
| [immich-fork-memory-usage-analysis.md](immich-fork-memory-usage-analysis.md) | immich, memory, nodejs, sharp, exiftool, bullmq, postgres, podman, performance | current | 2026-10-21 |
| [kt02h20-jcally-dac-ja11-firmware-flash-protocol.md](kt02h20-jcally-dac-ja11-firmware-flash-protocol.md) | kt02h20, ktmicro, jcally, fiio-ja11, usb-dac, firmware, reverse-engineering, hid, cdc-acm | current: protocol decoded (HID 0x54 unlock -> 8888:cdc0 CDC bootloader), cross-platform CLI built + tested, JA11 V2.2 flashed OK (now 2972:0102 JadeAudio JA11); no software backup possible | 2026-10-20 |
| [ingenic-x2000-swb-reboot-to-usb-boot.md](ingenic-x2000-swb-reboot-to-usb-boot.md) | ingenic, x2000, usb-boot, swb, boot-rom, snowsky-disc | current: SWB entry works (a108:eaef in 5 s); writer refuses after software entry (E320), NAND lock unsupported in FiiO kernel | 2026-10-19 |
| [diskos-usb-audio-reverse-engineering-mq-player.md](diskos-usb-audio-reverse-engineering-mq-player.md) | fiio, snowsky-disc, diskos, usb-audio, otg, reverse-engineering, ghidra, rea, mips | current: USB Audio fixed (switch-then-wait), verified 24/96 to Chu2; rea refuses NaN2008 MIPS | 2026-10-19 |
| [iqoo-z11-usb-audio-output-flags-bitperfect-hires.md](iqoo-z11-usb-audio-output-flags-bitperfect-hires.md) | android, iqoo, vivo, originos, otg, usb-c, audio, hi-res, bit-perfect, audio-policy, poweramp, snapdragon-sound | current: no Android BIT_PERFECT (DIRECT only); Poweramp usbx verified 24/96 exclusive | 2026-10-19 |
| [iqoo-vivo-otg-keepalive-not-possible-without-root.md](iqoo-vivo-otg-keepalive-not-possible-without-root.md) | android, iqoo, vivo, originos, otg, usb-audio, adb, jadx, reverse-engineering | blocked | 2026-10-19 |
| [ruijie-rg-es208gc-switch-audit-firmware-cve.md](ruijie-rg-es208gc-switch-audit-firmware-cve.md) | ruijie, reyee, rg-es208gc, switch, firmware, cve-2025-56752, security, web-scripting, arm-cluster | current — config already optimal, nothing changed; firmware B1P39 is vulnerable, upgrade to B1P48 still pending | 2026-10-12 |
| [home-nixos-config-best-practice-audit.md](home-nixos-config-best-practice-audit.md) | nixos, home, flake, audit, agenix, caddy, security, systemd, nix-gc | current — 13 findings; #2-#8 fixed on main 09-27, sandboxing (#9) merged + switch deployed 10-02; recovery-key move and `/root` stray state still open | 2026-10-03 |
| [home-k8s-resource-rightsizing-victoriametrics.md](home-k8s-resource-rightsizing-victoriametrics.md) | kubernetes, k3s, resource-limits, victoriametrics, right-sizing, home, memory, checkmk, monitoring | current — done: 60h of real data collected, requests/limits applied to 13 deployments, node memory limit overcommit 145% → 116%; Perses dashboard added 2026-09-16, expanded to 11 panels w/ kube-state-metrics 2026-09-17 | 2026-09-17 |
| [warp-vm-nixos-migration-plan.md](warp-vm-nixos-migration-plan.md) | nixos, warp-vm, migration, k3s, kubernetes, proxmox, mcp, tiktok-bot, technitium, caddy, cloudflared, netbird, democratic-csi, plan, px1 | current — migration complete (T1-T20), `warp-vm` retained powered-off as a rollback point | 2026-09-10 |
| [warp-vm-nixos-migration-retrospective.md](warp-vm-nixos-migration-retrospective.md) | nixos, warp-vm, migration, retrospective, k3s, kubernetes, proxmox, cloudflare, metallb, hermes, technitium, caddy, evomem, lessons-learned | current — lessons learned across all 20 tickets, what to do differently next time | 2026-09-10 |
| [podman-to-kubernetes-migration-plan.md](podman-to-kubernetes-migration-plan.md) | kubernetes, podman, migration, proxmox, talos, k3s, homelab-vm, democratic-csi | current — migration complete (Waves 1-3 + homelab-vm decommission), now tracking post-decommission fixes | 2026-09-06 |
| [netbird-exit-node-throughput-isp-hop-loss.md](netbird-exit-node-throughput-isp-hop-loss.md) | netbird, wireguard, throughput, packet-loss, isp, mtr, iperf3, exit-node | current — root cause confirmed (ISP-internal hop loss), not pursued further | 2026-08-31 |
| [arm-cluster-security-audit.md](arm-cluster-security-audit.md) | security, ssh, arm-cluster, armbian, cloudflared | current — clean, extra SSH keys confirmed legitimate | 2026-07-22 |
| [llama-server-dspark-gemma4-draft-investigation.md](llama-server-dspark-gemma4-draft-investigation.md) | llama-server, gemma4, dspark | blocked — upstream Qwen3-only, no Gemma4 support yet | 2026-07-04 |

## Secrets policy

Never commit real credentials, tokens, or passwords — use placeholders (`<MIKROTIK_PASSWORD>`, `<CLOUDFLARE_API_TOKEN>`, etc.) and point to where the real value actually lives (usually a Hermes skill reference file kept out of this repo). See the "Notes on secrets" section in any doc that touches credentials for the established convention.

This also covers anything that identifies the homelab itself, not just credentials: real hostnames/FQDNs (use a placeholder like `<HOST_HOSTNAME>`), the personal domain, VPS/box usernames, and public IPs. LAN-internal RFC1918 IPs (192.168.x.x) are lower risk and generally OK as-is since they are not internet-routable, but redact anything that resolves or is reachable from the public internet.

**Enforced by a pre-commit hook** (2026-09-18, after a real password leaked and had to be scrubbed from history — see [[claude-research-secrets-history-rewrite]]): [gitleaks](https://github.com/gitleaks/gitleaks) runs on every commit via a hook checked into `.githooks/pre-commit` (not the usual `.git/hooks/`, since that directory isn't version-controlled and wouldn't survive a fresh clone). **One-time setup per clone**, since git doesn't auto-activate a repo's hooks path:
```bash
sudo dnf install gitleaks   # or see https://github.com/gitleaks/gitleaks for other platforms
git config core.hooksPath .githooks
```
A commit containing something that looks like a real secret gets blocked outright (tested against the actual leaked password — correctly caught and blocked before this was added; a clean commit is unaffected). Placeholders like `<MIKROTIK_PASSWORD>` don't trigger it — only real-looking values do.
