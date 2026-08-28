---
type: how-to
tags: [mikrotik, routeros, firewall, security, dpi-bypass, hardening]
created: 2026-08-27
last_verified: 2026-08-28
status: current
---

# MikroTik hardening + BebasIT DPI-bypass, 2026-08-27

**Router:** MikroTik RB760iGS ("hEX S"), RouterOS 7.23.2 MIPS, gateway
192.168.50.1
**Access:** SSH with password auth (no key configured) —
`sshpass -p '<password>' ssh -o PubkeyAuthentication=no admin@192.168.50.1`.
RouterOS's CLI is not a POSIX shell: no `echo`, no `;`/`&&` chaining
between RouterOS commands the way a Linux shell allows — one command per
invocation, or use RouterOS's own scripting syntax (`:put`, `/system
script`) if chaining is needed.

---

## 1. Best-practice audit

Compared the live config against MikroTik's official IPsec docs and
community hardening checklists ([layer-x.com](https://tech.layer-x.com/mikrotik-hardening-guide-complete-security-checklist/),
[jcutrer.com](https://jcutrer.com/howto/networking/mikrotik/routeros-l2tp-ipsec-vpn-firewall-rules)).

### Already correct (no action needed)
- Firewall `input` chain default-drop policy — already blocked WAN access
  to every listening service (FTP/Telnet/WWW/API/Winbox) even before this
  pass, since no accept rule opened those ports on `ether1` and the final
  rule dropped everything else not explicitly matched. **No active
  external exposure existed at any point** — the gaps below were
  defense-in-depth, not open holes.
- FastTrack + established/related handling — correct, performance-sane.
- NAT masquerade scoped correctly (LAN 192.168.50.0/24 + VPN
  192.168.89.0/24 only, not blanket).
- DoH configured correctly (`cloudflare-dns.com/dns-query`).
- L2TP/IPsec WAN rule for the VPN service itself existed and was
  reasonably scoped.
- Neighbor discovery (CDP/LLDP/MNDP) is set to `tx-and-rx` but scoped to
  an interface-list called `static` that has **zero members** — so
  despite the mode setting, discovery isn't actually running on any
  interface. Checked, no action needed.

### Gaps found and fixed

| Issue | Fix applied |
|---|---|
| L2TP (port 1701) accepted without requiring IPsec | Added `ipsec-policy=in,ipsec` to the accept rule; added a separate logged `drop` rule for unencrypted L2TP attempts |
| No `connection-state=invalid` drop | Added to both `forward` and `input` chains |
| Unused services enabled (FTP, Telnet, WWW, unencrypted API) | Disabled all four (`/ip service disable ftp,telnet,www,api`) |
| DNS `allow-remote-requests=yes` | Set to `no` — closes open-resolver risk even though firewall already blocked WAN:53 |

### Gap found, deliberately NOT fixed
- **Default `admin` account is the only user.** Every source flags this
  first (default username = primary brute-force target). **Left
  untouched** — it's the user's daily login credential, and creating a
  replacement with a password *I* generate (rather than one they choose
  themselves) risks a lockout or hands them credentials they don't
  actually know. Safe fix path if revisited: create a new full-privilege
  user with a password the user sets themselves, confirm login works with
  it, *then* disable/rename the default `admin` — never disable the only
  working account before confirming a replacement works.
- Redundant/overlapping L2TP/IPsec input rules (rules matching UDP
  500/4500/1701 both with and without `in-interface=ether1` restriction)
  — cosmetic duplication, not a security issue, left as-is to avoid
  churn on a working VPN config.

## 2. BebasIT DPI-bypass

User suspected ISP-level DPI (deep packet inspection) interference —
common in Indonesia, where ISPs inject HTTP redirects to a government
block page (`aduankonten.id`) and/or inject TCP RST packets to kill
connections to blocked destinations. Applied the MikroTik-specific rules
from [bebasid/bebasit](https://github.com/bebasid/bebasit)
(`docs/mikrotik-tutorial.md`), **firewall rules only** — explicitly
declined the DNS-redirect portion of that guide.

```
/ip firewall filter add comment="BebasIT | Bypass DPI" chain=forward protocol=tcp in-interface=ether1 content="Location: http://lamanlabuh.aduankonten.id/" action=drop
/ip firewall filter add comment="BebasIT | Bypass DPI" chain=forward protocol=tcp in-interface=ether1 tcp-flags=rst,ack action=drop
```

- Rule 1 drops packets containing the ISP's injected redirect to the
  government block page before they reach the client.
- Rule 2 drops injected RST,ACK packets from the ISP's DPI system.
  **Caveat**: this rule is blunt — it drops *all* WAN-sourced TCP
  RST,ACK packets, not just ones identified as DPI injection. This is the
  standard trade-off for this technique (real servers closing connections
  with RST,ACK from the WAN side would also get dropped, potentially
  leaving connections to hang instead of closing cleanly). Known and
  accepted trade-off, not a bug.

### Why the DNS-redirect portion was skipped

The guide's DNS section DNAT-redirects all LAN port-53 traffic (TCP+UDP)
to BebasID's own resolvers, which would have **overridden the router's
existing DHCP-configured DNS** (192.168.50.200/warp-vm primary +
Cloudflare/AdGuard fallback) for every LAN client — silently breaking any
local DNS entries or Pi-hole-style filtering on `.200`, and imposing
BebasID's own third-party content policy (their "block ads" or "block
malware/adult/gambling" resolver) instead. User chose to skip this and
keep the existing local DNS setup; only the DPI-evasion firewall rules
were applied.

## 3. Verification

- `/ping 1.1.1.1 count=3` — 0% packet loss, ~2.5ms avg, confirmed
  connectivity intact after all changes
- SSH access (password auth) unaffected throughout — never modified the
  `ssh` service or the `input` chain's LAN-allow rule
- All rule insertions briefly showed an `I` (invalid) flag in
  `/ip firewall filter print` immediately after creation, then cleared on
  the next query — this is normal transient RouterOS behavior while it
  recalculates rule dependencies after an insert, not an actual problem.
  Don't panic if you see it; just re-query.

## 4. Reference: full current firewall filter chain (post-changes)

```
0  D  chain=forward action=passthrough                          ;;; fasttrack counter dummy
1     chain=forward action=fasttrack-connection                 ;;; FastTrack LAN traffic
      connection-state=established,related
2     chain=forward action=drop connection-state=invalid        ;;; Drop invalid forward  [NEW]
3     chain=forward action=accept connection-state=established,related  ;;; Accept est/rel
4     chain=forward action=accept in-interface=bridgeLocal out-interface=ether1  ;;; LAN->WAN
5     chain=input connection-state=established,related          ;;; Allow established/related
6     chain=input protocol=icmp limit=10,5                      ;;; Allow ICMP
7     chain=input action=drop connection-state=invalid          ;;; Drop invalid input  [NEW]
8     chain=input in-interface=bridgeLocal                      ;;; Allow LAN
9     chain=input action=accept protocol=udp dst-port=4500      ;;; allow IPsec NAT
10    chain=input protocol=udp in-interface=ether1 dst-port=500,4500,1701  ;;; Allow L2TP IPsec WAN
11    chain=input action=accept protocol=udp dst-port=1701      ;;; allow l2tp (ipsec-required)  [CHANGED: +ipsec-policy=in,ipsec]
      ipsec-policy=in,ipsec
12    chain=input action=drop protocol=udp dst-port=1701 log=yes log-prefix="unencrypted-l2tp"  ;;; Drop unencrypted L2TP  [NEW]
13    chain=input action=drop                                   ;;; Drop other input
14    chain=forward action=drop protocol=tcp in-interface=ether1 content="Location: http://lamanlabuh.aduankonten.id/"  ;;; BebasIT | Bypass DPI  [NEW]
15    chain=forward action=drop tcp-flags=rst,ack protocol=tcp in-interface=ether1  ;;; BebasIT | Bypass DPI  [NEW]
```

## Update 2026-08-28: re-audit found one real gap this pass missed

A follow-up session re-audited the same router the next day. Most of the
above still held (already-correct items stayed correct), but found one gap
this pass's fixes hadn't actually closed, plus a few smaller items:

- **The `forward` chain still had no catch-all `drop` at the end.** This
  pass added `connection-state=invalid` drop to `forward` (see table above),
  but never added the final default-deny drop that `input` already had (item
  1's "Reference" section above shows `forward` ending at rule 4, the
  LAN→WAN accept — nothing after it). Not exploitable at the time (no dstnat
  rules existed to let WAN traffic in), but a real gap versus the standard
  RouterOS defconf template, and it's exactly the kind of thing that becomes
  dangerous the moment someone adds a port-forward later without revisiting
  this rule. Fixed:
  ```
  /ip firewall filter add action=drop chain=forward comment="Drop other forward (default deny)"
  ```
- **RouterBOARD firmware badly out of sync** with the installed RouterOS
  version (several major versions behind on the bootloader). Flagged for
  `/system routerboard upgrade` + reboot; not applied automatically since it
  needs a reboot.
- **Storage nearly full** on this flash-backed model — turned out to be
  mostly the RouterOS system partition itself, not reclaimable user files
  (only a stray leftover packet-capture file from a prior `/tool sniffer`
  session was worth removing). Genuinely just a hardware ceiling on this
  model, not a config problem.
- **`/tool sniffer` left configured** (not running, but with a `file-limit`
  larger than the entire free disk) — a landmine if it's ever started by
  accident. Left as-is after confirming it wasn't actively capturing, flagged
  rather than force-changed in case it's wanted for on-demand debugging.
- **VPN credential reuse**: the L2TP PPP password and the IPsec pre-shared
  key for the same profile were set to the *identical* string — one secret
  protecting two independent security layers instead of two. (Found by
  querying the live property directly — `/ppp secret get [find name=...]
  password` and `/ip ipsec identity get [find] secret` — since `/export`
  and `print detail` both mask these fields even though the values were
  real, not blank.) Recommended splitting them; not changed automatically
  since it'd break the existing VPN client without coordinating.
- Default-`admin`-account gap (see "deliberately NOT fixed" above) still
  open — same reasoning still applies, still flagged rather than force-changed.
