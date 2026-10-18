---
type: how-to
tags: [tiktok-bot, home, anoa, camofox, scraping, cdp, gallery-dl, nixos]
created: 2026-10-18
last_verified: 2026-10-18
status: current
---

# tiktok-bot: anoa-browser as an alternative scrape backend (vs camofox) + skip slideshow .mp3

**Host:** home (NixOS). Bot: `/opt/tiktok-bot/tiktok_bot.py`, unit `tiktok-bot.service`, venv `/opt/tiktok-bot-venv`.

Two changes:

1. **anoa-browser** ([porcupine-md/anoa-browser](https://github.com/porcupine-md/anoa-browser)) evaluated and wired in as an optional backend for the "render the profile in a real browser and collect post links" step, which until now only camofox did.
2. **Stop downloading `.mp3`**: these were the background-music tracks of TikTok photo/slideshow posts that gallery-dl fetches by default. There were about 10.9k of them under `/mnt/photos/downloads/tiktok`.

## What anoa is

anoa is a single-binary browser built on Qt WebEngine (Chromium 140 inside). It can be driven by its CLI, by any CDP client (`/json/list`, then the page websocket), or over MCP at `POST /mcp` (tools named `browser_*`). It is MIT-licensed. It was young when tested: v0.19.1, released 2026-10-16, 31 stars.

The README says nothing about stealth or anti-detection. Its fingerprint is not stealthy:

```
navigator.userAgent = "... QtWebEngine/6.11.2 Chrome/140.0.0.0 Safari/537.36"
navigator.webdriver = false
navigator.plugins.length = 0
WebGL context = null (headless)
```

## Install / run on home (test instance)

On NixOS, the flake builds against cache.nixos.org Qt packages (a few minutes):

```bash
mkdir -p ~/anoa-test && cd ~/anoa-test
nix build github:porcupine-md/anoa-browser/v0.19.1 -o result-anoa
nohup ./result-anoa/bin/anoa --headless --port 9500 \
  --profile-dir ~/anoa-test/profiles --ephemeral > anoa.log 2>&1 &
./result-anoa/bin/anoa --port 9500 status
```

It uses 3 consecutive ports: 9500 (HTTP discovery, WS proxy, `/mcp`), 9501 (Chromium internal DevTools) and 9502 (CDP proxy). Without `--auth-token`, CDP is unauthenticated; it binds to 127.0.0.1.

RSS was about 1.7 GB after the test runs, versus about 1.9 GB for the camofox unit.

### CDP gotchas found

- **`/json/new` is not implemented**: `{"error":"not found"}` for both PUT and GET. Create tabs through the CLI (`anoa tab new about:blank --json` returns `{"tab":"t2","targetId":"…"}`) or through MCP:
  ```bash
  curl -s -X POST http://127.0.0.1:9500/mcp -H 'Content-Type: application/json' -d \
   '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"browser_tab",
     "arguments":{"action":"new","target":"about:blank","isolated":true,"json":true}}}'
  # close: {"action":"close","target":"t14"}
  ```
  Then match `anoaTabId` in `GET /json/list` to get that tab's `webSocketDebuggerUrl`.
- **`isolated: true` gives the tab its own throwaway cookie jar.** `Network.setCookies` sent on that tab's websocket lands in its jar only. This was verified with a probe cookie on example.com: a shared tab did not see the isolated tab's cookie. This is the equivalent of camofox's per-call `userId` session, so concurrent scrapes don't clobber each other.
- **Do NOT override the user agent.** `Network.setUserAgentOverride` with a "clean" Chrome 140 UA turned every TikTok profile into a hard **`Access to www.tiktok.com was denied … HTTP ERROR 403`**. The unmodified QtWebEngine UA works. The likely cause is a mismatch with the Sec-CH-UA client hints, which the override doesn't change.

## Test: same profiles, same cookies, anoa vs camofox

Script (scratch, kept at `~/anoa-test/anoa_vs_camofox.py` on home). It loads `/opt/tiktok-bot/cookies.txt` (tiktok.com cookies only), opens `https://www.tiktok.com/@<user>` and collects `a[href]` matching `/@user/(video|photo)/\d+`. It scrolls 2000px with a 1.5s settle, up to 25 rounds and stops after 3 stale rounds. This mirrors the bot's existing camofox loop. Run as root, with the camofox key from agenix:

```bash
sudo bash -c 'set -a; . /run/agenix/camofox-api-key; set +a;
  /opt/tiktok-bot-venv/bin/python3 ~moo/anoa-test/anoa_vs_camofox.py 200 bukanpidel1 tiktok intunnn039'
```

Results (2026-10-18, home's normal egress, not the WARP proxy):

| Profile | limit | anoa | camofox |
|---|---|---|---|
| bukanpidel1 | 30 | 30 in 8.4s | 30 in 7.8s |
| intunnn039 | 30 | 30 in 8.5s | 30 in 5.4s |
| tiktok | 30 | 30 in 9.5s | 30 in 7.8s |
| bukanpidel1 | 200 | **200 in 19.2s** (7 photo) | 118 in 24.7s (6 photo) |
| tiktok | 200 | **200 in 21.6s** (6 photo) | 113 in 25.4s (2 photo) |
| intunnn039 | 200 | **200 in 19.5s** (6 photo) | 118 in 27.8s (2 photo) |

anoa with the UA override returned 0 posts on all three (403 page).

"camofox-only" posts in the overlap check (13–39 per profile) are not real misses. Both lists are sorted and cut at `limit`; anoa found more than 200 posts, so some posts drop out of its top 200. camofox consistently stalls at about 113–118 posts. That ceiling is probably in its `/links` and scroll handling and was not investigated further.

**Verdict:** anoa works against TikTok right now, *despite* its non-stealthy fingerprint. It goes deeper on infinite scroll than camofox and is a bit faster on large profiles. camofox (Firefox-based, anti-fingerprint) is still the safer bet if TikTok starts fingerprinting QtWebEngine. So anoa is wired in as **opt-in, with automatic fallback to camofox**.

## Bot change 1: anoa backend (`SCRAPE_BROWSER`)

New in `tiktok_bot.py`:

- Config, read from env next to the `CAMOFOX_*` settings:
  - `SCRAPE_BROWSER`: `camofox` (default, old behavior) or `anoa`
  - `ANOA_URL`: default `http://127.0.0.1:9500`
  - `ANOA_TOKEN`: optional bearer token, used for both `/mcp` and the CDP websocket
- `_anoa_mcp()`: a small JSON-RPC `tools/call` helper.
- `_anoa_scrape_profile()`: async. It opens an isolated tab over MCP, connects to the tab websocket (the `websockets` package, already in the venv lock), runs `Network.setCookies` then `Page.navigate`, waits 6s, then does the same scroll/collect loop as camofox. The tab is always closed in `finally`.
- `_anoa_extract_video_urls()`: same signature and contract as `_camofox_extract_video_urls` (returns `[]` on any failure). It runs `asyncio.run()` because callers invoke it through `run_in_executor`, so it gets a fresh thread with no event loop.
- `_browser_extract_video_urls()`: dispatcher. With `SCRAPE_BROWSER=anoa` it tries anoa, and **falls back to camofox when anoa returns nothing** (anoa down, 403, or a genuinely empty profile).
- All 4 `run_in_executor(None, _camofox_extract_video_urls, …)` call sites now call `_browser_extract_video_urls`: profile camofox-first, the include-photos manifest pass, the fatal-error fallback and the watch check.

The real functions were tested by importing the module (the `__main__` guard means the bot doesn't start; the f2 msToken error at import is pre-existing noise):

```
('bukanpidel1', 30, False) 30 photo=0 8.2s
('bukanpidel1', 200, True) 200 photo=7 19.7s
('tiktok', 8, False)       8 photo=0 6.4s
fallback (ANOA_URL -> dead port 9599): "anoa fallback failed … Connection refused" -> camofox found 10, 7.8s
```

### Enabled on home (2026-10-18): home-nixos PR #8, generation 45

Bot code: `txtsamu/tiktok-bot` commit `27f8098`. Config: [txtsamu/home-nixos#8](https://github.com/txtsamu/home-nixos/pull/8), squash-merged as `140ca7d`.

- **`flake.nix`**: new input `anoa.url = "github:porcupine-md/anoa-browser/v0.19.1"`. It deliberately does *not* follow our nixpkgs, because its Qt WebEngine build is tested against its own pin. The package is passed to modules as `specialArgs.anoa = anoa.packages.${system}.default`.
- **`hosts/home/anoa.nix`**: `anoa-browser.service`. It runs as a `DynamicUser` (with State/Cache/RuntimeDirectory), `HOME=/var/lib/anoa-browser`, `NoNewPrivileges` and `PrivateTmp`. This was tested first with `systemd-run -p DynamicUser=yes …`; Chromium runs fine under it without `--no-sandbox`.
- **Auth token:** new agenix secret `secrets/anoa-auth-token.age` containing `ANOA_TOKEN=<64 hex>`, encrypted to both recipients (host key + recovery). The bot and anoa share this one secret.
  - The token was generated and encrypted on home without being printed:
    ```bash
    umask 077; T=$(mktemp)
    printf "ANOA_TOKEN=%s\n" "$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')" > $T
    nix shell nixpkgs#age -c age -r "<home ssh-ed25519 pubkey>" -r <recovery age1 pubkey> \
      -o /tmp/anoa-auth-token.age $T; shred -u $T
    sudo nix shell nixpkgs#age -c age -d -i /etc/ssh/ssh_host_ed25519_key /tmp/anoa-auth-token.age | wc -c  # 76
    ```
  - `--auth-token` on the command line would put the token in world-readable `/proc/<pid>/cmdline`. Instead, the unit `script` writes `printf '{"authToken":"%s"}' "$ANOA_TOKEN" > $RUNTIME_DIRECTORY/config.json` and runs `anoa --config` on it. `printf` is a bash builtin, so the token never appears in an argv.
  - **The config key is `authToken`** (camelCase). Both `auth-token=` (INI) and `{"auth-token":…}` (JSON) are silently ignored, and anoa then runs **without auth**. The key name comes from `tests/unit/test_config.cpp` in anoa's source.
  - anoa prints the token, plus a `/setup?token=…` URL, to stderr on every start (`src/main.cpp`). `LogFilterPatterns = "~token"` keeps those lines out of the journal; verified: `journalctl -u anoa-browser | grep -ci token` returns 0.
- **Bind address:** anoa binds HTTP (9500) and the CDP proxy (9502) to `QHostAddress::Any`, i.e. 0.0.0.0, and has no option to change it. Only Chromium's own DevTools port (9501) is loopback-only. The ports are therefore **not** opened in the firewall: `nixos-fw` has no trusted interfaces, so the LAN and k3s pods are both blocked. The token covers 9500 (including `/mcp`) and 9502 (Bearer header or `?token=` on the websocket, `src/cdp/cdp_proxy.cpp`). It does not cover 9501, which only local processes can reach.
- **`tiktok-bot.nix`**:
  - `SCRAPE_BROWSER = "anoa"`.
  - `EnvironmentFile = [ camofox-api-key anoa-auth-token ]`.
  - `after` and `wants` (not `requires`) on `anoa-browser.service`, so the bot still starts, and falls back to camofox, if anoa is down.
- **`provision.nix`**: tiktok-bot pin bumped `a3e7f1e` → `27f8098`. Checked first that `tiktok-bot-local.patch` still applies (`git apply --check`).

Pre-merge checks, run on home in a throwaway copy:

```bash
nix flake lock && nix fmt && nix flake check          # all checks passed, 0 files reformatted
nix build .#nixosConfigurations.home.config.system.build.toplevel -o result-sys
nix store diff-closures /run/current-system ./result-sys   # 87 additions (anoa + Qt runtime), 0 version changes
```

Then CI went green, the PR was squash-merged, and home was deployed with `sudo nixos-rebuild switch --flake github:txtsamu/home-nixos#home --refresh`. That started `anoa-browser.service` and restarted `tiktok-bot`.

Post-deploy verification:

```
no token  /json/list -> 401     no token /mcp -> 401     Bearer token /json/list -> 200
tiktok-bot environ: SCRAPE_BROWSER=anoa, ANOA_TOKEN set
live (bot code + real env): anoa found 30 videos for @bukanpidel1 (8.5s), dispatcher @tiktok 30 (10.6s)
```

The PR conflicts on `flake.lock` with the automated input-update PR #5; whichever merges second needs a rebase.

## Bot change 2: skip slideshow `.mp3`

gallery-dl's TikTok extractor sets `self.audio = self.config("audio", True)`. For photo posts with `"music"` it yields the audio track with `extension = "mp3"`. This was confirmed by reading `gallery_dl/extractor/tiktok.py` (gallery-dl 1.32.14) in the venv. Fix in `gallery_dl_download()`:

```python
# TikTok: skip the background-music .mp3 gallery-dl grabs alongside photo/slideshow posts
if platform_key == "tiktok":
    cmd.extend(["-o", "extractor.tiktok.audio=false"])
```

yt-dlp paths never produced these files. Existing `.mp3` files were left in place (about 10.9k); delete them separately if wanted:

```bash
find /mnt/photos/downloads/tiktok -name '*.mp3' -delete
```

A direct gallery-dl check on a photo URL couldn't confirm it end-to-end: plain gallery-dl gets "Failed to extract post" because of the Slardar WAF, which is why the bot uses `extractor.tiktok.ytdl=true` for profiles. The option name and behavior were verified from source instead.

## Deploy state / persistence

- First edited in place in `/opt/tiktok-bot` and tested, then committed to `txtsamu/tiktok-bot` as `27f8098`. Only the anoa and mp3 changes went in; the host-specific `/opt/hermes-venv` → `/opt/tiktok-bot-venv` paths stay as the nix patch. To isolate them: copy the live file into a clean clone, then `git apply -R hosts/home/patches/tiktok-bot-local.patch`.
- `provision-src-tiktok-bot` only clones when `/opt/tiktok-bot` is empty, so bumping the pin doesn't touch the live tree. The live checkout was synced so its git state matches a fresh provision (`27f8098` + local patch as the only diff). Home has no GitHub credentials (private repo, so `git fetch` fails with `could not read Username`), so the commit went over as a bundle:
  ```bash
  git bundle create tb.bundle a3e7f1e..main            # on fedora, in a clone
  scp tb.bundle home:/tmp/
  cd /opt/tiktok-bot && sudo git fetch /tmp/tb.bundle main:refs/remotes/origin/main \
    && sudo git reset --mixed 27f8098                  # working tree untouched
  ```

## References

- anoa-browser repo / README: https://github.com/porcupine-md/anoa-browser
- anoa v0.19.1 release: https://github.com/porcupine-md/anoa-browser/releases/tag/v0.19.1
- anoa config keys (`authToken`): https://github.com/porcupine-md/anoa-browser/blob/v0.19.1/tests/unit/test_config.cpp
- anoa token printed at startup / bind address: https://github.com/porcupine-md/anoa-browser/blob/v0.19.1/src/main.cpp
- anoa CDP proxy auth + `QHostAddress::Any` bind: https://github.com/porcupine-md/anoa-browser/blob/v0.19.1/src/cdp/cdp_proxy.cpp
- systemd `LogFilterPatterns=`: https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html#LogFilterPatterns=
- home-nixos PR enabling it: https://github.com/txtsamu/home-nixos/pull/8
- gallery-dl TikTok extractor (`audio` option): https://github.com/mikf/gallery-dl/blob/master/gallery_dl/extractor/tiktok.py
- gallery-dl configuration docs (`extractor.tiktok.audio`): https://gdl-org.github.io/docs/configuration.html
- Chrome DevTools Protocol, Network domain (`setCookies`, `setUserAgentOverride`): https://chromedevtools.github.io/devtools-protocol/tot/Network/
