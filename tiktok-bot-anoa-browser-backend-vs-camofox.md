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

### To actually enable it (not done yet)

1. Run anoa as a persistent service on home, as a unit in home-nixos next to `camofox-browser.service`, e.g. `anoa --headless --port 9500 --ephemeral --auth-token <agenix secret>`.
2. Set `SCRAPE_BROWSER=anoa` (and `ANOA_TOKEN`) in `tiktok-bot.service`, plus `After=` on the anoa unit.

Until then the bot runs with the default `camofox`, so behavior is unchanged.

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

- Edited in place in `/opt/tiktok-bot` (backup at `/tmp/tiktok_bot.py.bak` on home), then `systemctl restart tiktok-bot`; the bot came back healthy.
- `provision-src-tiktok-bot` only clones when `/opt/tiktok-bot` is empty (pinned commit `a3e7f1e` + a nix-store local patch), so in-place edits survive rebuilds. They are **not yet committed** to `github.com/txtsamu/tiktok-bot` or re-pinned in home-nixos.

## References

- anoa-browser repo / README: https://github.com/porcupine-md/anoa-browser
- anoa v0.19.1 release: https://github.com/porcupine-md/anoa-browser/releases/tag/v0.19.1
- gallery-dl TikTok extractor (`audio` option): https://github.com/mikf/gallery-dl/blob/master/gallery_dl/extractor/tiktok.py
- gallery-dl configuration docs (`extractor.tiktok.audio`): https://gdl-org.github.io/docs/configuration.html
- Chrome DevTools Protocol, Network domain (`setCookies`, `setUserAgentOverride`): https://chromedevtools.github.io/devtools-protocol/tot/Network/
