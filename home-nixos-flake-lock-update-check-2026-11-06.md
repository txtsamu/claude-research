---
type: investigation
tags: [nixos, home, flake-lock, nixpkgs, update, dry-activate, ci, k3s, cloudflared, kernel]
created: 2026-11-06
last_verified: 2026-11-06
status: superseded the same evening: PR #10 now conflicts with main and its nixpkgs part is older than what runs; not merged, not deployed
---

# What does home-nixos PR #10 (weekly flake.lock update) change? CI, build-only check, dry-activate

Question: what is PR #10 and is it safe to merge. It is the weekly `flake.lock` update opened by the update-flake-lock GitHub Action on 2026-11-02: 1 file, 9 lines, bumping `nixpkgs` (2026-09-27 to 2026-11-01), `agenix` (09-28 to 10-20) and `disko` (09-18 to 10-20). Home runs the 09-27 nixpkgs.

## Time estimate

Measured: CI about 4 minutes after the reopen; build on `home` 48 min 13 s (2 893 s), almost entirely downloading from cache.nixos.org (380+ paths when last sampled, no local compiles); closure diff and dry-activate seconds. Total about 1 hour including waiting.

## Steps

1. Bot PRs get no CI until reopened, so: `gh pr close 10 -R txtsamu/home-nixos && gh pr reopen 10 -R txtsamu/home-nixos`. CI (`nix flake check` plus a system build) then passed.
2. Build the combination that would actually deploy, not the PR branch (which sits on an older `main`): clone `main`, check that `main`'s `flake.lock` is unchanged since the PR base (`git diff <merge-base> origin/main -- flake.lock` empty), then `git checkout origin/update_flake_lock_action -- flake.lock`. Copy to `home`, `git init && git add -A` (flakes only see tracked files), then `nix flake check --no-build` (passed) and `nix build --no-link --print-out-paths .#nixosConfigurations.home.config.system.build.toplevel` (exit 0). Free space went 32.4 GB to 28.3 GB (about 4.1 GB until gc).
3. `nix store diff-closures /run/current-system $SYS` (179 lines). Notable: linux 6.18.54 to 6.18.60, systemd 260.4 to 260.5, glibc 2.42-84 to 2.42-103, openssh 10.5p1 to 10.6p1, caddy 2.11.4 to 2.11.7, cloudflared 2026.5.2 to 2026.10.3, nix 2.34.8 to 2.34.9, k3s same version but rebuilt.
4. `sudo $SYS/bin/switch-to-configuration dry-activate` prints the plan without changing anything. A switch would stop and start caddy, the cloudflared tunnel, evomem plus `iscsi-login-evomem-kb` and `iscsid`, hermes-gateway, hermes-mcp, k3s, netbird, nscd, headroom-proxy, camofox, anoa-browser and the provision-src oneshots; restart sshd, nix-daemon, udevd, journald and network-addresses; reload dbus-broker and the firewall; restart systemd. 122 unit files differ, mostly because store paths changed.
5. Cleaned the scratch dir on `home`. Running system verified unchanged (09-27 build).

## Reading

Same channel (26.05), mostly patch-level bumps, no evaluation warnings. The risk is the restart storm, not the code: Hermes' Telegram is offline about 2 minutes while the gateway reconnects (measured 112 s on 2026-11-06), Caddy, the public tunnel and the evomem iSCSI session restart, and the new kernel only applies after a reboot (this host has a boot-hang history; keep Proxmox console access and the previous generation as rollback). cloudflared has the largest version jump and fronts the public domain. Suggested plan: merge, deploy and reboot in one maintenance window.

## References

None from the web; sources are the PR body, `gh pr diff`, `nix store diff-closures` and `switch-to-configuration dry-activate` output on the host.

## Addendum (21:10 WIB): the check went stale before the deploy

When asked to "merge and deploy now", the pre-flight showed `home` no longer on the build I had compared against: someone merged home-nixos PR #19 (`flake.lock: bump nixpkgs`, cloudflared 2026.5.2 to 2026.10.7) at 20:38 WIB and deployed it at 21:00:47 (generation 57, configuration revision `8de7f82`, nixpkgs 26.05.20261105.c56a87d, newer than PR #10's 2026-11-01). That deploy already caused the service restarts the dry-activate listed, and the generation carries kernel 6.18.60 while 6.18.54 still runs (reboot pending). PR #10 became CONFLICTING/DIRTY against `main` because #19 changed the same `flake.lock` lines; what it would still add is `agenix` 2026-09-28 to 10-20 and `disko` 2026-09-18 to 10-20 (disko matters only at install time). Nothing was merged or deployed. Also found in the pre-flight: `netbird-up.service` has been failing in a retry loop since that 21:00 deploy (`failed to get config directory: neither $XDG_CONFIG_HOME nor $HOME are defined`, then a 90 s start timeout), while the main `netbird` service is active; zero failed units at 19:56, so it came with the newer nixpkgs, not with anything done in this session.

Lesson: the closure diff and dry-activate output are only valid for the exact running revision they were computed against. Re-read `nixos-version --configuration-revision` and `gh pr list` immediately before a deploy, especially when other sessions also deploy to this host.
