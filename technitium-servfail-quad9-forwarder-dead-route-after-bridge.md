---
type: troubleshooting
tags: [technitium, dns, servfail, doh, quad9, forwarders, mikrotik, static-route, fast-com, bridge-mode]
created: 2026-10-05
last_verified: 2026-10-05
status: current
---

# Technitium returns random SERVFAIL (fast.com speed test won't start) after bridging the ONU

Follow-up to [mikrotik-pppoe-bridge-vsol-onu-plan.md](mikrotik-pppoe-bridge-vsol-onu-plan.md). Not caused by Technitium itself: stale MikroTik routes made one of its DoH forwarders unreachable.

## Symptom
- `fast.com` page loads (HTTP 200) but the speed test never starts.
- `dig <name> @192.168.50.200` gives SERVFAIL for some names (netflix.com, wikipedia.org, openai.com, the `api.fast.com` CNAME chain) and NOERROR for others (example.com, github.com, cloudflare.com), and it varies between runs.
- The same names resolve fine from `192.168.50.40`, `1.1.1.1`, `8.8.8.8`. With `dig +cd` (DNSSEC checking off) `.200` also resolved, which made it look like DNSSEC/MTU at first.
- Network path to the real API was fine: `curl --resolve api.fast.com:443:<ip> https://api.fast.com/...` returns 403 (reachable, no token).

## DNS setup as found (for reference)
- DHCP hands LAN clients `192.168.50.200, .42, .40, 1.1.1.1, 1.0.0.1`. The MikroTik resolver has `allow-remote-requests=no`, so clients never query the router; it forwards `*.lan` to `.200` via a static FWD rule and uses Cloudflare DoH itself.
- `.200` = Technitium, native NixOS service `technitium-dns-server` (process `DnsServerApp`, web UI :5380, state `/var/lib/technitium-dns-server`, logs `/var/log/technitium/dns/<date>.log`, reach it with `ssh home`). Forwarders (DoH): Cloudflare 1.1.1.1/1.0.0.1, Google 8.8.8.8/8.8.4.4, **Quad9 9.9.9.9/149.112.112.112**.
- `192.168.50.42` (in the DHCP list) does not answer DNS at all (timeout).

## Diagnosis steps (in order)
1. Compare resolvers per name: `for s in 192.168.50.200 192.168.50.40 1.1.1.1; do dig +time=3 +tries=1 <name> @$s | grep status:; done`. Only `.200` failed, intermittently.
2. Ruled out MTU: DF pings of 1480 bytes pass over `pppoe-out1`; a 1.4 KB DNS/DNSKEY reply arrives over the PPPoE path.
3. Ruled out the network path (step above with `--resolve`).
4. On the DNS host: `ssh home`, test each forwarder: `timeout 4 bash -c 'echo > /dev/tcp/<ip>/443'`. 9.9.9.9 and 149.112.112.112 **timed out**, the other four were open. `ping` agreed.
5. Technitium log: `grep -a -i -E "quad9|9\.9\.9\.9|149\.112|failed" /var/log/technitium/dns/<date>.log` showed `DnsClient failed ... request timed out for name servers [https://dns.quad9.net/dns-query (9.9.9.9), ...]`, 1331 lines on the day of the bridge versus 14 the day before.
6. On the MikroTik: `/tool traceroute 9.9.9.9 count=1` went to `192.168.1.1` (the ONU). `/ip route print where comment~"PC-backup-wan-setup"` showed `9.9.9.9/32` and `149.112.112.112/32` via `192.168.1.1` (`probe-hop-1/2`) plus a recursive `0.0.0.0/0 via 9.9.9.9` (`real-wan-default-1`).

## Root cause
Those probe routes belonged to an old backup-WAN design that pinged Quad9 through the ONU. They were harmless while the ONU routed. After the ONU became a bridge, `192.168.1.1` no longer forwards, so all Quad9 traffic (including Technitium's Quad9 DoH forwarders) black-holed. Technitium waits for timeouts when it picks a Quad9 forwarder, hence random SERVFAIL.

## Fix (reversible)
```
/ip route disable [find comment~"probe-hop-1"]
/ip route disable [find comment~"probe-hop-2"]
/ip route disable [find comment~"real-wan-default-1"]
```
Verified: 9.9.9.9 and 149.112.112.112 answer over `pppoe-out1` (~2.4 ms), `home` reaches 9.9.9.9:443, every previously failing name returned NOERROR on two rounds, and the `api.fast.com` speed-test API resolves through the normal resolver. The three routes were first disabled, then deleted once everything was confirmed working (`/ip route remove [find comment~"probe-hop-1" disabled=yes]`, same for `probe-hop-2` and `real-wan-default-1`); re-check health afterwards (pings, default route via `pppoe-out1`, `dig netflix.com @192.168.50.200`). Export after the fix: `~/nethome/backup/post-dnsfix-<ts>.rsc` (secrets, chmod 600).

## Lessons
- After changing the WAN topology, grep the old router config for the old gateway address (`192.168.1.1`) and for `/32` probe routes.
- A dead forwarder in Technitium's pool causes intermittent SERVFAIL rather than a clean failure; test each forwarder's :443 from the DNS host.
- `+cd` working is not proof of a DNSSEC problem: smaller/cached answers can hide a forwarder timeout.

## Open items
- `real-wan-default-2` (disabled, recursive via 149.112.112.112) and the PC-USB-tether backup default route (distance 10, via 192.168.50.20) are still present; the first is dead weight, the second is the intentional safety net.
- Remove or fix `192.168.50.42` in the DHCP DNS list.
- Consider dropping Quad9 from Technitium's forwarder list if it is unreliable on this ISP.

## References
No external sources; derived on-box (dig, curl, Technitium logs, RouterOS traceroute).
