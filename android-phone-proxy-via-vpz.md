---
type: how-to
tags: [android, proxy, socks5, http-proxy, freeproxy, vpz, squid, microsocks]
created: 2026-08-30
last_verified: 2026-08-30
status: current
---

# Routing an Android phone's traffic through vpz's existing proxies

`vpz` already runs two separate proxy servers, both built for other
purposes earlier but reusable as-is for this:

- **Squid (HTTP/HTTPS, port 3128)** — built for opt-in k8s cluster egress.
  See the "Notes on secrets" section below for where the real credentials
  live.
- **microsocks (SOCKS5, port 1080)** — built for Suwayomi's
  Cloudflare-bypass proxy needs. See
  [suwayomi-k8s-deployment-fixes.md](suwayomi-k8s-deployment-fixes.md).

No new server needed — just point the phone at whichever one fits.

## The catch: Android's native proxy setting is WiFi-only

**Settings → Wi-Fi → (long-press a network) → Modify network → Advanced →
Proxy → Manual** works, but only applies to *that specific WiFi network* —
it does nothing on mobile data or other networks. There's also no
username/password field, which both proxies above require.

Two ways around this, depending on what you actually want:

## Option A — NetBird exit node (works everywhere, zero extra setup)

If the phone is already a NetBird peer (see
[netbird-selfhosted-podman-quadlet-setup.md](netbird-selfhosted-podman-quadlet-setup.md)),
selecting `vpz` as the exit node in the NetBird app routes *all* traffic —
WiFi and mobile data both — through `vpz`, with no auth issues since it's
inside the mesh already. Simplest option if "route everything through vpz,
everywhere" is the actual goal.

## Option B — FreeProxy (system-wide, works everywhere, supports proxy auth)

For actually using the Squid/microsocks proxies specifically (rather than
the NetBird tunnel), Android needs a VpnService-based app to get
system-wide + authenticated + works-on-mobile-data all at once, since the
native setting can't do any of the three beyond "same WiFi network, no
auth."

[FreeProxy](https://github.com/xVanTuring/free-proxy) — genuinely open
source (Apache 2.0, source on GitHub), distributed via
[F-Droid](https://f-droid.org/packages/tech.xvanturing.freeproxy/) (no
Google Play tracking), actively maintained. Supports both SOCKS5 and HTTP
CONNECT with username/password auth, plus per-app routing if you don't
want to send the phone's *entire* traffic through it.

**Setup:**
1. Install F-Droid (fdroid.org) if not already present.
2. Search **FreeProxy** in F-Droid, install.
3. Add profile:
   - **Type**: `SOCKS5` (port `1080`) or `HTTP CONNECT` (port `3128`) —
     either works, pick whichever proxy's credentials you're using.
   - **Host**: vpz's public IP (see secrets note below)
   - **Port**: `1080` or `3128` to match the type chosen
   - **Username** / **Password**: matching the chosen proxy (see secrets
     note below)
4. Use the app's built-in connectivity test before saving.
5. Enable — runs as a local VPN service (standard Android "VPN connected"
   key icon), works across WiFi and mobile data.

## Notes on secrets

Real host IP and both proxies' passwords are not reproduced here — see
`/etc/squid-k8s/passwd` and the `microsocks-vpz.service` unit file
(`ExecStart` line) directly on `vpz`, or the credentials already shared
out-of-band when each proxy was originally set up.
