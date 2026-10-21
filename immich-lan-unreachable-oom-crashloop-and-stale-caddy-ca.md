---
type: troubleshooting
tags: [immich, k3s, oomkilled, caddy, tls, internal-ca, home, fedora]
created: 2026-10-22
last_verified: 2026-10-22
status: current
---

# immich.lan "not reachable": server OOMKilled crash-loop + fedora trusts the old Caddy CA

Two independent causes were found. Cause 1 was fixed (memory limit raised, see below); the Cause 2 fix on fedora is proposed but not applied.

## Triage

```bash
getent hosts immich.lan                       # 192.168.50.200  (DNS fine; = home)
curl -sk -o /dev/null -w "%{http_code}\n" https://immich.lan/   # 200 (up at that moment)
curl -s  -o /dev/null -w "%{http_code}\n" https://immich.lan/   # 000, ssl_verify=20  <- strict TLS fails
curl -s  -o /dev/null -w "%{http_code} %{redirect_url}\n" http://immich.lan/   # 308 -> https
ssh moo@home 'systemctl is-active caddy'      # active (since 2026-09-28)
ssh moo@home 'sudo k3s kubectl get nodes'     # home Ready (single node, v1.35.8+k3s1)
```
Caddy on `home` is a native NixOS `services.caddy` (config at `/etc/caddy/caddy_config`, not `Caddyfile`); there is no podman/docker on that host.

## Cause 1: immich-server OOMKilled in a loop (the real outage)

```bash
sudo k3s kubectl -n homelab get pods,svc | grep immich
#  pod/immich-...  3/3 Running  4 (2m ago)   ; svc immich LoadBalancer 192.168.50.251:2283
sudo k3s kubectl -n homelab describe pod -l app=immich     # server: Last State Terminated, Reason OOMKilled, exit 137
sudo dmesg -T | grep "Memory cgroup out of memory"         # kills at 05:16, 05:17, 06:02, 06:04 (WIB)
```
- Victims: `immich`/`libvips worker`, anon-rss ~4.0-4.3 GB each time, against the `server` container limit of **4608Mi** (request 2560Mi). Redis and postgres containers had 0 restarts.
- `IMMICH_MACHINE_LEARNING_ENABLED=false`, so this is not ML. A libvips job (thumbnail/image processing) is the memory hog.
- After the last restart (06:05) the server was at ~1975m CPU / ~3.8 GiB and climbing back toward the limit, so a repeat OOM is likely until the heavy job finishes or the limit is raised.
- The 4608Mi limit is the value chosen in [home-k8s-resource-rightsizing-victoriametrics.md](home-k8s-resource-rightsizing-victoriametrics.md) (observed peak was 3857Mi). The peak is now above that.

Applied 2026-10-22 (node has ~15.5 GiB, ~62% used):
```bash
sudo k3s kubectl -n homelab set resources deploy/immich -c server --requests=memory=3Gi --limits=memory=6Gi
sudo k3s kubectl -n homelab rollout status deploy/immich
```
Rolled out clean, new pod 3/3 Running. Still worth doing if it recurs: lower job concurrency in Immich Admin > Settings > Job Settings (thumbnail generation, metadata extraction).

## Cause 2: this fedora box trusts the *old* Caddy CA (strict TLS clients fail)

`openssl s_client` shows the chain served by `home` is `leaf <- Caddy Local Authority - ECC Intermediate <- 2026 ECC Root`, verify code 20. Fingerprints:

| Where | Root SHA-256 (prefix) | Not Before |
|---|---|---|
| `home` `/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt` | `58:62:93:0A` | 2026-09-09 |
| fedora `/etc/pki/ca-trust/source/anchors/caddy-local-ca.crt` | `3E:AE:CA:22` | 2026-07-13 (old warp-vm CA) |

Same mechanism as [caddy-internal-ca-cert-mismatch-after-host-migration.md](caddy-internal-ca-cert-mismatch-after-host-migration.md) (that doc fixed the phone, fedora was missed). Browsers with a click-through still work; curl, PWAs and the Immich mobile app do not.

Proposed fix on fedora (needs sudo, not run):
```bash
ssh moo@home 'sudo cat /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt' \
  | sudo tee /etc/pki/ca-trust/source/anchors/caddy-local-ca.crt >/dev/null
sudo update-ca-trust
curl -s -o /dev/null -w "%{http_code}\n" https://immich.lan/   # expect 200 without -k
```
(Firefox/Chromium NSS stores may need the cert re-imported separately.)

## Notes
- evomem `evomem_search` timed out on the first call (tokenmax); the second call worked. Relevant prior art found: `homelab-k8s-resource-tuning-and-immich-redis-incident`.
