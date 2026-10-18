---
type: how-to
tags: [technitium, dns, blocklist, samsung, smart-tv, tizen, advanced-blocking, hagezi, mikrotik]
created: 2026-10-18
last_verified: 2026-10-18
status: current
---

# Samsung TV ad/telemetry blocking, scoped to the TV only (Technitium Advanced Blocking)

Goal: block ads and telemetry on the Samsung UA43T6500AKXXD (2020, Tizen 5.5,
`192.168.50.31`, MAC `64:E7:D8:EC:38:EE`) **without** affecting any other LAN
client. Netflix, firmware updates, the Samsung app store (Smart Hub), Gallery
and the browser must keep working.

Result: the Technitium **Advanced Blocking** app (v11.1) was installed on all
three LAN Technitium nodes, with a single group `samsung-tv` mapped only to
`192.168.50.31`. That group uses HaGeZi's Samsung native tracker list plus a
TV-only allowlist. Global block lists were not changed.

## 1. Find the DNS servers the TV actually gets

```bash
sshpass -p '<MIKROTIK_PASSWORD>' ssh mikrotik '/ip dhcp-server network print detail;
  /ip dhcp-server lease print detail where mac-address=64:E7:D8:EC:38:EE;
  /ip firewall nat print terse'
```

- DHCP hands out `dns-server=192.168.50.200,192.168.50.42,192.168.50.40,1.1.1.1,1.0.0.1`.
- So there are **three** Technitium nodes the TV can use: `.200` (home, the primary,
  identity `dns-warp-vm`), `.40` (arm1) and `.42` (arm3). Each one has its own
  separate config (clustering was abandoned), so **every change has to be made
  on all three**.
- `1.1.1.1` and `1.0.0.1` are also handed out, and there is no NAT redirect or
  filter rule for port 53/853. The TV can bypass the blocking (see Risks below).
- The TV lease was bound with `host-name="Samsung"`. No IPv6 prefix is
  advertised on the LAN, so IPv4 client mapping is enough.

## 2. Authenticate to the API (all three nodes)

The credentials are admin / `<TECHNITIUM_ADMIN_PASSWORD>`, and the same password works on all nodes (see
[[agenix-technitium-admin-password-fix]]; the real value lives in the agenix
secret on home, `/run/agenix/technitium-admin-password`).

```bash
S=<scratch dir>
for ip in 192.168.50.200 192.168.50.40 192.168.50.42; do
  /usr/bin/curl -s -X POST "http://$ip:5380/api/user/login" \
    --data-urlencode user=admin --data-urlencode 'pass=<TECHNITIUM_ADMIN_PASSWORD>' \
    | jq -r .token > $S/tok_$ip
done
```

Gotcha: use `/usr/bin/curl`, not plain `curl`. The rtk hook rewrites `curl`
and truncates JSON bodies at about 500 bytes, which breaks `jq`.

## 3. Snapshot the existing state before changing anything

```bash
/usr/bin/curl -s "http://$ip:5380/api/settings/get?token=$t" > $S/settings_$ip.json
jq -c '.response | {enableBlocking, blockListUrls, blockingType}' $S/settings_$ip.json
/usr/bin/curl -s "http://$ip:5380/api/apps/list?token=$t" | jq -c '.response.apps[]'
```

Before the change (Technitium 15.4 on all nodes, no apps installed):

- Global `blockListUrls` on all three: blocklistproject `ads.txt` and `redirect.txt`,
  ABPindo, and StevenBlack hosts. `.200` also has HaGeZi `gambling-onlydomains`.
  `blockingType=AnyAddress` (0.0.0.0).
- **Existing global lists already block `lcprd1.samsungcloudsolution.net` and
  `lcprd2...`** (blocklistproject ads + StevenBlack). Those are the Smart Hub
  connectivity test and app store domains, which are known to break app
  downloads when blocked. They also block `push.samsungosp.com` and
  `gld.samsungosp.com`. To see which list blocks a domain:
  `dig +short @192.168.50.200 lcprd1.samsungcloudsolution.net TXT`.

## 4. Choosing the list

| Candidate | Verdict |
|---|---|
| Perflyst `SmartTV.txt` (630 lines, last commit 2026-09-09) | **Rejected for Technitium.** It lists whole parent domains: `samsungcloudsolution.com`, `samsungcloudsolution.net`, `samsungqbe.com` and `www.samsungotn.net`. It relies on Pi-hole's exact-match behaviour and comments out the needed subdomains (`otnprd8-11`, `lcprd1`, `time.`, `cdn.`). Technitium block lists block a domain **and all of its subdomains**, so in Technitium this list would also block firmware updates (`otnprd*.samsungcloudsolution.net`), the app store and `time.` (which Netflix/YouTube need on some TVs). |
| HaGeZi `native.samsung` (200 entries, updated 2026-10-02) | **Chosen.** It targets telemetry and ads precisely: ACR (`acr-*-prd.samsungcloud.tv`, `samsungacr.com`), ads (`samsungads.com`, `samsungadhub.com`, `samsungtvads.com`), `osb.samsungqbe.com`, `devicelog.samsungcloudsolution.net`, error dumps and `*pu.samsungelectronics.com`. It does not block any parent of the firmware or app store hosts. HaGeZi's README names the "Wildcard Domains" format for TechnitiumDNS. |

URL used (the same jsDelivr style as the existing gambling list):
`https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/wildcard/native.samsung-onlydomains.txt`

## 5. Why Advanced Blocking (per-client) and not a global list

- Advanced Blocking supports `networkGroupMap` (client IP/subnet to group), with
  separate block and allow lists for each group.
- Clients that match no entry in `networkGroupMap` get no app blocking. They
  still get the built-in global lists as before.
- **An app "allowed" entry overrides the built-in global block lists.** This is
  confirmed in `DnsServerCore/Dns/DnsServer.cs`: `ProcessRecursiveQueryAsync`
  calls `IsAllowedAsync` first, which asks each app's `IsAllowedAsync`, and it
  only calls `ProcessBlockedQueryAsync` (blocked zone, then block list zone, then
  apps) when nothing allowed the query. So the group's allowlist can un-break
  `lcprd1` and `lcprd2` for the TV only, and global blocking stays as it is for
  everyone else.

## 6. App config (`samsung-tv` group)

```json
{
  "enableBlocking": true,
  "blockingAnswerTtl": 30,
  "blockListUrlUpdateIntervalHours": 24,
  "blockListUrlUpdateIntervalMinutes": 0,
  "localEndPointGroupMap": {},
  "networkGroupMap": { "192.168.50.31": "samsung-tv" },
  "groups": [{
    "name": "samsung-tv",
    "enableBlocking": true,
    "allowTxtBlockingReport": true,
    "blockAsNxDomain": true,
    "blockingAddresses": ["0.0.0.0", "::"],
    "allowed": [
      "lcprd1.samsungcloudsolution.net", "lcprd2.samsungcloudsolution.net",
      "time.samsungcloudsolution.com", "cdn.samsungcloudsolution.com",
      "otnprd8.samsungcloudsolution.net", "otnprd9.samsungcloudsolution.net",
      "otnprd10.samsungcloudsolution.net", "otnprd11.samsungcloudsolution.net",
      "samsungotn.net", "otn.samsungcloudcdn.com", "auth.samsungosp.com",
      "infolink.pavv.co.kr", "osb-ussvc.samsungqbe.com"
    ],
    "blocked": [], "allowListUrls": [],
    "blockListUrls": ["https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/wildcard/native.samsung-onlydomains.txt"],
    "allowedRegex": [], "blockedRegex": [], "regexAllowListUrls": [],
    "regexBlockListUrls": [], "adblockListUrls": []
  }]
}
```

The allowlist is taken from the "required" comments in Perflyst's list: firmware
(`otnprd*`, `samsungotn.net`, `otn.samsungcloudcdn.com`), the app store and
connectivity test (`lcprd1/2`, `infolink.pavv.co.kr`), Netflix/Plex/YouTube
(`time.`), account login (`auth.samsungosp.com`) and TV Plus (`osb-ussvc`).
Today only `lcprd1/2` are actually blocked by anything. The other entries
protect against future changes to the lists.

**Watch out for the default config:** the app ships with a sample config that
maps `0.0.0.0/0` to an "everyone else" group (StevenBlack, a `^ads\.` regex and
`example.com`). Replace that config right after install, or you get LAN-wide
side effects.

## 7. Install + configure (repeat for .200, .40, .42)

```bash
/usr/bin/curl -s -X POST "http://$ip:5380/api/apps/downloadAndInstall?token=$t" \
  --data-urlencode "name=Advanced Blocking" \
  --data-urlencode "url=https://download.technitium.com/dns/apps/AdvancedBlockingApp-v11.1.zip"
/usr/bin/curl -s -X POST "http://$ip:5380/api/apps/config/set?token=$t" \
  --data-urlencode "name=Advanced Blocking" --data-urlencode "config@$S/advblock.json"
/usr/bin/curl -s "http://$ip:5380/api/apps/config/get?token=$t&name=Advanced%20Blocking" \
  | jq -r .response.config | jq -c .networkGroupMap
```

(The store URL came from `/api/apps/listStoreApps`.) No service restart was
needed.

## 8. Verification

You can't send queries from the TV's IP, so for testing this host
(`192.168.50.20`) was **temporarily** added to `networkGroupMap` as
`samsung-tv` on all three nodes. After the dig tests the production config was
pushed back:

```bash
jq '.networkGroupMap["192.168.50.20"]="samsung-tv"' advblock.json > advblock_test.json
# config/set advblock_test.json on all 3; sleep 20; dig tests; then config/set advblock.json again
```

The results were identical on .200, .40 and .42 (which also proves the arm
nodes' Podman containers see the real client IP):

| Domain | As TV | Source |
|---|---|---|
| acr-eu-prd.samsungcloud.tv | NXDOMAIN | new list (was resolving before) |
| osb.samsungqbe.com | NXDOMAIN | new list (was resolving before) |
| devicelog.samsungcloudsolution.net | NXDOMAIN | new list |
| samsungtvads.com, ads.samsungads.com, log-ingestion.samsungacr.com | 0.0.0.0 | already blocked globally |
| lcprd1.samsungcloudsolution.net | resolves (34.160.212.185) | now allowed for TV (still 0.0.0.0 for others) |
| otnprd10.samsungcloudsolution.net, www.samsungotn.net, time.samsungcloudsolution.com, osb-apps-v2.samsungqbe.com | resolve | |
| Samsung account host (auth subdomain of samsungosp.com) | resolves | |
| netflix.com, api-global.netflix.com, nflxvideo.net, occ-0-58-64.1.nflxso.net | resolve | |

TXT blocking report:
`source=advanced-blocking-app; group=samsung-tv; blockListUrl=...native.samsung-onlydomains.txt; domain=acr-eu-prd.samsungcloud.tv`

After reverting: non-TV clients resolve `acr-eu-prd.samsungcloud.tv` normally,
`lcprd1` is still 0.0.0.0 for them, and the global `blockListUrls` counts are
unchanged (5 on .200, 4 on .40 and .42).

## Risks / open items

- **The TV can bypass Technitium.** DHCP gives it `1.1.1.1` and `1.0.0.1` as the
  4th and 5th DNS servers, and nothing redirects or blocks outbound port 53/853.
  Samsung TVs are also reported to fall back to hardcoded public resolvers.
  Possible fixes, **not applied** because they need explicit approval:
  - Remove the public resolvers from DHCP. This is LAN-wide, but `.40` and `.42`
    already give redundancy. Or give the TV its own DHCP option 6 through a
    static lease.
  - Add a MikroTik `dstnat` rule for `src-address=192.168.50.31 protocol=udp/tcp
    dst-port=53` to `192.168.50.200`, and/or drop TCP/853 from the TV.
- `lcprd1/2` were blocked globally before this change. If the TV's app store or
  Smart Hub test was failing, it should start working now.
- Undo: uninstall "Advanced Blocking" on each node (`/api/apps/uninstall?name=Advanced%20Blocking`),
  or remove the `192.168.50.31` mapping.
- If the TV gets a different IP, the mapping stops applying. Consider a static
  DHCP lease for `64:E7:D8:EC:38:EE`.

## References

- [HaGeZi dns-blocklists README (formats; Wildcard Domains for TechnitiumDNS)](https://github.com/hagezi/dns-blocklists)
- [HaGeZi native.samsung wildcard list](https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/wildcard/native.samsung-onlydomains.txt)
- [Perflyst PiHoleBlocklist SmartTV.txt](https://raw.githubusercontent.com/Perflyst/PiHoleBlocklist/master/SmartTV.txt)
- [Perflyst issue #60 (otn.samsungcloudcdn.com breaks updates)](https://github.com/Perflyst/PiHoleBlocklist/issues/60)
- [Pi-hole Discourse: Samsung TV dashboard / lcprd1 whitelist for app store](https://discourse.pi-hole.net/t/this-is-what-your-dashboard-looks-like-with-a-samsung-tv/3165)
- [NextDNS community thread listing HaGeZi Samsung tracker list](https://help.nextdns.io/t/p8ykkx2/add-extra-hagezi-and-shadowwhisperer-lists)
- [Technitium AdvancedBlockingApp sample dnsApp.config](https://github.com/TechnitiumSoftware/DnsServer/blob/master/Apps/AdvancedBlockingApp/dnsApp.config)
- [Technitium DnsServer.cs (allow-before-block precedence)](https://github.com/TechnitiumSoftware/DnsServer/blob/master/DnsServerCore/Dns/DnsServer.cs)
