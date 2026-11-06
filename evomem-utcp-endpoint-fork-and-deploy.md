---
type: how-to
tags: [evomem, utcp, mcp, rust, nixos, home, fork, deploy, claude-code, skill, podman]
created: 2026-11-06
last_verified: 2026-11-06
status: current
---

# evomem: add a UTCP endpoint in the fork, deploy to home, replace the MCP bridge

Goal: stop using the Python MCP bridge (`~/evomem-bridge/mcp_server.py`) and let agents call evomem's REST API directly through a [UTCP](https://utcp.io) manual. Background on why the old path "often failed": [evomem-mcp-failures-diagnosis.md](evomem-mcp-failures-diagnosis.md).

## Time estimate

Total about 1 h 40 min wall clock (10:20 to 11:57 WIB, measured from first command to verified deploy), including diagnosis and time spent waiting for approvals; the compute steps are short. Measured: `cargo test --release` in the container 51 s (cold crate download), musl release build 47 s (52 s with apt + target install), DB hot backup 2 s, `nixos-rebuild switch` 34 s (a failed build on a wrong hash took 47 s), service restart about 1 s. Estimate (not measured): writing the Rust module and tests about 15 min.

## What exists

| Piece | Where |
|---|---|
| Fork (not upstream) | `txtsamu/evomem`, branch `feat/utcp` (commit `6b7f0c3`), release `v0.4.2-utcp1` |
| Server change | `src/server/utcp.rs` (manual + base-URL logic + tests), routes in `src/server/mod.rs` |
| Deploy config | `txtsamu/home-nixos` PR #11, branch `evomem-utcp`, file `hosts/home/evomem.nix` |
| Client | `~/.local/bin/evomem` (symlink to `~/sessions/2026-11-06-evomem-utcp/bin/evomem`), `evomem-manual.json` next to it, skill `~/.claude/skills/evomem/SKILL.md` |

## Steps

### 1. Pick the right base branch

The fork has `perf/cache-lexical-vocabulary` (the 5 s to 0.3 s search fix that production already runs) on top of upstream `main`. Base the feature on it, or the fix is lost.

```bash
git clone https://github.com/txtsamu/evomem.git repo && cd repo
git checkout -b feat/utcp origin/perf/cache-lexical-vocabulary
```

### 2. Server: serve the manual

New `src/server/utcp.rs` builds the manual as `serde_json::Value`: `utcp_version`, `manual_version`, `tools[]` (name, description, inputs, `tool_call_template` of type `http`). Seven tools mapped to the existing routes: `search`, `think`, `capture` (POST, `body_field: body`), `graph`, `stats`, `doc` (`/api/docs/{slug}`), `sync`. Routes in `server/mod.rs`:

```rust
.route("/utcp", get(utcp::handler))
.route("/.well-known/utcp", get(utcp::handler))
```

Base URL in the manual: `EVOMEM_PUBLIC_URL` if set, else `X-Forwarded-Proto` + `Host`. Also added `#[serde(alias = "query")]` on the search/think `q` and `#[serde(alias = "slug")]` on graph `start`.

Gotcha found only by running the real client: the reference python client builds `UtcpManual` from `utcp_version`, `manual_version`, `tools` only and rejects any other top-level key (`TypeError: UtcpManual.__init__() got an unexpected keyword argument 'info'`). Unit tests pass without noticing; there is now a test pinning the allowed keys.

### 3. Test in a Rust container (no toolchain on the host)

```bash
R=~/sessions/2026-11-06-evomem-utcp; mkdir -p $R/cargo-cache
podman run --rm --security-opt label=disable \
  -v $R/repo:/w -v $R/cargo-cache:/usr/local/cargo/registry -w /w \
  -e CARGO_TARGET_DIR=/w/target docker.io/library/rust:1-bookworm cargo test --release
```

`--security-opt label=disable` is needed on Fedora (SELinux blocks the bind mount otherwise: `could not find Cargo.toml in /w`), and the bind-mount path must be absolute. Result: 88 unit + 24 integration tests pass.

### 4. End-to-end with the official UTCP client

Official libs in a venv: `pip install utcp utcp-http utcp-file` (`utcp-text` no longer accepts `file_path`; use the `file` protocol). Start the built binary on a throwaway KB, then:

```python
c = await UtcpClient.create(config={"manual_call_templates": [{
  "name": "evomem", "call_template_type": "http",
  "url": "http://127.0.0.1:17700/utcp", "http_method": "GET",
  "allowed_communication_protocols": ["http"]}]})   # without this, tools register as 0
await c.call_tool("evomem.search", {"query": "caddy"})
```

Limit: the `utcp-http` plugin refuses plain HTTP to anything but loopback (`URL must use HTTPS or be a literal loopback address`). home is `http://192.168.50.200:7700`, so the official client works only against localhost or after putting evomem behind TLS (for example a Caddy `.lan` route) and setting `EVOMEM_PUBLIC_URL=https://...`. That is why the CLI below executes the manual itself.

### 5. Release build (static musl)

```bash
podman run --rm --security-opt label=disable -v $R/repo:/w -v $R/cargo-cache:/usr/local/cargo/registry -w /w \
  -e CARGO_TARGET_DIR=/w/target-musl -e CC_x86_64_unknown_linux_musl=musl-gcc docker.io/library/rust:1-bookworm \
  bash -c 'apt-get update -qq && apt-get install -y -qq musl-tools zip && rustup target add x86_64-unknown-linux-musl && cargo build --release --target x86_64-unknown-linux-musl'
cd dist && cp ../repo/target-musl/x86_64-unknown-linux-musl/release/evomem . && zip -9 evomem-0.4.2-utcp1-x86_64-unknown-linux-musl.zip evomem
gh release create v0.4.2-utcp1 evomem-0.4.2-utcp1-x86_64-unknown-linux-musl.zip --repo txtsamu/evomem --target feat/utcp --title "v0.4.2-utcp1: UTCP manual endpoint"
```

The zip must have `evomem` at its root (nix `fetchzip` with `stripRoot = false` plus `install -Dm755 evomem`). The release is public; the auto-mode classifier blocked the first attempt, so it needed an explicit go-ahead.

### 6. Back up and prove the data is compatible (before touching production)

The new build changes no schema, but verify. Hot backup (no outage; home has no `sqlite3` CLI, python's sqlite3 `backup()` works):

```bash
ssh <USER>@home 'B=/root/evomem-backups; sudo mkdir -p $B; ts=$(date +%Y%m%d-%H%M%S)
sudo python3 - <<EOF
import sqlite3
s=sqlite3.connect("file:/root/evomem-kb/.evomem.db?mode=ro", uri=True); d=sqlite3.connect("$B/evomem-$ts.db"); s.backup(d); d.close()
print(sqlite3.connect("$B/evomem-$ts.db").execute("pragma integrity_check").fetchone())
EOF
sudo tar -C /root/evomem-kb --exclude=".evomem.db*" --exclude=lost+found -czf $B/evomem-md-$ts.tgz .'
```

Then run old and new binaries side by side on two copies of that backup (ports 17701/17702, loopback) and compare `/api/stats` plus 12 queries x search/think. Result: stats identical, 23 of 24 responses identical, the other differed only by float rounding in the 7th digit of one score (different compiler builds), ranking the same. Kill the trial servers afterwards and delete `/root/evomem-trial`.

### 7. Deploy through home-nixos (careful: main is stale)

home deploys with `nixos-rebuild switch --flake github:txtsamu/home-nixos/<ref>#home --refresh` (no checkout on the host, push from Fedora). Production ran the perf build from branch `evomem-perf-vocab-cache` (config revision 77d6524, generation 46) while `main` still pinned upstream 0.4.2, because PR #9 was closed unmerged. A deploy from `main` would have silently reverted the latency fix. So branch from that branch:

```bash
git clone https://github.com/txtsamu/home-nixos.git hn && cd hn
git checkout -b evomem-utcp origin/evomem-perf-vocab-cache
# edit hosts/home/evomem.nix: url ...-utcp1/evomem-${version}-utcp1-..., new hash
git push -u origin evomem-utcp && gh pr create --base main ...   # PR #11
ssh <USER>@home 'sudo nixos-rebuild switch --flake github:txtsamu/home-nixos/evomem-utcp#home --refresh'
```

Hash gotcha: `nix store prefetch-file --unpack <zip-url>` gave `sha256-QPmU2SSo...` but `fetchzip` computes `sha256-hFQadnfe7+OJg+QlRUtvdNn7ZITbIOSIEMkLGG6xU5w=` for the same zip (zip unpack/permission handling differs). The first deploy failed at build time with `hash mismatch in fixed-output derivation` and changed nothing on the host (still generation 46, service not restarted). Use the `got:` hash from the error.

Rollback: `sudo nixos-rebuild switch --rollback` (generation 46) or restore from `/root/evomem-backups`.

### 8. Verify after the switch

```bash
ssh <USER>@home 'systemctl is-active evomem; systemctl show evomem -p ExecMainStartTimestamp -p NRestarts; nixos-version --configuration-revision; curl -s -o /dev/null -w "%{http_code}\n" 127.0.0.1:7700/utcp'
evomem stats      # compare with the pre-deploy baseline
```

Result (11:57 WIB): active, new `ExecStart` store path, `/utcp` 200 with `url: http://192.168.50.200:7700/api/search`, searches 0.26-0.41 s. Stats before/after: docs 1182 to 1184, chunks 51436 to 51466 (live session capture kept adding). 7 of 8 test queries kept the identical top-10 order; the 8th changed because this very session got captured and now ranks third for it.

### 9. Switch the client over

```bash
ln -sfn ~/sessions/2026-11-06-evomem-utcp/bin/evomem ~/.local/bin/evomem
cp ~/.claude.json ~/sessions/2026-11-06-evomem-utcp/backups/        # backup first
claude mcp remove evomem -s user                                       # was: python3 .../mcp_server.py with EVOMEM_URL
```

Plus the skill `~/.claude/skills/evomem/SKILL.md` and the "How" section of `~/.claude/evomem.md` rewritten for `evomem search <words>`. The CLI (`bin/evomem`) is stdlib-only: it reads `evomem-manual.json`, substitutes `{path}` params, sends leftover args as the query string and `body_field` as the JSON body, retries twice on connection errors and 5xx, timeout 120 s. The hooks that capture sessions (`hook.py`, rsync + `sync_to_evomem.py`) are separate and unchanged. `~/evomem-bridge/mcp_server.py` is left in place, unused.

## Open items

- PR #11 is not merged on purpose; until it is, `home-nixos` main does not match production.
- Upstream (`anvie/evomem`) has no UTCP; nothing was sent there.
- The cold first-query latency and the Nov 2 iSCSI blip are still unexplained (see the diagnosis doc).

## References

- [UTCP site](https://utcp.io/) and [UTCP vs MCP](https://utcp.io/0.1/utcp-vs-mcp): direct-call design, manual format.
- [UTCP HTTP protocol page](https://www.utcp.io/protocols/http): `url` path placeholders, `body_field`, `header_fields`, HTTPS-or-loopback rule.
- [Unified.to UTCP docs](https://docs.unified.to/utcp): UTCP-to-MCP bridge route into Claude Code, OpenAPI conversion.
- [utcp-mcp on PyPI](https://pypi.org/project/utcp-mcp/) and [go-utcp-mcp-bridge](https://github.com/universal-tool-calling-protocol/go-utcp-mcp-bridge): the two bridge directions (not used in the end).
- Upstream evomem: <https://github.com/anvie/evomem>
