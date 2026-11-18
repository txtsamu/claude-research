---
type: investigation
tags: [fiio, snowsky, snowsky-echo, dap, cs43198, indonesia, shopping, tokopedia, aliexpress]
created: 2026-11-18
last_verified: 2026-11-18
status: current
---

# Cheapest CS43198 DAP on the Indonesian market (Nov 2026)

## Request

"Cheapest CS43198 DAP on Indonesia market." The Cirrus Logic CS43198 is the
DAC chip (130 dBA, 32-bit/384 kHz) used in FiiO's budget players and a pile of
dongles. Question was specifically about *players* (standalone DAPs), not USB
dongle DAC/amps.

## TL;DR

**FiiO SNOWSKY ECHO** (dual CS43198, USD 69.99 MSRP) is the cheapest real
CS43198 DAP sold into Indonesia, at **Rp 1.36-1.41 juta** on Tokopedia via
gray-import sellers. The cheapest mainstream alternative is the FiiO JM21
(dual CS43198, Android 13) at **Rp ~2.76 juta** with local warranty.
Everything cheaper in the search results is either a CS43131 device or a
dongle, not a CS43198 DAP.

## Verified prices (live browser check, 2026-11-18)

Checked by driving the real browser against Tokopedia search pages and
extracting rendered product cards (JS-rendered, so plain HTTP fetch of
Tokopedia/Shopee returns nothing; static sites like the Porta-Fi review and
Intium store fetched fine over HTTP).

| Device | Chip | Cheapest ID price seen | Where |
|---|---|---|---|
| FiiO Snowsky ECHO (full-size, cassette retro) | 2x CS43198 | Rp 1.362.500 (COD); chip-named listings Rp 1.394.000-1.414.000 | Tokopedia: Smphone Affiliate, SUBR ANTI, SANAOKANASA (all Jakarta Timur, gray import) |
| FiiO JM21 (Android 13, Snapdragon 680) | 2x CS43198 | Rp 2.760.000 ("garansi resmi") | Tokopedia 1121 shop; ~Rp 3 juta retail per Intium/reviews |
| FiiO M21 | 4x CS43198 | well above JM21, not price-checked | Shopee/Tokopedia official channels |

Key URLs used:

- `https://www.tokopedia.com/find/snowsky-echo` (full-size ECHO listings)
- `https://www.tokopedia.com/find/cs43198` (all CS43198-tagged items)
- `https://www.tokopedia.com/find/fiio-jm21`
- `https://id.aliexpress.com/item/1005013454573956.html` (Fosi DAP NEO)
- `https://id.aliexpress.com/item/1005012569909810.html` (no-name CS43198 player)

## Traps ruled out (all cheaper, all NOT CS43198)

- **Snowsky Echo Mini** (Rp 935.000-985.000, cheapest FiiO player in ID):
  dual **CS43131**, not CS43198. Easy to misread because listings appear in
  the same search results.
- **Snowsky Echo Nano** (Rp 1.083.000-1.100.000, Intium/FiiO Official Store):
  single **CS43131** (confirmed on fiio.com/echonano).
- **Ruizu X50 "Sport"** (Rp ~300.000 on Jakmall/Shopee): the cheap sport MP3
  player, not a HiFi DAP at all. No verified CS43198 claim.
- **Dongles that dominate "cs43198" searches**: EPZ TP35 Pro (Rp 1.184.000),
  EPZ TP55, Akliam PD1 (Rp 845.430), JCALLY JM98 Max (Rp 564.000), Tanchjim
  Space Pro, Truthear Shio, ONIX Alpha XI1. All USB DAC/amps, not DAPs.
- **SMSL PL150** shows up in "CS43198" searches: it's a desktop **CD player**
  (Rp 2.750.000), not portable.
- **Shanling H2**: battery-powered but a USB DAC/amp with no local playback.

## AliExpress route (ruled out for ID)

- Fosi Audio DAP NEO (single CS43198, retro click-wheel): the AliExpress
  listing loads but reports **"Sorry, this item's currently unavailable in
  your location"** for Indonesia. No local reseller found (Intium carries
  Fosi Audio but only amps like the BT20A Pro so far).
- No-name "Dual CS43198 HiFi WiFi Bluetooth Music Player" (AliExpress
  1005012569909810): *does* ship to ID but at **Rp 4.265.097** - not cheap,
  likely a higher-tier WiFi player listing.
- Net: importing does not beat the local Snowsky ECHO price.

## Gotchas

- Tokopedia "fiio jm21" search is polluted with **case/accessory listings**
  at Rp 235.000-393.000 (NEST POD case, SK-JM21 leather case) and an
  Rp 393.000 "JM21 DAP" listing from an unknown seller that is almost
  certainly not a real player. The real player is ~Rp 2.76 juta.
- The full-size Snowsky ECHO is **gray import only** in ID right now: Intium
  (FiiO's distributor) and the FiiO Official Store on Tokopedia sell only the
  Echo Mini/Nano and cases, not the full-size ECHO. Warranty on the Rp 1.4 juta
  listings is therefore seller-provided, not official.
- The Intium product page for the JM21 shows a broken price range
  ("Rp 250.000 - Rp 4.200.000" - that low bound is a case SKU), so use the
  marketplace/retail figure of ~Rp 2.76-3 juta.
- Marketplace prices drift daily and promo vouchers can knock 1-5% off the
  quoted numbers.

## Not verified

- **Shopee**: search is behind a login/language-dialog wall in this browser
  session; a Shopee listing for the full-size ECHO exists (item
  `i.915751395.52809438043`) but its price was not read. Lazada carries the
  same players at similar prices per search snippets.
- **Used market** (OLX/FB Marketplace): a used Shanling M0 Pro or Hidizs AP80
  (both CS43198-era players) could undercut Rp 1.36 juta; not surveyed.
- Whether FiiO Indonesia (Intium) will pick up the full-size ECHO officially.

Related: the Snowsky Disc that runs diskOS uses the **CS43131** (see
[[snowsky-disc-quieter-sound-dac-filter-nos-sysconfig-db-2026-11-11]] and
[[snowsky-disc-quieter-after-usb-audio-cs43131-reinit-gain-reset-2026-11-11]]);
the CS43198 players above are the bigger-sibling DAC. DAP research context in
[[redmi-10-selene-dac-compat-and-dap-setup-research]] and
[[fiio-snowsky-disc-diskos-flash-fedora]].

## References

- [Porta-Fi SNOWSKY ECHO review](https://porta-fi.com/snowsky-echo-review-dual-cs43198-retro-dap/) (dual CS43198 spec, USD 69.99)
- [FiiO ECHO NANO official page](https://www.fiio.com/echonano) (CS43131)
- [HiFi Oasis SnowSky Echo Mini page](https://www.hifioasis.com/dap/snowsky-echo-mini/) (2x CS43131, USD 52.99)
- [Intium Store Fiio JM21 page](https://intiumstore.com/product/98/fiio-jm21) (dual CS43198 specs, ID distributor)
- [Headfonics FiiO SNOWSKY ECHO NANO review](https://headfonics.com/fiio-snowsky-echo-nano-review/) (CS43131)
- [Cirrus Logic CS43198 product page](https://www.cirrus.com/products/cs43198)
- [Tokopedia find: snowsky echo](https://www.tokopedia.com/find/snowsky-echo)
- [Tokopedia find: cs43198](https://www.tokopedia.com/find/cs43198)
- [Fosi Audio DAP Neo (AliExpress, geo-blocked for ID)](https://www.aliexpress.com/item/1005013454573956.html)
