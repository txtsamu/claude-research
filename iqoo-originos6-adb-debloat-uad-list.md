---
type: how-to
tags: [android, iqoo, vivo, originos, adb, debloat, uad-ng, wireless-debugging, technitium, advanced-blocking, hagezi, mikrotik]
created: 2026-10-19
last_verified: 2026-10-19
status: current
---

# iQOO (OriginOS 6) debloat over wireless ADB, using the UAD-ng list

Debloated an iQOO phone without root: wireless ADB from the fedora desktop, cross-referenced installed packages against the Universal Android Debloater (next-gen) list, then `pm uninstall --user 0` with a `disable-user` fallback.

**Device:** iQOO model `I2512`, OriginOS 6, Android 16, region `ID` (Indonesia). Phone at `192.168.50.26` on the LAN.

## Result

- 41 packages targeted, **32 uninstalled for user 0**, **1 disabled** (`com.vivo.magazine`), **8 refused** by vivo (`DELETE_FAILED_USER_RESTRICTED`, and `disable-user` also throws a SecurityException).
- Refused (still installed and enabled): `com.bbk.iqoo.logsystem`, `com.vivo.appstore`, `com.vivo.hiboard`, `com.vivo.globalsearch`, `com.vivo.cota`, `com.iqoo.website`, `com.bbk.cloud`, `com.vivo.assistant`. OriginOS protects these at the framework level, so plain ADB can't remove or disable them. This matches forum reports that "generic ADB commands don't work with most vivo apps".

## Steps

### 1. Connect over wireless debugging (pairing needed first)

`adb connect` to the wireless debugging port failed with `failed to connect` even though the TCP port was open (`bash -c '</dev/tcp/192.168.50.26/43831'` succeeded). On Android 11+ a host must be **paired** first: Developer options → Wireless debugging → *Pair device with pairing code* shows a code and a **different** port.

```bash
adb pair 192.168.50.26:<pairing-port> <6-digit-code>
adb connect 192.168.50.26:43831      # the main wireless debugging port
adb devices -l                       # -> device product:I2512 model:I2512
```

The connect port changes whenever wireless debugging is toggled, so re-read it from the phone each session. Pairing is remembered.

### 2. Device info and package inventory

```bash
D=192.168.50.26:43831
adb -s $D shell getprop ro.build.version.release        # 16
adb -s $D shell getprop ro.vivo.os.build.display.id     # OriginOS 6
adb -s $D shell getprop ro.product.country.region       # ID
adb -s $D shell pm list packages -s | sed 's/package://' | sort > system.txt   # 392
adb -s $D shell pm list packages -3 | sed 's/package://' | sort > user.txt     # 202
adb -s $D shell pm list packages -d | sed 's/package://' | sort > disabled.txt
adb -s $D shell pm list packages -3 -i     # installer per user app
```

`-3 -i` showed every "user" app came from `com.android.vending` (Play Store), so the user had installed them. The exceptions were Facebook and TikTok (`com.google.android.packageinstaller`), which may be preloads. That's why UAD's "Recommended" hits on user apps (WhatsApp, Instagram, Office…) were **not** treated as targets.

### 3. Cross-reference against UAD-ng

```bash
curl -sL -o uad_lists.json \
  https://raw.githubusercontent.com/Universal-Debloater-Alliance/universal-android-debloater-next-generation/main/resources/assets/uad_lists.json
```

The JSON is a dict keyed by package name, with `list` (Aosp/Google/Oem/Misc/Carrier), `removal` (Recommended/Advanced/Expert/Unsafe) and `description` fields. A small `python3 -I` script grouped every installed package by `(removal, list)` and printed the vivo/bbk/iqoo system packages UAD doesn't know about. OriginOS 6 adds about 40 of these, such as `com.vivo.ai.agent`, `com.vivo.cardstore` and `com.vivo.connbase*`. UAD had 161 vivo/iQOO entries in total.

### 4. Pick targets (judgment on top of UAD)

The user chose four groups:

- **Ads, telemetry and vivo services:** `com.bbk.iqoo.logsystem com.vivo.nps com.android.bbklog com.vivo.magazine com.vivo.hybrid com.vivo.appstore com.vivo.browser com.vivo.hiboard com.vivo.globalsearch com.vivo.cota com.iqoo.website com.bbk.cloud com.vivo.unionpay com.vivo.assistant com.vivo.smartanswer android.autoinstalls.config.vivo.devices com.baidu.map.location com.tencent.soter.soterserver`
- **Factory test apps:** `com.goodix com.goodix.deltadiff com.vivo.fingerprintvit com.touchscreen.vtstouchscreencheck com.vivotouchscreen.synadeltadiff com.vos.user.vit com.vos.as.vit`
- **Google ads and telemetry:** `com.google.android.adservices.api com.google.android.federatedcompute com.google.android.ondevicepersonalization.services com.google.android.feedback com.google.android.gms.location.history com.google.android.apps.tachyon com.google.ambient.streaming com.google.ar.core com.google.android.onetimeinitializer com.android.egg com.android.traceur`
- **Qualcomm telemetry:** `com.qualcomm.qti.qms.service.connectionsecurity com.qualcomm.qti.qms.service.trustzoneaccess com.qualcomm.qti.devicestatisticsservice com.qualcomm.qti.server.qtiwifi com.qualcomm.qti.ridemodeaudio`

**Deliberately kept, even though UAD rates some of them "Recommended" (they break things on vivo):** `com.vivo.upslide` (gesture navigation), `com.vivo.safecenter` (vivo's permission manager), `com.vivo.sps` and `com.vivo.daemonService` (process management), `com.bbk.theme`, `com.vivo.setupwizard`, `com.bbk.account`, `com.bbk.updater`, `com.vivo.pushservice`, `com.vivo.vibrator4d`, `com.vivo.abe`/`com.vivo.audiofx`, and everything for fingerprint, face unlock, lockscreen or connectivity.

**Smart Remote (IR blaster app) is `com.vivo.vhome`.** UAD labels it "Smart Remote" and rates it Recommended. Keep it if you use the TV remote.

### 5. Remove

Gotcha: in a `while read` loop, `adb shell` eats stdin, so the loop stops after the first package. Redirect with `</dev/null`.

```bash
while read -r p; do
  r=$(adb -s $D shell pm uninstall -k --user 0 "$p" </dev/null 2>&1 | tr -d '\r')
  if [ "$r" != "Success" ]; then
    r2=$(adb -s $D shell pm disable-user --user 0 "$p" </dev/null 2>&1 | tr -d '\r' | tail -1)
    r="$r | disable: $r2"
  fi
  echo "$p => $r"
done < remove.txt | tee removal_log.txt
```

The user ran this themselves with `! bash debloat.sh`, because Claude Code's auto-mode classifier blocks `pm uninstall` loops as irreversible deletion.

## Restore

`pm uninstall --user 0` keeps the APK on `/system`, so nothing here needs a factory reset:

```bash
adb shell cmd package install-existing <pkg>   # uninstalled ones
adb shell pm enable <pkg>                      # com.vivo.magazine (disabled)
```

OTA updates can bring removed packages back. Re-run the loop after major updates.

## Background restriction on the 8 protected packages (done 2026-10-19)

```bash
for p in com.bbk.iqoo.logsystem com.vivo.appstore com.vivo.hiboard com.vivo.globalsearch \
         com.vivo.cota com.iqoo.website com.bbk.cloud com.vivo.assistant; do
  adb -s $D shell cmd appops set $p RUN_ANY_IN_BACKGROUND ignore </dev/null
  adb -s $D shell cmd appops set $p RUN_IN_BACKGROUND ignore </dev/null
  adb -s $D shell am set-standby-bucket $p restricted </dev/null
  adb -s $D shell am force-stop $p </dev/null
done
# verify
adb -s $D shell cmd appops get <pkg> | grep IN_BACKGROUND
adb -s $D shell am get-standby-bucket <pkg>   # 5=exempted 10=active 45=restricted
adb -s $D shell pidof <pkg>
```

Outcome:
- **Appops `ignore` stuck on all 8.** OriginOS didn't reject them.
- **Standby bucket `restricted` (45) only stuck on `com.iqoo.website`.** The rest silently stayed at 5 (exempted: appstore, cota, bbk.cloud) or 10 (active: logsystem, hiboard, globalsearch, assistant). vivo exempts its own system apps from App Standby.
- **Processes that came back right after force-stop:** `com.bbk.iqoo.logsystem`, `com.vivo.globalsearch` and `com.vivo.assistant`. They're persistent or bound by the system/launcher, so appops can't keep them stopped. The other 5 stayed stopped.
- Undo: `cmd appops set <pkg> RUN_ANY_IN_BACKGROUND allow` (and `RUN_IN_BACKGROUND allow`), plus `am set-standby-bucket <pkg> active`.

The 3 that keep running are handled at the DNS level instead (next section).

**Gotcha: don't restrict `com.vivo.assistant`.** It drives OriginOS's **status bar music capsule** (the Origin Island-style media pill). After it was background-restricted and force-stopped, the capsule disappeared while music played (BitChord had a normal MediaStyle notification and an active session, so the player wasn't at fault). Removing the restriction fixed it:
```bash
adb -s $D shell cmd appops set com.vivo.assistant RUN_ANY_IN_BACKGROUND allow
adb -s $D shell cmd appops set com.vivo.assistant RUN_IN_BACKGROUND allow
adb -s $D shell am set-standby-bucket com.vivo.assistant active
```
After this the user paused and replayed music (and/or rebooted) and the capsule came back. The package stayed `stopped=true` from the force-stop. Its only MAIN activity (`.ui.GuideActivity`) isn't exported, so `am start`/`monkey` can't clear the flag over ADB. It made no difference here. Diagnosing from logs wasn't possible: vivo suppresses SystemUI/app logcat output, and `com.android.bbklog` had already been removed. The DNS block still covers its telemetry. So **7** packages stay background-restricted.

## DNS-level block: phone-only Technitium group (done 2026-10-19)

This uses the same mechanism as `technitium-samsung-tv-ad-telemetry-block-advanced-blocking.md`: an extra **Advanced Blocking** group, scoped to the phone's IP only, on all three LAN nodes (.200, .40, .42).

- The phone has Private DNS **off** (`settings get global private_dns_mode` returns `off`) and gets `192.168.50.200, .42, .40, 1.1.1.1, 1.0.0.1` from DHCP (`dumpsys connectivity | grep DnsAddresses`).
- List: **HaGeZi `native.vivo`** (wildcard format, 244 domains, mostly `*.vivoglobal.com` stats SDK, adlog, appstore analytics and per-region cota). URL: `https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/wildcard/native.vivo-onlydomains.txt`
- The list also includes functional hosts, so the group allowlists the Asia-region ones: `asia-timesync` (clock), `asia-st-exappupgrade` and `cname-asia-st-exappupgrade` (updates for vivo system apps, e.g. Smart Remote), `asia-album-api` (Gallery) and `asia-romsp-unifyconfig` (ROM config). OTA (`com.bbk.updater`) has no Asia `sysupgrade` entry in the list, so it isn't affected.
- Many vivo ad domains (`adsdk.vivo.com.cn`, `asia-stsdk`…) were **already blocked globally** by blocklistproject ads. The new group adds the rest for the phone only.

Credentials gotcha: `/run/agenix/technitium-admin-password` on home is an **env file** (`DNS_SERVER_ADMIN_PASSWORD=...`), not a bare password. Logging in with the whole line returns `Invalid username or password`.

```bash
PW=$(ssh home 'sudo cat /run/agenix/technitium-admin-password' | sed -n 's/^DNS_SERVER_ADMIN_PASSWORD=//p')
# per node: login -> token, back up current config, merge, set
/usr/bin/curl -s "http://$ip:5380/api/apps/config/get?token=$t&name=Advanced%20Blocking" | jq -r .response.config > advblock_before_$ip.json
jq --slurpfile g iqoo_group.json '.networkGroupMap["192.168.50.26"]="iqoo-phone"
   | .groups = ([.groups[] | select(.name!="iqoo-phone")] + $g)' advblock_before_$ip.json > advblock_new_$ip.json
/usr/bin/curl -s -X POST "http://$ip:5380/api/apps/config/set?token=$t" \
  --data-urlencode "name=Advanced Blocking" --data-urlencode "config@advblock_new_$ip.json"
```

`iqoo_group.json` has the same shape as the samsung-tv group: `blockAsNxDomain: true`, the HaGeZi URL in `blockListUrls`, and the 5 hosts above in `allowed`. **Merge into the existing config; don't replace it.** The samsung-tv group and the `.200`-only `192.168.50.1` mapping must survive.

Verification (run from the phone itself with `adb shell ping -c1 <host>`, since the phone is the real client):

| Host | Phone | This PC |
|---|---|---|
| asia-adlog / asia-cota / id-analyzer-appstore .vivoglobal.com | `unknown host` (NXDOMAIN) | asia-cota resolves (177.0.132.97), so other clients aren't affected |
| asia-stsdk.vivoglobal.com, adsdk.vivo.com.cn | 127.0.0.1 | 0.0.0.0 (global blocklistproject ads) |
| asia-timesync, asia-st-exappupgrade, asia-album-api | resolve | |
| google.com | resolves | |

See the next section for the static lease and the 1.1.1.1 bypass fix.

## Static lease + forced DNS redirect on the MikroTik (applied 2026-10-19)

Same pattern as the TV (`technitium-samsung-tv-ad-telemetry-block-advanced-blocking.md` §9), with one difference: **the phone is redirected to `.40`, not `.200`.** Redirected queries reach Technitium from `192.168.50.1` (hairpin masquerade), and on `.200` that IP is already mapped to `samsung-tv`. So `.40` alone gets `"192.168.50.1": "iqoo-phone"`, and each device's redirected traffic lands on its own node. This is safe because the router uses DoH for its own lookups and doesn't query `.40`.

```bash
# Technitium .40 only (config backed up first as advblock_pre_redirect_192.168.50.40.json)
jq '.networkGroupMap["192.168.50.1"]="iqoo-phone"' advblock_pre_redirect_192.168.50.40.json > advblock_redirect.json
# then apps/config/set as above
```

```routeros
/export file=pre-iqoo-dns-2026-10-19
/ip dhcp-server lease make-static [find address=192.168.50.26]
/ip dhcp-server lease set [find address=192.168.50.26] comment="iQOO I2512 phone (static, DNS redirect + phone-only vivo blocking)"
/ip firewall mangle add chain=prerouting src-address=192.168.50.26 dst-address-list=!lan-dns protocol=udp dst-port=53 connection-state=new action=mark-connection new-connection-mark=iqoo-dns-redirect passthrough=yes comment="iQOO DNS redirect mark udp"
/ip firewall mangle add chain=prerouting src-address=192.168.50.26 dst-address-list=!lan-dns protocol=tcp dst-port=53 connection-state=new action=mark-connection new-connection-mark=iqoo-dns-redirect passthrough=yes comment="iQOO DNS redirect mark tcp"
/ip firewall nat add chain=dstnat src-address=192.168.50.26 dst-address-list=!lan-dns protocol=udp dst-port=53 action=dst-nat to-addresses=192.168.50.40 comment="iQOO DNS redirect udp -> Technitium .40"
/ip firewall nat add chain=dstnat src-address=192.168.50.26 dst-address-list=!lan-dns protocol=tcp dst-port=53 action=dst-nat to-addresses=192.168.50.40 comment="iQOO DNS redirect tcp -> Technitium .40"
/ip firewall nat add chain=srcnat connection-mark=iqoo-dns-redirect action=masquerade comment="iQOO DNS redirect hairpin"
```

Notes:
- The `lan-dns` address list (.200/.40/.42) already existed from the TV setup.
- The phone's MAC is an Android **randomized** MAC (`client-id 1:32:2e:...`, locally administered). It stays the same for this SSID unless the Wi-Fi privacy setting is changed to "non-persistent" or the network is forgotten and re-added. Either of those would break the static lease.
- The new rules showed the `I` flag briefly, then it cleared, the same as with the TV.
- `nslookup` is not on the phone (`toybox` doesn't have it), so it can't test the redirect itself.

Verification: this PC (`192.168.50.20`) got temporary copies of the udp mangle+dstnat rules (comment `TEMP test iqoo`) to `.40`, which were removed straight after:
```
dig @1.1.1.1 asia-cota.vivoglobal.com            -> NXDOMAIN
  TXT: source=advanced-blocking-app; group=iqoo-phone; ... domain=asia-cota.vivoglobal.com
dig @1.1.1.1 id-analyzer-appstore.vivoglobal.com -> NXDOMAIN
dig @1.1.1.1 asia-timesync.vivoglobal.com        -> NOERROR (allowlisted)
dig @1.1.1.1 google.com                          -> NOERROR
# after removing TEMP rules: real 1.1.1.1 answer again (NOERROR, no Technitium TXT)
```
A `:foreach ... /ip firewall connection remove` one-liner for clearing test conntrack entries hit a RouterOS `syntax error` over ssh. It wasn't needed: the UDP entries had already expired by the time of the re-check.

Open items / undo:
- Not covered: DoT (TCP/853) or DoH from the phone. Private DNS is currently `off`. If it's ever turned on, it bypasses all of this.
- Undo: `/ip firewall nat remove [find comment~"iQOO DNS"]`, `/ip firewall mangle remove [find comment~"iQOO DNS"]`, `/ip dhcp-server lease make-dynamic [find address=192.168.50.26]`. In Technitium, remove `192.168.50.26` from every node's map, remove `192.168.50.1` from the map on `.40` only, and delete the `iqoo-phone` group.

## References

- [UAD-ng (Universal Android Debloater next-gen) repo, source of `uad_lists.json`](https://github.com/Universal-Debloater-Alliance/universal-android-debloater-next-generation)
- [Universal Android Debloater (original)](https://github.com/0x192/universal-android-debloater)
- [TechEnclave: FuntouchOS 14 debloat](https://techenclave.com/t/funtouchos-14-debloat/272600)
- [TechEnclave: FuntouchOS 14 debloat (older thread)](https://techenclave.com/threads/funtouchos-14-debloat.224435/)
- [DroidWin: vivo bloatware removal](https://droidwin.com/?p=39836)
- [Technastic: safe-to-remove packages without root](https://technastic.com/?p=15193)
- [HaGeZi dns-blocklists (native.vivo tracker list)](https://github.com/hagezi/dns-blocklists)
- [HaGeZi native.vivo wildcard list](https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/wildcard/native.vivo-onlydomains.txt)
