---
type: how-to
tags: [gamdl, apple-music, music, downloader, fedora, uv, widevine, drm, cli]
created: 2026-11-18
last_verified: 2026-11-18
status: current
---

# Installing Gamdl 4.x (Apple Music downloader) on Fedora 43 with uv

Gamdl is Glomatico's command-line Apple Music downloader: songs, albums, playlists, artist pages, your own library, music videos, and uploaded videos. Version 4.0.x is a rewrite: subcommands (`rip`, `search`, `library`, `sync`, `organize`, `database`, `auth`, `config`), YAML config at `~/.gamdl/config.yml`, a native (Rust, abi3) mux/decrypt extension, and a bundled Widevine L3 device in the `[widevine]` extra.

Installed on the workstation (Fedora 43, Python 3.14.10 system, `uv` 0.11.6). The resulting tool env actually runs on CPython 3.13 because `uv` picked an available interpreter for the `>=3.10` requirement; the shipped wheel is `cp310-abi3-manylinux_2_17_x86_64`, so no Rust toolchain or build step was needed.

## Time estimate

| Step | Time |
|---|---|
| `uv tool install "gamdl[widevine]"` (warm cache, prebuilt wheel) | ~20 to 40 s, estimate, not instrumented |
| DRM sanity check (bundled Widevine device loads) | ~2 s, measured by feel, one-shot command |
| `gamdl auth` wizard (cookies or token route) | 1 to 3 min, dominated by exporting cookies from the browser |
| First `gamdl rip` of a single song | ~10 to 20 s per track, depends on codec |

Total to a working downloader: well under 5 minutes if you already have an Apple Music subscription and a signed-in browser.

## Prerequisites verified on this box

```bash
cat /etc/os-release | head -3      # Fedora 43 Workstation
python3 --version                  # Python 3.14.10
uv --version                       # uv 0.11.6
which ffmpeg                       # /usr/bin/ffmpeg (not required by 4.x, native muxer)
```

Gamdl 4.x needs Python 3.10+ and, only if no prebuilt wheel matches, Rust plus native build deps. Check wheels before assuming a build:

```bash
curl -s https://pypi.org/pypi/gamdl/json | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(d['info']['version'], d['info']['requires_python'])
print([u['filename'] for u in d['urls']])
"
```

At the time of writing: `4.0.2`, `>=3.10`, with `manylinux_2_17_x86_64` and `aarch64` abi3 wheels, so Linux installs never touch Rust.

## Install

Use `uv tool install` rather than a hand-made venv. It keeps Gamdl in an isolated environment under `~/.local/share/uv/tools/gamdl` and symlinks the `gamdl` entry point into `~/.local/bin`, which is already on `PATH` here.

```bash
uv tool install "gamdl[widevine]"
```

The `[widevine]` extra is the important part: it pulls `pywidevine` and Gamdl embeds a Widevine **L3** device in `gamdl/drm/service.py`, so no `.wvd` file is needed for normal 256 kbps AAC downloads.

Alternatives, for the record:

```bash
uv tool install "gamdl[playready]"   # needs your own .prd device via --device-path
uv tool install gamdl                # base only, protected streams will fail without DRM/wrapper
```

Verify:

```bash
which gamdl      # /home/moo/.local/bin/gamdl
gamdl --version  # Gamdl 4.0.2
gamdl --help     # auth, config, database, library, organize, rip, search, sync
```

Confirm the DRM backend really loads, since a broken CDM only shows up mid-download otherwise:

```bash
/home/moo/.local/share/uv/tools/gamdl/bin/python - <<'EOF'
import asyncio
from gamdl.drm.service import _make_cdm, DrmBackend
async def m():
    cdm = await _make_cdm(DrmBackend.WIDEVINE, None)
    print("Widevine CDM OK:", type(cdm).__name__)
asyncio.run(m())
EOF
```

Output: `Widevine CDM OK: Cdm`.

## Config location and shape

Skipping the wizard still creates the file on first run:

```bash
gamdl config path       # /home/moo/.gamdl/config.yml
gamdl config show       # effective settings
gamdl config validate   # Valid config_version=1
```

Defaults that matter:

- `auth.mode: null` means "ask me on first use".
- `output.directory: null`, so the first download prompts and remembers the answer. `$XDG_MUSIC_DIR` here is `/home/moo/Music`.
- `download.overwrite: false`, existing files are skipped, use `--overwrite`.
- `download.song_codec_priority: [aac]`, i.e. HLS AAC 256 kbps.
- `download.max_height: 1080` for video.
- `database.disabled: false`, a SQLite index at `~/.gamdl/media.sqlite3` lets re-runs skip already-downloaded catalog IDs before touching the network.

## Authentication

Three modes. `gamdl auth` is an interactive TUI, so run it in a real terminal, not piped or through an agent shell.

### 1. Media user token (fastest)

Sign in at <https://music.apple.com/>, open DevTools, Application, Cookies, `https://music.apple.com`, and copy the value of the `media-user-token` cookie. Then either

```bash
gamdl auth     # choose "Media User Token", paste it
```

or store it in the config:

```yaml
auth:
  mode: media-user-token
  media_user_token: "YOUR_TOKEN"
```

Treat that token like a password. Apple invalidates it when the session ends, at which point re-export.

### 2. Browser cookies (Netscape `cookies.txt`)

Export cookies for `music.apple.com` while signed in with "Get cookies.txt LOCALLY" (Chromium) or "Export Cookies" (Firefox), save to the default path `~/.gamdl/cookies.txt` (`auth.cookies_path`), then `gamdl auth` and pick Cookies. The file must contain the `media-user-token` cookie; that is literally what Gamdl reads.

```bash
ls -l ~/.gamdl/cookies.txt   # check it exists and chmod 600 it
chmod 600 ~/.gamdl/cookies.txt
```

### 3. Wrapper v2 (only if you want reliable ALAC)

[wrapper-v2](https://github.com/glomatico/wrapper-v2) is a local service that holds an authenticated Apple Music session and does its own playback/decryption. Gamdl talks to it at `http://127.0.0.1` and its decrypt port `10020`.

```yaml
auth:
  mode: wrapper
  wrapper_url: http://127.0.0.1
```

Worth the extra setup only for lossless: Apple often refuses Widevine L3 licenses for ALAC streams, and the README warns about exactly that. With the bundled L3 device, `aac` (256 kbps) is the reliable path; `alac` is a gamble without Wrapper.

## Configured auth on this box (cookies mode)

A full-browser Netscape export was provided at `/home/moo/cookies (1).txt` (1369 lines, every site, not just Apple). Gamdl only ever reads the `media-user-token` cookie for `music.apple.com`, and that export had one unique token duplicated across `.music.apple.com`, `.apps.apple.com`, `.podcasts.apple.com`, and `.tv.apple.com`, so pointing at the file directly works.

Check the export before trusting it, without printing the secret:

```bash
head -1 "/home/moo/cookies (1).txt"        # must be "# Netscape HTTP Cookie File"
awk -F'\t' '$6=="media-user-token"{print $1}' "/home/moo/cookies (1).txt" | sort | uniq -c
awk -F'\t' '$6=="media-user-token"{print length($7)}' "/home/moo/cookies (1).txt"
```

That file also carries Google, x.ai, and shop session cookies, so it was tightened to owner-only:

```bash
chmod 600 "/home/moo/cookies (1).txt"
```

Config was written directly instead of through the interactive `gamdl auth` wizard, which needs a TTY:

```python
import yaml, pathlib
p = pathlib.Path.home()/".gamdl/config.yml"
cfg = yaml.safe_load(p.read_text())
cfg["auth"]["mode"] = "cookies"
cfg["auth"]["cookies_path"] = "/home/moo/cookies (1).txt"
p.write_text(yaml.safe_dump(cfg, sort_keys=False))
```

```bash
chmod 600 ~/.gamdl/config.yml
gamdl config validate   # Valid config_version=1
```

Authentication was then proven without downloading anything, because `AppleMusicApi.from_cookies` fetches account metadata on construction:

```bash
/home/moo/.local/share/uv/tools/gamdl/bin/python - <<'EOF'
import asyncio
from gamdl.api import AppleMusicApi
async def m():
    api = await AppleMusicApi.from_cookies("/home/moo/cookies (1).txt")
    print("AUTH OK, storefront:", api.storefront)
    await api.aclose()
asyncio.run(m())
EOF
```

Result: `AUTH OK, storefront: id` (Indonesia), so metadata and search default to that storefront. Pass `--storefront us` for US-only catalogue items if needed.

End-to-end proof, one song into a throwaway directory:

```bash
gamdl rip "https://music.apple.com/us/album/never-gonna-give-you-up-2022-remaster/1624945511?i=1624945512" \
  --output-dir /tmp/opencode/gamdl-test --no-progress
```

Output:

```
✓ Authenticated
Created database at /home/moo/.gamdl/media.sqlite3
✓ Never Gonna Give You Up (2022 Remaster): downloaded →
/tmp/opencode/gamdl-test/Rick Astley/Whenever You Need Somebody (2022 Remaster)/01 Never Gonna Give You Up (2022 Remaster).m4a
Finished: 1 downloaded, 0 overwritten, 0 skipped, 0 failed, 0 finalization failures (1 discovered)
```

`ffprobe` on the result: `aac` (`codec_long_name=AAC (Advanced Audio Coding)`, profile **LC**), 48 kHz stereo, **258 840 bps**, 7.29 MB for 213.6 s, plus an embedded mjpeg cover and a companion `.lrc` sidecar. That is the expected HLS AAC 256 profile, decrypted through the bundled L3 device with no extra device file. It is **lossy**, not lossless; the config default `download.song_codec_priority: [aac]` is what decides that.

### Lossless is refused on this setup (measured)

Trying to force lossless on the same track:

```bash
gamdl rip "<song url>" --output-dir /tmp/alac-test --song-codec alac --no-tracebacks
```

```
! ALAC selected without Wrapper. Apple Music may refuse Widevine/PlayReady
licenses for ALAC; use Wrapper for more reliable lossless downloads
✗ Never Gonna Give You Up (2022 Remaster): Unable to acquire or process
decryption key (DrmLicenseError)
Finished: 0 downloaded, 0 overwritten, 0 skipped, 1 failed
```

With tracebacks the failing call is `gamdl/drm/service.py:300 get_keys` → `DrmLicenseError("Unable to obtain or process DRM license")`. So the bundled L3 device gets no key for ALAC, exactly as the README warned. `--song-codec alac-hires` and `alac-lossless` take the same path and fail the same way.

For contrast, `--song-codec atmos` on the same track fails earlier with `Requested codec or stream unavailable`, which is a stream-availability answer (this track, this storefront), not a DRM refusal.

Conclusion: AAC 256 is the realistic ceiling with cookies auth plus Widevine L3. Lossless requires [wrapper-v2](https://github.com/glomatico/wrapper-v2), which brings its own authenticated session and decryption. Verify a failed codec with `--ask-song-codec`, not by assuming the install is broken.

Caveat: this token dies when the Apple Music web session ends. Re-export cookies and overwrite the same file, no config change needed. If the export file disappears, auth breaks; copying it to `~/.gamdl/cookies.txt` and pointing `auth.cookies_path` there would make it less fragile.

## Everyday usage

Gamdl 4.x is subcommand-first. URLs go after `rip`; passing them bare is the 3.x syntax and will not work.

```bash
# one song
gamdl rip "https://music.apple.com/us/album/never-gonna-give-you-up-2022-remaster/1624945511?i=1624945512"

# several URLs in one session
gamdl rip "<url1>" "<url2>"

# whole album or playlist, no prompts
gamdl rip "<album-or-playlist-url>"

# album/playlist with a track picker
gamdl rip "<url>" --select

# by ISRC, no URL needed
gamdl rip isrc:USUM71703085

# artist page, auto-pick categories
gamdl rip "<artist-url>" --artist-auto-select main-albums,singles-eps,music-videos

# your saved library
gamdl library
gamdl library --library-auto-select albums,playlists

# search and pick
gamdl search "Thriller" --type song
gamdl search "Thriller" --type album --feeling-lucky
gamdl search "Caravan Palace" --search-api itunes
```

Interactive keys: arrows move, Space marks items in multi-select, Ctrl+A selects all, Enter confirms or starts the download, B backs out of a search category.

Format and metadata overrides, per command:

```bash
gamdl rip "<url>" --song-codec alac                 # best ALAC tier, single codec
gamdl rip "<url>" --song-codec-priority alac,atmos,aac
gamdl rip "<url>" --ask-song-codec                  # pick a stream interactively
gamdl rip "<video-url>" --music-video-codec-priority h265,h264 --max-height 2160
gamdl rip "<url>" --save-cover --file-cover-size max
gamdl rip "<url>" --lyrics-file-format enhanced-lrc --embedded-lyrics-format lrc
gamdl rip "<url>" --no-lyrics-file --exclude-tags comment,cover
gamdl rip "<url>" --output-dir /home/moo/Music/Apple
gamdl rip "<url>" --no-progress --no-tracebacks     # scripts
```

Library maintenance:

```bash
gamdl database info
gamdl database scan --dry-run && gamdl database scan
gamdl database prune --dry-run
gamdl organize --dry-run          # always dry-run before changing templates
gamdl sync playlists --dry-run
gamdl sync playlists              # fetch missing playlist tracks
```

Codecs available for songs: `aac`, `aac-he`, `aac-binaural`, `aac-downmix`, `aac-he-binaural`, `aac-he-downmix`, `aac-web`, `aac-he-web`, `atmos`, `ac3`, `alac`, `alac-lossless`, `alac-hires`. `aac` is HLS and works with Widevine L3; `aac-web` needs Widevine/PlayReady even when Wrapper is connected; `atmos` is E-AC-3 JOC at roughly 768 kbps.

## Gotchas hit or worth knowing

- **Not every track offers every codec.** A failed ALAC or Atmos request is a stream-availability problem, not a broken install. Test with `--ask-song-codec` to see what the manifest actually advertises.
- **ALAC without Wrapper is unreliable.** The README explicitly warns that Apple may refuse Widevine/PlayReady licenses for lossless. AAC first, lossless only after Wrapper.
- **Above 1080p video needs L1 or SL3000.** The bundled device is L3. Raising `--max-height` past 1080 will warn and probably fail to license.
- **Rebooting the tool env.** `uv tool upgrade gamdl` to update; `uv tool list` to inspect; `uv tool uninstall gamdl` to remove. Config and database live outside the env, in `~/.gamdl`.
- **Old 3.x SQLite indexes cannot be opened by 4.x.** Move the old DB aside instead of letting it confuse the index.
- **Tracebacks can leak signed URLs and tokens.** Review before pasting into an issue; `--no-tracebacks` hides them.
- **`gamdl auth` and the first-run wizard need a TTY.** They cannot be driven from a piped/agent shell.

## What was verified vs assumed

Verified on this machine: install completes from the PyPI abi3 wheel, `gamdl --version` reports 4.0.2, `gamdl --help` lists all subcommands, config created and validates (`config_version=1`), bundled Widevine device constructs a `Cdm`, `ffmpeg` and `~/Music` present, cookies auth succeeds (`storefront: id`), and a real AAC download completes with a 258 kbps m4a, embedded cover, and `.lrc` sidecar.

Not verified: video downloads, ALAC/Atmos, library and playlist sync, and token lifetime. Per-track codec availability is account- and region-dependent; treat the codec tables here as the README's typical figures, not guarantees.

## References

- [glomatico/gamdl README (branch 4.0)](https://github.com/glomatico/gamdl/blob/4.0/README.md)
- [gamdl on PyPI](https://pypi.org/project/gamdl/)
- [wrapper-v2](https://github.com/glomatico/wrapper-v2)
- [uv tool install docs](https://docs.astral.sh/uv/guides/tools/)
- [Apple Music web player](https://music.apple.com/)

Related: [[xiaomi-phone-music-library-sync-adb]], [[truenas-music-dedupe-and-tag-cleanup]], [[redmi-note-12-pro-ruby-apple-music-192khz-jack-vs-usb-dac]]
