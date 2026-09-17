---
type: troubleshooting
tags: [hermes, hermes-agent, nixos, uv, git, home, proxmox, migration, systemd]
created: 2026-09-17
last_verified: 2026-09-18
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

**This recurred on every `hermes update` that had real work to do** — hit it
again 2026-09-18 pulling 407 new upstream commits, exact same error and exit
127. `/root/.hermes/bin/uv` isn't a one-time download; the updater re-
provisions/uses it each run, so the manual per-run fix below had to be
re-applied each time — until permanently fixed at the OS level, see
**Permanent fix** below.

## Root cause 3: `hermes gateway restart` can't rewrite a NixOS-managed systemd unit

Found this one 2026-09-18, trying to clear the "did not restart running
gateways" warning (step 4 below) the way hermes itself suggests
(`hermes gateway restart` instead of a raw `systemctl restart`):

```
File ".../hermes_cli/gateway.py", line 3144, in refresh_systemd_unit_if_needed
    unit_path.write_text(new_unit, encoding="utf-8")
OSError: [Errno 30] Read-only file system: '/etc/systemd/system/hermes-gateway.service'
```

hermes's restart path first tries to "refresh" (rewrite) its own systemd
unit file — reasonable on a normal Linux box where hermes's installer wrote
that unit file itself, but on `home` the unit is declared in the
`home-nixos` flake and materialized read-only by `nixos-rebuild`. hermes has
no way to know that and doesn't need to: the unit content is already correct
via Nix, there's nothing for hermes to "refresh." Bypass by using plain
`systemctl restart` directly instead of the hermes-native command (see step
4 — this is what was already being done, just confirming it's the *correct*
approach here, not merely a workaround).

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

**Don't use `hermes gateway restart`** for this — see root cause 3 above,
it fails outright trying to rewrite the NixOS-managed unit file. Plain
`systemctl restart` is the correct approach on this box, not a workaround.

A `~/.hermes/fleet_restart_pending` flag file (`started=<epoch>
pid=<pid> expected_sha=<sha>`) tracks this same pending-restart state.
2026-09-17 it cleared on its own after a `systemctl restart`; 2026-09-18 it
did **not** — `hermes doctor` kept showing the stale warning even after the
services were confirmed running the new code. Not yet clear what makes it
clear itself sometimes and not others; when it doesn't, delete it manually
once the restart is confirmed:
```bash
sudo rm -f /root/.hermes/fleet_restart_pending
```

## Permanent fix (2026-09-18): enable `nix-ld`

Root cause 2 (and any *future* generic dynamically-linked binary hermes or
anything else vendors) is fixed for good by enabling **nix-ld** — nix.dev's
own documented general fix for exactly this error class (*"NixOS cannot run
dynamically linked executables intended for generic linux environments"*),
not something specific to this investigation. Added to the `home-nixos`
flake, in `hosts/home/mcp.nix` right next to the hermes systemd units it
fixes:

```nix
programs.nix-ld.enable = true;
```

No extra `programs.nix-ld.libraries` needed — the error was a missing
dynamic *loader*, not a missing shared library, and `uv` is otherwise
essentially statically linked (Rust binary).

```bash
cd ~/home-nixos
git add hosts/home/mcp.nix && git commit -m "..." && git push origin main
```

**Hit the flake's known stale-eval-cache gotcha again applying this** (see
[[nixos-home-python-venv-uv-port]]'s Gotchas: *"`nixos-rebuild switch` needs
`--refresh` after a push (stale root eval cache...)"*) — this time even
`--refresh` on the bare `github:txtsamu/home-nixos#home` ref wasn't enough;
`nixos-rebuild build` kept returning the exact same pre-push store path.
Fix: pin the flake ref to the exact commit instead of trusting cache
invalidation:
```bash
sudo nixos-rebuild build  --flake github:txtsamu/home-nixos/<commit-sha>#home
sudo nixos-rebuild switch --flake github:txtsamu/home-nixos/<commit-sha>#home
```
That rebuild visibly pulled in `nix-ld-2.0.6` and its supporting derivations
(`ld-library-path`, `set-environment`, `etc-pam-environment`) — confirming
the stale build genuinely hadn't included it before.

Verified fixed directly against the binary that was failing:
```bash
sudo /root/.hermes/bin/uv --version
# -> uv 0.11.23 (x86_64-unknown-linux-gnu)   (previously: exit 127)
```
`hermes doctor` and all four affected services (`hermes-gateway`,
`hermes-mcp`, `technitium-dns-server`, `caddy`) confirmed still healthy
after the `nixos-rebuild switch`.

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
- [nix.dev FAQ — "How to run non-nix executables?"](https://nix.dev/guides/faq#how-to-run-non-nix-executables) — the actual permanent fix used: `programs.nix-ld.enable = true;` in `configuration.nix`, one of several documented options (nixpkgs package, `autoPatchelfHook`, `buildFHSEnv`, or nix-ld) for this exact error class.
- [NousResearch/hermes-agent issue #35105](https://github.com/NousResearch/hermes-agent/issues/35105) and linked #29700/#29703 — a related-but-distinct `uv`/hermes-update failure class (PyPI/editable installs failing with "No virtual environment found" because `uv pip install` isn't told which Python to target); ruled out as the cause here (this is a git-source install, not PyPI) but worth knowing they're different bugs with the same "uv co-mingled with hermes update" flavor.
