---
type: troubleshooting
tags: [hermes, hermes-agent, nixos, uv, git, home, proxmox, migration, systemd]
created: 2026-09-17
last_verified: 2026-09-17
status: current
---

# hermes-agent `hermes update` broken on `home` (missing `.git`, then NixOS `uv`)

## Symptom

`hermes update --check` on `home` (the NixOS box hermes-agent was migrated to
from `warp-vm`, see [[nixos-home-python-venv-uv-port]]) failed immediately:

```
✗ Not a git repository — cannot check for updates.
```

`hermes update --plan` also reported `Install: unknown (v0.21.0)` instead of
naming a real install kind (git/docker/nix).

After fixing that (below) and actually running `hermes update`, it progressed
further — git pull succeeded — but then failed installing dependencies:

```
✓ Cleared 152 stale __pycache__ directories
→ Updating Python dependencies...
Could not start dynamically linked executable: /root/.hermes/bin/uv
NixOS cannot run dynamically linked executables intended for generic
linux environments out of the box. For more information, see:
https://nix.dev/permalink/stub-ld
  ⚠ Optional extras failed, reinstalling base dependencies and retrying extras individually...
Could not start dynamically linked executable: /root/.hermes/bin/uv
✗ Python dependency install failed: Command '['/root/.hermes/bin/uv', 'pip', 'install', '-e', '.']' returned non-zero exit status 127.
```

## Root cause 1: `.git` was excluded during the `warp` → `home` migration

`hermes update` shells out to `git pull` against `/opt/hermes-source`. The T8
migration (2026-09-09) tar'd the source tree over with `--exclude=.git` (to
avoid carrying git history bloat — see [[nixos-home-python-venv-uv-port]] §1),
so the working tree arrived on `home` with no git metadata at all: no
detectable remote, no ref, nothing for the git-based updater to act on. Hence
`Not a git repository` and `Install: unknown`.

Confirmed the tree really had been a proper checkout at some point: the built
source leaves a `.bytecode-fingerprint` file recording
`git:refs/heads/main:245e48008fa814b3251f50755eb656bd9fb86cb1`.

## Root cause 2: hermes's own bundled `uv` can't run on NixOS

Independent of root cause 1 — once `hermes update` could see a real git repo
and pulled new code, its dependency-install step shells out to
`/root/.hermes/bin/uv`, a generic-Linux `uv` binary the *updater itself*
downloads/vendors (distinct from the Nix-packaged `uv` used originally to
build `/opt/hermes-venv` per [[nixos-home-python-venv-uv-port]] §2-3). That
binary is dynamically linked against glibc's normal loader path, which NixOS
doesn't provide by default (`Could not start dynamically linked executable`,
exit 127) — same class of problem as the original venv-build recipe, just
hitting a different (self-updater-owned) binary this time.

## Fix

### 1. Recreate `.git` in `/opt/hermes-source`

The old `warp` VM (Proxmox VMID 101 on `px1`) was still around, powered off —
used it as the source of truth instead of re-cloning from GitHub, since the
commit matched exactly (`245e48008fa814b3251f50755eb656bd9fb86cb1`, tree
clean).

**Gotcha**: `warp`'s cloud-init `ipconfig0` is a *static*
`192.168.50.200/24` — the exact IP `home` inherited during the migration.
Booting `warp` as-is would have put two hosts on the same IP live on the LAN.
Reassign the IP before powering on, copy, then power off and revert:

```bash
ssh px1 'sudo qm set 101 --ipconfig0 ip=192.168.50.201/24,gw=192.168.50.1'
ssh px1 'sudo qm start 101'
# wait for ssh on .201, then:
ssh moo@192.168.50.201 'sudo git -C /opt/hermes-source log -1 --format="%H"'   # sanity-check commit matches
ssh moo@192.168.50.201 'sudo tar -C /opt/hermes-source -cf - .git' | \
  ssh home 'sudo tar -C /opt/hermes-source -xf -'
ssh px1 'sudo qm shutdown 101 --timeout 20'
ssh px1 'sudo qm set 101 --ipconfig0 ip=192.168.50.200/24,gw=192.168.50.1'   # revert
```

Verified: `hermes update --check` on `home` then correctly reported "4202
commits behind origin/main" instead of erroring.

If the source VM/host is gone entirely, the documented fallback is
`git init && git remote add origin https://github.com/NousResearch/hermes-agent.git
&& git fetch origin main && git reset --hard <sha-from-.bytecode-fingerprint>`.

### 2. Finish the dependency install with the Nix-packaged `uv`, not hermes's own

```bash
UV=/nix/store/ipjv9qq222qldhqmvg4g1bdz3frppg65-uv-0.11.21/bin/uv   # find via: find /nix/store -maxdepth 1 -iname '*-uv-0.*' ! -iname '*.drv'
sudo env HOME=/root $UV pip install --python /opt/hermes-venv/bin/python -e /opt/hermes-source
sudo env HOME=/root $UV pip install --python /opt/hermes-venv/bin/python -e '/opt/hermes-source[all]'
```

### 3. Clear the stuck recovery marker

Because the automatic recovery path kept invoking the broken vendored `uv` and
kept failing, it left `/opt/hermes-source/.update-incomplete` (JSON body
`{"attempts": 3}`) behind — maxed out its retry budget. Every subsequent
`hermes` invocation (even unrelated ones, e.g. `hermes doctor`) re-ran the
full 3-attempt broken-uv retry loop and reprinted the manual-recovery banner,
even though the venv was already fixed by step 2. Delete it once the manual
install has actually succeeded:

```bash
sudo rm -f /opt/hermes-source/.update-incomplete /opt/hermes-source/.lazy-refresh-incomplete
```

Confirmed via `hermes doctor` → `✓ Version files consistent (0.21.3)` and no
more recovery banner.

### 4. Restart the systemd-supervised gateway

`hermes update` does **not** restart a systemd-managed gateway itself — it
just warns:

```
⚠ A previous `hermes update` pulled new code but did not restart running gateways.
  Gateways may still be serving pre-update modules (mixed sys.modules).
```

```bash
sudo systemctl restart hermes-gateway.service hermes-mcp.service
```

A `~/.hermes/fleet_restart_pending` flag file existed too; it cleared on its
own once the restart actually happened (no manual deletion needed for that
one).

## Related cleanup done in the same pass

`hermes doctor`/`hermes profile list` surfaced three stopped, unused
profiles (`gemma-local`, `xlam-local` — no model configured, their backing
local models had already been removed per an earlier 2026-05-11 session;
`qwen-local` — model configured but gateway stopped) all sharing the
`default` profile's Telegram bot credential, which `hermes` flags as an error
condition (a multiplexed gateway can't have two profiles on the same bot
token). Removed all three: `hermes profile delete <name> -y`. Only `default`
remains; the credential-conflict warnings are gone.

## References

- [NousResearch/hermes-agent PR #33659](https://github.com/NousResearch/hermes-agent/pull/33659) — `hermes update` printing `docker pull` guidance instead of a bogus git error for Docker installs; same failure class (install-method detection), no NixOS-specific equivalent exists yet.
- [NousResearch/hermes-agent issue #110428](https://github.com/NousResearch/hermes-agent/issues/110428) — feature request for git-compatible export/restore; confirms `hermes backup`/`restore` intentionally excludes `.git` (different code path than this migration's manual tar, but same underlying gap).
- [NousResearch/hermes-agent issue #32384](https://github.com/NousResearch/hermes-agent/issues/32384) — "`hermes update` Corrupts Git Repo and Breaks Installation," closed/fixed on `main`. Different failure (corrupted repo, not a missing one) but same subsystem; the macOS-arm64 comment on that thread documents the same "interrupted mid-install, retry loop doesn't fix it" symptom shape as root cause 2 here, with its own manual recovery (`git reset --hard origin/main && uv pip install -e .`).
- [Nix/NixOS Setup — Hermes Agent docs](https://hermes-agent.nousresearch.com/docs/getting-started/nix-setup) — confirms Nix is a best-effort install path for hermes-agent and updates there are meant to go through `nix flake update` + `nixos-rebuild switch`, not `hermes update` — this box instead uses the hybrid "Nix manages the interpreter, uv manages the app" approach from [[nixos-home-python-venv-uv-port]], so `hermes update`'s git+uv path is still the intended update mechanism here, just needs the Nix-packaged `uv` substituted in by hand.
- [nix.dev: dynamically linked executables on NixOS](https://nix.dev/permalink/stub-ld) — explains why a generic-Linux dynamically-linked binary (hermes's vendored `uv`) can't run on NixOS without `nix-ld`/stub-ld.
