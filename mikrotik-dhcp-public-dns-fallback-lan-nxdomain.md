---
type: troubleshooting
tags: [mikrotik, routeros, dhcp, dns, technitium, lan, nxdomain, immich]
created: 2026-10-19
last_verified: 2026-10-19
status: current
---

# MikroTik DHCP advertised public DNS next to Technitium, so `*.lan` names randomly failed

## Symptom

LAN clients sometimes failed to resolve `*.lan` names such as `immich.lan`,
even though all the local Technitium servers were healthy and answered
correctly.

## Root cause

The router's DHCP network entry gave clients five DNS servers, two of them
public:

```
dns-server=192.168.50.200,192.168.50.42,192.168.50.40,1.1.1.1,1.0.0.1
```

Cloudflare knows nothing about `.lan`:

```bash
dig @1.1.1.1 immich.lan        # -> NXDOMAIN
```

Many client resolvers don't treat the list as "primary, then fallback".
Android, systemd-resolved, Windows and browsers with built-in resolvers may
send queries in parallel, rotate between servers, or switch to whichever one
answered fastest. If a `.lan` query goes to 1.1.1.1, the client gets NXDOMAIN
and **caches the negative answer**, so the name stays broken for a while even
though the local servers would have answered it.

The public fallbacks aren't needed for internet names either: all three
Technitium servers forward public names themselves.

| IP | What |
|---|---|
| 192.168.50.200 | Technitium on host `home` (primary, holds the `.lan` zone) |
| 192.168.50.42 | Technitium on an ARM node (secondary zone) |
| 192.168.50.40 | Technitium on an ARM node (secondary zone) |

## Fix (applied 2026-10-19)

Remove 1.1.1.1 and 1.0.0.1 from the DHCP network's `dns-server` list.
Nothing else was changed: no `/ip dns`, no static records, no firewall, no
leases, no reboot.

Access (password redacted):

```bash
SSHPASS='<MIKROTIK_PASSWORD>' sshpass -e ssh -o ConnectTimeout=8 \
  -o ControlMaster=no -o ControlPath=none admin@192.168.50.1 '<RouterOS command>'
```

### 1. Read-only check: confirm there is only one network entry

```
/ip dhcp-server network print detail
/ip dhcp-server print detail
```

Result: one network entry (`0`, `192.168.50.0/24`, gateway `192.168.50.1`)
and one server (`dhcp1` on `bridgeLocal`, `lease-time=30m`,
`add-dns-entries-suffix="lan"`). With more than one entry, or a different
value, the plan was to stop and not change anything.

### 2. Check that every LAN server answers both name types before removing the fallbacks

```bash
for s in 192.168.50.200 192.168.50.42 192.168.50.40; do
  echo "$s: $(dig +short +time=3 +tries=1 @$s immich.lan | tr '\n' ' ') | \
$(dig +short +time=3 +tries=1 @$s google.com | tr '\n' ' ')"
done
```

All three returned `192.168.50.200` for `immich.lan` and Google A records
for `google.com`. If any server had failed, the public fallbacks would have
stayed.

### 3. Save a rollback record

```
/ip dhcp-server network export
```

```
/ip dhcp-server network
add address=192.168.50.0/24 dns-server=\
    192.168.50.200,192.168.50.42,192.168.50.40,1.1.1.1,1.0.0.1 gateway=\
    192.168.50.1 netmask=24
```

### 4. Apply the change

```
/ip dhcp-server network set [find address="192.168.50.0/24"] dns-server=192.168.50.200,192.168.50.42,192.168.50.40
```

### 5. Verify

```
/ip dhcp-server network print detail
```

```
0  address=192.168.50.0/24 gateway=192.168.50.1 netmask=24
   dns-server=192.168.50.200,192.168.50.42,192.168.50.40 ...
```

## Rollback

```
/ip dhcp-server network set [find address="192.168.50.0/24"] dns-server=192.168.50.200,192.168.50.42,192.168.50.40,1.1.1.1,1.0.0.1
```

## When clients pick it up

- Clients get the new list when they renew their lease. With
  `lease-time=30m`, renewal happens at about T/2, so roughly 15–30 minutes.
- To get it now, reconnect Wi-Fi or Ethernet. On Linux:
  `nmcli con down <conn> && nmcli con up <conn>`.
- A client may still have a cached NXDOMAIN for a `.lan` name from 1.1.1.1.
  Flush it: `resolvectl flush-caches` (Linux), `ipconfig /flushdns`
  (Windows), toggle Wi-Fi (phones), or restart the browser if it has its
  own DNS cache.

## Trade-off

There is no longer a public fallback. If all three Technitium servers are
down at once, LAN clients lose DNS completely. The three servers run on
separate hosts (`home` plus two ARM nodes), so all of them failing together
is unlikely. If it does happen, the rollback command above restores the old
list.

## Related

- [mikrotik-doh-bypasses-local-dns-for-lan-domains.md](mikrotik-doh-bypasses-local-dns-for-lan-domains.md):
  the same kind of problem on the router's own resolver (DoH skipped the
  local server for `.lan`)
- [technitium-lan-secondary-zone-real-replication.md](technitium-lan-secondary-zone-real-replication.md):
  why .42 and .40 can answer `.lan` names
