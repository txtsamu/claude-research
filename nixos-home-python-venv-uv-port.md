---
type: how-to
tags: [nixos, uv, python, venv, home, hermes, proxmox-mcp-plus, mcp, migration, systemd]
created: 2026-09-09
last_verified: 2026-09-09
status: current
---

# Porting a Python venv service to NixOS `home` with uv (MCP trio case study)

## Goal

Move Python-service war-vm apps onto the NixOS `home` host declaratively. Learned
the reusable recipe while doing T8 (hermes-gateway / hermes-mcp / proxmox-mcp-plus,
txtsamu/claude-research#16). Apply the same recipe to the remaining Python services
(tiktok-bot, headroom-proxy).

## Key insight: venvs are not portable across OSes, but the *recipe* is

A Debian venv's `bin/python3` symlinks to `/usr/bin/python3`, which NixOS doesn't
have. And the venv's compiled extensions are ABI-tied to the interpreter. So you
**rebuild** the venv on `home` instead of rsyncing it. The app *source* and *state*
dirs DO get rsynced (they're just files).

The plan (warp-vm-nixos-migration-plan.md §1.4) prescribes: **Nix manages the
interpreter, uv manages the app deps** — i.e. a plain uv-managed venv, not a full
hermetic Nix `buildPythonApplication`.

## Procedure (does for the MCP trio)

### 1. Provision data out of band (tar-over-ssh, like evomem T7)

```bash
# app source working tree (excl. .git) - 1.0G
ssh warp 'sudo tar -C /opt -cf - --exclude=.git --exclude=venv.stale.* hermes-source' | \
  ssh home 'sudo tar -C /opt -xf -'

# runtime state dir (config, .env, caches, node_modules) - 2.9G
ssh warp 'sudo tar -C /root -cf - .hermes' | ssh home 'sudo tar -C /root -xf -'
```

> Prefer rsync over a fresh `git clone` for the source when the running tree may
> carry working-tree state (node_modules, built dist assets). A fresh checkout at
> the pinned commit is equivalent only if the source is git-clean.

### 2. Get a working Nix `uv` + interpreter

The official uv static binary is dynamically-linked and **won't run on NixOS**
("NixOS cannot run dynamically linked executables"). Use the Nix-packaged uv via
`nix run` (needs the nix-command feature, disabled by default for the `moo` user):

```bash
# nix-command feature is off for regular users - pass the flag
nix --extra-experimental-features "nix-command flakes" run nixpkgs#uv -- --version
# get the Nix python3.13 store path to use as the venv base
nix --extra-experimental-features "nix-command flakes" build nixpkgs#python313 --no-link --print-out-paths
# => /nix/store/<hash>-python3-3.13.15
```

Cache the uv store path so you don't re-evaluate every call:
`/nix/store/...-uv-<ver>/bin/uv`.

### 3. Build the venv on the Nix python base

```bash
UV=/nix/store/...-uv-*/bin/uv
PY=/nix/store/...-python3-3.13.15/bin/python3.13
sudo env HOME=/root $UV venv --python $PY /opt/hermes-venv
sudo env HOME=/root $UV pip install --python /opt/hermes-venv/bin/python -e /opt/hermes-source
```

### 4. Don't blindly reinstall warp-vm's `pip freeze` — it's inconsistent

The freeze is a snapshot of a venv built over time; it contains **leaked**
dependencies and **drifted pins** that a modern resolver rejects:

- `f2==0.0.1.7` (a tiktok-bot dep leaked into hermes's venv) requires
  `websockets<13`, but the venv has `websockets==15.0.1`.
- `websockets-proxy==0.1.2` requires `python-socks[asyncio]==2.4.4`, but
  python-socks is `2.8.2`.

`uv pip install -r freeze.txt` fails with "No solution found". Fix: install the app
from source (`-e /path/to/source`, which pulls its exact-pinned `[project].dependencies`),
then add only the **runtime lazy-deps** the app actually needs (hermes's `mcp serve`
needs `mcp`; `gateway run` needs nothing beyond its declared deps).

### 5. Non-FHS pitfalls in the systemd units

- No `/usr/bin/python3` → run scripts/daemons with the venv python.
- No `/bin/kill` → `ExecReload` uses `${pkgs.coreutils}/bin/kill`.
- warp-vm's `node` under the state dir is dynamically-linked → use `pkgs.nodejs_22`
  on the unit `PATH` instead (node_modules under the source are kept).
- Add the venv-base python to a GC root (`sudo nix-store --add-root
  /root/gc-roots/<name> --realise <python-store-path>`) so `nix-collect-garbage`
  doesn't delete the interpreter the venv symlinks to.
- Wire env exactly: `WorkingDirectory`, `HOME`, `PATH` (venv bin first, then
  `nodejs_22`/system), `HERMES_HOME`, etc. — the warp-vm unit is the reference.

### 6. Rebuild + verify

```bash
sudo nixos-rebuild build --flake github:txtsamu/home-nixos#home --refresh   # validate
sudo nixos-rebuild switch --flake github:txtsamu/home-nixos#home --refresh  # apply
```

Verify MCP servers speak MCP (equivalent to a Claude Code session calling tools):

```bash
# streamable HTTP (proxmox-mcp-plus on :8811): initialize -> capture Mcp-Session-Id -> tools/list -> tools/call
# unix socket (hermes-mcp on /run/hermes-mcp.sock): send newline-delimited JSON-RPC initialize + tools/list
```

## Gotchas hit, in short

- `proxmox-mcp-plus` **ignores `--help` and boots a long-lived server** — a smoke
  test leaves an orphan bound to :8811 that aborts the first `systemctl start`
  ("address already in use"). Kill the orphan and restart.
- `nixos-rebuild switch` needs `--refresh` after a push (stale root eval cache,
  recurring across T2/T3/T7/T13/T8).
- `nix-command`/`flakes` disabled for regular users on `home`; pass
  `--extra-experimental-features "nix-command flakes"`.
- `sudo env HOME=/root nix ...` needed when running `nix` as root (HOME for the
  nix cache/profile).
