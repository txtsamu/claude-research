---
type: how-to
tags: [disk, home, nixos, journald, tmpfiles, technitium, nix-gc, k3s, containerd, hermes, vmalert, alerting, arm1]
created: 2026-11-06
last_verified: 2026-11-06
status: current
---

# Disk usage audit across hosts, `home` cleanup, log retention and disk alerts (2026-11-06)

Question: which hosts are filling up, what takes the space on `home`, and make it stay fixed. Result: `home` 73% -> 66% (98 GB root), arm1 78% -> 68%, plus disk alerts for every host and log retention declared in NixOS.

## Time estimate
- Whole session: about 3 h wall clock, most of it waiting (measured from the shell timestamps, estimate).
- `du` over `home`'s root: about 1-2 min per run (measured). Do it in the background.
- NixOS PR CI: 4 min 45 s (measured). `nixos-rebuild switch` from GitHub: about 2-3 min each (estimate from the sessions).

## 1. Check all hosts at once (VictoriaMetrics)
```bash
# usage per filesystem, all hosts (run through the Perses datasource proxy, curl -k)
curl -sk -o du.json --data-urlencode 'query=100 - (node_filesystem_avail_bytes{fstype!~"tmpfs|overlay|squashfs|ramfs|devtmpfs|fuse.*|nsfs|zfs",mountpoint!~"/run.*|/var/lib/(kubelet|containers|docker|rancher).*|/boot/efi.*"} / node_filesystem_size_bytes * 100)' \
  https://perses.lan/proxy/globaldatasources/victoriametrics/api/v1/query
```
Always `-o file` (the rtk curl wrapper truncates stdout). ZFS and NFS need separate handling: per-dataset ZFS percentages are meaningless, and NFS mounts just mirror the NAS. Proxmox: `pvesm status`, `lvs`.

Findings: arm1 `/` 78% (5.9 GB eMMC), home 73%, fedora 58%, arm2/3/4 about 50%, px1 22%, TrueNAS pool about 50%.

## 2. arm1
Cause: every VS Code update leaves another 600 MB server build in `/root/.vscode-server/cli/servers` (`lru.json` lists newest first). Fix: `ssh arm1 'rm -rf /root/.vscode-server/cli/servers/Stable-<old>'` after confirming no `server-main` process. It will return with each VS Code update.

## 3. What takes the space on `home`
```bash
ssh moo@home 'sudo -n du -xh --max-depth=1 / | sort -rh | head'   # then drill into the top entries
# sudo with a glob needs a root shell: sudo sh -c "cd DIR && du -xsm * | sort -rn | head"
```
Breakdown of 68 GB: `/var/lib/rancher/k3s` 24 GB (containerd 21 GB: 16 GB unpacked image layers for 48 images that are only 6 GB compressed; not a leak, only 2 unused images), `/root` 18 GB (`.hermes` 8.3 GB, 4.1 GB old k3s-upgrade backups, caches), `/nix` 11 GB, `/var/log` 2.3 GB (journal 970 MB, Technitium 843 MB), `/opt` 3.7 GB.

## 4. Cleanup done on `home`
| Step | Command | Freed |
|---|---|---|
| Old k3s upgrade backup (4 weeks old) | `sudo rm -rf /root/k3s-upgrade-backups-2026-10-09` | 4.1 GB |
| Journal | `journalctl --rotate; journalctl --vacuum-size=200M` (a bare vacuum freed 0 B: active files are not vacuumed, rotate first) | 780 MB |
| Caches | `rm -rf /root/.cache/{uv,pip,node-gyp} /root/.npm/_cacache ~/.cache/{pip,uv}` (left camoufox browser and HuggingFace models: not caches) | about 1 GB |
| Unused Hermes tools | `sudo sh -c 'cd /root/.hermes/tools && rm -rf python-3.14.7* node-26.7.0* uv-0.12.3*'`, after checking `facts.json` (Hermes' registry lists the current versions), no running process and no symlink or venv pointing at them | 680 MB |
| Nix GC | `sudo nix-collect-garbage --delete-older-than 14d` | 877 MB |
| Technitium logs | via the NixOS rule below | 630 MB |

Nix GC was already healthy: `nix.gc` weekly, `--delete-older-than 14d`, Monday 00:00, last run 2 Nov freed 537 MiB. No change needed.

## 5. Log retention in NixOS (the persistent fix)
`home` is NixOS, so retention goes in the flake repo (`txtsamu/home-nixos`, `hosts/home/logging.nix`, imported from `configuration.nix`), not in `/etc`:
```nix
services.journald.extraConfig = ''
  SystemMaxUse=300M
  MaxRetentionSec=1month
'';
systemd.tmpfiles.rules = [ "e /var/log/private/technitium/dns - - - m:14d" ];
```
Dead end worth remembering: the first version used `14d` without `m:`. systemd-tmpfiles ages by the **newest of atime/mtime/ctime**, and Technitium re-reads its old logs daily, so every file looked fresh and nothing was removed (59 files stayed). The `m:` prefix ages by modification time only: 59 -> 15 files, 844 -> 217 MB. Debug with `SYSTEMD_LOG_LEVEL=debug systemd-tmpfiles --clean --prefix=/var/log/private` and `stat` on a file.

Verify before deploying (home has nix, the fedora desktop does not):
```bash
rsync -a --exclude .git repo/ home:/tmp/hn-check/
ssh home 'cd /tmp/hn-check && nix run nixpkgs#nixfmt -- --check hosts/home/*.nix && nix eval --raw ".#nixosConfigurations.home.config.services.journald.extraConfig"'
```

### Deployment gotcha: another branch was live
`home` deploys with `sudo nixos-rebuild switch --flake github:txtsamu/home-nixos#home --refresh`. After merging PR #12 the running generation still lacked the change: another session had deployed the unmerged `evonic` branch (PR #13) at 14:00, and a rebuild from `main` would have switched its service off while it was in use. Find out what is live before rebuilding: `nixos-version --configuration-revision` (compare with `git ls-remote origin`) and `journalctl -t sudo | grep nixos-rebuild`. Resolution: branch `evonic-plus-log-retention` = `evonic` + `main` (one trivial import-line conflict), deployed from that; PR #14 carries the mtime fix for `main`. Until #13 and #14 merge, a rebuild from plain `main` drops evonic and the mtime fix.

## 6. Disk alerts (vmalert, homelab ns)
Rules live in ConfigMap `vmalert-rules`; vmalert does not watch it, so after `kubectl apply` run `kubectl -n homelab rollout restart deploy/vmalert`. Added, all warnings to Telegram:
- `Arm1DiskFull`: arm1 `/` above 80% for 10 min.
- `HostDiskFull`: ext4/xfs/btrfs above 85% for 10 min on every host except arm1, excluding `/dev/zram*`.
- `NasPoolFull`: the dashboard's pool-used expression above 85% for 30 min (reads about 3 points low).
`Arm4DiskFull` (90%) stays, so arm4 gets an early and a late alert. Files: `~/sessions/2026-11-05-perses-dashboards-review/alerts/` (`rules.before.yml`, `rules.after.yml`, `rules.v3.yml`). Check with `curl http://<vmalert clusterIP>:8880/api/v1/rules`.

## 7. Memory pressure check on `home` (same day)
Earlier notes said "2 OOM kills/hour"; re-measured and it is much healthier: 15.9 GB RAM, 8.4 GB available, swap 3.2 GB used (stale pages of headroom-proxy, node servers, Technitium, anoa), memory PSI about 0.05. Only one OOM kill in 48 h (vmsingle, 2026-11-05 21:49, before its limit was raised to 768Mi) and forgejo-db on 2026-10-28. Container limits sum to 123% of the node but requests only 50%, which is by design.
Commands: `free -m`, `cat /proc/pressure/memory`, `journalctl -k --since -48h | grep "Killed process"`, `kubectl top pods -A --containers` joined with each container's `limits.memory` (usage/limit ratio), `kubectl describe node | grep -A6 Allocated`.
Containers closest to their limit: uptime-kuma 369/384 Mi (96%), openwebui 69%, forgejo-db 62% of a 64 Mi limit. Raised (backup of both Deployments in `~/deploy-before-memlimits-20261106.yaml` on home):
```bash
kubectl -n homelab set resources deploy/uptime-kuma --limits=memory=768Mi --requests=memory=320Mi
kubectl -n homelab set resources deploy/forgejo-db  --limits=memory=160Mi --requests=memory=64Mi
```
Both rolled out in under a minute; forgejo-app kept answering 200. These Deployments are plain `kubectl apply` (no Helm), so if their manifests live in a repo, copy the new limits there or the next apply reverts them.

## Status / still open
- PR #14 (mtime fix) merged 2026-11-06. PR #13 (evonic) is still open; `home` runs the branch `evonic-plus-log-retention`, so merge #13 and then rebuild from `main`.
- Remaining space on `home` is mostly container layers (24 GB) and `/root/.hermes` (about 7.6 GB); neither shrinks on its own.
