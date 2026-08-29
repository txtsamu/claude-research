---
type: how-to
tags: [mikrotik, routeros, openvpn, wireguard, cloudflare-warp, digitalocean, isp, dpi, vpn]
created: 2026-08-28
last_verified: 2026-08-29
status: current
---

# Site-to-site VPN from MikroTik to a VPS, when the ISP actively interferes with VPN traffic

## Goal

Remote access into the home LAN from outside, using a small DigitalOcean VPS
as the reachable rendezvous point (the MikroTik itself has no usable public
IP — see the double-NAT doc). Ended up needing three attempts before landing
on something that actually works.

## Attempt 1: WireGuard — dead on arrival

RouterOS 7 has native WireGuard (`/interface wireguard`), no packages needed.
Set up a straightforward site-to-site tunnel: MikroTik as client-role peer,
VPS running `wg0` as the fixed endpoint.

Handshake never completed — `tx` counter climbing on the MikroTik side,
`rx` always zero, and `wg show ... dump` on the VPS showed `endpoint: (none)`
the entire time, meaning the kernel WireGuard module never even processed a
valid packet from the client. Tried moving the listen port from the default
`51820` to `443/udp` (in case it was a simple port blacklist) — no change.

**Confirmed it wasn't WireGuard-specific**: stood up a plain `nc -u -l` raw
UDP listener on the VPS (no WireGuard involved at all) and sent a UDP packet
from the home network. Also silently vanished — `Connection timed out`.
Conclusion: this ISP blocks/drops non-standard UDP outbound almost entirely,
regardless of protocol. Not fixable by changing WireGuard's config.

**Gotcha when testing this kind of thing over SSH:** background a listener with
`nohup ... & disown`, not just `cmd &`, inside a *non-interactive* SSH
command — the remote shell session ending (which happens as soon as the SSH
command returns) kills backgrounded children that aren't explicitly detached
first. Cost one wasted test cycle before catching it.

WireGuard interfaces disabled on both ends after this, not deleted, in case
useful later.

## Attempt 2: OpenVPN over TCP/443 direct — also failed, differently

Since TCP clearly worked on this network (SSH, HTTPS all fine), pivoted to
OpenVPN (`tcp-server` mode, port 443) as a TLS-wrapped alternative. Built with
`easy-rsa` (CA + server + client certs), RouterOS's native
`/interface ovpn-client`.

**Gotcha — Debian's `openvpn-server@` systemd unit sandboxes `/root` away**
(`ProtectHome`). Certs generated under `/root/easy-rsa/pki/...` gave
`No such file or directory` even though they existed and root owned the
process. Fix: copy the cert/key files into `/etc/openvpn/server/` and
reference them from there instead.

**Gotcha — `easy-rsa` prompts need `EASYRSA_BATCH=1`** for non-interactive use
(`gen-req`, `sign-req`); piping a throwaway answer into the one CN prompt
works for `build-ca` but not reliably for the rest.

Got a TCP connection through this time, but the OpenVPN handshake corrupted
immediately: `Bad encapsulated packet length from peer (5635) ... this
condition could also indicate a possible active attack on the TCP link`.
The real tell was the **source IP on the VPS end changing on every single
retry** (confirmed by re-checking `journalctl -u openvpn-server@server`
across several reconnect attempts) despite the client's actual public IP
being stable. That's not a dropped connection — it's a transparent
proxy/MITM box on the ISP's network intercepting and re-terminating the TCP
connection from a rotating pool of IPs, then mangling the payload because it
doesn't recognize OpenVPN's handshake as ordinary HTTPS. No TLS-version or
cipher tweak fixes this; the corruption happens before OpenVPN ever sees
clean bytes.

## Attempt 3: same OpenVPN setup, relayed through an existing Cloudflare WARP client — worked

The LAN already had a box running the Cloudflare WARP client (`warp-cli`,
connected, healthy) for a different, narrower purpose (bypassing this same
ISP's DPI for a couple of specific apps). Its own egress already rides
Cloudflare's network, so anything relayed *through* it should look like
ordinary WARP traffic to the ISP instead of raw/recognizable VPN traffic.

Set up a simple persistent TCP relay on that box (`socat`, wrapped in a
systemd unit so it survives reboot):

```
[Service]
ExecStart=/usr/bin/socat TCP-LISTEN:<relay-port>,bind=<lan-ip>,fork,reuseaddr TCP:<vps-ip>:443
Restart=always
```

Pointed the MikroTik's `ovpn-client` `connect-to`/`port` at the relay
(LAN IP + relay port) instead of the VPS directly. TLS/control-channel
handshake succeeded immediately — confirmed by the VPS-side connection
source IP now being a genuine Cloudflare address instead of a rotating ISP
proxy IP.

### Remaining compatibility gotchas (RouterOS OpenVPN client ≠ full parity with upstream OpenVPN)

Getting from "TCP connects cleanly" to "tunnel actually up" needed several
more fixes, each with its own error message:

1. **`Bad encapsulated packet length` even over the clean WARP path at
   first** — RouterOS's OpenVPN client had trouble with the server's default
   TLS 1.3 control channel. Fix: `tls-version-max 1.2` in `server.conf`.
2. **`AUTH_FAILED, Data channel cipher negotiation failed (no shared
   cipher)`** — server's modern `data-ciphers` default (AES-GCM/ChaCha20)
   has no overlap with RouterOS's default cipher choice. Fix: explicit
   `cipher=aes256-cbc` on the MikroTik side (**not** `aes256` — RouterOS
   rejects that value; the exact accepted enum string needs the `-cbc`
   suffix, confirmed by brute-forcing a few variants against the syntax
   error), plus `data-ciphers AES-256-GCM:AES-256-CBC` /
   `data-ciphers-fallback AES-256-CBC` on the server so CBC is actually
   offered, not just GCM.
3. **`unsupported auth digest SHA1`** — once cipher fell back to CBC (a
   non-AEAD mode), it needs a separate HMAC auth digest, and the two ends
   picked different defaults. Fix: explicit `auth SHA256` on both the server
   config and the RouterOS client (`auth=sha256`).
4. **Skipped `tls-crypt`/`tls-auth` entirely** rather than debugging RouterOS
   support for it — not worth the risk of another silent incompatibility on
   top of everything else; standard TLS client-cert auth was already solid
   enough for the threat model here.

Final working RouterOS `ovpn-client` config shape:
```
protocol=tcp
connect-to=<relay-lan-ip>
port=<relay-port>
mode=ip
certificate=<client-cert>
cipher=aes256-cbc
auth=sha256
add-default-route=no
```

And the matching pieces on the VPS side: `route <lan-subnet> <mask>` in
`server.conf` plus a `client-config-dir` entry with
`iroute <lan-subnet> <mask>` for the specific client, so the VPS knows to
route that subnet back through this one tunnel client rather than just
handing out its own `/24`.

### Firewall: don't forget the forward-chain rule for the new tunnel interface

The default-deny `forward` chain (see the hardening-audit doc) blocks the new
tunnel interface's traffic to the LAN by default — needs its own explicit
accept, placed *before* the catch-all drop:
```
/ip firewall filter add chain=forward in-interface=<ovpn-if> out-interface=<lan-bridge> action=accept place-before=[find comment="Drop other forward (default deny)"]
```

## Verified end to end

Pinged the tunnel endpoints both directions (0% loss, ~20ms — geographically
consistent with the VPS's region), then confirmed actual LAN reachability
specifically (not just the tunnel interface) by reaching a *different* LAN
host's SSH port from the VPS — pinging the router itself doesn't prove much
since ICMP is allowed globally regardless of interface on this router's
existing ruleset.

## Key lesson

"My ISP blocks VPNs" can mean at least three completely different things,
each needing a different fix:
1. Blocks the *protocol* outright (raw UDP here) → no config tweak helps,
   need a different protocol.
2. Actively *interferes* with recognizable VPN handshakes on an otherwise-open
   protocol/port (the MITM behavior here) → wrapping the traffic in something
   the ISP already trusts (Cloudflare WARP, in this case) sidesteps it
   without needing a different protocol.
3. Isn't actually the ISP at all — see the double-NAT/DMZ doc, where a
   separate, unrelated block turned out to be the destination's own cloud
   firewall.

Rotating source IPs on retries and `timeout` vs. `connection refused` vs.
`corrupted handshake` are the cheap, distinguishing signals between these.

## Update 2026-08-29: the "ISP blocks all raw UDP" theory doesn't fully hold up

The VPS got migrated to a different provider/host a day later. Rebuilt plain
WireGuard from scratch against the new host — same MikroTik, same
`/interface wireguard` config shape, default port `51820`, no relay, no
tricks — and it **worked immediately**: real handshake, 0% packet loss
bidirectional, full LAN reachability confirmed through the tunnel from the
far end.

This directly contradicts the "ISP blocks non-standard UDP almost entirely"
conclusion from Attempt 1 above, which was based on real evidence at the
time (WireGuard failing on two different ports, *and* a protocol-agnostic
raw `nc -u` UDP test failing the same way, against the original VPS). That
evidence wasn't wrong — the underlying interpretation of *why* was
incomplete.

**Revised understanding:** whatever was blocking UDP was more likely
specific to the *original* VPS's provider/IP range/ASN reputation than a
blanket "this ISP drops all non-standard UDP" policy. Possible mechanisms
(not confirmed, just plausible): that provider/ASN was already on some
threat-intel or abuse-reputation blocklist the ISP subscribes to, or
something about that specific IP had accumulated a bad reputation before
this session ever touched it. The MITM/handshake-corruption behavior
against direct OpenVPN/TCP (also in this doc, above) still stands as
independently confirmed on its own terms — that was a live, observed
active-interception behavior, not just an absence of a response, and
nothing has since contradicted it.

**Practical takeaway:** "my ISP blocks protocol X" conclusions drawn against
a single destination/provider don't necessarily generalize — worth
re-testing against a different provider/IP range before fully trusting a
protocol-level verdict, especially for UDP where blocking is cheap for a
network to apply selectively (by destination reputation) rather than
universally.

The WARP-relay setup built in this doc still stands as a working, hardened
fallback — general "wrap it in traffic the ISP already trusts" is a
robust pattern regardless of whether the direct path happens to work for
a given VPS. But it's no longer accurate to say direct WireGuard *always*
fails on this connection — it depends on the destination.
