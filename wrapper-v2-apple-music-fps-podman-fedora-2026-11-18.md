---
type: how-to
tags: [wrapper-v2, apple-music, gamdl, fairplay, drm, podman, quadlet, fedora, alac, lossless]
created: 2026-11-18
last_verified: 2026-11-18
status: current
---

# Wrapper V2 on Fedora 43 with rootless podman, to unlock ALAC in gamdl

Gamdl with cookies plus its bundled Widevine **L3** device cannot get FairPlay keys for lossless: `--song-codec alac` dies with `DrmLicenseError`. The documented escape is [wrapper-v2](https://github.com/glomatico/wrapper-v2), a local daemon that loads Apple Music's own Android native libraries and exposes an HTTP control API plus a raw TCP decrypt port. Gamdl then talks to it instead of provisioning its own CDM.

This note is the working install on the workstation. It deviates from the project's `docker compose` instructions in three places, each for a reason, and all three are recorded below.

## Time estimate

| Step | Measured |
|---|---|
| Clone repo (shallow) | ~2 s |
| `tools/extract-libs.sh` from the APKM, hash-verified | ~4 s |
| `tools/stage-system.sh` (vendored Android libs) | ~2 s |
| `podman build`, first attempt (OCI format, failed at compile step) | 1 min 7 s (layer cache reused for the retry) |
| `podman build --format docker` retry | 1 min 30 s |
| Quadlet unit plus first start | ~15 s |
| Login (Apple ID, password, 2FA) | up to you, 1 to 2 min |

Wall clock to a running daemon: about 4 minutes. A cold build without the cached Debian/NDK layers will take longer, since the Dockerfile pulls Android NDK r23b (roughly 1 GB unzipped) and compiles a C++ daemon plus a Rust supervisor.

## Hard prerequisite: the Apple Music APK

The repo ships no Apple code by design. `rootfs/system/lib64/` must contain Apple Music's Android native libraries matching the SHA-256 digests pinned in `LIBS_VERSION.json`, which names the tested source:

```
com.apple.android.music  version 3.6.0-beta  build 1109  ndk r23b
```

Obtained legitimately from APKMirror as `com.apple.android.music_3.6.0-beta-1109_2arch_2dpi_..._apkmirror.com.apkm` (84 MB, 2 arch / 2 dpi bundle containing `base.apk` plus `split_config.x86_64.apk` and `split_config.arm64_v8a.apk`). Without that file the build cannot complete and the daemon cannot decrypt anything.

## Build

```bash
git clone --depth 1 https://github.com/glomatico/wrapper-v2.git ~/wrapper-v2
cd ~/wrapper-v2

bash tools/extract-libs.sh \
  --bundle "/home/moo/Downloads/com.apple.android.music_3.6.0-beta-1109_2arch_2dpi_d17c9d486201413b9aa9a1d62bc7b1d3_apkmirror.com.apkm" \
  --arch x86_64
# extract-libs: 18 ok, 0 failed (arch=x86_64 out=.../rootfs/system/lib64 from split_config.x86_64.apk lib/x86_64)

bash tools/stage-system.sh --arch x86_64
# stage-system: 83 ok, 0 failed
```

`extract-libs.sh` verifies every `.so` against `LIBS_VERSION.json`, so a wrong APK version fails loudly instead of producing a subtly broken daemon. 18 Apple libs plus 83 AOSP libs, `rootfs` ends up ~115 MB.

### Gotcha 1: podman defaults to OCI, which ignores `SHELL`

First build attempt:

```
podman build -t wrapper-v2:latest .
...
/bin/sh: 1: Syntax error: "(" unexpected
```

Because podman's default OCI image format emits `time=... level=warning msg="SHELL is not supported for OCI image format, [/bin/bash -c] will be ignored. Must use `docker` format"`, and the Dockerfile's compile step uses bash arrays. Fix:

```bash
podman build --format docker \
  --build-arg TARGET_ARCH=x86_64 \
  --build-arg BUILD_PLATFORM=linux/amd64 \
  --build-arg RUNTIME_PLATFORM=linux/amd64 \
  -t wrapper-v2:latest .
```

### Gotcha 2: rootless podman cannot mount proc, and the launcher needs it

Default rootless run:

```
wrapperd: starting ipc worker /app/wrapper
wrapper: mount proc: Permission denied
```

Then `GET /me` returns `{"detail":"worker stdout closed","error":"worker_unavailable"}` while `/health` still says `status: ok`. That split is misleading: the supervisor is healthy, the worker is dead.

`src/launcher/wrapper.c` does `unshare(CLONE_NEWPID)` and `mount("proc", "/proc", "proc", 0, NULL)` to give the Android bionic runtime a `/proc` inside the chroot. Rootless podman will not grant that, and adding `--security-opt seccomp=unconfined --cap-add SYS_ADMIN` does not help. `--privileged` does:

```bash
podman run -d --name wrapper-v2 --privileged \
  -p 127.0.0.1:8080:80 -p 127.0.0.1:10020:10020 \
  -v /home/moo/wrapper-v2/data:/app/rootfs/data/data/com.apple.android.music/files:Z \
  wrapper-v2:latest
```

Then the logs show the real worker coming up:

```
wrapper-v2: ipc worker mode starting
wrapper-v2: opening Apple libs from /system/lib64
auth: cached-session restore found Apple session files but token harvest failed
wrapper-v2: ipc worker ready
```

and `GET /me` reports `"loader_ok": true, "playback_ready": true, "auth": {"state": "logged_out"}`.

The `dlsym(... getPersistentKey ...): undefined symbol` lines in that startup are expected on a fresh volume: there is no cached session to harvest yet.

Rootful podman was not used. Rootless plus `--privileged` was enough, and keeps files owned by `moo`.

### Gotcha 3: port 80 is privileged, so the wrapper lives on 8080

`ip_unprivileged_port_start` is `1024` here, so rootless podman cannot bind host port 80. The compose file maps `${HTTP_PORT:-80}`, and gamdl's default `wrapper_url` is `http://127.0.0.1` (port 80). Mapping 8080 instead means the gamdl config must be updated, which is exactly the trade recorded below.

## Persistence: quadlet unit

`podman generate systemd` is deprecated, so this uses a quadlet. `~/.config/containers/systemd/wrapper-v2.container`:

```ini
[Unit]
Description=Wrapper V2 Apple Music FPS decrypt daemon
After=network-online.target

[Container]
Image=localhost/wrapper-v2:latest
ContainerName=wrapper-v2
PublishPort=127.0.0.1:8080:80
PublishPort=127.0.0.1:10020:10020
Volume=/home/moo/wrapper-v2/data:/app/rootfs/data/data/com.apple.android.music/files:Z
PodmanArgs=--privileged

[Service]
Restart=always

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user start wrapper-v2
systemctl --user is-active wrapper-v2      # active
loginctl show-user moo -p Linger           # Linger=yes
```

`Linger=yes` was already set, so the unit also starts at boot without an open session. If it were `no`: `sudo loginctl enable-linger moo`.

Both published ports are pinned to `127.0.0.1` on purpose. The daemon has no authentication of its own and speaks plain HTTP, so publishing on `0.0.0.0` would let anything on the LAN drive `POST /login` or `GET /playback` with the stored Apple session. Verified with `ss -ltn`, which shows both listeners on loopback only.

## Point gamdl at it

`~/.gamdl/config.yml`:

```yaml
auth:
  mode: wrapper
  wrapper_url: http://127.0.0.1:8080
  wrapper_decrypt_host: 127.0.0.1
  wrapper_decrypt_port: 10020
```

Keep `cookies_path` in the file as a fallback; switching back is a one-line change to `mode: cookies`.

Smoke checks before logging in:

```bash
curl -s http://127.0.0.1:8080/health
timeout 3 bash -c 'exec 3<>/dev/tcp/127.0.0.1/10020 && echo "decrypt port: accepts TCP"'
```

`WrapperApi.create` in gamdl raises `GamdlAuthenticationError("Wrapper is not authenticated")` until a login succeeds, which is expected, not a fault.

## Login

Credentials never touch this note and never touch the wrapper config. Gamdl asks for them by itself, because its wrapper path calls `ask_text` for Apple ID, password, and a 2FA code when `/me` reports `logged_out`:

```bash
gamdl rip "<any song url>" --output-dir /tmp/wrapper-test
```

There is a full-screen wizard route too (`gamdl auth`, pick Wrapper), but a normal download triggers the same prompts. Apple will likely force a 2FA code; the wrapper accepts it through `POST /login/2fa` and gamdl prompts for it inline.

After a successful login the session is written into `~/wrapper-v2/data` (`mpl_db/kvs.sqlitedb`), and `WRAPPER_RESTORE_SESSION` defaults to on, so a container restart re-harvests tokens with no password prompt.

## Then ask for lossless

```bash
gamdl rip "<song url>" --song-codec alac
```

Expected to succeed where the L3 device failed. Check the result, do not trust the exit code:

```bash
ffprobe -v error -show_entries stream=codec_name,codec_long_name,sample_rate,bit_rate \
  -of default=noprint_wrappers=1 file.m4a
```

ALAC appears as `codec_name=alac` with a bitrate well above 258 kbps. Hi-Res tier is `--song-codec alac-hires`, and `alac` picks the best available tier automatically.

## What was verified vs not

Verified: APKM hash matches between the two downloads of the same file, all 18 Apple libs pass the pinned SHA-256 check, the Docker build succeeds with `--format docker`, the image runs under rootless podman only with `--privileged`, the worker reaches `ipc worker ready` / `playback_ready: true`, the quadlet unit starts and restarts cleanly, both ports listen on loopback only, the TCP decrypt port accepts connections, and gamdl reads the wrapper at `127.0.0.1:8080`.

Not verified at the time of writing: the Apple ID login, session restore after a container restart, and whether ALAC actually licenses and downloads. Those need the account holder at the keyboard for credentials and 2FA, and the lossless result depends on the account and track.

## References

- [glomatico/wrapper-v2 README](https://github.com/glomatico/wrapper-v2)
- [wrapper-v2 `LIBS_VERSION.json` (pinned hashes, tested build)](https://github.com/glomatico/wrapper-v2/blob/main/LIBS_VERSION.json)
- [glomatico/gamdl README, authentication and ALAC sections](https://github.com/glomatico/gamdl/blob/4.0/README.md)
- [Podman docs: quadlet units](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html)

Related: [[gamdl-apple-music-downloader-install-fedora-2026-11-18]], [[snowsky-disc-quieter-after-usb-audio-cs43131-reinit-gain-reset-2026-11-11]]
