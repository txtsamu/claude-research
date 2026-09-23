---
type: how-to
tags: [mikrotik, routeros, hardening, security, firewall, ssh, mac-server, services, hex-s]
created: 2026-09-24
last_verified: 2026-09-24
status: current
---

# MikroTik hEX S hardening — round 2 (service/MAC/discovery lockdown)

Follow-up to [mikrotik-hardening-dpi-bypass-2026-08-27.md](mikrotik-hardening-dpi-bypass-2026-08-27.md)
(which did the firewall input chain + DPI-bypass work). This round audited the
remaining management-plane attack surface on the **hEX S (RB760iGS)**, RouterOS
**7.24.4**, and locked down services, MAC-layer access, and neighbor discovery.
Router IP `192.168.50.1`, admin over IP SSH from a LAN host (`192.168.50.20`).

## Pre-check that made the changes safe

The firewall input chain already ends in `action=drop` (rule "Drop other
input") and trusts LAN via `chain=input in-interface=bridgeLocal` (rule "Allow
LAN"). Admin host is `192.168.50.20` ∈ `192.168.50.0/24` on `bridgeLocal`, so
every change below is reachable from the admin host and none touch the LAN
accept rule → **no lockout risk**. Interface lists already existed:
`LAN=bridgeLocal`, `WAN=ether1`. L2TP/IPsec VPN server is enabled (admin may
also arrive from the `192.168.89.0/24` VPN pool) — so service ACLs include that
subnet too.

Audit commands used:
```
/user print detail; /user group print
/ip service print; /ip ssh print
/tool mac-server print; /tool mac-server mac-winbox print; /tool mac-server ping print
/tool bandwidth-server print
/ip neighbor discovery-settings print
/ip cloud print; /snmp print; /ip socks print; /ip proxy print; /ip upnp print
/system routerboard print; /system package print
/interface list print; /interface list member print
```

## Changes applied (all safe, no reboot)

```
# 1. SSH: disable weak ciphers/MACs (keeps existing host key — no reconnection break)
/ip ssh set strong-crypto=yes

# 2. Legacy Bandwidth Test server off (btest, was enabled=yes)
/tool bandwidth-server set enabled=no

# 3. MAC-layer management was allowed-interface-list=all (incl ether1/WAN L2).
#    Restrict MAC-telnet + MAC-winbox to LAN, disable MAC-ping.
/tool mac-server set allowed-interface-list=LAN
/tool mac-server mac-winbox set allowed-interface-list=LAN
/tool mac-server ping set enabled=no

# 4. Neighbor discovery (CDP/LLDP/MNDP) was discover-interface-list=static,
#    and the builtin "static" list INCLUDES ether1 (WAN) — i.e. the router was
#    announcing itself out the WAN. Scope to LAN only.
/ip neighbor discovery-settings set discover-interface-list=LAN

# 5. Defense-in-depth: bind management services to LAN + VPN subnets
#    (firewall already blocks WAN, but this is a second layer).
/ip service set ssh     address=192.168.50.0/24,192.168.89.0/24
/ip service set winbox  address=192.168.50.0/24,192.168.89.0/24
/ip service set www     address=192.168.50.0/24,192.168.89.0/24
/ip service set api-ssl address=192.168.50.0/24,192.168.89.0/24
```

Verified after: `strong-crypto: yes`, `bandwidth-server enabled: no`, both
mac-server lists = `LAN`, mac-ping `enabled: no`, discovery list = `LAN`, and
`/ip service print` shows `AVAILABLE-FROM` populated on ssh/www/winbox/api-ssl.
Re-connected over SSH afterward to confirm access intact.

### Already-good state found (left as-is)
`ftp`, `telnet`, `api` (plaintext 8728), `www-ssl` = disabled. SNMP off, SOCKS
off, web-proxy off, UPnP off, RoMON off. NTP synced (Asia/Jakarta). Neighbor
discovery already `add-dns-entries=no`. `/ip cloud` DDNS is intentional (part of
the remote-access setup; router is behind ISP NAT anyway).

## NOT changed — needs owner decision (recommended, deferred)

1. **RouterBOARD (RouterBOOT) firmware is stale.** `/system routerboard print`
   shows `current-firmware: 6.46.8` vs `upgrade-firmware: 7.24.4` (RouterOS is
   already 7.24.4). Sync + reboot:
   ```
   /system routerboard upgrade
   /system reboot
   ```
   **Requires a reboot** (drops the whole network briefly) → do on maintenance
   window, not unattended. (Also flagged in the 2026-08-27 doc; still pending.)

2. **Plaintext HTTP WebFig (`www` :80) still enabled** (now LAN/VPN-restricted).
   Better: disable it and manage via Winbox (8291), or stand up `www-ssl` with a
   cert. Left enabled in case browser WebFig is in active use.
   ```
   /ip service disable www          # if Winbox-only is acceptable
   ```

3. **`api-ssl` (8729)** — restricted to LAN/VPN now; disable if nothing consumes
   the RouterOS API (`/ip service disable api-ssl`).

4. **Default `admin` username + weak password.** Still the built-in `admin`
   (default = #1 brute-force target) with a weak password. Recommend a
   non-default admin username + strong password, e.g.:
   ```
   /user add name=<newadmin> group=full password=<strong>
   # log in as the new user, verify, then:
   /user disable admin      # (or remove once confident)
   ```
   Left untouched — it's the owner's active credential.

## Key takeaways

- On RouterOS, the firewall input `drop` protects the WAN, but **service `address=`
  ACLs, `mac-server` interface lists, and neighbor-discovery scope are separate
  attack surfaces** worth locking to `LAN` regardless.
- The builtin **`static` interface list includes the WAN port** — using it for
  neighbor discovery leaks CDP/LLDP/MNDP out the WAN. Use the explicit `LAN`
  list.
- `strong-crypto=yes` is safe to flip (doesn't regenerate the host key);
  bumping `host-key-size` DOES regenerate it and will trigger SSH host-key-changed
  warnings — skip unless you mean to.
