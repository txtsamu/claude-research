---
type: how-to
tags: [caddy, pihole, dns, https, podman, mikrotik, brave, virtualmin]
created: 2026-07-13
last_verified: 2026-07-13
status: current
---

# Clean Local `.lan` Domains with HTTPS via Caddy + Pi-hole

**Date:** 2026-07-13
**Host:** homelab (Rocky Linux 9.8, rootful podman quadlets in `/etc/containers/systemd/`)
**Goal:** Give podman services clean, port-less local URLs (e.g. `https://jellyfin.lan`) with browser-trusted HTTPS, no purchased domain, no interference with the existing Cloudflare Tunnel.

Based on the approach from ["Clean Local Domains with HTTPS for Your Homelab"](https://dbtechreviews.com/2026/07/06/clean-local-domains-with-https-for-your-homelab-no-domain-purchase-required/) (dbtechreviews.com): Caddy as reverse proxy + built-in local CA, Pi-hole for DNS rewrites.

---

## 1. Why Caddy instead of Nginx Proxy Manager

NPM is designed around Let's Encrypt, which needs to prove domain ownership over the public internet — doesn't work for `.lan`. Caddy has its own built-in certificate authority (`tls internal`) that issues locally-trusted certs for any domain, no external dependency. Install its root CA once per device, every subdomain added afterward "just works" with a green padlock.

## 2. TLD choice: `.lan`

Picked `.lan` over `.local` (reserved for mDNS/Bonjour, can conflict with AirDrop-style discovery) and `.internal` (IANA's official recommendation, equally valid — just went with the more conventional homelab choice).

---

## 3. Pre-flight: mapping the existing environment

Before touching anything, worth checking what's already running, since a naive host-network Caddy deployment (as the guide describes) assumes ports 80/443 are free.

```bash
podman ps -a                          # inventory all containers + published ports
ss -tlnp | grep -E ':80 |:443 |:53 '  # who's actually bound to the ports we need
```

Findings on this host:

- **`virtualmin`** container already published `0.0.0.0:80` and `0.0.0.0:443` (plus `10000`/`20000` for Webmin) — a hard conflict with Caddy's `network_mode: host` requirement.
- **`pihole`** container runs with `Network=host` and is the **live DNS server for the whole LAN** — confirmed via MikroTik (`/ip dns print` and `/ip dhcp-server network print` both pointed to `192.168.50.80`, this host). Its admin UI was already moved off port 80 to `8081` (`FTLCONF_webserver_port=8081` in the quadlet), so no conflict there.
- **`cloudflared`** runs as a separate `Network=host` quadlet doing outbound-only connections to Cloudflare's edge (named tunnel, ingress configured remotely in the Cloudflare dashboard) — doesn't bind any local port, so it's structurally incapable of conflicting with Caddy.

**Gotcha:** `ss -tlnp` showed virtualmin's port 80/443 as `LISTEN`, but `curl` got connection refused on both — the host port was reserved by podman's port-forwarding but nothing was actually serving behind it (the container's internal Apache/webserver likely hadn't come up). Don't assume `LISTEN` means "actually working" — verify with a real request.

### Freeing 80/443

Edited `/etc/containers/systemd/virtualmin.container`:

```diff
- PublishPort=80:80
- PublishPort=443:443
+ PublishPort=8090:80
+ PublishPort=8453:443
```

(First attempt used `8080`/`8443` — `8080` collided with `openwebui`. Checked free ports first with a sweep over `ss -tln` before picking `8090`/`8453`.)

```bash
systemctl daemon-reload
systemctl restart virtualmin
```

---

## 4. Caddy quadlet

`/root/caddy/{Caddyfile,data,config}` — bind-mounted, matching the guide's docker-compose layout but as a podman quadlet to match the rest of this host's IaC pattern.

`/etc/containers/systemd/caddy.container`:

```ini
[Unit]
Description=Caddy reverse proxy - local .lan domains with HTTPS
After=network-online.target
Wants=network-online.target

[Container]
Image=docker.io/library/caddy:latest
ContainerName=caddy
Network=host
Volume=/root/caddy/Caddyfile:/etc/caddy/Caddyfile:Z
Volume=/root/caddy/data:/data:Z
Volume=/root/caddy/config:/config:Z

[Service]
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`Network=host` lets Caddy bind 80/443 directly — same reasoning as the guide's `network_mode: host`.

### Caddyfile

```caddyfile
{
	local_certs
}

jellyfin.lan {
	tls internal
	reverse_proxy 127.0.0.1:8096
}

nextcloud.lan {
	tls internal
	reverse_proxy 127.0.0.1:8181
}

# ... one block per service, same pattern ...

virtualmin.lan {
	tls internal
	reverse_proxy https://127.0.0.1:10000 {
		transport http {
			tls_insecure_skip_verify
		}
	}
}
```

The `virtualmin.lan` block is the guide's "proxying services with their own self-signed certs" pattern — Webmin serves HTTPS on `10000` with a self-signed cert, so Caddy needs `tls_insecure_skip_verify` on the *backend* connection (the connection from browser to Caddy is still a fully trusted cert either way).

Full current domain list: `jellyfin.lan`, `nextcloud.lan`, `immich.lan`, `vaultwarden.lan`, `grafana.lan`, `uptime.lan`, `oneterm.lan`, `bookstack.lan`, `pihole.lan`, `openwebui.lan`, `proxcenter.lan`, `virtualmin.lan`, `copyparty.lan`, `mihon.lan` (renamed from `suwayomi.lan`, see §8), `9router.lan` — all pointing to `127.0.0.1:<service port>` since Caddy runs on the same host as the services.

```bash
systemctl daemon-reload
systemctl start caddy
```

All 15 certs were issued successfully on first start (checked via `podman logs caddy | grep "certificate obtained successfully"`).

---

## 5. Pi-hole DNS rewrites

Pi-hole v6 stores custom DNS records in `/etc/pihole/pihole.toml` under `[dns] hosts`, as an array of `"IP HOSTNAME"` strings — this is the v6 equivalent of the old "Local DNS Records" UI page.

Host path (via the quadlet's named volume): `/var/lib/containers/storage/volumes/systemd-pihole-data/_data/pihole.toml`

```toml
[dns]
  hosts = [
    "192.168.50.80 jellyfin.lan",
    "192.168.50.80 nextcloud.lan",
    "192.168.50.80 immich.lan",
    "192.168.50.80 vaultwarden.lan",
    "192.168.50.80 grafana.lan",
    "192.168.50.80 uptime.lan",
    "192.168.50.80 oneterm.lan",
    "192.168.50.80 bookstack.lan",
    "192.168.50.80 pihole.lan",
    "192.168.50.80 openwebui.lan",
    "192.168.50.80 proxcenter.lan",
    "192.168.50.80 virtualmin.lan",
    "192.168.50.80 copyparty.lan",
    "192.168.50.80 mihon.lan",
    "192.168.50.80 9router.lan"
  ]
```

All entries point at the Caddy host IP (`192.168.50.80`), not the individual service IPs — Caddy handles routing from there, per the guide.

**Gotcha — found a pre-existing landmine while editing this file:** there are *two* `hosts = [...]` arrays in `pihole.toml` — one under `[dns]` (what we want) and a visually-similar one under `[dhcp]` (static DHCP leases, expects `"mac,ip,hostname,lease"` format). The DHCP one already had a malformed entry (`"192.168.50.80 test.ssamu.id"` — wrong format for that field) predating this work. Left it alone since fixing it wasn't in scope and touching DHCP static-lease config carries its own risk. **Lesson: `grep -n hosts pihole.toml` before editing — check which section you're actually in.**

**Gotcha — `pihole reloaddns` did not apply the change.** The command ran without error but `dig` against the new domains kept returning `NXDOMAIN`. Only a full container restart picked up the edit:

```bash
systemctl restart pihole
```

**This caused a real incident**: `pihole-pod.service` failed to come back up cleanly (`A dependency job for pihole.service failed`), which took the **live network DNS offline** for about 90 seconds, since MikroTik has `192.168.50.80` as its primary DNS server for both its own resolver and DHCP-issued clients. Fix was:

```bash
systemctl start pihole-pod
systemctl start pihole
```

...then it came back healthy. **Because this is the network's actual DNS server, any `pihole` container restart is a live-infrastructure-risk operation, not a routine config reload** — worth remembering next time a `.lan` domain needs to change.

---

## 6. Verifying MikroTik was already correctly configured

The user asked "does my MikroTik already set it up?" — checked via SSH (`admin@192.168.50.1`):

```
/ip dns print
  servers: 192.168.50.80, 1.1.1.1, 1.0.0.1, 94.140.14.14

/ip dhcp-server network print
  0  192.168.50.0/24  192.168.50.1  192.168.50.80,1.1.1.1,1.0.0.1,94.140.14.14
```

Both the router's own resolver and DHCP-issued clients were already pointed at Pi-hole (`192.168.50.80`) first, with public resolvers as fallback — this was pre-existing, not something this task needed to change. **Lesson for next time: check `/ip dns print` and `/ip dhcp-server network print` before assuming DNS needs router-side changes** — the router may already be correctly wired, and the real problem is client-side (see §7).

---

## 7. Client-side DNS troubleshooting (Fedora)

`https://jellyfin.lan` failed to resolve on the user's Fedora 43 desktop, despite the server side (Pi-hole record + Caddy cert + reverse proxy) all verified working via `dig ... @192.168.50.80` and `curl --resolve ... --cacert root.crt` from the homelab host itself.

Since the Claude session runs on the homelab server, not the user's desktop, diagnosis had to be handed off as commands for the user to run themselves. Fedora uses NetworkManager + systemd-resolved:

```bash
# What DNS server is actually active?
resolvectl status

# Force-test against Pi-hole directly
dig jellyfin.lan @192.168.50.80

# Test through the normal resolution path (the one that matters)
dig jellyfin.lan
```

Three likely culprits on the client side:
1. **Stale negative DNS cache** (cached NXDOMAIN from before the record existed) → `sudo resolvectl flush-caches`
2. **Browser/OS "Secure DNS" (DoH) bypassing the LAN resolver entirely** → check Chrome/Firefox Secure DNS settings and Android-style "Private DNS" equivalents
3. **NetworkManager per-connection static DNS override** → `nmcli -f NAME,IP4.DNS,IP4.GATEWAY con show --active`; if `IP4.DNS` isn't `192.168.50.80`, clear the override: `nmcli con mod "<name>" ipv4.dns "" ipv4.ignore-auto-dns no && nmcli con up "<name>"`

(This diagnosis wasn't concluded in this session — pending output from the user's own machine.)

---

## 8. Adding / renaming a service

Two files, two reload steps. Worked example: renaming `suwayomi.lan` → `mihon.lan`.

```bash
# 1. Caddyfile: rename the site block
sed -i 's/^suwayomi\.lan {/mihon.lan {/' /root/caddy/Caddyfile

# 2. pihole.toml: rename the [dns] hosts entry (NOT the dhcp.hosts one — see §5 gotcha)
sed -i 's/192.168.50.80 suwayomi.lan/192.168.50.80 mihon.lan/' /var/lib/containers/storage/volumes/systemd-pihole-data/_data/pihole.toml

# 3. Apply
systemctl restart caddy    # do NOT rely on `caddy reload` — see gotcha below
systemctl restart pihole   # brief live-DNS blip, see §5
```

**Gotcha — `podman exec caddy caddy reload --config /etc/caddy/Caddyfile` silently no-oped after editing the Caddyfile on the host.** Caddy's admin API logged `"config is unchanged"` even though the file content had changed. Root cause: the editor tool writes via "new file + rename," which changes the file's inode; podman's **single-file** bind mount stays pinned to the original (now-deleted) inode, so the container kept reading the old content (`stat` inside the container showed `Links: 0` on the old inode — deleted but still open). `caddy reload` re-read that same stale mount and correctly concluded nothing had changed.

**Fix / lesson: after editing `/root/caddy/Caddyfile` on the host, always `systemctl restart caddy` (or `podman restart caddy`) — never trust `caddy reload` alone to pick up host-side file edits under a single-file bind mount.** (A directory bind mount wouldn't have this problem, only single-file mounts do — worth switching to a directory mount if this friction shows up often.)

---

## 9. Nextcloud's `trusted_domains` check

`https://nextcloud.lan` returned **HTTP 400** through Caddy (valid cert, valid proxy — just an app-level rejection). Nextcloud validates the `Host` header against `config.php`'s `trusted_domains` and rejects anything not on the list:

```bash
podman exec nextcloud-app php occ config:system:set trusted_domains 1 --value=nextcloud.lan
```

Appended as **index 1**, alongside the existing `cloud.ssamu.id` (index 0, used by the Cloudflare Tunnel) — did not touch or reorder the existing entry. After this, `nextcloud.lan` returned the normal login-redirect (302).

**Lesson: any app with server-side Host-header/vhost validation (Nextcloud, sometimes Grafana's `root_url`, etc.) may need its own local-domain allowlist entry even after Caddy + DNS are both working correctly.** Worth a quick `curl -o /dev/null -w '%{http_code}'` check per service after wiring it up, not just a DNS/TLS check.

---

## 10. Installing the root CA on client devices

Public artifact, not a secret — get it from:

```bash
scp root@192.168.50.80:/root/caddy/data/caddy/pki/authorities/local/root.crt .
```

**Fedora (system trust store — covers curl, Chrome, GTK apps):**
```bash
sudo cp root.crt /etc/pki/ca-trust/source/anchors/caddy-local-ca.crt
sudo update-ca-trust extract
```

**Firefox on Linux keeps its own NSS cert store, separate from the system trust store:**
```bash
sudo dnf install -y nss-tools   # provides certutil
certutil -A -n "Caddy Local CA" -t "C,," \
  -i /etc/pki/ca-trust/source/anchors/caddy-local-ca.crt \
  -d sql:$HOME/.mozilla/firefox/$(ls ~/.mozilla/firefox | grep default-release)
```
Or via GUI: `about:preferences#privacy` → Certificates → View Certificates → Authorities → Import → check "Trust this CA to identify websites."

Windows/Android/iOS steps are per the original guide (`certutil -addstore`, install-as-CA-cert, and the two-step iOS profile-install-then-Certificate-Trust-Settings-toggle respectively).

---

## 11. Brave (and Chromium-based browsers) on Linux: a separate trust store, again

Got `NET::ERR_CERT_AUTHORITY_INVALID` on Brave even after the system trust store (`update-ca-trust`) was correctly updated and verified (`trust list` showed the cert as a trusted `anchor`/`authority`). Debugging path, including the wrong turns:

1. **First theory: Flatpak sandboxing.** Brave is commonly distributed as a Flatpak on Fedora, and Flatpak sandboxes apps away from `/etc/pki`. Asked the user which install method they used — they initially said Flatpak, then corrected with `which brave-browser` → `/usr/bin/brave-browser`, which is the **native RPM install** (`brave-browser.repo` pointing at Brave's own `dnf` repo). Flatpak's exported binaries live under `~/.local/share/flatpak/exports/bin/` or `/var/lib/flatpak/exports/bin/`, not `/usr/bin/`, so this ruled the theory out. **Lesson: verify the install method with `which <bin>` / `rpm -q <pkg>` before diagnosing sandbox-related cert issues — don't trust a remembered answer over a live command.**

2. **Root cause: Brave/Chromium on Linux doesn't use the OS trust store at all**, regardless of install method (native or Flatpak). It reads a **per-user NSS database** at `~/.pki/nssdb` — same mechanism Firefox uses (per-profile NSS db), but a completely separate database from Firefox's, and separate from the system `p11-kit`/`trust` store that `update-ca-trust` manages. Confirmed via a Brave Community solution thread: [Trust CA Certificates in Brave on Linux using Policy](https://community.brave.app/t/solution-trust-ca-certificates-in-brave-on-linux-using-policy/535346).

3. **Fix — import via `certutil` into Brave's NSS db directly** (the in-app `brave://certificate-manager` → Authorities → Import path was also tried first and didn't reliably stick; the CLI path is the documented-reliable one):

```bash
sudo dnf install -y nss-tools   # provides certutil

mkdir -p ~/.pki/nssdb
modutil -dbdir sql:$HOME/.pki/nssdb --empty-password -f   # only if the db doesn't already exist

certutil -d sql:$HOME/.pki/nssdb -A -t "TC,C,C" \
  -n "Caddy Local Authority" \
  -i /etc/pki/ca-trust/source/anchors/caddy-local-ca.crt
```

Verify: `certutil -d sql:$HOME/.pki/nssdb -L | grep -i caddy` → should show trust flags `CT,C,C`.

**Gotcha:** the system anchor file (`/etc/pki/ca-trust/source/anchors/caddy-local-ca.crt`) was `root:root`, mode `600` — unreadable by the normal user, so `certutil -A -i <that path>` failed with `unable to open ... for reading (-5966, 13)`. Worked around by `sudo cat`-ing it to a user-readable temp copy first:
```bash
sudo cat /etc/pki/ca-trust/source/anchors/caddy-local-ca.crt > /tmp/caddy-local-ca.crt
certutil -d sql:$HOME/.pki/nssdb -A -t "TC,C,C" -n "Caddy Local Authority" -i /tmp/caddy-local-ca.crt
rm -f /tmp/caddy-local-ca.crt
```

4. **Fully quit Brave, not just close windows**, then relaunch — `pgrep -a brave-browser` before relaunching confirmed no leftover background process holding the old (untrusted) state.

All of this was executed **over SSH to the user's Fedora desktop** (`moo@fedora`, key-based auth already trusted from this homelab host) since the Claude session runs on the homelab server, not the client machine — a reminder that "install a cert on your machine" tasks can sometimes be done directly by the agent if passwordless SSH already exists, rather than only handed to the user as copy-paste instructions.

---

## 12. Summary of gotchas (quick reference)

| Symptom | Root cause | Fix |
|---|---|---|
| Caddy can't bind 80/443 | `virtualmin` already published those ports, serving nothing behind them | Remap virtualmin to `8090`/`8453`, free 80/443 for Caddy |
| `curl` refused on a `LISTEN` port | Host port reserved by podman but container's internal service not actually up | Verify with a real request, don't trust `ss` alone |
| Edited `pihole.toml`, `pihole reloaddns` didn't apply it | `reloaddns` doesn't re-read core config, only gravity/blocklists | Full `systemctl restart pihole` needed for `dns.hosts` changes |
| `pihole` restart briefly broke all LAN DNS | It's MikroTik's actual primary DNS server, not a toy instance | Treat any `pihole` restart as live-infra risk; have `systemctl start pihole-pod && systemctl start pihole` ready if the pod dependency fails to come back |
| `caddy reload` says "config is unchanged" after a real edit | Single-file bind mount pinned to old (deleted) inode after an atomic file rewrite | `systemctl restart caddy` instead of relying on reload |
| `https://nextcloud.lan` → HTTP 400 despite valid cert/proxy | App-level `trusted_domains` Host-header allowlist | `occ config:system:set trusted_domains N --value=<domain>` |
| Two `hosts = [...]` arrays in `pihole.toml` | `[dns]` and `[dhcp]` sections both have a field named `hosts`, different formats | `grep -n` to confirm which section before editing |
| Brave shows `NET::ERR_CERT_AUTHORITY_INVALID` despite system trust store being correctly updated | Brave/Chromium on Linux ignores `/etc/pki/ca-trust` entirely, uses its own per-user `~/.pki/nssdb` | `certutil -d sql:$HOME/.pki/nssdb -A -t "TC,C,C" -n "<name>" -i <cert>`, then fully quit + relaunch Brave |

---

## 13. Notes on secrets

Credentials referenced during this session (MikroTik SSH password, Cloudflare API token from `~/.hermes/skills/devops/homelab-mcp-setup/references/cloudflare-mcp.md`) are intentionally **not** reproduced here — see the relevant Hermes skill reference files for those, kept out of this repo. Placeholder convention used above: `<MIKROTIK_PASSWORD>`, `<CLOUDFLARE_API_TOKEN>`.
