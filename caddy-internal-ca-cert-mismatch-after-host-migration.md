---
type: troubleshooting
tags: [caddy, tls, pwa, android, certificate, home, warp-vm, migration]
created: 2026-09-10
last_verified: 2026-09-10
status: current
---

# Caddy internal CA cert mismatch after `warp-vm` → `home` migration (PWAs broke, browser tabs didn't)

## Symptom

After the `warp-vm` → `home` cutover (see [[warp-vm-nixos-migration-plan]]), a phone could no longer open the Suwayomi or Immich PWAs (installed home-screen web apps) — they just failed to load. Regular browser tabs to the same `.lan` domains still worked fine (with a "not secure, proceed anyway" style warning history already dismissed once).

## Root cause

Caddy's `tls internal` directive generates its own self-signed local CA the *first time it starts* on a given host, unique to that Caddy instance's data directory. `home` runs a completely fresh Caddy instance (native `services.caddy`, not a copy of `warp-vm`'s data), so it minted a **new, different root CA** the day `home` was stood up:

```
$ ssh home "sudo find / -xdev -path '*caddy*pki*' -iname 'root.crt'"
/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt

$ curl -s http://127.0.0.1:2019/pki/ca/local | python3 -m json.tool
{
    "root_common_name": "Caddy Local Authority - 2026 ECC Root",
    ...
}
```
The root cert's `Not Before` matched the exact day `home`'s Caddy first started.

The phone had (at some point) been told to trust `warp-vm`'s old CA — see [[local-lan-domains-caddy-pihole-setup]] for the original "trust this local CA" setup pattern. `home`'s new CA is a completely different certificate, so every TLS chain now terminates at an untrusted root as far as the phone is concerned.

**Why browser tabs kept working but PWAs didn't**: a normal browser tab shows an interstitial "your connection isn't private" warning with a manual "proceed anyway" override. An installed PWA has no such UI — it enforces strict TLS validation with no user-facing bypass, so it just silently fails to load instead of prompting.

## Fix

1. Grab the new root CA cert from `home`:
   ```bash
   sudo cp /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt /tmp/caddy-root-ca.crt
   sudo chmod 644 /tmp/caddy-root-ca.crt
   ```
2. Get it onto the phone. A quick throwaway HTTP server on the LAN is the simplest transport (no need to touch production Caddy config for this):
   ```bash
   cd /tmp && python3 -m http.server 8899 --bind 0.0.0.0
   ```
   then from the phone's browser: `http://<home-ip>:8899/caddy-root-ca.crt`
3. **Android**: Settings → Security → More security settings → Encryption & credentials → Install a certificate → CA certificate → select the downloaded file (there's a "not recommended" warning for installing a CA cert manually — expected here, it's a self-signed local CA you control).
4. Reopen the PWAs.
5. Tear down the temp HTTP server once confirmed working — it's not meant to be left running.

## Lesson for next time

Any host migration that stands up a **fresh** Caddy instance (native module, not a copied data directory) mints a new internal CA by construction. Every client that was told to trust the old host's CA needs the new one pushed out too — this is a real, easy-to-miss step distinct from the DNS/IP repointing itself, since the symptom (PWAs silently failing while browser tabs "just work" via the manual-override path) doesn't obviously point at a certificate problem unless you already know to check for it.

Diagnosed entirely from direct on-box inspection (the `root.crt` file's timestamp, Caddy's own `/pki/ca/local` admin API) — no web research needed for this one.
