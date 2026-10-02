---
type: how-to
tags: [nixos, home, flake, github, rebase, systemd-hardening, flake-lock, deploy, ci]
created: 2026-10-02
last_verified: 2026-10-02
status: current
---

# Merging and deploying home-nixos PRs #2 (sandboxing) and #4 (flake.lock bump)

How `home` (NixOS 26.05) picked up two pending PRs on `txtsamu/home-nixos`, including the conflict, the CI quirk on bot PRs, and the post-switch checks. Context: `home` builds straight from `github:txtsamu/home-nixos#home`; there is no checkout on the host and no `nix` on the fedora desktop. See [home-nixos-config-best-practice-audit.md](home-nixos-config-best-practice-audit.md) for why the PRs exist.

## Starting state

`ssh moo@home` showed a fully flake-based system, pinned at `8b5af06`, with no `/etc/nixos` config and no channels:

```bash
ssh moo@home 'nixos-version --json; sudo nix flake metadata github:txtsamu/home-nixos'
gh pr list -R txtsamu/home-nixos
```

- **#2**: systemd hardening for the root services (evomem 9.4 → 7.4, headroom-proxy 9.0 → 7.1 on `systemd-analyze security`). Opened 2026-09-23, never merged.
- **#4**: `update-flake-lock` bot PR, nixpkgs `5e2305d` → `cf5e765`, agenix bump, and agenix's unused `darwin`/`home-manager` inputs dropped.

## PR #2: rebase, merge, deploy

1. `gh pr view 2 --json mergeable,mergeStateStatus` reported `CONFLICTING`. Main had since removed the Checkmk host agent (commit `0374724`), and the PR modified `hosts/home/checkmk-agent.nix`.
2. Rebased in a throwaway clone:
   ```bash
   gh repo clone txtsamu/home-nixos hn && cd hn
   git fetch origin hardening
   git checkout -b hardening origin/hardening
   git rebase origin/main            # conflict: DU hosts/home/checkmk-agent.nix
   git rm hosts/home/checkmk-agent.nix   # keep main's deletion; this drops the cmk-agent-ctl-daemon hardening hunk
   GIT_EDITOR=true git rebase --continue
   grep -rn -i "cmk\|checkmk" hosts flake.nix   # only comments remained
   ```
3. `nix fmt` / `nix flake check` could not run locally (`nix: command not found` on fedora). CI is the first real check.
4. Pushed with `git push --force-with-lease origin hardening`. The auto-mode classifier denied this the first time, as it rewrites remote history. It was retried after the user explicitly approved the force-push.
5. Waited for CI (`gh pr checks 2 --watch`; it passed, including the full-system build), then squash-merged:
   ```bash
   gh pr merge 2 --squash --delete-branch    # merge commit e34c178
   ```
6. Deployed:
   ```bash
   ssh moo@home 'sudo nixos-rebuild switch --flake github:txtsamu/home-nixos#home --refresh'
   ```
   This restarted evomem, headroom-proxy, netbird, netbird-up, netbird-k8s-fwd-fix, proxmox-mcp-plus and tiktok-bot.
7. Post-switch checks (taken from the PR body):
   ```bash
   ssh moo@home 'sleep 20
   systemd-analyze security evomem headroom-proxy --no-pager | grep -E "^(evomem|headroom)"
   curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:7700/health   # 200
   curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8787/health   # 200 (headroom needs ~15s)
   systemctl is-active evomem headroom-proxy netbird netbird-up proxmox-mcp-plus tiktok-bot
   systemctl --failed --no-legend
   journalctl -b -p warning --since "-3min" -u evomem -u headroom-proxy -u netbird -u tiktok-bot --no-pager'
   ```
   Result: evomem 7.4 MEDIUM, headroom-proxy 7.1 MEDIUM, both health endpoints 200, all units active, no failed units, no warnings.

Not sandboxed by design (documented in the PR): hermes-gateway, hermes-mcp, camofox-browser (steam-run bubblewrap conflicts with systemd namespaces), check-mk-agent units.

Open follow-up found by the PR: proxmox-mcp-plus runs with `cwd=/` and writes `/proxmox-jobs.sqlite3` and `/proxmox_mcp.log` into the filesystem root. The fix is a real `WorkingDirectory` + `StateDirectory`, which relocates the job DB, so it was left as its own change.

## PR #4: CI trigger quirk, merge, deploy

GitHub does not run workflows on PRs opened by an Action, so `gh pr checks 4` said "no checks reported". The PR body documents the workaround:

```bash
gh pr close 4 -R txtsamu/home-nixos && gh pr reopen 4 -R txtsamu/home-nixos
gh run list -R txtsamu/home-nixos --branch update_flake_lock_action --limit 3
gh run watch <run-id> -R txtsamu/home-nixos --exit-status
```

An older run on that branch had failed (a previous lock update), so the new run was watched rather than assumed. It passed. Then:

```bash
gh pr merge 4 -R txtsamu/home-nixos --squash --delete-branch   # merge commit 5460c58
ssh moo@home 'sudo nixos-rebuild switch --flake github:txtsamu/home-nixos#home --refresh'
ssh moo@home 'nixos-version; systemctl --failed --no-legend; systemctl is-active evomem headroom-proxy netbird proxmox-mcp-plus tiktok-bot k3s'
```

Result: `26.05.20260927.cf5e765`, no failed units, health endpoints 200. The only recent error-priority journal lines were dbus-broker "Ignoring duplicate name" messages (duplicate systemd D-Bus service files in the system path), which are harmless. This switch did not restart the hardened services because their closures were unchanged.

## Order and rationale

#2 was deployed before #4 so any sandbox breakage would not be confounded with a package bump.

## Still open (reproducibility gaps, from the same session)

- Move `/root/age-recovery-key.txt` off the host (agenix recovery key).
- Loose state in `/root` not covered by the flake: Caddy CA certs, `camofox-browser`, `camoufox`, `dns-backups`, `agentic_harness.py`, `aux_verify.py`. The Caddy CA matters most: clients trust it.
- Check that the `hosts/home/venvs/*.txt` files are hash-pinned and that the upstream sources behind the two `patches/*.patch` files are pinned to a rev.
- Verify `/dev/sda2` (ext4) matches `disko.nix`.
- No backups for k3s state, Technitium zones/records or evomem data.
- The proxmox-mcp-plus state-directory fix above.

## References

- [txtsamu/home-nixos PR #2: Sandbox the root services](https://github.com/txtsamu/home-nixos/pull/2)
- [txtsamu/home-nixos PR #4: flake.lock: update inputs](https://github.com/txtsamu/home-nixos/pull/4) (the "close and re-open to run Actions" workaround is in the bot's PR body, from the [update-flake-lock action](https://github.com/DeterminateSystems/update-flake-lock))
