---
type: how-to
tags: [oxigram, rust, cargo, fedora, nixos, build, github-release]
created: 2026-11-23
last_verified: 2026-11-23
status: current
---

# Building oxigram on fedora, not the NixOS box

Rebuild of the `oxigram` fork at the tip of `forum-topics`, install over `~/.local/bin/oxigram-native`, and refresh the `v0.3.3-forum.1` draft release asset and checksum.

## Time estimate

- Clone and checkout: about 5 seconds (measured).
- `cargo build --release -p oxigram-native` on fedora: 3m 34s wall clock (measured, from cargo's own `Finished` line).
- gzip, asset delete, asset upload, download-back verify: about 20 seconds total (measured).
- End to end including the failed home build: about 25 minutes, most of it the wrong-host detour.

## Why not home

`home` is NixOS. A build there has to go through `nix shell` with a hand-built `PKG_CONFIG_PATH`, and the resulting binary links against `/nix/store`. That is fine for running on `home`, but the release is a portable x86_64 tarball meant for other machines, and the previous release body already states the build host:

> The binary is x86_64 Linux, built on Fedora 43 against glibc 2.42.

So the correct host is `moo@fedora` (Fedora 43, glibc 2.42, native `cargo`/`rustc` 1.99.1, `gtk3-devel` already installed). Checked with `uname -m`, `/etc/os-release`, `ldd --version`, `pkg-config --modversion gtk+-3.0`.

## Steps

1. Confirm the target commit. The newest commit across all branches was `c596cc0` "Keep the command list inside the window" on `forum-topics` (2026-11-23 13:22 +0700), which is also what the draft release targets. `main` was older (`d01c07d`, upstream 0.3.3).

2. Clone and check out on fedora:

```
ssh moo@fedora 'mkdir -p ~/src && cd ~/src && git clone https://x-access-token:<TOKEN>@github.com/txtsamu/oxigram.git oxigram'
ssh moo@fedora 'cd ~/src/oxigram && git checkout forum-topics'
```

3. Build (backgrounded, logged):

```
ssh moo@fedora 'cd ~/src/oxigram && nohup env CARGO_TERM_COLOR=never cargo build --release -p oxigram-native > /tmp/oxigram-build.log 2>&1 &'
```

Result: exit 0 in 3m 34s. Three dead-code warnings only, in `native/src/countries.rs:257` and `native/src/video/mod.rs` (unused `Player` methods and unread `Options` fields). Artifact 24,768,760 bytes, stripped, `GLIBC_2.39` max, zero `/nix/store` dependencies.

4. Stop the running instance and install over it:

```
ssh moo@fedora 'pkill -x oxigram-native; sleep 2; install -m 755 ~/src/oxigram/target/release/oxigram-native ~/.local/bin/oxigram-native'
```

5. Relaunch inside the graphical session (a bare ssh shell has no display, see gotchas):

```
ssh moo@fedora 'setsid env DISPLAY=:1 WAYLAND_DISPLAY=wayland-1 XDG_SESSION_TYPE=wayland XDG_RUNTIME_DIR=/run/user/1000 ~/.local/bin/oxigram-native > /tmp/run5.log 2>&1 < /dev/null &'
```

6. Update the release body checksum, then swap the asset. The release is a draft, so the by-tag API endpoint 404s; find the release id from the list endpoint and `PATCH` the body:

```
curl -s -H "Authorization: Bearer <TOKEN>" "https://api.github.com/repos/txtsamu/oxigram/releases?per_page=10"
sed -i 's/<OLD_SHA>/<NEW_SHA>/' /tmp/relbody.md
python3 -c "import json; json.dump({'body': open('/tmp/relbody.md').read()}, open('/tmp/patch.json','w'))"
curl -s -X PATCH -H "Authorization: Bearer <TOKEN>" -H "Accept: application/vnd.github+json" --data @/tmp/patch.json https://api.github.com/repos/txtsamu/oxigram/releases/<ID>
```

7. Replace the asset: gzip the new binary, delete the old asset, upload the new one.

```
ssh moo@fedora 'cd ~/src/oxigram/target/release && gzip -9 -c oxigram-native > /tmp/oxigram-native.gz'
curl -s -X DELETE -H "Authorization: Bearer <TOKEN>" https://api.github.com/repos/txtsamu/oxigram/releases/assets/<ASSET_ID>
curl -s -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/gzip" --data-binary @/tmp/oxigram-native-linux-x86_64.gz "https://uploads.github.com/repos/txtsamu/oxigram/releases/<ID>/assets?name=oxigram-native-linux-x86_64.gz"
```

8. Verify by downloading the asset back through the API, gunzipping, and checking the documented hash plus a `cmp` against the installed file:

```
gzip -dc dl.gz > oxigram-native && sha256sum -c <<< '<NEW_SHA>  oxigram-native'
cmp oxigram-native ~/.local/bin/oxigram-native
```

Both passed: `oxigram-native: OK`, and the downloaded file was byte-identical to the installed one.

## Gotchas

- **`build.sh` in the old hermes workspace is nix-specific and cwd-sensitive.** It does `cd "$1"` where `$1` is the invoking `$PWD`, so it must be run from the repo root, not from the workspace directory. Running it from the workspace gives `error: could not find Cargo.toml`. On fedora you do not need it at all, plain `cargo build` is enough.
- **`build.sh` is not executable** (`-rw-r--r--`), so `nohup ./build.sh` fails with `Permission denied`. Use `bash ./build.sh`.
- **A bare ssh shell has no display.** The binary panics with `Could not initialize backend ... EventLoop can't be recreated` / `No backends configured`. Pass the session's `DISPLAY`, `WAYLAND_DISPLAY` and `XDG_RUNTIME_DIR` (read them from `systemctl --user show-environment`), or launch from the desktop.
- **Second launch exits silently.** `core/src/tg.rs` takes a `try_lock` on a lock file in the data dir and returns `ALREADY_RUNNING`. Stop the running instance before testing a new build, or you will think the build is broken.
- **`pkill -f "target/release/oxigram-native"` kills your own ssh session**, because the remote command string contains that text. `pkill -x oxigram-native` is safer.
- **Draft releases have no public download URL.** `releases/download/<tag>/<file>` returns 404 while the release is a draft; use the asset API with `Accept: application/octet-stream` and a token to verify.
- **The tag is annotated.** `refs/tags/v0.3.3-forum.1` resolves to tag object `7e1d1628`, which dereferences to commit `c596cc0`. Do not read the tag object sha as a commit.
- The release is still a **draft** and must be published before the public URL and checksum instructions work for anyone else.

## Not verified

- No interactive smoke test of the forum-topic UI or the `/` command menu in the new build. Only that it starts, holds a window, and logs nothing.
- `--features gstreamer` and `cargo test` were not run.
- The installed binary hash differs from the previous release binary (`92ac06a3…` to `4f4915c9…`) at the same commit, because the toolchain differs. The old binary was built in a nix shell, this one with fedora's rustc 1.99.1.

## References

- Fork: <https://github.com/txtsamu/oxigram>
- Upstream: <https://github.com/Timon2306/oxigram>
- GitHub REST: create a release asset, <https://docs.github.com/en/rest/releases/assets#upload-a-release-asset>
- GitHub REST: update a release, <https://docs.github.com/en/rest/releases/releases#update-a-release>
