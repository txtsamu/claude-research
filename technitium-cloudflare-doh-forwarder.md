---
type: how-to
tags: [technitium, dns, doh, dns-over-https, cloudflare, google, quad9, home, privacy, forwarder]
created: 2026-09-24
last_verified: 2026-09-24
status: current
---

# Switch Technitium (on `home`) to Cloudflare DNS-over-HTTPS forwarders

Changed the primary Technitium DNS server's upstream from **plain UDP to
1.1.1.1/1.0.0.1** over to **Cloudflare DoH** (`https://cloudflare-dns.com/dns-query`),
so all recursive/forwarded lookups leave the network encrypted instead of as
cleartext UDP/53 the ISP (or anyone on-path) can read or tamper with.

- **Server**: Technitium DNS Server v15.4.0 on **`home`** (`192.168.50.200`,
  NixOS, systemd unit `technitium-dns-server`, web/API on `:5380`). This is the
  primary that `arm1`/`arm3`/`vpz` replicate the `.lan` zone from
  (see [[technitium-lan-secondary-zone-real-replication]]).
- **Before**: `forwarders=[1.1.1.1, 1.0.0.1]`, `forwarderProtocol=Udp`.
- **After**: `forwarderProtocol=Https` with **three providers over DoH** for
  redundancy (all with bootstrap IPs):
  - Cloudflare — `https://cloudflare-dns.com/dns-query` (`1.1.1.1`, `1.0.0.1`)
  - Google — `https://dns.google/dns-query` (`8.8.8.8`, `8.8.4.4`)
  - Quad9 — `https://dns.quad9.net/dns-query` (`9.9.9.9`, `149.112.112.112`)

  DNSSEC validation was already on and stays on (all three support it).

**Forwarder behavior (so "backup" is understood correctly):** Technitium does
*not* treat the list as strict primary→secondary. It forwards concurrently and
uses the fastest responder, dropping ones that error/time out — so the extra
providers are live redundancy (if Cloudflare is unreachable, Google/Quad9 answer
seamlessly), but individual queries can go to any provider. All three are
Cloudflare/Google/Quad9's privacy-oriented resolvers; pick a smaller list if you
want to minimize how many providers see your traffic.

## GUI method (what the docs describe)

Web console → **Settings → Proxy & Forwarders** → set **Forwarder Protocol** to
**DNS-over-HTTPS (DoH)** → set forwarders to
`https://cloudflare-dns.com/dns-query (1.1.1.1)` and
`https://cloudflare-dns.com/dns-query (1.0.0.1)` → **Save**.

The `(1.1.1.1)` / `(1.0.0.1)` in parentheses is the **bootstrap IP**: Technitium
connects TLS straight to that IP (SNI `cloudflare-dns.com`) instead of needing to
resolve the DoH hostname first — avoids the chicken-and-egg where you need DNS to
find your DNS server.

## API method (what was actually run, headless)

The admin password on `home` is agenix-managed and readable only as root
(see [[agenix-technitium-admin-password-fix]] for why it's the *live* value):

```bash
# on home, get the live admin password and a session token
PW=$(sudo sed -n 's/^DNS_SERVER_ADMIN_PASSWORD=//p' /run/agenix/technitium-admin-password)
TOKEN=$(curl -s "http://127.0.0.1:5380/api/user/login?user=admin&pass=$(python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))' "$PW")&includeInfo=false" \
        | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])')

# apply: protocol=Https + all provider DoH URLs, comma-separated, URL-encoded whole
LIST="https://cloudflare-dns.com/dns-query (1.1.1.1), https://cloudflare-dns.com/dns-query (1.0.0.1), https://dns.google/dns-query (8.8.8.8), https://dns.google/dns-query (8.8.4.4), https://dns.quad9.net/dns-query (9.9.9.9), https://dns.quad9.net/dns-query (149.112.112.112)"
FWD=$(python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))' "$LIST")
curl -s "http://127.0.0.1:5380/api/settings/set?token=$TOKEN&forwarderProtocol=Https&forwarders=$FWD"
# -> {"status":"ok", ... "forwarderProtocol":"Https", "forwarders":[6 entries]}
```

Notes / gotchas:
- **URL-encode the forwarders string** — it contains `/`, spaces, and `()`.
  Comma-separate multiple forwarders inside the one `forwarders=` param.
- `/api/settings/set` is a partial update — passing only `forwarderProtocol` and
  `forwarders` leaves everything else (DNSSEC, blocklists, zones) untouched.
- `dig` is **not installed on `home`** (minimal NixOS) — test from another host
  (`dig @192.168.50.200 ...`) or use Technitium's own
  `/api/dnsClient/resolve?...&server=this-server&...`.

## Verification (all passed)

```bash
# from a host that has dig, external names still resolve (now via DoH):
dig @192.168.50.200 cloudflare.com +short   # -> 104.16.132.229
dig @192.168.50.200 google.com +short       # -> ok
dig @192.168.50.200 dns.lan +short          # -> 192.168.50.200  (.lan zone still authoritative)

# PROOF it's really encrypted DoH, not a silent UDP fallback:
# on home, there are live TLS sessions to every provider on 443:
sudo ss -tnp | grep :443 | grep DnsServer
#   1.1.1.1:443  1.0.0.1:443  8.8.8.8:443  8.8.4.4:443  9.9.9.9:443  149.112.112.112:443
```
Technitium does **not** silently fall back to UDP if DoH fails — resolution would
break outright — so working resolution + the two persistent `:443` sessions
together confirm the DoH path is genuinely in use. No forwarder/DoH errors in the
day's log.

## Not done (offer): the backup resolvers still use UDP

Only `home` (`.200`) was switched. The other Technitium instances that clients
fail over to per the MikroTik DHCP list — `arm3` (`192.168.50.42`), `arm1`
(`192.168.50.40`), and `vpz` — are independent resolvers still forwarding over
plain UDP. For consistent privacy, apply the same `settings/set` call to each
(each has its own admin login). Their `.lan` **zone** replication is unaffected
either way (that's AXFR/NOTIFY, separate from the recursive forwarder).

## References

- [Setup DNS-over-HTTPS on Technitium with Cloudflare — ambient_node](https://ambientnode.uk/setting-up-dns-over-https-on-technitium-with-cloudflare)
- [Technitium Blog: Configuring DNS Server For Privacy & Security](https://blog.technitium.com/2018/06/configuring-dns-server-for-privacy.html)
- [Technitium Blog: Configuring DNS-over-TLS and DNS-over-HTTPS with any DNS Server](https://blog.technitium.com/2018/12/configuring-dns-over-tls-and-dns-over.html)
- [Use a combination of Cloudflare and Google DNS forwarders — DnsServer issue #910](https://github.com/TechnitiumSoftware/DnsServer/issues/910)
