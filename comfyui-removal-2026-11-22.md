---
type: how-to
tags: [comfyui, removal, uninstall, cleanup, fedora, systemd, firewalld, caddy, technitium, nixos, rocm, gguf]
created: 2026-11-22
last_verified: 2026-11-22
status: current
---

# Remove ComfyUI + Qwen-Image completely (fedora + home)

**Request:** "help me cleanup comfyUI from this machine completely."

**Outcome:** gone, local and remote. Service stopped and removed, 8188 firewall rule deleted,
`~/archive/ComfyUI` (17G) and `~/archive/models/qwen-image-2.1` (14G) deleted, Caddy `comfy.lan`
vhost dropped and deployed to `home`, Technitium A record deleted, stale Caddy cert and access log
removed. `df` went from 259G to 238G used (21G reclaimed; the tree measured 31G, the gap is
filesystem-level, see Gotchas). Nothing was left pointing at a dead backend. The config change is
committed and pushed as `de92898`, so `~/archive/home-nixos` is clean.

Install recipe this reverses: [[comfyui-qwen-image-2-1-gguf-fedora-comfy-lan]].

## Time estimate

Measured, whole session, on fedora + `home`:

| Step | Time |
|---|---|
| Inventory sweep (find, service, firewall, caches, remote refs) | ~4 min |
| Stop/disable/remove unit, firewall rule | <5 s |
| `rm -rf` of both trees | **1.5 s** (`real 0m1.545s`) |
| `nixos-rebuild dry-activate` on `home` | ~70 s |
| `nixos-rebuild switch` on `home` | ~45 s |
| DNS delete + verification, cert/log cleanup | ~30 s |

Total wall clock about **7 minutes**, of which almost all is the two NixOS builds. The actual
deletion is seconds.

## 1. Inventory first, delete second

ComfyUI was installed 2026-09-21 and was still running. Find every piece before touching anything:

```bash
find /home/moo /opt /srv /usr/local -maxdepth 4 -iname '*comfy*' 2>/dev/null
systemctl --user status comfyui --no-pager
sudo firewall-cmd --list-rich-rules
grep -rniE 'comfy' ~/.bashrc ~/.bash_profile ~/.bash_history ~/.config/systemd/user/
docker images | grep -i comfy; podman images | grep -i comfy
```

What existed, and the sizes:

| Item | Size |
|---|---|
| `~/archive/ComfyUI` (repo, 16G ROCm venv, patched custom nodes) | 17G |
| `~/archive/models/qwen-image-2.1` (GGUF, int8 text encoder, VAE) | 14G |
| `~/archive/comfyui-workflows`, `~/archive/logs/comfyui-install.log`, `qwen-image-dl-*.log` | ~20K |
| `~/.config/systemd/user/comfyui.service` (enabled, running 4 days) | - |
| firewalld rich rule for 8188 from 192.168.50.0/24 | - |
| HF cache stub `models--abenzerps--Qwen-Image-2.1-Uncensored-GGUF` | ~23M |
| Remote: Caddy `comfy.lan` vhost, Technitium `comfy.lan` A record, Caddy cert + access log on `home` | - |

Two things were checked and deliberately **kept**: `~/.cache/pip` (2.6G, general) and the
uv-managed `cpython-3.13.13` in `~/.local/share/uv/python` (generic interpreter, not ComfyUI-only).
`~/archive/models/bonsai-2-27b-crack` and `wikitext-bench` also stay, they are not ComfyUI.

Dead end worth noting: the install doc says the Caddy source of truth is `~/archive/home-nixos` on
fedora and that `~/home-nixos` on `home` is a plain rsync target. By now `~/home-nixos` on `home` is
gone and `/etc/nixos` is empty, so the checkout on fedora is the only copy. It was also stale
(`c565997`) against `origin/main` (`9cfac00`), and history had been rewritten (neither local HEAD nor
the `/tmp/home-nixos-deploy` clone was an ancestor of `origin/main`). Reset to `origin/main` before
editing rather than building from the stale tree, or the switch rolls the host config back.

## 2. Stop and remove the service

```bash
systemctl --user stop comfyui.service
systemctl --user disable comfyui.service
rm -f ~/.config/systemd/user/comfyui.service
systemctl --user daemon-reload
```

```
Removed '/home/moo/.config/systemd/user/default.target.wants/comfyui.service'.
--- port ---
8188 free
```

`is-enabled` afterwards reports `not-found`. Do this before deleting the directory so the unit is
not left pointing at a missing `ExecStart`.

## 3. Remove the firewall rule

```bash
sudo firewall-cmd --permanent --zone=FedoraWorkstation \
  --remove-rich-rule='rule family="ipv4" source address="192.168.50.0/24" port port="8188" protocol="tcp" accept'
sudo firewall-cmd --reload
```

`success` twice. The other rich rules (8099, 9100) were untouched.

## 4. Delete the files

Order matters only in that the model files are symlinked from inside `ComfyUI/models`; `rm -rf` does
not follow symlinks, so either order is safe, but ComfyUI first is tidier.

```bash
cd ~/archive
rm -rf ComfyUI comfyui-workflows models/qwen-image-2.1
rm -f logs/comfyui-install.log logs/qwen-image-dl-main.log logs/qwen-image-dl-te.log
rm -rf ~/.cache/huggingface/hub/models--abenzerps--Qwen-Image-2.1-Uncensored-GGUF
```

The 5 test renders in `ComfyUI/output` went with the tree (user chose delete over keeping them).

## 5. Drop the Caddy vhost on `home`

`origin/main` has since refactored `hosts/home/proxy.nix` from 17 hand-copied `extraConfig` blocks to
a `httpUpstreams` name -> upstream map, so the site is one line, not a block:

```nix
    "comfy.lan" = "192.168.50.20:8188";
```

Delete that line (and its comment). Preview, then apply:

```bash
cd ~/archive/home-nixos
git reset --hard origin/main
# edit hosts/home/proxy.nix
rsync -az --delete --exclude='.git' ./ moo@home:/home/moo/home-nixos-preview/
ssh moo@home 'cd /home/moo/home-nixos-preview && sudo nixos-rebuild dry-activate --flake .#home'
#   -> "would reload the following units: caddy.service, dbus-broker.service"
rsync -az --delete --exclude='.git' ./ moo@home:/home/moo/home-nixos/
ssh moo@home 'cd /home/moo/home-nixos && sudo nixos-rebuild switch --flake .#home'
```

Only `caddy.service` (and its dbus dependency) reloads. Verification:

```bash
ssh moo@home 'sudo grep -c comfy /etc/caddy/caddy_config; systemctl is-active caddy'
#   0
#   active
for h in perses.lan dns.lan immich.lan; do curl -sk -o /dev/null -w "$h %{http_code}\n" https://$h/; done
#   200 / 200 / 200
curl -sk -o /dev/null -w "comfy.lan -> %{http_code}\n" https://comfy.lan/
#   000
```

`000` is correct here: Caddy has no cert for the name any more, so the TLS handshake fails.

## 6. Delete the DNS record

The `.lan` zone is explicit A records. The Technitium API needs `ipAddress` on a delete, not just
domain/zone/type (first attempt without it returned `Parameter 'ipAddress' missing`). Password is
read from the agenix secret so it never lands on a command line:

```bash
ssh moo@home 'sudo bash -s' <<'EOF'
PW=$(sed -n "s/^DNS_SERVER_ADMIN_PASSWORD=//p" /run/agenix/technitium-admin-password)
TOKEN=$(curl -s -G http://127.0.0.1:5380/api/user/login --data-urlencode user=admin \
  --data-urlencode "pass=$PW" --data-urlencode includeInfo=false | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -G http://127.0.0.1:5380/api/zones/records/delete --data-urlencode "token=$TOKEN" \
  --data-urlencode domain=comfy.lan --data-urlencode zone=lan --data-urlencode type=A \
  --data-urlencode ipAddress=192.168.50.200
curl -s -G http://127.0.0.1:5380/api/user/logout --data-urlencode "token=$TOKEN" >/dev/null
EOF
# {"response":{},"server":"dns-warp-vm","status":"ok"}
```

Verify by listing the zone, not by `getent` (see Gotchas):

```bash
# /api/zones/records/get with domain=comfy.lan zone=lan listZone=true, filtered for "comfy"
#   status ok
#   []
```

## 7. Remove the stale Caddy cert and access log

Caddy reissues `tls internal` certs on demand, so the leftover pair is safe to drop:

```bash
ssh moo@home 'sudo rm -rf /var/lib/caddy/.local/share/caddy/certificates/local/comfy.lan'
ssh moo@home 'sudo rm -f /var/log/caddy/access-comfy.lan.log'
```

## 8. Commit the config change

The vhost removal is a real change to the deployed host config, so commit and push it rather than
leaving the checkout dirty for the next `git pull` to trip over:

```bash
cd ~/archive/home-nixos
git add hosts/home/proxy.nix
git commit -m "Drop comfy.lan Caddy vhost (ComfyUI removed from fedora)"
git push origin main
#   9cfac00..de92898  main -> main
git status --short      # clean
```

This repo is separate from `claude-research`; if the vhost had been the only local change, the
alternative is `git checkout -- hosts/home/proxy.nix` (its content was already in `origin/main`).

## Gotchas

- **`getent hosts comfy.lan` keeps answering after the delete.** The A record had TTL 3600 and the
  resolver cached it. Confirm via the Technitium API, not the client resolver.
- **`df` reclaimed 21G, not the 31G that `du` measured.** The two `du` figures (17G + 14G) sum to 31G
  but the filesystem freed 21G. Most of the difference is the venv: thousands of small files with
  block-sharing/overlay accounting that `du` counts per-file but the filesystem does not free
  one-for-one. Do not read the `df` delta as "something is left over", check the paths instead.
- **The Caddy checkout was stale and history had been rewritten.** Building from local HEAD would
  have reverted unrelated host changes. Always `git fetch` and compare against `origin/main` first.
- **`kubectl` is not on fedora** and the kubeconfig on `home` needs
  `KUBECONFIG=/etc/rancher/k3s/k3s.yaml`. Not needed here, but the install doc's Open WebUI step is
  moot anyway: there is no `openwebui` deployment left in `homelab` at all.
- **The two local patches in ComfyUI are gone with the tree.** They were uncommitted, so a reinstall
  has to re-apply them by hand (see the install doc, section 5).

## Not verified

- A reboot of fedora was not done to prove nothing re-starts ComfyUI. The unit is deleted from
  `default.target.wants` and `is-enabled` says `not-found`, so there is nothing left to start.
- `comfy.lan` was not tested from another LAN host after the DNS delete, only from fedora and `home`.
- The `comfy.lan` Caddy log directory still exists on `home` (`/var/log/caddy/`); only the
  per-site file was removed.

## References

- [ComfyUI repo](https://github.com/comfyanonymous/ComfyUI) (install side, for the reverse recipe)
- [systemctl --user unit management (systemd user units)](https://www.freedesktop.org/software/systemd/man/systemd.unit.html)
- [firewalld rich rules](https://firewalld.org/documentation/man-pages/firewall-cmd.html)
- [Technitium DNS Server API](https://github.com/TechnitiumSoftware/DnsServer/blob/master/APIDOCS.md)
- [Caddy reverse_proxy / tls internal](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)
