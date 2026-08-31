---
type: troubleshooting
tags: [dns, hosts-file, ssh-config, nmcli, networkmanager, homelab, cleanup]
created: 2026-08-31
last_verified: 2026-08-31
status: current
---

# Homelab-wide sweep for stale `/etc/hosts`, resolver, and SSH-config entries

Triggered while migrating DNS to the [3(later 4)-node Technitium
deployment](technitium-dns-3node-cluster-deployment.md) — decided to audit
every host's static DNS references rather than assume they were all
current, since one stale entry (a dead old Pi-hole box) had already turned
up once by accident. Worth being systematic: checked `/etc/hosts`,
`nmcli`/`resolvectl`-level DNS overrides, and `~/.ssh/config` across every
host in the network.

## What was actually found (real bugs, not just tidying)

### `/etc/hosts`
| Host | Stale entry found | Real impact |
|---|---|---|
| `fedora` | `vpz → <STALE_PUBLIC_IP_1>` (dead, connection timeout) | any local tool resolving `vpz` via `/etc/hosts` got a dead IP |
| `fedora` | `pihole → 192.168.50.50` (fully dead host, no route) | — |
| `arm1-4` (all four) | `pihole → 192.168.50.50`; `vpz → <STALE_PUBLIC_IP_2>` (a **third**, also-wrong IP, different from fedora's) | same class of bug, independently wrong on each host |
| `px1` | `master`/`worker1`/`worker2` at `.150`/`.151`/`.152` — dead, no DHCP lease, no ping response | leftover from a decommissioned CKA-practice cluster, unrelated to the current Talos cluster |

`vpz`'s IP was wrong in **three mutually-inconsistent ways** across
different hosts before this sweep (one wrong IP on fedora, a different
wrong IP on all four arm boards, both different from the actual current
`<VPZ_PUBLIC_IP>`) — a good reminder that stale `/etc/hosts` entries drift
independently per-host with no single source of truth, unlike DNS.

`nas` and `warp-vm` were checked and found already clean.

### DNS resolver config (separate from `/etc/hosts` — this is what a host
actually queries for names *not* hardcoded locally)
| Host | Problem | Fix |
|---|---|---|
| `arm2`, `arm3`, `arm4` | `nmcli` `ipv4.dns` statically pinned to `192.168.50.50` (the same dead old Pi-hole box) — bypassing DHCP-provided DNS entirely | `nmcli con mod 'Wired connection 1' ipv4.dns '<new-list>'` + `nmcli con up` |
| `px1` | `/etc/resolv.conf`'s *only* local nameserver was `192.168.50.80` (a **different** dead old Pi-hole install), with just `1.1.1.1` as fallback | direct rewrite of `/etc/resolv.conf` |

The `px1` finding is the more serious one — it means the Proxmox host had
likely never resolved any `.lan` name correctly at all, silently falling
through to public DNS for everything, until this sweep caught it.
Discovered only because the DNS cutover work prompted checking every
host's resolver config directly rather than assuming DHCP alone was
sufficient — several of these hosts had static overrides that DHCP-list
changes on the MikroTik would never have touched.

`arm1` was already correctly pointed at the live DNS server — the one
host that didn't need fixing on this front.

### `~/.ssh/config`
Two aliases pointed at now-permanently-dead hosts, removed on request
once confirmed unrecoverable:
```
Host pihole
    HostName 192.168.50.50   # dead, no route
    User root

Host cka
    Hostname 192.168.50.150  # dead, same decommissioned CKA cluster as px1's /etc/hosts finding
    User ubuntu
```
Also fixed while auditing: `Host nas` was configured `User root`, but the
box only actually accepts `moo` — this had been silently broken (or
working around it some other way) rather than a recent regression.

## Method

Nothing exotic — the value here was being systematic and actually testing
each finding rather than assuming based on config alone:
```bash
# per host: dump both files
ssh <host> 'cat /etc/hosts'
ssh <host> 'resolvectl status eth0 | grep "DNS Server"'  # or cat /etc/resolv.conf on non-NetworkManager hosts

# then verify liveness of anything suspicious before deciding stale vs. real
ping -c1 -W1 <suspect-ip>
ssh -o ConnectTimeout=4 <suspect-ip> 'hostname'   # if ping is inconclusive, e.g. host up but service dead
```
For `px1` and the arm boards specifically, cross-referenced against the
MikroTik's own DHCP lease table (`/ip dhcp-server lease print`) to confirm
an IP had genuinely gone dark (no active lease, no ping, no SSH) before
concluding "dead" rather than "just quiet right now."

## Not touched, and why

- Caddy's own `.lan` site blocks were audited separately (two dangling
  entries — `vaultwarden.lan`, `9router.lan` — found and removed as part
  of the DNS migration itself, not this sweep; see the Technitium
  deployment doc).
- RHCSA-lab and `whatismyip.akamai.com`-blackhole entries left in some
  hosts' `/etc/hosts` were left alone — clearly intentional (an unrelated
  training lab, and a deliberate geolocation-check block), not drift.
