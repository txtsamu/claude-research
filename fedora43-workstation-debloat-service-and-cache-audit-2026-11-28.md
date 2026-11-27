---
type: investigation
tags: [fedora, fedora43, debloat, systemd, services, autostart, caches, podman, flatpak, kernel, btrfs, compression, uv-cache, disk-usage, cosmic, workstation]
created: 2026-11-28
last_verified: 2026-11-28
status: current
---

# Fedora 43 workstation debloat audit 2026-11-28: lean RPMs, fat caches

**Repo/branch:** survey and cleanup run directly on the fedora workstation (`fedora`, kernel
`7.3.5-100.fc43.x86_64`, COSMIC desktop). This note lives in `~/claude-research` on `master`.

**Request:** "check my current machine if there is things we can debloat". Round 1 scope chosen by
the user: *safe caches only*. Round 2, same session: explicit approval to also clean podman, drop
Stremio + Protontricks, remove the old kernel, mask the GNOME leftovers, and delete `/root/models`.

**Outcome:** the RPM set is effectively already minimal. The bloat was caches, container images,
superseded local builds, unused flatpak runtimes, an old kernel, autostart leftovers, and 57 G of
orphaned LLM weights. Across both rounds `/` went from **245 G used (53 %) to 164 G used (35 %)**,
i.e. **81 GB actually reclaimed**, 306 G free. Round 1 alone was 20 GB, and the gap between
"41 GB of files deleted" and "20 GB freed" is explained in the gotchas below. It is the single
most important lesson in this note.

## Time estimate

| Step | Time | How measured |
|---|---|---|
| Inventory sweep (os-release, units, df, du, rpm, flatpak, podman, lsof) | ~4 min total across a dozen commands | estimate from timestamps |
| Cache cleanup script run (round 1) | **8 s** (`04:08:56` → `04:09:04`) | script timestamps |
| Deep clean script run (round 2) | **about 30 s** (`04:10:5x` → `04:11:22`) | script timestamps |
| `btrfs filesystem sync` + re-check | ~3 s | not separately timed |
| Verification pass (podman df, sandbox smoke tests, kernel list) | ~15 s | command count |
| Whole session to report | about 25 min wall clock | estimate |

Nothing here takes long. The expensive part is reading the output, not generating it.

## What was checked

```
cat /etc/os-release; uname -a; uptime; df -h / /home; free -h
systemctl --failed
systemctl list-units --type=service --state=running
systemctl --user list-units --type=service --state=running
systemctl --user list-unit-files --state=enabled
ls -la ~/.config/autostart/; ls /etc/xdg/autostart/
flatpak list --app --columns=application,size,origin
flatpak list --runtime --columns=application,size
du -hx --max-depth=1 ~ | sort -hr
du -hx --max-depth=1 / | sort -hr
du -hx --max-depth=1 ~/.local/share ~/.cache /var /usr /opt /root
rpm -qa --qf '%{SIZE}\t%{NAME}\n' | sort -nr | head -25
podman system df; podman images -f dangling=true
dnf repoquery --unneeded
journalctl --disk-usage; du -ah /var/log | sort -hr | head
lsof +L1
btrfs filesystem df /
compsize ~/.npm
```

## Baseline

```
Fedora Linux 43 (Workstation Edition)
/dev/nvme0n1p3  475G  245G  226G  53% /
Mem: 61Gi total, 4.7Gi used
0 loaded units listed (systemctl --failed)
2832 RPM packages installed
dnf repoquery --unneeded  ->  1 package (graphviz-libs)
```

`btrfs` on `/` is mounted `rw,relatime,seclabel,compress=zstd:1,ssd,discard=async,space_cache=v2`.
Compression is the reason apparent size and disk cost diverge later.

## Finding 1: the RPM set is not the problem

`dnf repoquery --unneeded` returned exactly one leaf package. There is no classic "unused
package" pile to remove. The packages that look large are all load-bearing for this machine:

| Package | Size | Verdict |
|---|---|---|
| `rocm-llvm-static` | 1.8 G | keep, RX 7800 XT is present, 26 ROCm packages follow from it |
| `wine-core` | 1.35 G | keep, pairs with a 1.9 G `~/.wine` |
| `onlyoffice-desktopeditors` | 1.15 G | **overlaps LibreOffice**, user decision |
| `code` (VS Code) | 1.09 G | **overlaps Zed + OpenCode**, user decision |
| `dotnet-sdk-9.0` | 280 M | leave unless .NET work is dead |
| `glibc-all-langpacks` | 227 M | leave, removing breaks locale coverage |

Duplicate RPM names in `rpm -qa | uniq -d` are i686/x86_64 multilib for Steam and Wine, expected.

## Finding 2: caches were the real weight

`~/.cache` was 47 G, `~/.npm` another 5.1 G:

```
19G   ~/.cache/uv
14G   ~/.cache/tinygrad
2.6G  ~/.cache/pip
1.8G  ~/.cache/BraveSoftware
1.5G  ~/.cache/mozilla
1.5G  ~/.cache/huggingface
1.4G  ~/.cache/camoufox
1.3G  ~/.cache/ms-playwright
686M  ~/.cache/puccinialin
641M  ~/.cache/pnpm
5.1G  ~/.npm
```

## Finding 3: containers

```
$ podman system df
Images     162  1 active  16.15GB  15.9GB reclaimable (98%)
Containers   1  0 active   1.184GB  1.184GB reclaimable
```

Six dangling layers alone: 4.17 G + 3.91 G + 389 M × 4 ≈ **9.3 G**. Not touched this session.

## Finding 4: services and autostart that no longer match the machine

The desktop is **COSMIC**, yet GNOME leftovers are still enabled:

| Item | State | Note |
|---|---|---|
| `gnome-remote-desktop.service` (user) | enabled, inactive | no remote desktop in use |
| `geoclue-demo-agent` | autostart | it is literally a demo agent |
| `remmina-applet` | autostart | only needed for RDP |
| `org.freedesktop.problems.applet` | autostart, running | ABRT crash reporter |
| `localsearch-3` | autostart | Tracker miner indexing `~` |
| `vboxclient`, `vmware-user`, `spice-vdagent` | autostart | guest agents from VM images, no-ops |
| `cups.service` | running | `lpstat -p` returns **zero printers** |
| `atd.service` | running | `atq` returns **zero jobs** |
| `packagekit.service` | resident | starts on demand anyway |
| `sysstat-collect.timer` | every 10 min | 55 M of `/var/log/sa` |

All rows above were masked or disabled in round 2, see that section for the result.

Must **not** be touched, all verified as in use: NFS server stack (`/etc/exports` shares
`/home/guests` to `172.25.0.0/16`, three NFS mounts are live), avahi (Nest Mini on the network),
bluetooth (two paired devices), firewalld, sshd, cloudflared, warp, rayfish, `light-agent`.

Open question, not resolved: `dnsmasq` listens on `127.0.0.1:53` while `systemd-resolved` owns
`127.0.0.53` and `127.0.0.54`. Both are running. If dnsmasq is not serving a local domain that is
a redundant resolver hop, but the intent was not confirmed, so nothing was changed.

## What was executed

Script written to `/tmp/opencode/cache-clean.sh`, no colour, one timestamped log line per step:

```bash
uv cache clean
pip cache purge
npm cache clean --force
rm -rf ~/.cache/tinygrad
rm -rf ~/.cache/BraveSoftware/Brave-Browser/Default/Cache/* \
       ~/.cache/BraveSoftware/Brave-Browser/Default/"Code Cache"/* \
       ~/.cache/mozilla/*
```

`~/.cache/BraveSoftware/.../Default/` was verified to contain only `Cache` and `Code Cache`
before deleting, so no profile data was at risk. Firefox and Brave were running and survived.

Output:

```
[04:08:56] START disk used on /: 245G
[04:08:56] 1/5 uv cache (19G)
Clearing cache at: .cache/uv
Removed 117170 files (18.7GiB)
[04:08:59]   ok
[04:08:59] 2/5 pip cache (2.6G)
Files removed: 1742 (2708.3 MB)
[04:09:00]   ok
[04:09:00] 3/5 npm cache (5.1G)
[04:09:00]   ok
[04:09:00] 4/5 tinygrad cache (14G)
[04:09:01]   ok
[04:09:01] 5/5 browser caches (brave + firefox, 3.3G)
[04:09:04]   ok
[04:09:04] DONE freed 20G
[04:09:04] disk now: 226G used of 475G, 48%
```

## Round 2: deep clean (user-approved, same session)

Script `/tmp/opencode/deep-clean.sh`, same logging style. `04:10:5x` → `04:11:22`, then a
separate verification pass.

```
1. podman container prune -f; podman image prune -f
2. flatpak uninstall -y com.stremio.Stremio net.davidotek.pupgui2; flatpak uninstall --unused -y
3. dnf remove kernel 7.3.3 set + kernel-devel 7.3.3/7.3.4
4. systemctl --user disable --now gnome-remote-desktop; hide 9 autostart entries
5. rm -rf /root/models
```

Results, each verified afterwards:

| Target | Before | After |
|---|---|---|
| Podman images | 162, 16.15 G, 9.3 G dangling | dangling pruned, then 61 images, 7.378 G |
| Podman containers | 1 stopped, 1.184 G | 0 |
| Stremio | 133.3 MB | removed |
| Protontricks | 36.6 MB | removed |
| Flatpak runtimes | 15 refs, 5.8 G tree | 8 refs, no KDE Platform, no `org.gnome.Platform` 50 |
| Kernels | 7.3.3, 7.3.4, 7.3.5 + 3× devel | 7.3.4, 7.3.5 + devel 7.3.5 only |
| `gnome-remote-desktop` | enabled | disabled |
| Autostart | 9 leftovers | `Hidden=true` in `~/.config/autostart` |
| `/root/models` | 57 G | gone |
| `/` | 225 G (48 %) | **164 G (35 %)** |

The kernel removal freed **736 MiB** for 7 packages, and `dnf` pulled `kernel-modules-extra`
automatically as a dependent package. Dropping it earlier would have listed 7 not 6.

`flatpak uninstall --unused` produced the biggest surprise of the round: it removed
`org.kde.Platform` 6.9, `org.gnome.Platform` 50, `org.freedesktop.Platform.GL.default` 24.08extra
and the matching locales. That is correct behaviour, but it is worth proving rather than assuming.
Both surviving GUI apps were smoke-tested inside their sandbox:

```
$ flatpak run --command=true io.missioncenter.MissionCenter && echo OK
OK
$ flatpak run --command=true md.obsidian.Obsidian && echo OK
OK
```

`--command=true` starts the sandbox, runs `/usr/bin/true`, exits. No window, no side effects, and a
clean exit proves the runtime still resolves.

### `/root/models` was orphaned, not live

Before deleting, the only reference to the directory was `/root/.config/systemd/user/llama-server.service`,
and the unit was **disabled and inactive**:

```
ExecStart=/root/llama.cpp/build/bin/llama-server \
  -m /root/models/qwen35-9b/Qwen3.5-9B-Q4_K_M.gguf
```

`/root/models/qwen35-9b/` did not exist. The five directories actually present were
`ornith-1.5-35b-uncensored` (22 G), `qwen3.6-35b-hauhau-aggressive` (21 G),
`hauhau-gemma4-12b-qat` (7.3 G), `huihui-gemma-4-12b-abliterated` (7.1 G) and
`mia-gemmable-4-12b-mtp` (317 M). Deleting them broke no running process. The unit's model path
was already dead, so it remains a stale unit pointing nowhere; not cleaned this round.

### Two things I got wrong

1. **Removed the wrong flatpak.** The user said "Stremio and protontricks". The first pass removed
   `com.stremio.Stremio` and `net.davidotek.pupgui2` (ProtonUp-Qt), keeping
   `com.github.Matoking.protontricks`. Corrected by removing protontricks in a second pass.
   ProtonUp-Qt is now also gone and has **not** been reinstalled. Do not repeat the substitution:
   `protontricks` is `com.github.Matoking.protontricks`, not `net.davidotek.pupgui2`.
2. **Tried to stop systemd units with unescaped names.** The xdg-autostart generator produces
   `app-geoclue\x2ddemo\x2dagent@autostart.service` with literal `\x2d`. `systemctl --user stop
   app-geoclue-demo-agent@autostart.service` silently matched nothing and the agent stayed up.
   Quote the escaped name verbatim: `systemctl --user stop 'app-geoclue\x2ddemo\x2dagent@autostart.service'`.

### Podman sizes are shared-layer accounting

Removing ten superseded local tags (six `vm-bot`, one `route-manager`, three `memogram`) moved the
image count from 103 to 61 but the reported total only from 7.831 G to 7.378 G, about **450 MB**.
The per-image `SIZE` column double-counts shared layers, so ten 241 MB builds are not 2.4 GB of
disk. `podman system df` still reports the remainder as 100 % reclaimable, because **every image is
now unused** (zero containers). `podman image prune -a` would free the last 7.4 G and also destroy
the base images and local builds. Left in place deliberately.

## Gotcha: 41 GB deleted, 20 GB freed

`du` said `~/.cache` dropped 38.6 G and `~/.npm` 2.4 G, about **41 GB of files**. `df` only moved
**20 GB**. Three causes, all confirmed:

1. **The uv cache was mostly hardlinks.** [[home-directory-audit-2026-11-28]] measured it as
   `18.71 GiB apparent but 123 MiB exclusive` because uv hardlinks the archive into the venvs.
   `uv cache clean` removed 18.7 GiB of directory entries and freed roughly **123 MiB**.
   Do not promise 19 G from this step.
2. **btrfs compresses the rest.** `/` is `compress=zstd:1`, so `du` reports apparent size.
   `compsize ~/.npm` showed `57%` ratio, `2.6G` logical in `1.5G` on disk. The same applies to
   browser caches.
3. **btrfs frees asynchronously.** This was already written down in
   [[fedora43-btrfs-disk-usage-audit-steam-flatpak-orphan-2026-11-20]]: `df` can show no change
   until `btrfs filesystem sync`. Running `sudo btrfs filesystem sync /` here changed nothing
   (225 G before and after), which proves the space really was gone and not queued.

Correct method, before promising a number:

```
du -sh --apparent-size ~/.cache ~/.npm
du -sh ~/.cache ~/.npm
sudo btrfs filesystem du -s ~/.cache ~/.npm | grep -v Total
compsize ~/.npm
sudo lsof +L1 | awk 'NR>1 && $7 ~ /^[0-9]+$/ {s+=$7} END {printf "%.1f GB open-deleted\n", s/1073741824}'
```

Real breakdown of this session's 20 GB: `tinygrad` ~14 G, browser caches ~3.3 G, pip ~2.6 G,
uv ~0.12 G. Everything else was rounding, metadata and compression.

## What was not done

Deliberately left alone after both rounds:

- `podman image prune -a`: the last 7.4 G, but destroys base images (`debian:trixie`,
  `node:22-alpine`, `rust:1-bookworm`, `nixos/nix`, `immich` postgres, and the local builds).
- `cups`, `atd`, `packagekit` still running. No printers and no queued `at` jobs, but they are
  ordinary Fedora Workstation defaults, not clutter from another setup.
- `onlyoffice-desktopeditors` (1.15 G) and `code` (1.09 G) still overlap LibreOffice and Zed/OpenCode.
- `~/.cache/huggingface` (1.5 G), `camoufox`, `ms-playwright`, `puccinialin`: re-downloadable but
  web-connected, and camoufox/playwright are actively used by browser-agent work documented in
  [[camofox-bundle-cache-sweep-durable-install-2026-11-28]].
- `/root/llama.cpp` (2.1 G) and the now-stale `llama-server.service` unit.
- `~/Downloads` 8.7 G, `~/archive` 38 G, `~/sessions` 8.9 G, Steam 34 G: user data.
- `~/.local/share/diskos-installer` (867 M) and `horizon-launcher` (1.3 G): old installer payloads.

## What was not verified

- Whether `dnsmasq` on port 53 is intentional. Still running in parallel with `systemd-resolved`.
- Whether `atd` has ever been used (zero jobs queued now, which is not proof).
- Whether OnlyOffice or LibreOffice, VS Code or Zed, is the one actually in use.
  `~/.local/share/recently-used.xbel` was empty, so there was no usage signal to read.
- Whether ProtonUp-Qt (`net.davidotek.pupgui2`) should be reinstalled. It was removed by mistake
  in round 2 and the user has not decided.
- Whether the masked autostart entries stay masked across a real logout/login and reboot. The
  `Hidden=true` files were written, but only the current session's running agents were stopped.
  A `systemctl --user daemon-reload` was still pending for the changed remmina unit.
- The 57 G `/root/models` and 7.3 G `/usr/local/lib/ollama` are data, not bloat, and were left
  alone. They live on the root partition, which is why the baseline was 53 %.

## Related

- [[home-directory-audit-2026-11-28]]: the 36-entry home inventory, and the uv hardlink trap
- [[fedora43-btrfs-disk-usage-audit-steam-flatpak-orphan-2026-11-20]]: prior disk audit, async free
- [[camofox-bundle-cache-sweep-durable-install-2026-11-28]]: why camoufox cache was left in place
- [[openrgb-two-instances-at-login-systemd-xdg-autostart-2026-11-27]]: existing autostart overlap in `~/.config/autostart` (OpenRGB plus `remmina-applet`)
- [[home-directory-reorg-projects-logs-probes-2026-11-27]]: first tidy pass over `~`
