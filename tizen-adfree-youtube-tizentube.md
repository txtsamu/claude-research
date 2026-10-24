---
type: investigation
tags: [samsung, tizen, youtube, tizentube, ad-block, kants2, apps2samsung]
created: 2026-10-24
last_verified: 2026-10-24
status: current
---

# Ad-free YouTube on a Tizen 5.5 Samsung TV: TizenTube

Question: is there a YouTube client without ads that can be installed on the
UA43T6500AKXXD (Tizen 5.5, Novatek NT72172)? Answer: yes — **TizenTube**, and this
TV's exact Tizen generation is one of its two supported build targets.

## What it is

`reisxd/TizenTube` — originally a TizenBrew module, now also a standalone app. It
replaces the YouTube front end and removes ads, and adds SponsorBlock, DeArrow,
playback-speed control and picture-in-picture. Official project page:
<https://github.com/reisxd/TizenTube>.

Latest release checked 2026-10-24: **v2.1.1**, three `.wgt` assets:

| Asset | Target |
|---|---|
| `TizenTubeCobalt.wgt` | Tizen 6 (2021) and later |
| `TizenTubeCobaltTizenTubeProxyAddress.wgt` | same, but with the proxy address set to `http://tizentube:8101` for TVs that cannot resolve the default `http://127.0.0.2:8101` (needs a DNS entry `tizentube` → the TV's own static IP) |
| `TizenTubeOld.wgt` | **Tizen 3, 4, 5 and 5.5** ← this TV (Tizen 5.5) |

Minimum requirement is Tizen 3 (2017), so a 2020 KantS2 set is inside support.

## Install route

The documented path is **Apps2Samsung** (`github.com/Apps2Samsung/Apps2Samsung`),
because the `.wgt` must be signed with a Samsung certificate at install time:

1. On the TV: Apps panel → enter `12345` → Developer Mode → **On**, Host PC IP =
   the address of the machine running Apps2Samsung.
2. On that machine: Apps2Samsung → pick the TV → enable **Force Samsung Certificate**
   and **Partner Signing** (PC: settings gear; Android: Certificate → Partner).
3. Choose release `TizenTubeOld.wgt`, click Install.
4. On older Tizen the guide then suggests setting Host PC IP to `127.0.0.1` and
   rebooting to avoid playback issues.

Notes specific to this TV:

- Developer mode is already on and the host IP is already `192.168.50.20`, so step 1
  is done — but step 4's advice to switch the host to `127.0.0.1` would **kill the
  sdb injection path** that the root chain depends on (see
  [samsung-tv-uep-bypass-and-kants2-root.md](samsung-tv-uep-bypass-and-kants2-root.md)).
  Try playback without that change first.
- We have root and a working `sdb` channel, so pushing a `.wgt` with
  `pkgcmd -i`/`sdb install` is worth trying, but Tizen enforces the signature, so the
  Apps2Samsung partner-certificate route stays the documented fallback.
- YouTube itself is intact on this TV: package `9Ur5IzDKqV` v2.1.498, app id
  `9Ur5IzDKqV.TizenYouTube`, launch verified (pid 3686) after the debloat passes.

## Alternatives ruled out

- **SmartTube / SmartTubeNext** — Android TV only; no Tizen build, cannot run here.
- **Patching the stock YouTube app** (`com.samsung.tv.cobalt-yt`, package
  `com.samsung.tv.cobalt`) — it is a signed Cobalt binary inside a signed package;
  modifying it invalidates the package signature and Tizen will refuse to launch it.
  TizenTube sidesteps this by shipping its own signed package.
- **DNS/hosts-level ad blocking** — YouTube serves ads from the same hosts as video
  content, so hosts sinkholes break playback rather than remove ads.

## Not yet done

TizenTube has not been installed on this unit yet — the release/target mapping above
is from the project's own install guide, not from a successful install here. Open
risks for this hardware: the NT72172 SoC is weak, so dearrow/SponsorBlock overhead
may be noticeable, and the launcher/Home routing work is orthogonal (TizenTube will
show up as just another app id in `getAppsInfo`, which means it can be pinned to the
launcher dock and, if unwanted, hidden through `HIDE_IDS`).
