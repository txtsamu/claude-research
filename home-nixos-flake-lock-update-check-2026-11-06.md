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

When asked to "merge and deploy now", the pre-flight showed `home` no longer on the build I had compared against: someone merged home-nixos PR #19 (`flake.lock: bump nixpkgs`, cloudflared 2026.5.2 to 2026.10.7) at 20:38 WIB and deployed it at 21:00:47 (generation 57, configuration revision `8de7f82`, nixpkgs 26.05.20261105.c56a87d, newer than PR #10's 2026-11-01). That deploy already caused the service restarts the dry-activate listed, and the generation carries kernel 6.18.60 while 6.18.54 still runs (reboot pending). PR #10 became CONFLICTING/DIRTY against `main` because #19 changed the same `flake.lock` lines; what it would still add is `agenix` 2026-09-28 to 10-20 and `disko` 2026-09-18 to 10-20 (disko matters only at install time). Nothing was merged or deployed. Also found in the pre-flight: `netbird-up.service` in a retry loop (90 s start timeout each time) since the daemon was restarted at 21:02, so the NetBird mesh has been down since then: `netbird` is active but there is no `wt0` interface, and `netbird-k8s-fwd-fix` (which `requires` netbird-up) is dead with "Dependency failed", so the nft accept rule for the k3s pod CIDR is missing. Cause: not the unit and not the nixpkgs bump. The client log shows about 960 gRPC connect failures to the management server with `tls: failed to verify certificate: x509: certificate is valid for *.google-analytics.com, ...` : the management host (a subdomain of the personal domain) resolves to the personal VPS (reverse DNS `vpz`), answers on 443, and presents an unrelated certificate, i.e. the proxy or NetBird management server on the VPS is broken or serving a default vhost. The apex domain is healthy (Cloudflare, valid certificate), so this is not a domain expiry like the one noted in `vpn.nix` for 2026-09-28. The "neither $XDG_CONFIG_HOME nor $HOME are defined" line in the netbird-up log is a warning that appears next to the failure but is not what fails it. The client correctly refuses the wrong certificate. Fix is on the VPS side (not reachable from this session); `systemctl restart netbird-up netbird-k8s-fwd-fix` after it is fixed.

Lesson: the closure diff and dry-activate output are only valid for the exact running revision they were computed against. Re-read `nixos-version --configuration-revision` and `gh pr list` immediately before a deploy, especially when other sessions also deploy to this host.

## Follow-up (22:00-22:13 WIB): PR #10 closed, `netbird-up` removed (PR #20)

PR #10 was closed (comment: superseded by #19). On request the failing `netbird-up.service` was removed even though the check above showed it was not the cause: home-nixos PR #20 deletes the unit from `vpn.nix`, points `netbird-k8s-fwd-fix` at `netbird.service` instead of `netbird-up.service`, and makes that fix script end with exit 0 and a message when the netbird forward-filter chain does not exist (otherwise it would just become the next failed unit while the mesh is down). The agenix `netbird-setup-key` secret was kept for manual enrollment; the manual command is in the `vpn.nix` comment. Verified before deploying: `nix fmt` clean, build-only, only `netbird-k8s-fwd-fix.service` changed and only `netbird-up.service` removed versus the running revision `8de7f82` (re-read right before the switch), dry-activate would only reload `dbus-broker`, CI green. After the switch: 0 failed units, `netbird-k8s-fwd-fix` active (ran and exited quietly), Hermes Telegram connected, hermes-gateway, evomem, k3s and caddy active. The VPN itself is still down: nothing on `home` can fix the management host's wrong certificate.

Deploy hiccup worth remembering: `nixos-rebuild switch --flake github:txtsamu/home-nixos/<branch>#home` failed at the fetch step (before any change) because `api.github.com` returned HTTP 504 for the repo's `commits` and `tarball` endpoints from `home` (the `rate_limit` endpoint answered 200 and the API worked from the workstation). The same commit deployed fine through git itself, which uses github.com and not the API: `nixos-rebuild switch --flake 'git+https://github.com/txtsamu/home-nixos?ref=<branch>&rev=<full sha>#home' --refresh`, preceded by the same command with `build` as a dry check. Locked inputs were already in the store, so only the toplevel was rebuilt (23 s build, 40 s switch).
