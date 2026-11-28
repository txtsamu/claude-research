# claude-research

Working notes from Claude Code sessions on the homelab — deployment write-ups, investigations, and troubleshooting logs. Written primarily so a *future* session (human or AI) can pick up context fast without re-deriving it.

## Structure

Flat, no folders. Research says metadata beats hierarchy for a collection this size — a deep PARA/Zettelkasten-style folder tree is overkill for a few dozen docs and just adds navigation cost. Each file has YAML frontmatter instead:

Another code folder: **`hermes-to-evonic-migration/`** holds the converter, import and cutover scripts behind `hermes-to-evonic-migration.md`. Another code folder: **`evonic-hermes-benchmark/`** holds the agent benchmark harness and raw results behind `evonic-vs-hermes-agent-benchmark.md`. Another code folder: **`kt0211l-flasher/`** holds the Linux flasher (`ktflash_kt0211l.py`, tests, README) for KTMicro KT02H20/KT0211L dongles, documented in `fission-rational-hifi-firmware-upgrade-linux-flasher-ktmicro-kt0211l.md`.

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
| 2026-11-29 | [opencode-auto-compaction-200k-context-2026-11-29.md](opencode-auto-compaction-200k-context-2026-11-29.md) | how-to |
| 2026-11-28 | [diskos-audit-25-categories-dev-2f705ac-2026-11-28.md](diskos-audit-25-categories-dev-2f705ac-2026-11-28.md) | build-log |
| 2026-11-28 | [diskos-flash-dev-82ffa18-2026-11-28.md](diskos-flash-dev-82ffa18-2026-11-28.md) | build-log |
| 2026-11-28 | [diskos-architecture-review-seven-findings-2026-11-28.md](diskos-architecture-review-seven-findings-2026-11-28.md) | build-log |
| 2026-11-28 | [diskos-wifisup-extract-2026-11-28.md](diskos-wifisup-extract-2026-11-28.md) | build-log |
| 2026-11-28 | [diskos-codebase-audit-fixes-2026-11-28.md](diskos-codebase-audit-fixes-2026-11-28.md) | build-log |
| 2026-11-28 | [agy-tmux-ssh-file-token-relogin-2026-11-28.md](agy-tmux-ssh-file-token-relogin-2026-11-28.md) | troubleshooting |
| 2026-11-28 | [fedora43-workstation-debloat-service-and-cache-audit-2026-11-28.md](fedora43-workstation-debloat-service-and-cache-audit-2026-11-28.md) | investigation |
| 2026-11-28 | [camofox-bundle-cache-sweep-durable-install-2026-11-28.md](camofox-bundle-cache-sweep-durable-install-2026-11-28.md) | troubleshooting |
| 2026-11-28 | [home-directory-audit-2026-11-28.md](home-directory-audit-2026-11-28.md) | investigation |
| 2026-11-28 | [camofox-browser-missing-binary-http500-2026-11-28.md](camofox-browser-missing-binary-http500-2026-11-28.md) | troubleshooting |
| 2026-11-28 | [light-agent-ecrrefused-8099-hidraw-ownership-2026-11-28.md](light-agent-ecrrefused-8099-hidraw-ownership-2026-11-28.md) | troubleshooting |
| 2026-11-28 | [hermes-gateway-post-reboot-mcp-children-2026-11-28.md](hermes-gateway-post-reboot-mcp-children-2026-11-28.md) | troubleshooting |
| 2026-11-28 | [home-vm-reboot-hangs-k3s-killall-self-stop-2026-11-28.md](home-vm-reboot-hangs-k3s-killall-self-stop-2026-11-28.md) | troubleshooting |
| 2026-11-27 | [home-directory-reorg-projects-logs-probes-2026-11-27.md](home-directory-reorg-projects-logs-probes-2026-11-27.md) | how-to |
| 2026-11-27 | [replace-text-in-scanned-pdf-font-match-2026-11-27.md](replace-text-in-scanned-pdf-font-match-2026-11-27.md) | how-to |
| 2026-11-27 | [android-vpn-jsch-stream-order-and-ipv6-leak-2026-11-27.md](android-vpn-jsch-stream-order-and-ipv6-leak-2026-11-27.md) | troubleshooting |
| 2026-11-27 | [kt02h20-generic-31b2-1052-crossflash-ja11-v21-2026-11-27.md](kt02h20-generic-31b2-1052-crossflash-ja11-v21-2026-11-27.md) | how-to |
| 2026-11-27 | [fiio-ja11-stuck-bootloader-recover-wrong-firmware-2026-11-27.md](fiio-ja11-stuck-bootloader-recover-wrong-firmware-2026-11-27.md) | troubleshooting |
| 2026-11-27 | [opencode-hermes-default-model-opencode-go-2026-11-27.md](opencode-hermes-default-model-opencode-go-2026-11-27.md) | how-to |
| 2026-11-27 | [openrgb-two-instances-at-login-systemd-xdg-autostart-2026-11-27.md](openrgb-two-instances-at-login-systemd-xdg-autostart-2026-11-27.md) | troubleshooting |
| 2026-11-26 | [ternary-bonsai-27b-mtp-7800xt-vulkan-2026-11-26.md](ternary-bonsai-27b-mtp-7800xt-vulkan-2026-11-26.md) | how-to |
| 2026-11-26 | [fiio-ja11-firmware-reverse-engineering-output-diagnosis-2026-11-26.md](fiio-ja11-firmware-reverse-engineering-output-diagnosis-2026-11-26.md) | investigation |
| 2026-11-26 | [android-apple-music-bitrate-check-audio-flinger-redmi-note-12-pro.md](android-apple-music-bitrate-check-audio-flinger-redmi-note-12-pro.md) | investigation |
| 2026-11-26 | [ktflash-rust-toolkit-linux-kt02h20-reflash-2026-11-26.md](ktflash-rust-toolkit-linux-kt02h20-reflash-2026-11-26.md) | how-to |
| 2026-11-23 | [oxigram-fork-build-on-fedora-2026-11-23.md](oxigram-fork-build-on-fedora-2026-11-23.md) | how-to |
| 2026-11-22 | [comfyui-removal-2026-11-22.md](comfyui-removal-2026-11-22.md) | how-to |
| 2026-11-22 | [diskos-firmware-re-status-2026-11-22.md](diskos-firmware-re-status-2026-11-22.md) | investigation |
| 2026-11-22 | [opencode-orvix-provider-from-hermes-agent-2026-11-22.md](opencode-orvix-provider-from-hermes-agent-2026-11-22.md) | how-to |
| 2026-11-20 | [fedora43-btrfs-disk-usage-audit-steam-flatpak-orphan-2026-11-20.md](fedora43-btrfs-disk-usage-audit-steam-flatpak-orphan-2026-11-20.md) | investigation |
| 2026-11-20 | [diskos-usb-audio-reverse-engineering-mq-player.md](diskos-usb-audio-reverse-engineering-mq-player.md) | investigation |
| 2026-11-20 | [vesktop-update-fedora-rpm-2026-11-20.md](vesktop-update-fedora-rpm-2026-11-20.md) | how-to |
| 2026-11-19 | [redmi-note-12-pro-hyperos-duplicate-storage-folders-2026-11-19.md](redmi-note-12-pro-hyperos-duplicate-storage-folders-2026-11-19.md) | investigation |
| 2026-11-19 | [diskos-flash-build-7-2026-11-19.md](diskos-flash-build-7-2026-11-19.md) | how-to |
| 2026-11-19 | [diskos-fork-build-7-release-2026-11-19.md](diskos-fork-build-7-release-2026-11-19.md) | how-to |
| 2026-11-18 | [diskos-ui-deepening-six-modules-and-harness-2026-11-18.md](diskos-ui-deepening-six-modules-and-harness-2026-11-18.md) | build-log |
| 2026-11-18 | [diskos-build-harness-declare-once-tests-2026-11-18.md](diskos-build-harness-declare-once-tests-2026-11-18.md) | build-log |
| 2026-11-18 | [outlook-bulk-inbox-cleanup-categories-browser-agent-2026-11-18.md](outlook-bulk-inbox-cleanup-categories-browser-agent-2026-11-18.md) | troubleshooting |
| 2026-11-18 | [diskos-card-module-card-close-spine-2026-11-18.md](diskos-card-module-card-close-spine-2026-11-18.md) | build-log |
| 2026-11-18 | [wrapper-v2-apple-music-fps-podman-fedora-2026-11-18.md](wrapper-v2-apple-music-fps-podman-fedora-2026-11-18.md) | how-to |
| 2026-11-18 | [diskos-idle-machine-idlegov-extract-2026-11-18.md](diskos-idle-machine-idlegov-extract-2026-11-18.md) | build-log |
| 2026-11-18 | [gmail-bulk-inbox-cleanup-browser-agent-2026-11-18.md](gmail-bulk-inbox-cleanup-browser-agent-2026-11-18.md) | troubleshooting |
| 2026-11-18 | [diskos-transport-command-vocabulary-2026-11-18.md](diskos-transport-command-vocabulary-2026-11-18.md) | build-log |
| 2026-11-18 | [fedora-pipewire-snowsky-disc-missing-falls-back-analog-2026-11-18.md](fedora-pipewire-snowsky-disc-missing-falls-back-analog-2026-11-18.md) | troubleshooting |
| 2026-11-18 | [cheapest-cs43198-dap-indonesia-2026-11-18.md](cheapest-cs43198-dap-indonesia-2026-11-18.md) | investigation |
| 2026-11-18 | [gamdl-apple-music-downloader-install-fedora-2026-11-18.md](gamdl-apple-music-downloader-install-fedora-2026-11-18.md) | how-to |
| 2026-11-11 | [hermes-gateway-restart-deferred-runtime-draining-2026-11-11.md](hermes-gateway-restart-deferred-runtime-draining-2026-11-11.md) | troubleshooting |
| 2026-11-10 | [diskos-usb-debug-source-menu-serial-no-ethernet-2026-11-10.md](diskos-usb-debug-source-menu-serial-no-ethernet-2026-11-10.md) | investigation |
| 2026-11-11 | [diskos-usb-audio-volume-keys-double-click-and-hold-2026-11-11.md](diskos-usb-audio-volume-keys-double-click-and-hold-2026-11-11.md) | troubleshooting |
| 2026-11-11 | [diskos-working-mode-auto-via-local-2026-11-11.md](diskos-working-mode-auto-via-local-2026-11-11.md) | how-to |
| 2026-11-11 | [diskos-settings-ui-round-buttons-theme-kit-keep-and-battery-qs-2026-11-11.md](diskos-settings-ui-round-buttons-theme-kit-keep-and-battery-qs-2026-11-11.md) | how-to |
| 2026-11-11 | [snowsky-disc-quieter-sound-dac-filter-nos-sysconfig-db-2026-11-11.md](snowsky-disc-quieter-sound-dac-filter-nos-sysconfig-db-2026-11-11.md) | troubleshooting |
| 2026-11-11 | [snowsky-disc-quieter-after-usb-audio-cs43131-reinit-gain-reset-2026-11-11.md](snowsky-disc-quieter-after-usb-audio-cs43131-reinit-gain-reset-2026-11-11.md) | troubleshooting |
| 2026-11-11 | [diskos-eq-how-it-works-and-upstream-1-2-2-port-2026-11-11.md](diskos-eq-how-it-works-and-upstream-1-2-2-port-2026-11-11.md) | investigation |
| 2026-11-12 | [forgejo-create-pull-mirror-with-temporary-admin-token-2026-11-12.md](forgejo-create-pull-mirror-with-temporary-admin-token-2026-11-12.md) | how-to |
| 2026-11-10 | [hermes-mcp-servers-audit-cloudflare-truenas-2026-11-10.md](hermes-mcp-servers-audit-cloudflare-truenas-2026-11-10.md) | investigation |
| 2026-11-10 | [evomem-usage-review-vs-upstream-2026-11-10.md](evomem-usage-review-vs-upstream-2026-11-10.md) | investigation |
| 2026-11-10 | [evomem-claude-code-capture-broken-and-stale-kb-2026-11-10.md](evomem-claude-code-capture-broken-and-stale-kb-2026-11-10.md) | investigation |
| 2026-11-10 | [diskos-boot-starting-state-and-boot-net-errors-2026-11-10.md](diskos-boot-starting-state-and-boot-net-errors-2026-11-10.md) | investigation |
| 2026-11-09 | [horizon-offline-launcher-linux-prepare-failing.md](horizon-offline-launcher-linux-prepare-failing.md) | troubleshooting |
| 2026-11-09 | [redmi-note-12-pro-ruby-apple-music-192khz-jack-vs-usb-dac.md](redmi-note-12-pro-ruby-apple-music-192khz-jack-vs-usb-dac.md) | investigation |
| 2026-11-09 | [redmi-10-selene-dac-compat-and-dap-setup-research.md](redmi-10-selene-dac-compat-and-dap-setup-research.md) | investigation |
| 2026-11-07 | [px2-perses-monitoring-added.md](px2-perses-monitoring-added.md) | how-to |
| 2026-11-07 | [memos-k3s-deploy-on-home.md](memos-k3s-deploy-on-home.md) | how-to |
| 2026-11-06 | [home-nixos-flake-lock-update-check-2026-11-06.md](home-nixos-flake-lock-update-check-2026-11-06.md) | investigation |
| 2026-11-06 | [hermes-to-evonic-migration.md](hermes-to-evonic-migration.md) | how-to |
| 2026-11-06 | [evonic-vs-hermes-agent-benchmark.md](evonic-vs-hermes-agent-benchmark.md) | investigation |
| 2026-11-06 | [home-disk-usage-audit-and-log-retention-2026-11-06.md](home-disk-usage-audit-and-log-retention-2026-11-06.md) | how-to |
| 2026-11-06 | [evomem-search-algorithm-research.md](evomem-search-algorithm-research.md) | investigation |
| 2026-11-06 | [home-disk-usage-audit-and-log-retention-2026-11-06.md](home-disk-usage-audit-and-log-retention-2026-11-06.md) | cloudflared, smart, disk, home, nixos, journald, tmpfiles, technitium, nix-gc, k3s, containerd, hermes, vmalert, alerting, arm1 | 2026-11-06 |
| [evomem-utcp-endpoint-fork-and-deploy.md](evomem-utcp-endpoint-fork-and-deploy.md) | how-to |
| 2026-11-06 | [evomem-mcp-failures-diagnosis.md](evomem-mcp-failures-diagnosis.md) | investigation |
| 2026-11-05 | [perses-dashboards-audit-and-expansion-2026-11-05.md](perses-dashboards-audit-and-expansion-2026-11-05.md) | how-to |
| 2026-11-05 | [mikrotik-hex-s-sqm-cake-fq-codel-cpu-ceiling.md](mikrotik-hex-s-sqm-cake-fq-codel-cpu-ceiling.md) | investigation |
| 2026-11-05 | [mediatek-usb-audio-hal-mt6768-reverse-engineering.md](mediatek-usb-audio-hal-mt6768-reverse-engineering.md) | investigation |
| 2026-11-05 | [android-apple-music-usb-dac-bit-perfect-redmi-10-selene.md](android-apple-music-usb-dac-bit-perfect-redmi-10-selene.md) | investigation |
| 2026-11-05 | [immich-medium-tests-leak-exiftool-and-postgres.md](immich-medium-tests-leak-exiftool-and-postgres.md) | troubleshooting |
| 2026-11-03 | [redmi-10-magisk-zygisk-play-integrity-fork-device-integrity-fails.md](redmi-10-magisk-zygisk-play-integrity-fork-device-integrity-fails.md) | investigation |
| 2026-10-29 | [arm4-uptime-kuma-flapping-and-persistent-journal.md](arm4-uptime-kuma-flapping-and-persistent-journal.md) | troubleshooting |
| 2026-10-28 | [boox-poke3-adb-debloat-telemetry-and-firmware-check.md](boox-poke3-adb-debloat-telemetry-and-firmware-check.md) | how-to |
| 2026-10-27 | [diskos-build-diskos-bin-image-locally.md](diskos-build-diskos-bin-image-locally.md) | how-to |
| 2026-10-27 | [diskos-loudness-spdif-ja11-and-main-release.md](diskos-loudness-spdif-ja11-and-main-release.md) | investigation |
| 2026-10-27 | [diskos-pet-tamagotchi-app-digimon-agents.md](diskos-pet-tamagotchi-app-digimon-agents.md) | how-to |
| 2026-10-27 | [diskos-screenshots-over-key-ssh-and-terminal-home-layout.md](diskos-screenshots-over-key-ssh-and-terminal-home-layout.md) | how-to |
| 2026-10-27 | [diskos-lastfm-removal-terminal-cursor-and-subagent-worktrees.md](diskos-lastfm-removal-terminal-cursor-and-subagent-worktrees.md) | how-to |
| 2026-10-27 | [diskos-persistent-clock-timekeep.md](diskos-persistent-clock-timekeep.md) | troubleshooting |
| 2026-10-30 | [diskos-strip-comments-from-source-into-comments-md.md](diskos-strip-comments-from-source-into-comments-md.md) | how-to |
| 2026-10-27 | [diskos-hotload-gotchas-test-outputs-usb-storage-reboot.md](diskos-hotload-gotchas-test-outputs-usb-storage-reboot.md) | troubleshooting |
| 2026-10-27 | [diskos-fork-consolidated-into-dev-branch.md](diskos-fork-consolidated-into-dev-branch.md) | how-to |
| 2026-10-27 | [diskos-persistent-debug-checkboxes.md](diskos-persistent-debug-checkboxes.md) | how-to |
| 2026-10-27 | [diskos-ui-architecture-review-output-sequencer-design.md](diskos-ui-architecture-review-output-sequencer-design.md) | investigation |
| 2026-10-29 | [diskos-session-and-play-admission-modules-parallel-agents.md](diskos-session-and-play-admission-modules-parallel-agents.md) | how-to |
| 2026-10-29 | [diskos-disc-player-stuck-play-thread-spin-flash-size-root-limits.md](diskos-disc-player-stuck-play-thread-spin-flash-size-root-limits.md) | troubleshooting |
| 2026-10-29 | [diskos-usb-dac-app-stream-rate-pcm-dsd-volume.md](diskos-usb-dac-app-stream-rate-pcm-dsd-volume.md) | how-to |
| 2026-10-29 | [diskos-ultrareview-dev-to-main-findings-and-first-fixes.md](diskos-ultrareview-dev-to-main-findings-and-first-fixes.md) | investigation |
| 2026-10-29 | [diskos-dev-next-steps-plan-2026-10-29.md](diskos-dev-next-steps-plan-2026-10-29.md) | how-to |
| 2026-10-29 | [diskos-parallel-wave-keyssh-restore-switchflow-radio-icon-backbutton.md](diskos-parallel-wave-keyssh-restore-switchflow-radio-icon-backbutton.md) | how-to |
| [diskos-srcswitch-source-mode-switch-extraction.md](diskos-srcswitch-source-mode-switch-extraction.md) | diskos, snowsky-disc, architecture, refactor, srcswitch, source-mode, usb-storage, usb-dac, host-tests, podman, hot-load | current | 2026-10-29 |
| [diskos-apps-page-scrolls-up-when-settings-tile-pressed.md](diskos-apps-page-scrolls-up-when-settings-tile-pressed.md) | diskos, snowsky-disc, lvgl, apps, scroll-on-focus, touch, input-injection, evdev, hot-load | current | 2026-10-29 |
| 2026-10-27 | [evomem-search-timeout-cached-vocabulary-fix.md](evomem-search-timeout-cached-vocabulary-fix.md) | evomem search timeouts: real cause was a per-query full word_index vocabulary scan (not a vector scan); fixed with a cached vocabulary, ~5 s -> ~0.3 s |
| 2026-10-27 | [8bitdo-ultimate-2c-wireless-linux-web-firmware-update.md](8bitdo-ultimate-2c-wireless-linux-web-firmware-update.md) | how-to |
| 2026-10-27 | [fission-rational-hifi-firmware-upgrade-linux-flasher-ktmicro-kt0211l.md](fission-rational-hifi-firmware-upgrade-linux-flasher-ktmicro-kt0211l.md) | how-to |
| 2026-10-27 | [ktmicro-dsp-dongles-fission-ja11-chu2-same-chip-comparison-and-otg.md](ktmicro-dsp-dongles-fission-ja11-chu2-same-chip-comparison-and-otg.md) | investigation |
| 2026-10-27 | [moondrop-chu2-dsp-ktmicro-peq-match-tin-hifi-c7.md](moondrop-chu2-dsp-ktmicro-peq-match-tin-hifi-c7.md) | how-to |
| 2026-10-26 | [fiio-ja11-peq-match-tin-hifi-c7-hidraw.md](fiio-ja11-peq-match-tin-hifi-c7-hidraw.md) | how-to |
| 2026-10-26 | [tanchjim-fission-ktmicro-dsp-peq-match-tin-hifi-c7.md](tanchjim-fission-ktmicro-dsp-peq-match-tin-hifi-c7.md) | how-to |
| 2026-10-28 | [tanchjim-fission-peq-match-crinear-daybreak.md](tanchjim-fission-peq-match-crinear-daybreak.md) | how-to |
| 2026-10-27 | [tanchjim-fission-peq-match-crinear-nightfall-cross-rig.md](tanchjim-fission-peq-match-crinear-nightfall-cross-rig.md) | how-to |
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
| 2026-10-29 | [immich-external-library-offline-assets-relink.md](immich-external-library-offline-assets-relink.md) | investigation |
| 2026-10-28 | [immich-effect-v4-stage4-verification.md](immich-effect-v4-stage4-verification.md) | how-to |
| 2026-10-28 | [immich-effect-v4-stage3-utils-streams.md](immich-effect-v4-stage3-utils-streams.md) | how-to |
| 2026-10-21 | [immich-effect-v4-stage3-utils-streams.md](immich-effect-v4-stage3-utils-streams.md) | immich, fork, effect, effect-ts, nestjs, streams, subagents, podman | 2026-10-28 |
| [immich-effect-v4-stage2-services.md](immich-effect-v4-stage2-services.md) | how-to |
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
| 2026-10-28 | [xiaomi-phone-music-library-sync-adb.md](xiaomi-phone-music-library-sync-adb.md) | how-to |
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
| [opencode-auto-compaction-200k-context-2026-11-29.md](opencode-auto-compaction-200k-context-2026-11-29.md) | opencode, compaction, config, context-window, deepseek, opencode-go, fedora | 2026-11-29 |
| [home-directory-reorg-projects-logs-probes-2026-11-27.md](home-directory-reorg-projects-logs-probes-2026-11-27.md) | fedora, home, organization, filesystem, mv, projects, systemd, dotfiles, agent-config, diskos, immich, oxigram, ktflash, probes, cleanup | 2026-11-27 |
| [kt02h20-generic-31b2-1052-crossflash-ja11-v21-2026-11-27.md](kt02h20-generic-31b2-1052-crossflash-ja11-v21-2026-11-27.md) | kt02h20, ktmicro, 31b2-1052, crossflash, ja11, fiio, jadeaudio, ktflash, firmware, usb-dac, hid, fedora, linux, alsa, pipewire | 2026-11-27 |
| [opencode-hermes-default-model-opencode-go-2026-11-27.md](opencode-hermes-default-model-opencode-go-2026-11-27.md) | opencode, hermes, model, default, opencode-go, deepseek, config, nixos, home, fedora | 2026-11-27 |
| [ternary-bonsai-27b-mtp-7800xt-vulkan-2026-11-26.md](ternary-bonsai-27b-mtp-7800xt-vulkan-2026-11-26.md) | llama.cpp, vulkan, rocm, vllm, gfx1101, rx-7800-xt, gguf, ternary, mtp, speculative-decoding, bonsai, qwen | 2026-11-26 |
| [ktflash-rust-toolkit-linux-kt02h20-reflash-2026-11-26.md](ktflash-rust-toolkit-linux-kt02h20-reflash-2026-11-26.md) | kt02h20, ktmicro, fiio-ja11, jcally-jm12, moondrop, usb-dac, firmware, ktflash, rust, fedora | 2026-11-27 |
| [opencode-orvix-provider-from-hermes-agent-2026-11-22.md](opencode-orvix-provider-from-hermes-agent-2026-11-22.md) | opencode, hermes, orvix, provider, model, api-key, fedora, home, nixos | 2026-11-22 |
| [vesktop-update-fedora-rpm-2026-11-20.md](vesktop-update-fedora-rpm-2026-11-20.md) | vesktop, discord, fedora, rpm, update-alternatives, electron, vencord | 2026-11-20 |
| [diskos-flash-build-7-2026-11-19.md](diskos-flash-build-7-2026-11-19.md) | diskos, flash, mask-rom, installer, build-7, mq_ui, snowsky-disc, fat, unmount, verification | 2026-11-19 |
| [diskos-fork-build-7-release-2026-11-19.md](diskos-fork-build-7-release-2026-11-19.md) | diskos, release, github, fork, tag, mq_ui, cross-build, podman, snowsky-disc, stable | 2026-11-19 |
| [wrapper-v2-apple-music-fps-podman-fedora-2026-11-18.md](wrapper-v2-apple-music-fps-podman-fedora-2026-11-18.md) | wrapper-v2, apple-music, gamdl, fairplay, drm, podman, quadlet, fedora, alac, lossless | 2026-11-18 |
| [gamdl-apple-music-downloader-install-fedora-2026-11-18.md](gamdl-apple-music-downloader-install-fedora-2026-11-18.md) | gamdl, apple-music, music, downloader, fedora, uv, widevine, drm, cli | 2026-11-18 |
| [diskos-device-check-2026-11-12-and-choice-picker-scroll-fix.md](diskos-device-check-2026-11-12-and-choice-picker-scroll-fix.md) | diskos, snowsky-disc, verification, apps-page, equalizer, settings, quick-settings, max-volume, working-mode, tinj, screenshots, upstream | 2026-11-12 |
| [px2-perses-monitoring-added.md](px2-perses-monitoring-added.md) | perses, victoriametrics, vmagent, proxmox, px2, node-exporter, blackbox, dashboard, k3s, home, monitoring, pve-exporter | 2026-11-07 |
| [memos-k3s-deploy-on-home.md](memos-k3s-deploy-on-home.md) | memos, memogram, telegram, k3s, metallb, truenas-iscsi, service-links, caddy, route-manager | 2026-11-07 |
| [hermes-to-evonic-migration.md](hermes-to-evonic-migration.md) | hermes, evonic, telegram, cron, systemd-timers, nixos, home, migration, evomem, multi-agent, profiles | 2026-11-06 |
| [evomem-utcp-endpoint-fork-and-deploy.md](evomem-utcp-endpoint-fork-and-deploy.md) | evomem, utcp, mcp, rust, nixos, home, fork, deploy, claude-code, skill, podman | 2026-11-06 |
| [perses-dashboards-audit-and-expansion-2026-11-05.md](perses-dashboards-audit-and-expansion-2026-11-05.md) | perses, metallb, coredns, cert-manager, vmalert, victoriametrics, dashboard, promql, k3s, home, monitoring, node-exporter, snmp, blackbox, zfs, proxmox, helm, oomkilled, subagents | 2026-11-05 |
| [diskos-usb-audio-headset-click-gestures-and-flash.md](diskos-usb-audio-headset-click-gestures-and-flash.md) | diskos, snowsky-disc, usb-audio, usbhid, headset, ja11, click-gestures, subagents, flash | 2026-10-31 |
| [redmi-note-12-pro-hyperos2-adb-debloat.md](redmi-note-12-pro-hyperos2-adb-debloat.md) | android, xiaomi, redmi, hyperos, adb, debloat, uad-ng, mediatek | 2026-10-28 |
| [boox-poke3-adb-debloat-telemetry-and-firmware-check.md](boox-poke3-adb-debloat-telemetry-and-firmware-check.md) | boox, onyx, poke3, android10, e-ink, adb, debloat, telemetry, firmware, koreader | 2026-10-28 |
| [fission-rational-hifi-firmware-upgrade-linux-flasher-ktmicro-kt0211l.md](fission-rational-hifi-firmware-upgrade-linux-flasher-ktmicro-kt0211l.md) | tanchjim, fission, ktmicro, kt0211l, firmware, flash, rea, ghidra, reverse-engineering, fedora | 2026-10-27 |
| [moondrop-chu2-dsp-ktmicro-peq-match-tin-hifi-c7.md](moondrop-chu2-dsp-ktmicro-peq-match-tin-hifi-c7.md) | moondrop, chu-ii-dsp, ktmicro, dsp, peq, hidraw, squig-link, iem, eq, tin-hifi | 2026-10-27 |
| [fiio-ja11-peq-match-tin-hifi-c7-hidraw.md](fiio-ja11-peq-match-tin-hifi-c7-hidraw.md) | fiio, ja11, ktmicro, dsp, peq, hidraw, squig-link, iem, eq, tin-hifi | 2026-10-26 |
| [tanchjim-fission-ktmicro-dsp-peq-match-tin-hifi-c7.md](tanchjim-fission-ktmicro-dsp-peq-match-tin-hifi-c7.md) | tanchjim, fission, ktmicro, dsp, peq, hid, squig-link, iem, eq, fedora | 2026-10-26 |
| [tanchjim-fission-peq-match-crinear-nightfall-cross-rig.md](tanchjim-fission-peq-match-crinear-nightfall-cross-rig.md) | tanchjim, fission, ktmicro, dsp, peq, squig-link, crinear-nightfall, cross-rig | 2026-10-27 |
| [tanchjim-fission-peq-match-crinear-daybreak.md](tanchjim-fission-peq-match-crinear-daybreak.md) | tanchjim, fission, ktmicro, dsp, peq, squig-link, crinear-daybreak, ja11, chu-ii | 2026-10-28 |
| [samsung-tv-t6500-sideload-and-apps.md](samsung-tv-t6500-sideload-and-apps.md) | samsung, tizen, tv, sideload, sdb, tizen-studio, fedora, clean-home, youtube, tizentube, ad-block | 2026-10-25 |
| [samsung-tv-t6500-power-states-and-remote-control.md](samsung-tv-t6500-power-states-and-remote-control.md) | samsung, tizen, kants2, t6500, power, standby, wol, ex-link, mdc, suspend, sdb | 2026-10-25 |
| [xiaomi-fm-radio-backup-and-cross-device-install.md](xiaomi-fm-radio-backup-and-cross-device-install.md) | android, xiaomi, redmi, fm-radio, adb, wireless-debugging, apk-backup | 2026-10-23 |
| [redmi-10-miui125-adb-debloat-telemetry-ads.md](redmi-10-miui125-adb-debloat-telemetry-ads.md) | android, xiaomi, redmi, miui, adb, debloat, telemetry, ads | 2026-10-23 |
| [diskos-stock-plus-round-screen-features-and-flash.md](diskos-stock-plus-round-screen-features-and-flash.md) | fiio, snowsky-disc, diskos, lvgl, round-display, flash, usbboot | 2026-10-23 |
| [immich-effect-v4-stage1-repositories.md](immich-effect-v4-stage1-repositories.md) | immich, fork, effect, effect-ts, nestjs, kysely, subagents, git-subtree | 2026-10-21 |
| [immich-strip-ai-machine-learning-fork.md](immich-strip-ai-machine-learning-fork.md) | immich, fork, machine-learning, postgres, migration, pnpm, podman | 2026-10-21 |
| [fiio-snowsky-disc-diskos-flash-fedora.md](fiio-snowsky-disc-diskos-flash-fedora.md) | fiio, snowsky-disc, diskos, dap, ingenic, mask-rom, flashing, squashfs, udev, fedora, usb-dac, usb-audio | 2026-10-19 |
| [snowsky-disc-music-sync-from-nas.md](snowsky-disc-music-sync-from-nas.md) | fiio, snowsky-disc, rsync, nas, fat32, fsck, dedup, flac | 2026-10-28 |
| [xiaomi-phone-music-library-sync-adb.md](xiaomi-phone-music-library-sync-adb.md) | xiaomi, android, adb, music, nas, sync | 2026-10-28 |
| [pipewire-native-sample-rate-usb-dac-cosmic-volume-keys.md](pipewire-native-sample-rate-usb-dac-cosmic-volume-keys.md) | pipewire, fedora, cosmic, usb-dac, sample-rate, bit-perfect, volume-keys | 2026-10-19 |
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
| [comfyui-removal-2026-11-22.md](comfyui-removal-2026-11-22.md) | comfyui, removal, uninstall, cleanup, fedora, systemd, firewalld, caddy, technitium, nixos, rocm, gguf | 2026-11-22 |
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
| [agy-tmux-ssh-file-token-relogin-2026-11-28.md](agy-tmux-ssh-file-token-relogin-2026-11-28.md) | antigravity, agy, tmux, ssh, keyring, oauth, token-storage, fedora, cosmic | 2026-11-28 |
| [camofox-bundle-cache-sweep-durable-install-2026-11-28.md](camofox-bundle-cache-sweep-durable-install-2026-11-28.md) | camofox, camoufox, home, nixos, systemd, hermes, cache-cleanup, provisioning, opencode, websearch | 2026-11-28 |
| [camofox-browser-missing-binary-http500-2026-11-28.md](camofox-browser-missing-binary-http500-2026-11-28.md) | camofox, camoufox, mcp, headless-browser, browser-automation, home, nixos, systemd, hermes, health-check | 2026-11-28 |
| [light-agent-ecrrefused-8099-hidraw-ownership-2026-11-28.md](light-agent-ecrrefused-8099-hidraw-ownership-2026-11-28.md) | light-agent, vm-bot, telegram, gbrgb, hidraw, udev, uaccess, fedora, cosmic-greeter, systemd-user, rgb | 2026-11-28 |
| [hermes-gateway-post-reboot-mcp-children-2026-11-28.md](hermes-gateway-post-reboot-mcp-children-2026-11-28.md) | hermes, hermes-gateway, mcp, telegram, gowa, k3s, home, nixos, systemd, polkit, reboot | 2026-11-28 |
| [home-vm-reboot-hangs-k3s-killall-self-stop-2026-11-28.md](home-vm-reboot-hangs-k3s-killall-self-stop-2026-11-28.md) | home, proxmox, px1, k3s, systemd, shutdown, reboot, deadlock, nixos, k3s-killall, prestop | 2026-11-28 |
| [android-vpn-jsch-stream-order-and-ipv6-leak-2026-11-27.md](android-vpn-jsch-stream-order-and-ipv6-leak-2026-11-27.md) | android, vpnservice, vpn, jsch, ssh, direct-tcpip, ipv6, leak, foreground-service, kotlin, gradle, ndk, cloudflared, multi-profile | 2026-11-27 |
| [fiio-ja11-stuck-bootloader-recover-wrong-firmware-2026-11-27.md](fiio-ja11-stuck-bootloader-recover-wrong-firmware-2026-11-27.md) | fiio, jadeaudio, ja11, kt02h20, ktmicro, usb-dac, firmware, brick, bootloader, ktflash, fiio-control, android, otg, fedora, linux, alsa, pipewire | 2026-11-27 |
| [openrgb-two-instances-at-login-systemd-xdg-autostart-2026-11-27.md](openrgb-two-instances-at-login-systemd-xdg-autostart-2026-11-27.md) | openrgb, systemd, xdg-autostart, fedora, autostart, rgb, login, systemd-xdg-autostart-generator | 2026-11-27 |
| [fedora-pipewire-snowsky-disc-missing-falls-back-analog-2026-11-18.md](fedora-pipewire-snowsky-disc-missing-falls-back-analog-2026-11-18.md) | snowsky-disc, fiio, usb-audio, pipewire, wireplumber, fedora, alsa, dac | 2026-11-18 |
| [hermes-gateway-restart-deferred-runtime-draining-2026-11-11.md](hermes-gateway-restart-deferred-runtime-draining-2026-11-11.md) | hermes, hermes-gateway, telegram, systemd, home, runtime-draining, restart, cron | 2026-11-11 |
| [immich-medium-tests-leak-exiftool-and-postgres.md](immich-medium-tests-leak-exiftool-and-postgres.md) | immich, vitest, exiftool, testcontainers, ryuk, podman, memory, orphan-processes | 2026-11-05 |
| [arm4-uptime-kuma-flapping-and-persistent-journal.md](arm4-uptime-kuma-flapping-and-persistent-journal.md) | arm4, armbian, uptime-kuma, victoriametrics, journald, armbian-ramlog, cloudflared, flapping | 2026-10-29 |
| [evomem-search-timeout-cached-vocabulary-fix.md](evomem-search-timeout-cached-vocabulary-fix.md) | evomem, mcp, timeout, search, latency, sqlite, embeddings | 2026-10-27 |
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
| [diskos-audit-25-categories-dev-2f705ac-2026-11-28.md](diskos-audit-25-categories-dev-2f705ac-2026-11-28.md) | diskos, snowsky-disc, audit, subagents, worktrees, sqlite, wifi, bluetooth, http, ota, timezone, playlists, installer | current: 25 category audit fixed on 11 file-disjoint branches from `2f705ac`, merged into `dev` at `a3fa383`; 23 commits, 50 files, +1,384/-379; clean mipsel build 5,537,452 bytes md5 `157a0a0e`, 23 warnings, 0 errors; `make -C ui/tests check` exit 0, 55 C groups and 7 Python COMPLETE, 0 FAIL; skipped `mdb_core_close` call, Up Next rewrite, registry `BEGIN IMMEDIATE`, UNIQUE PEQ; not flashed, Disc offline | 2026-11-28 |
| [diskos-flash-dev-82ffa18-2026-11-28.md](diskos-flash-dev-82ffa18-2026-11-28.md) | diskos, snowsky-disc, flash, mask-rom, installer, dev, mq_ui, command-spawn, boot-splash | current: `dev` `82ffa18` flashed from the local build with `--ui ui/mq_ui --variant public -y`; image md5 `04d80ed4`, baked UI md5 `21c3f99c` matching source, manifest sha256 `84725ec3`, size 5,528,880; 20 m 10 s total, `SUCCESS` at 20:36:55, same bad blocks [128, 522]; post-boot checks pending | 2026-11-28 |
| [diskos-architecture-review-seven-findings-2026-11-28.md](diskos-architecture-review-seven-findings-2026-11-28.md) | diskos, snowsky-disc, architecture, refactor, subagents, worktrees, command-spawn, wifi, dhcp, playctl, gesture, coverart, sqlite, boot-splash, host-tests | current: all 7 review findings implemented on 7 worktree branches and merged into `dev` at `a87980f`; command_spawn (`dd54748`), wifisup (`49373ed`), playctl (`00d98ca`), mdb_core + playlistdb (`7dae7ac`), coverart seam (`88c79ec`), gesture (`f59c0b6`), splash-first boot (`e865491`); restored `PR_SET_PDEATHSIG` for the `wpa_cli` listener via `command_spawn_lifetime` (`9b8a4c5`); checkpoint `82ffa18` fixed 8 merge regressions; clean mipsel build 5,528,880 bytes md5 `21c3f99c`, 23 warnings, 54 host test groups exit 0; image flashed on V2.57, post-boot checks pending | 2026-11-28 |
| [diskos-wifisup-extract-2026-11-28.md](diskos-wifisup-extract-2026-11-28.md) | diskos, snowsky-disc, wifi, wifisup, dhcp, wpa-cli, refactor, ports-and-adapters, host-tests | current: Wi-Fi radio policy and 5-phase lease FSM moved out of `wifi.c` (1,232 -> 711 lines) into host-testable `wifisup`; branch md5 `239a3595`, superseded by the integration binary `02855665` | 2026-11-28 |
| [diskos-codebase-audit-fixes-2026-11-28.md](diskos-codebase-audit-fixes-2026-11-28.md) | diskos, snowsky-disc, code-audit, concurrency, sqlite, performance, subagents, c, python | current: all 25 audit categories worked; 9 parallel agents by file ownership + batch APIs after; commits `5b25831`, `a8f96db`, `fc88105`, `f162cf5`, `13b551a`; mipsel musl build 4,367,560 bytes, host ASan/UBSan suite exit 0, installer suite at its 9 pre-existing failures; `dev` integrates WAL (`14.3`) and HTTP reuse (`18`, libcurl + mbedTLS); build and host suite pass, device HTTP/WAL probes pass; released as build 8 (`v1.2.1-fork.8`, `15e45ff`, md5 `b3168307`), flashed and writer-verified, boot check pending | 2026-11-28 |
| [fedora43-workstation-debloat-service-and-cache-audit-2026-11-28.md](fedora43-workstation-debloat-service-and-cache-audit-2026-11-28.md) | fedora, fedora43, debloat, systemd, services, autostart, caches, podman, flatpak, kernel, btrfs, compression, uv-cache, disk-usage, cosmic, workstation | current: RPMs already lean (`dnf repoquery --unneeded` = 1 package, 2832 installed); two rounds took `/` from **245 G (53 %) to 164 G (35 %), 81 GB real**, 306 G free; round 1 safe caches (`~/.cache` 47 G → 8.4 G, `~/.npm` 5.1 G → 2.7 G) delivered only 20 GB because the uv cache was `18.7 GiB apparent / ~123 MiB exclusive` (hardlinks into venvs), `/` is `compress=zstd:1`, and btrfs frees async; round 2 pruned 9.3 G of dangling podman images plus stopped container, removed Stremio + Protontricks + ProtonUp-Qt (the last by mistake), dropped kernel 7.3.3 and 2 stale `kernel-devel` (736 MiB), disabled `gnome-remote-desktop` and masked 9 autostart leftovers, deleted orphaned `/root/models` (57 G, `llama-server.service` disabled and its `qwen35-9b` path already gone); podman still holds 7.4 G in 61 unused images (`image prune -a` not run); `protontricks` is `com.github.Matoking.protontricks`, not `net.davidotek.pupgui2` | 2026-11-28 |
| [home-directory-audit-2026-11-28.md](home-directory-audit-2026-11-28.md) | fedora, home, organization, audit, filesystem, btrfs, disk-usage, duplicates, android-sdk, oxigram, beets, net-diag, scripts, secrets, nfs | current: visible root 36 entries (27 dirs, 9 files), 94 hidden dirs; `/home` btrfs 245 G used of 475 G, `nfs_photos` a separate NFS mount; ~9 GiB exclusive reclaimable across a duplicate Coldplay album (2.45 GiB, track hashed), `oxigram-build` (1.90 GiB), `src/oxigram/target` (~1.88 GiB), and `Android/Sdk` (2.51 GiB); eight loose net-diag scripts unreferenced, target `tools/probes/2026-11-28-net-diag/`; nothing moved | 2026-11-28 |
| [fiio-ja11-firmware-reverse-engineering-output-diagnosis-2026-11-26.md](fiio-ja11-firmware-reverse-engineering-output-diagnosis-2026-11-26.md) | fiio, jadeaudio, ja11, kt02h20, ktmicro, usb-dac, firmware, reverse-engineering, ghidra, rea, nds32, uac1, uac2, peq, dsp, hid | current: core is **Andes NDS32** (independently confirmed), code base `0x80000`, 25,770/55,024 bytes reached, no decompiler; **UAC 1.0/2.0 is FiiO cmd `0x20`**, now UAC 2.0 (`2972:0102`, 480 Mbps, 384 kHz verified); PerfCfg patched ADC `0x10e8` 0x04→0x00 and **DAC `0x10ec` 0x0d→0x05 (−12 dB)**, flashed and verified (`0x3A=0`, `0x3B=5`, mic −91.7 dBFS); **`0x12=0` switches to a playback-only descriptor set** (capture interface gone, `iSerial=0`), `1` restores it; V2.1 compared (PerfCfg 03/0d, identical clean playback), no V2.2 regression; **all of it verified across a real unplug/replug** (device 061 came back `2972:0102` at high speed with `0x3A=0`, `0x3B=5`, flat EQ); image EQ tables at `0x106a`/`0x109a` flat; amp `0x1D` write-only with zero register trace, `0x16` read-only; analog THD+N still unmeasurable (no loopback) | 2026-11-27 |
| [android-apple-music-bitrate-check-audio-flinger-redmi-note-12-pro.md](android-apple-music-bitrate-check-audio-flinger-redmi-note-12-pro.md) | android, apple-music, audioflinger, bitrate, lossless, hi-res, redmi-note-12-pro, adb, dumpsys, bit-perfect, fiio-ja11 | current: Apple Music 7.0.3 opens the AudioTrack at the source rate (44100, 48000 and 192000 Hz observed, `BitPerfect false`); 3.5 mm path mixes at 48 kHz, JA11 USB path mixes at 96 kHz and the USB HAL caps the dongle at 96 kHz, so 24/192 is resampled 2:1 before the DAC; test tracks were offline files (~1.3 KB/s wifi), and the app leaves no MediaCodec audio records | 2026-11-26 |
| [diskos-firmware-re-status-2026-11-22.md](diskos-firmware-re-status-2026-11-22.md) | diskos, snowsky-disc, fiio, ghidra, reverse-engineering, firmware-decompiled, mips, fp64, rea, toolchain-loss | current: RE output intact and pushed (411 ELFs inventoried, 27 decompiled, 34,960 userland + 734 kernel functions, 0 failures); the `/var/tmp` toolchain was stripped, lane rebuilt on `~/tools` with the fp64 language and a jumptable.cc fallback patch, the 3 `wl` switches now decompile with warnings, 0 x86 regressions; `FindFuncs`/`ExportAll` and the kernel artefacts still missing | 2026-11-22 |
| [fedora43-btrfs-disk-usage-audit-steam-flatpak-orphan-2026-11-20.md](fedora43-btrfs-disk-usage-audit-steam-flatpak-orphan-2026-11-20.md) | disk, btrfs, fedora43, compression, zstd, du, steam, flatpak, uv-cache, podman, iso | current: `/` 282 G used (60%) at start, 222 G (48%) after three cleanups; `du` reports apparent size, so real cost was 6.4x lower on the uv cache, 2.1x on game data, 1:1 on ISOs; `btrfs filesystem du -s` gives the real number where `compsize` fails (`SEARCH_V2: Operation not permitted`); deleted a 32 G orphaned `~/.var/app/com.valvesoftware.Steam` tree (backed up to `~/archive`) for 15.0 GiB, `uv cache clean` 46.5 GiB for 7.3 GiB, and four installer files 15.55 G for 15.44 GiB, so 94 G apparent delivered 37.7 GiB; btrfs frees asynchronously, `df` shows zero change until `btrfs filesystem sync` | 2026-11-22 |
| [diskos-usb-audio-reverse-engineering-mq-player.md](diskos-usb-audio-reverse-engineering-mq-player.md) | fiio, snowsky-disc, diskos, usb-audio, otg, reverse-engineering, ghidra, rea, mips | current: USB Audio fixed (switch-then-wait), verified 24/96 to Chu2; build 7 with the JA11 re-checked 2026-11-20, 44.1 and 96 kHz follow the file with no resampling; rea refuses NaN2008 MIPS | 2026-11-20 |
| [redmi-note-12-pro-hyperos-duplicate-storage-folders-2026-11-19.md](redmi-note-12-pro-hyperos-duplicate-storage-folders-2026-11-19.md) | android, hyperos, xiaomi, redmi-note-12-pro, ruby, adb, fuse, sdcard, duplicate-folders, storage, readdir | current: 7 of 42 root entries are returned twice by readdir through FUSE (same inode, no data duplicated); symlink theory and `ls -lid` / `find -type l` tests refuted; `pm clear` on the APEX MediaProvider is a no-op (same playlist `_id`, duplicates unchanged); a cold boot does not clear it either; deleted second space ruled out (only user 0, no 999 mount, f2fs is casefold); a real rebuild needs root | 2026-11-19 |
| [cheapest-cs43198-dap-indonesia-2026-11-18.md](cheapest-cs43198-dap-indonesia-2026-11-18.md) | fiio, snowsky-echo, dap, cs43198, indonesia, shopping, tokopedia, aliexpress | current: cheapest real CS43198 DAP in ID is the FiiO Snowsky ECHO at Rp 1.36-1.41 jt (gray import, Tokopedia); JM21 dual CS43198 ~Rp 2.76 jt with warranty; Echo Mini/Nano are CS43131, Fosi DAP NEO geo-blocked from AliExpress | 2026-11-18 |
| [diskos-usb-debug-source-menu-serial-no-ethernet-2026-11-10.md](diskos-usb-debug-source-menu-serial-no-ethernet-2026-11-10.md) | diskos, snowsky-disc, usb-gadget, configfs, acm, serial, ecm, rndis, usb-debug, source-menu | current: USB Debug row (single ACM serial shell, overlay on Local, ordered exit) built and checked with a PC attached; USB Ethernet impossible: the kernel has no ECM/RNDIS/NCM/EEM, TUN or PPP | 2026-11-10 |
| [diskos-usb-audio-volume-keys-double-click-and-hold-2026-11-11.md](diskos-usb-audio-volume-keys-double-click-and-hold-2026-11-11.md) | diskos, snowsky-disc, usb-audio, dacvol, volume-keys, key-codes, usb-serial | current: volume keys dead on USB Audio when Double click = Switch Track, and hold not working; fixed in dacvol (single, double suppression, hold 262/263), key codes, serial-shell push attempt | 2026-11-11 |
| [diskos-working-mode-auto-via-local-2026-11-11.md](diskos-working-mode-auto-via-local-2026-11-11.md) | diskos, snowsky-disc, working-mode, srcswitch, usb-dac, usb-storage, usb-debug, usb-audio | current: non-Local Working Mode switches hop through Local by themselves (DAC, Bluetooth, Storage with a restart-safe pending target, USB Audio row); tests host-only for Storage | 2026-11-11 |
| [diskos-settings-ui-round-buttons-theme-kit-keep-and-battery-qs-2026-11-11.md](diskos-settings-ui-round-buttons-theme-kit-keep-and-battery-qs-2026-11-11.md) | diskos, snowsky-disc, lvgl, theme-kit, kit_keep, settings, max-volume, quick-settings, battery | current: Max Volume -10/+10 round buttons and knob, battery on Quick Settings; theme kit overrides widget styles unless kit_keep; Max Volume slider stuck at 120 on USB Audio not solved | 2026-11-11 |
| [snowsky-disc-quieter-sound-dac-filter-nos-sysconfig-db-2026-11-11.md](snowsky-disc-quieter-sound-dac-filter-nos-sysconfig-db-2026-11-11.md) | snowsky-disc, cs43131, dac-filter, nos, sysconfig-db, mq_player, loudness | current: sound quieter with DAC Filter on NOS; how to read the Player settings database, filter log and diskOS config | 2026-11-11 |
| [snowsky-disc-quieter-after-usb-audio-cs43131-reinit-gain-reset-2026-11-11.md](snowsky-disc-quieter-after-usb-audio-cs43131-reinit-gain-reset-2026-11-11.md) | snowsky-disc, diskos, cs43131, gain, usb-audio, dac-power, mq_player, outroute | current: 4.4 mm output quieter after USB Audio because the DAC re-init resets Gain; fixed by re-sending gain, DRE and filter after leaving USB | 2026-11-11 |
| [diskos-eq-how-it-works-and-upstream-1-2-2-port-2026-11-11.md](diskos-eq-how-it-works-and-upstream-1-2-2-port-2026-11-11.md) | diskos, snowsky-disc, equalizer, peq, custom-eq, apps-page, upstream | current: how the EQ works (software biquads in mq_player, V2.57 view-only), what upstream v1.2.2 changed, what was ported plus an Equalizer tile on Apps | 2026-11-11 |
| [forgejo-create-pull-mirror-with-temporary-admin-token-2026-11-12.md](forgejo-create-pull-mirror-with-temporary-admin-token-2026-11-12.md) | forgejo, k3s, homelab, pull-mirror, github, api, access-token | current: create a private pull mirror of a GitHub repo on the k3s Forgejo with a short-lived admin-CLI token that is deleted afterwards (done for diskos) | 2026-11-12 |
| [redmi-note-12-pro-ruby-apple-music-192khz-jack-vs-usb-dac.md](redmi-note-12-pro-ruby-apple-music-192khz-jack-vs-usb-dac.md) | android, apple-music, usb-dac, bit-perfect, redmi-note-12-pro, ruby, mt6877, audioflinger | current: 192 kHz plays end to end over USB DAC; 3.5 mm jack HAL capped at 44.1/48 kHz (resampled); 96 kHz was the song; software volume bypassed (media volume 15 = 0 dB, tested); Hi-ResAudio needs root, mtkclient unlock researched but not done | 2026-11-09 |
| [redmi-10-selene-dac-compat-and-dap-setup-research.md](redmi-10-selene-dac-compat-and-dap-setup-research.md) | android, redmi-10, selene, mt6768, magisk, usb-dac, otg, dap, poweramp, miui | current: no Magisk module for DAC detection on MTK/Android 11; Hi-ResAudio refuses Android 11; jack hi-res at 192/96 kHz tested and reverted (CPU cost, weird sound); only lasting change is the Poweramp volume-key grant | 2026-11-09 |
| [home-nixos-flake-lock-update-check-2026-11-06.md](home-nixos-flake-lock-update-check-2026-11-06.md) | nixos, home, flake-lock, nixpkgs, update, dry-activate, ci, k3s, cloudflared, kernel | current: PR #10 checked (CI green, build ok, dry-activate lists the restarts), not deployed | 2026-11-06 |
| [evonic-vs-hermes-agent-benchmark.md](evonic-vs-hermes-agent-benchmark.md) | evonic, hermes, agent-benchmark, nixos, home, deepseek, opencode-go, evomem, fork, subagents | current: 96 runs, accuracy tied at 100 %, Evonic about 1.9x faster, Hermes about 1/3 fewer tool calls | 2026-11-06 |
| [evomem-search-algorithm-research.md](evomem-search-algorithm-research.md) | evomem, search, bm25, rrf, embeddings, hybrid-retrieval, rust, sqlite, latency, multilingual | current: recommendations only; nothing implemented; no Indonesian/chat-transcript benchmark found | 2026-11-06 |
| [evomem-mcp-failures-diagnosis.md](evomem-mcp-failures-diagnosis.md) | evomem, mcp, iscsi, truenas, home, claude-code, hooks, latency, pydantic | current: server healthy; failures were q/query mismatch, a since-fixed latency tail and one bridge startup crash; cold-cache first query and the Nov 2 iSCSI blip still open | 2026-11-06 |
| [mikrotik-hex-s-sqm-cake-fq-codel-cpu-ceiling.md](mikrotik-hex-s-sqm-cake-fq-codel-cpu-ceiling.md) | mikrotik, routeros, hex-s, mmips, sqm, qos, cake, fq-codel, bufferbloat, queue-tree, fasttrack, pppoe | current: CAKE and FQ-CoDel both work on ROS 7.25 hEX S but are single-core bound at ~170 / ~240 Mbps against a 630 Mbps line; bufferbloat already mild (38 ms max under load), so SQM was measured and deliberately left disabled | 2026-11-05 |
| [mediatek-usb-audio-hal-mt6768-reverse-engineering.md](mediatek-usb-audio-hal-mt6768-reverse-engineering.md) | android, mediatek, mt6768, usb-audio, usb-dac, audio-hal, ghidra, reverse-engineering, libalsautils, aurisys | current: static RE of audio.usb.mt6768.so + libalsautils; the "96 kHz cap" is a table-order quirk (96000 first, returned as default/highest), 192 kHz is supported; Aurisys handler in the playback path unverified; no DAC test yet | 2026-11-05 |
| [android-apple-music-usb-dac-bit-perfect-redmi-10-selene.md](android-apple-music-usb-dac-bit-perfect-redmi-10-selene.md) | android, apple-music, usb-dac, bit-perfect, magisk, redmi-10, selene, android11 | current: Android 11 + HIDL USB HAL, no documented Magisk route for Apple Music bit-perfect; measure with dumpsys/stream0 once a DAC is attached | 2026-11-05 |
| [redmi-10-magisk-zygisk-play-integrity-fork-device-integrity-fails.md](redmi-10-magisk-zygisk-play-integrity-fork-device-integrity-fails.md) | android, xiaomi, redmi-10, magisk, zygisk, play-integrity, playintegrityfork, adb | blocked | 2026-11-03 |
| [immich-external-library-offline-assets-relink.md](immich-external-library-offline-assets-relink.md) | immich, external-library, offline-assets, trash, nestjs, effect, kysely | current | 2026-10-29 |
| [immich-fork-memory-usage-analysis.md](immich-fork-memory-usage-analysis.md) | immich, memory, nodejs, sharp, exiftool, bullmq, postgres, podman, performance | current | 2026-10-29 |
| [diskos-build-diskos-bin-image-locally.md](diskos-build-diskos-bin-image-locally.md) | diskos, snowsky-disc, installer, firmware, image, squashfs, bin | current | 2026-10-27 |
| [diskos-loudness-spdif-ja11-and-main-release.md](diskos-loudness-spdif-ja11-and-main-release.md) | diskos, snowsky-disc, volume, gain, loudness, usb-audio, spdif, ja11, wifi-interference, flash, release | current | 2026-10-27 |
| [diskos-pet-tamagotchi-app-digimon-agents.md](diskos-pet-tamagotchi-app-digimon-agents.md) | diskos, snowsky-disc, pet, tamagotchi, digimon, apps, lvgl, subagents, canvas, screenshots | current | 2026-10-27 |
| [diskos-screenshots-over-key-ssh-and-terminal-home-layout.md](diskos-screenshots-over-key-ssh-and-terminal-home-layout.md) | diskos, snowsky-disc, screenshot, framebuffer, terminal-theme, layout, round-screen, lvgl | current | 2026-10-27 |
| [diskos-lastfm-removal-terminal-cursor-and-subagent-worktrees.md](diskos-lastfm-removal-terminal-cursor-and-subagent-worktrees.md) | diskos, snowsky-disc, lastfm, terminal-theme, cursor, lvgl, subagents, worktree, git | current | 2026-10-27 |
| [diskos-persistent-clock-timekeep.md](diskos-persistent-clock-timekeep.md) | diskos, snowsky-disc, rtc, clock, hwclock, ntp, timezone, boot, timekeep | current | 2026-10-27 |
| [diskos-hotload-gotchas-test-outputs-usb-storage-reboot.md](diskos-hotload-gotchas-test-outputs-usb-storage-reboot.md) | diskos, snowsky-disc, hot-load, usb-audio, test-outputs, usb-storage, reboot, podman, ssh | current | 2026-10-27 |
| [diskos-fork-consolidated-into-dev-branch.md](diskos-fork-consolidated-into-dev-branch.md) | diskos, snowsky-disc, git, branches, fork, merge, hot-load, wrong-base | current | 2026-10-27 |
| [diskos-persistent-debug-checkboxes.md](diskos-persistent-debug-checkboxes.md) | diskos, snowsky-disc, debug-mode, ssh, wifi, boot, lvgl, hot-load, podman | current | 2026-10-27 |
| [diskos-ui-architecture-review-output-sequencer-design.md](diskos-ui-architecture-review-output-sequencer-design.md) | diskos, snowsky-disc, ui, c, architecture, refactor, working-mode, output-route, ipc, outseq, c-audit | current | 2026-10-27 |
| [diskos-session-and-play-admission-modules-parallel-agents.md](diskos-session-and-play-admission-modules-parallel-agents.md) | diskos, snowsky-disc, architecture, refactor, session, playadmit, outseq, subagents, worktree, host-tests | current | 2026-10-29 |
| [diskos-disc-player-stuck-play-thread-spin-flash-size-root-limits.md](diskos-disc-player-stuck-play-thread-spin-flash-size-root-limits.md) | diskos, snowsky-disc, mq_player, play_thread, ipc, ssh, flash, mtd, root, squashfs | current | 2026-10-29 |
| [diskos-usb-dac-app-stream-rate-pcm-dsd-volume.md](diskos-usb-dac-app-stream-rate-pcm-dsd-volume.md) | diskos, snowsky-disc, usb-dac, uac2, uevent, netlink, alsa, apps, lvgl | current | 2026-10-29 |
| [diskos-ultrareview-dev-to-main-findings-and-first-fixes.md](diskos-ultrareview-dev-to-main-findings-and-first-fixes.md) | diskos, snowsky-disc, ultrareview, code-review, ipc, installer, chargemode, session, subagents, worktree | current | 2026-10-29 |
| [diskos-dev-next-steps-plan-2026-10-29.md](diskos-dev-next-steps-plan-2026-10-29.md) | diskos, snowsky-disc, plan, roadmap, review-findings, hot-load, flash, release | current | 2026-10-29 |
| [diskos-parallel-wave-keyssh-restore-switchflow-radio-icon-backbutton.md](diskos-parallel-wave-keyssh-restore-switchflow-radio-icon-backbutton.md) | diskos, snowsky-disc, subagents, worktree, debug-mode, key-ssh, session, radio, nowplaying, hot-load, tinj, screenshots | current | 2026-10-29 |
| [ktmicro-dsp-dongles-fission-ja11-chu2-same-chip-comparison-and-otg.md](ktmicro-dsp-dongles-fission-ja11-chu2-same-chip-comparison-and-otg.md) | ktmicro, helios, fission, ja11, chu2-dsp, uac, otg, xiaomi, hidraw | current | 2026-10-27 |
| [samsung-tv-t6500-root-and-persistence.md](samsung-tv-t6500-root-and-persistence.md) | samsung, tizen, tv, root, kants2, uep, kernel-exploit, armv7l, dotnet-launcher, remotepc, cifs, smack, ghidra, persistence, raw-block | current: merges the full root journey (negative compat probe -> Remote PC/CIFS -> archive-root -> dotnet-launcher invocation solved from source -> kernel-exploit survey -> UEP bypass, 152ms fast path -> boot-persistent root via raw-block profile.d patch); the one open thread is a custom launcher as Home target (see the debloat-and-launcher doc), blocked on setuid(5001); UEP mechanism re-measured 2026-10-28 (the signature verdict is per-inode, so no copy is executable on writable storage; execve and PROT_EXEC mappings hit the same kernel handler; the script check is user-space `libkUEPUser` `verifyFile`) and qualified 2026-11-09 by the Q70T controls on issue #29: the preload maps with UEP down (one verifier, two hooks), and an unsigned copy on a read-only bind mount is accepted, so mount writability gates the verdict | 2026-11-14 |
| [redmi-10-magisk-root-swap-zram-and-modules.md](redmi-10-magisk-root-swap-zram-and-modules.md) | android, redmi, miui, magisk, root, swap, zram, lmkd | current: root over adb works (Magisk 30.7); swap already on as 2.2 GB lz4 zram, swappiness 100, MIUI writeback loop device; magisk-swapspace installed but inactive; encore module flagged for removal | 2026-10-23 |
| [snowsky-disc-usb-dac-uac2-android-and-firmware-decompile.md](snowsky-disc-usb-dac-uac2-android-and-firmware-decompile.md) | fiio, snowsky-disc, usb-dac, uac2, android, ghidra, reverse-engineering, firmware | current | 2026-10-22 |
| [kt02h20-jcally-dac-ja11-firmware-flash-protocol.md](kt02h20-jcally-dac-ja11-firmware-flash-protocol.md) | kt02h20, ktmicro, jcally, fiio-ja11, usb-dac, firmware, reverse-engineering, hid, cdc-acm | current: protocol decoded (HID 0x54 unlock -> 8888:cdc0 CDC bootloader), cross-platform CLI built + tested, JA11 V2.2 flashed OK (now 2972:0102 JadeAudio JA11); no software backup possible | 2026-11-27 |
| [ingenic-x2000-swb-reboot-to-usb-boot.md](ingenic-x2000-swb-reboot-to-usb-boot.md) | ingenic, x2000, usb-boot, swb, boot-rom, snowsky-disc | current: SWB entry works (a108:eaef in 5 s); writer refuses after software entry (E320), NAND lock unsupported in FiiO kernel | 2026-10-19 |
| [iqoo-z11-usb-audio-output-flags-bitperfect-hires.md](iqoo-z11-usb-audio-output-flags-bitperfect-hires.md) | android, iqoo, vivo, originos, otg, usb-c, audio, hi-res, bit-perfect, audio-policy, poweramp, snapdragon-sound | current: no Android BIT_PERFECT (DIRECT only); Poweramp usbx verified 24/96 exclusive | 2026-10-19 |
| [iqoo-vivo-otg-keepalive-not-possible-without-root.md](iqoo-vivo-otg-keepalive-not-possible-without-root.md) | android, iqoo, vivo, originos, otg, usb-audio, adb, jadx, reverse-engineering | blocked | 2026-10-19 |
| [diskos-six-module-deepening-parallel-agents-merge-charging-fixes.md](diskos-six-module-deepening-parallel-agents-merge-charging-fixes.md) | diskos, snowsky-disc, architecture, refactor, subagents, worktrees, merge, usb-audio, charging, hot-load, flash | current | 2026-10-31 |
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
