---
type: how-to
tags: [disk, home, nixos, journald, tmpfiles, technitium, nix-gc, k3s, containerd, hermes, vmalert, alerting, arm1]
created: 2026-11-06
last_verified: 2026-11-07
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
- Resolved (written 2026-11-07): PR #14 (mtime fix) and #13 (evonic) merged and deployed from `main` (section 8). Evonic was then removed from `home` again the same evening by a separate session (PR #18), so the Evonic parts of section 5 and 8 are history; the journal cap and the `m:14d` Technitium rule live in `hosts/home/logging.nix` on `main` and are unaffected.
- Final state: `home` root 68% used, 30 GB free. What remains is container layers (about 21 GB) and `/root/.hermes` (about 6 GB); neither shrinks on its own (section 9).
- Related: MetalLB pool cleanup, SMART and MetalLB alerts and the CoreDNS/MetalLB/cert-manager dashboard sections are in [[perses-dashboards-audit-and-expansion-2026-11-05]].

## 8. Follow-up the same day
- **Evonic landed.** Pushed branch `evonic-plus-log-retention` (= `evonic` + `main`) as a fast-forward into `evonic`, waited for CI (about 4 min), merged PR #13, and rebuilt from plain `main` (`nixos-version --configuration-revision` = main's head). Journal cap and the `m:14d` Technitium rule confirmed live; evonic, technitium, k3s and caddy active.
- **Failed-units audit (run by a subagent, verified afterwards; notes in `~/sessions/2026-11-06-failed-units-fix/`):**
  - `cloudflared.service` failed on px1 and arm1: a stale unit from `podman generate systemd` pointing at a container that no longer exists. The real tunnel is the Quadlet `cloudflared-armbian` (two replicas of one tunnel). Fix: `systemctl disable cloudflared.service; rm /etc/systemd/system/cloudflared.service; systemctl daemon-reload; systemctl reset-failed`.
  - Version skew (px1 2026.8.2 vs arm1 2026.3.0, both `:latest`): pinned `Image=docker.io/cloudflare/cloudflared:2026.10.7` in `/etc/containers/systemd/cloudflared-armbian.container`, `podman pull`, `systemctl daemon-reload; systemctl restart cloudflared-armbian`, arm1 first, confirmed 4 "Registered tunnel connection" lines before doing px1. Backups `~/cloudflared-armbian.container.bak-20261106`.
  - `motd-news` (arm2/3/4): `/etc/update-motd.d/50-motd-news` missing on Armbian (exit 203). `systemctl disable --now motd-news.timer; systemctl mask motd-news.service`.
  - `netfilter-persistent` (arm2): `/etc/iptables/rules.v6` held stale k3s rules with an `xt_nfacct` object that no longer exists (restore failed at line 37, exit 4; reproduced in a throwaway netns). Replaced it with an empty ACCEPT `*filter` table (matches live IPv6), left `rules.v4` alone. Backup `/etc/iptables/rules.v6.bak-20261106`.
  - Result: `systemctl --failed` empty on px1, arm1-arm4.
- **NAS drive sde:** SSH to the NAS was denied, so the check used the smartctl exporter (`192.168.50.10:9633`, `smartctl_device_attribute`): CRC raw = 1, constant for the whole retention window, no reallocated/pending sectors, error log 0, SMART passed; the other 4 disks have 0. Benign. Added vmalert rules `DiskCrcErrorsRising` (increase over 24 h > 0), `DiskBadSectors` (reallocated/pending/offline-uncorrectable > 0), `DiskSmartFailed` (status == 0, critical); `alerts/rules.v4.yml`, previous `alerts/rules.live-before-smart.yml`. 16 rules loaded, all inactive.
- **Remaining `home` space:** 66% used. Optional: `/root/.hermes/cache/uv` (859 MB, regenerable) and the 2026-07-15 `state-snapshots` entry (294 MB). Left alone: `checkpoints` (1.2 GB) and `claude-staging` (812 MB, recently modified).

## 9. Last cleanup round (2026-11-06/07)
- Deleted `/root/.hermes/cache/uv` (859 MB, regenerable) and `/root/.hermes/state-snapshots/20260715-045650-pre-update` (294 MB, nothing else in that dir).
- Root rose from 66% to 70% during the day because `/nix` grew 11 -> 15 GB: about 10 `nixos-rebuild switch` runs (generations 49-59) in one day. The weekly GC only deletes generations older than 14 days, so they stay. `sudo nix-env -p /nix/var/nix/profiles/system --delete-generations +2; sudo nix-collect-garbage` kept generations 58 (previous) and 59 (current) and freed only 945 MiB (I had estimated 3-4 GB: most of the growth was live paths, not dead ones). Root 70% -> 68%.
- `/root/.hermes/checkpoints/store` (Hermes' undo history: one shared git repo, refs `refs/hermes/*`, per-session ledgers) is 1.2 GB, almost all incompressible objects: `git --git-dir=. gc` (40 s, safe while Hermes runs) only brought it to 1.1 GB. Only pruning old refs would shrink it materially (loses old undo history); left as is.
- `home` ends at 68% used (30 GB free). What remains is container layers (about 21 GB of unpacked image layers for 48 images, nothing unused) and `/root/.hermes` (about 6 GB).
