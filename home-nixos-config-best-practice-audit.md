---
type: investigation
tags: [nixos, home, flake, audit, best-practice, agenix, caddy, security, systemd, nix-gc]
created: 2026-09-27
last_verified: 2026-09-27
status: current
---

# `home` NixOS config — best-practice audit (2026-09-27)

**Verdict: a solid, working homelab config, but not yet best practice.** The module-per-service layout, agenix secrets, disko, `mutableUsers = false`, key-only SSH, the pinned `nixos-26.05` input with `follows`, and the scoped `allowUnfreePredicate` are all correct. The gaps are operational: where the source of truth lives, Nix housekeeping, how reproducible the host is, and security hardening.

This is a re-audit. An earlier one ran on 2026-09-23 (a hermes session, captured in evomem as `sessions/2026-09-23_20260923_153429_90911292`, never written up here). **None of that audit's findings have been fixed since.** GitHub `txtsamu/home-nixos` is still at `c565997` (2026-09-18), and the live dir is unchanged. This audit also found two new issues: an **unauthenticated Proxmox MCP server on the LAN**, and a dead `rancher.lan` route.

## What was checked (commands)

```bash
# locate config: /etc/nixos is empty, the flake lives in ~moo
ssh moo@home 'ls -la /etc/nixos; find ~ -maxdepth 4 -name flake.nix'
#   -> /home/moo/home-nixos/flake.nix, /home/moo/home-nixos-preview/flake.nix (identical copy)

# is the local dir what's actually running?
ssh moo@home 'cd ~/home-nixos && nix --extra-experimental-features "nix-command flakes" \
  eval --raw .#nixosConfigurations.home.config.system.build.toplevel.outPath; readlink /run/current-system'
#   -> both /nix/store/07hi8pij...-nixos-system-home-26.05.20260907.93108a5  (local dir == gen 36)

# is GitHub the same?
gh repo clone txtsamu/home-nixos hn && rsync -a moo@home:home-nixos/ live/ && diff -r -x .git hn live
#   -> only diff: live proxy.nix has comfy.lan, GitHub doesn't

# nix housekeeping
ssh moo@home 'grep -Ev "^#|^$" /etc/nix/nix.conf; systemctl list-timers --all | grep -Ei "nix|gc|optim"; df -h /; du -sh /nix/store'
#   -> no experimental-features, auto-optimise-store = false, no gc timer; / 81% (18G free), store 24G

# LAN exposure of opened firewall ports (from fedora)
curl -s -X POST http://192.168.50.200:8811/mcp -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"audit","version":"0"}}}'
#   -> full initialize result from "ProxmoxMCP" 1.30.0, no auth challenge
```

The eval also prints: `evaluation warning: camofox-browser.service is ordered after 'network-online.target' but doesn't depend on it`.

## Findings

### High

1. **Unauthenticated Proxmox control on the LAN (new).** `mcp.nix` opens TCP 8811 host-wide. `proxmox-mcp-plus` completes an MCP `initialize` for any client with no credentials, and it holds a Proxmox API token (from the `proxmox-mcp-config` secret). So any device on 192.168.50.0/24, and any NetBird peer allowed through, can drive px1's VMs. Fix: bind it to NetBird/localhost only, or put an auth layer in front (Caddy `basic_auth`/bearer header). At minimum, restrict the port with `networking.firewall.extraInputRules` to known source IPs. Evomem :7700 and headroom :8787 are also open to the whole LAN; they're less dangerous, but the same fix applies.
2. **Two sources of truth, and a drift has been deployed.** Gen 36 was built from `/home/moo/home-nixos`, which is **not a git checkout** (no `.git`). A second copy, `~/home-nixos-preview`, also exists. GitHub is missing the `comfy.lan` vhost that is live, so a rebuild from GitHub silently drops ComfyUI's route. `configurationRevision` shows `Unknown` in `nixos-rebuild list-generations` for the same reason. Fix: make `~/home-nixos` a real clone, commit and push `comfy.lan`, delete `-preview`, and add `system.configurationRevision = self.rev or self.dirtyRev or null;` (pass `self` via `specialArgs`).
3. **No Nix housekeeping.** Flakes aren't enabled in config: a bare `nix flake …` fails, and every command needs `--extra-experimental-features`. There's no `nix.gc` timer and `auto-optimise-store` is off. With `/` at 81% (k3s alone is 33G in `/var/lib/rancher`), this is the next outage. It's the same class as the 2026-09-21 OOM cascade, but for disk. Fix:
   ```nix
   nix.settings = {
     experimental-features = [ "nix-command" "flakes" ];
     auto-optimise-store = true;
     trusted-users = [ "root" "@wheel" ];
   };
   nix.gc = { automatic = true; dates = "weekly"; options = "--delete-older-than 14d"; };
   boot.loader.systemd-boot.configurationLimit = 10;
   ```

### Medium

4. **Agenix has no recovery recipient.** `secrets/secrets.nix` lists only the host SSH key for all 5 secrets. If `/etc/ssh/ssh_host_ed25519_key` is lost (disk failure, or a reinstall via nixos-anywhere, which regenerates it), every secret is unrecoverable. Fix: add an offline admin age/SSH key as a second recipient and run `agenix -r`. The file's comments are also stale: they reference the deleted `cloudflare-tunnel-token.age` and keyscan against `.202`, which is now `.200`.
5. **The flake can't rebuild the host.** Everything in `/opt/*` (hermes, proxmox, tiktok-bot, headroom venvs: 3.0G), `/usr/local/bin/evomem`, and `/root/camofox-browser` plus `~/.cache/camoufox` was placed by hand. The units only point at them. A reinstall from the flake gives you units that crash. Fix, in order of value: package evomem (a static Rust binary, so trivial with `fetchurl`/`rustPlatform`), and move the venvs to `uv2nix` or at least a documented bootstrap script in-repo. Make sure `/opt` and `/root` are covered by a backup.
6. **No CI, `checks`, or `formatter`.** A broken module only shows up during `switch` on the live box. Fix: add `formatter.x86_64-linux = nixpkgs.legacyPackages.x86_64-linux.nixfmt-rfc-style;` and a GitHub Action that runs `nix flake check` plus a build of `toplevel`. Also add a `flake.lock` updater (e.g. `DeterminateSystems/update-flake-lock`). The lock is currently frozen at nixpkgs 2026-09-07, so security updates only arrive when someone remembers.
7. **Hard-coded paths instead of references.** `tiktok-bot.nix` uses `EnvironmentFile = "/run/agenix/camofox-api-key"`. It should be `config.age.secrets.camofox-api-key.path` like `camofox.nix`. `camofox-browser` has `after = network-online.target` with no `wants` (the eval warning above).
8. **Dead config.** `rancher.lan` still proxies to Rancher's old ClusterIP `10.43.126.48`, but Rancher was fully decommissioned on 2026-09-17 (`rancher-full-decommission-k3s-home.md`). `tunnel.nix` still carries the `home-t5-test.ssamu.id` throwaway test route. `jellyfin/grafana/bastion.lan` point at warp-vm-era IPs that were already flagged as down.

### Low

9. **No systemd hardening.** None of the 9 hand-written units use `ProtectSystem`, `ProtectHome`, `NoNewPrivileges`, `PrivateTmp`, or `DynamicUser`. `hermes-*`, `proxmox-mcp-plus`, `evomem`, `camofox`, and `tiktok-bot` all run as root. `systemd-analyze security <unit>` scores them. Start with `proxmox-mcp-plus` (it holds the Proxmox token) and `camofox`.
10. **Caddy repetition.** There are 18 near-identical vhosts, and `tls internal` on each is redundant under global `local_certs`. A `lib.mapAttrs` over an `{ name = upstream; }` attrset would make this ~20 lines. This is cosmetic.
11. **DNS fallback bypasses the blocklist.** `nameservers = [ ".200" "1.1.1.1" "8.8.8.8" ]`: when Technitium is slow, glibc falls through to public DNS and loses `.lan` resolution, so the host's own `.lan` lookups fail intermittently. Consider local-only, or `services.resolved` with `.200` as the only resolver.
12. **No LAN short names in `/etc/hosts`.** `networking.extraHosts` is unset, so `getent hosts nas fedora px1` returns nothing. It's cheap to add.
13. **Minor style.** The single-host flake hardcodes `system = "x86_64-linux"`, which is fine for now. `configuration.nix` could set `nixpkgs.hostPlatform` instead (the modern idiom). Admin access uses one RSA key from a Windows box; consider adding an ed25519 key.

## Suggested order

1 (MCP auth/firewall) → 2 (git + push comfy.lan) → 3 (gc/flakes, disk at 81%) → 4 (agenix recovery key) → 6 (CI + lock updates) → the rest opportunistically.

## References

- NixOS manual — `nix.gc`, `nix.settings.auto-optimise-store`, `boot.loader.systemd-boot.configurationLimit`: https://nixos.org/manual/nixos/stable/options
- agenix — recipients / rekey (`agenix -r`): https://github.com/ryantm/agenix
- uv2nix (declarative Python venvs from uv lockfiles): https://github.com/pyproject-nix/uv2nix
- update-flake-lock GitHub Action: https://github.com/DeterminateSystems/update-flake-lock
- Related: [warp-vm-nixos-migration-plan.md](warp-vm-nixos-migration-plan.md), [warp-vm-nixos-migration-retrospective.md](warp-vm-nixos-migration-retrospective.md), [home-oom-cascade-cloudflared-outage.md](home-oom-cascade-cloudflared-outage.md), [rancher-full-decommission-k3s-home.md](rancher-full-decommission-k3s-home.md)
