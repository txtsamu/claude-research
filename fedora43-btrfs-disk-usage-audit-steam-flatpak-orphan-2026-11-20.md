---
type: investigation
tags: [disk, btrfs, fedora43, compression, zstd, du, steam, flatpak, uv-cache, podman, disk-usage-audit]
created: 2026-11-20
last_verified: 2026-11-20
status: current
---

# Disk usage audit on the Fedora 43 desktop, and the orphaned flatpak Steam tree

Question: what fills the 475 GB NVMe on this workstation, and what is safe to reclaim? Two cleanups were carried out: a 32 GB **orphaned flatpak Steam data tree** with no Steam app attached to it, and the 48 GB `uv` cache. Together they were **79 G apparent but only 22.3 GiB on disk**, taking the disk from 282 G used (60%) to 260 G used (56%). The main lesson: on btrfs with `compress=zstd:1`, `du` reports apparent size and overstates real cost by 2x on game data and 6x on Python caches, so never size a cleanup from `du` alone.

## Time estimate

- Whole audit: about 4 to 5 minutes wall clock (measured: first probe at 14:27:17, last at 14:31:18, from `uptime` and `date`).
- `du -xhd1 /`: under 1 minute (estimate, not individually timed).
- `du -xhd1 /home/moo`: about 1 to 2 minutes (estimate). Both ran in parallel.
- `du` drill-downs (`.cache`, `.local`, `.var`, `/root`, `/var`): seconds each, all parallel.
- `compsize /home`: ran in the background and **failed**, so no compression measurement was obtained. It aborted on the NFS photo mount after several minutes.
- No deletion was performed in this session, so no reclaim time is known.

## Environment

```bash
hostname                       # fedora
cat /etc/os-release            # Fedora Linux 43 (Workstation Edition)
uname -r                       # 7.3.3-100.fc43.x86_64
btrfs --version                # btrfs-progs v7.1
free -h                        # 61 GiB total, 9.9 GiB used, 52 GiB available
nproc                          # 32
```

Storage: one NVMe, `/dev/nvme0n1p3`, btrfs, two subvolumes (`subvol=/root`, `subvol=/home`), mounted with `compress=zstd:1,ssd,discard=async,space_cache=v2`. **No snapshots** (`btrfs subvolume list /` returned nothing). Deleted-but-open files were checked with `lsof` and account for only 0.4 GiB, so they are not a factor.

Three NFS mounts live under the local tree and do **not** count against this disk: `/home/moo/nfs_photos` (2.5 T), `/mnt/nextcloud` (1.5 T), `/mnt/vm` (1.6 T). All are served by 192.168.50.10.

## 1. The big picture

```bash
df -hT -x tmpfs -x devtmpfs -x squashfs
```

| Mount | Device | Size | Used | Free | Type |
|---|---|---|---|---|---|
| `/` | nvme0n1p3 | 475 G | 282 G (60%) | 189 G | btrfs |
| `/boot` | nvme0n1p2 | 2.0 G | 605 M (34%) | 1.2 G | ext4 |
| `/boot/efi` | nvme0n1p1 | 599 M | 20 M (4%) | 580 M | vfat |

Ground truth from btrfs, which is the only number that matters:

```bash
sudo btrfs filesystem usage /
# Data,single:  Size 282.00GiB  Used 273.93GiB (97.14%)
# Metadata,DUP: Size 6.00GiB    Used 3.67GiB
# Free (estimated): 188.36GiB
```

## 2. Where the space goes

The `-x` flag is essential here: without it `du` walks straight into the NFS mounts and reports 1.6 T for `/home`. Use `du -xhd1` so it stays on the btrfs filesystem.

```bash
du -xhd1 / 2>/dev/null | sort -rh | head -20
du -xhd1 /home/moo 2>/dev/null | sort -rh | head -25
```

**Root side, 104 G** (`/home` is a separate mount, so `du -x /` excludes it):

| Path | Size | Contents |
|---|---|---|
| `/root/models` | 57 G | local LLM weights: `ornith-1.5-35b-uncensored` 22 G, `qwen3.6-35b-hauhau-aggressive` 21 G, two Gemma 4 12B variants 7.3 G + 7.1 G |
| `/usr` | 30 G | normal for this tooling load |
| `/var` | 11 G | flatpak runtime 5.8 G, `/var/tmp` 4.2 G |
| `/opt` | 3.3 G | |

`/var/tmp` is the interesting one: 2.6 G of `buildah-cache-1000` and 1.6 G of `moo-ghidra` scratch, both disposable.

**Home side, 306 G logical:**

| Path | Size | Contents |
|---|---|---|
| `archive/` | 83 G | models 21 G, installers 20 G, ComfyUI 17 G, `samsung-tv-t6500-2026-10` 9.6 G, games 5.2 G |
| `.cache/` | 74 G | **uv 48 G** (47 G of it in `archive-v0`), tinygrad 14 G, pip 2.6 G, browsers ~5 G |
| `.local/` | 58 G | **Steam 34 G**, podman containers 15 G |
| `.var/` | 33 G | **32 G is an orphaned flatpak Steam tree** (see below) |
| `sessions/` | 8.9 G | dated working dirs, top four 1.1 to 1.6 G each |
| `Downloads/` | 8.7 G | |
| `Music/` | 8.3 G | |
| `.config/`, `.npm/`, `diskos/` | 6.4 / 5.1 / 4.2 G | |

## 3. Gotcha: `du` reports apparent size, so it badly overstates this disk

`du -x` sums to about 410 G (104 G root side + 306 G home side) while btrfs says 273.9 GiB is used. The gap is `compress=zstd:1`, and it is **not** uniform: it depends entirely on how compressible a tree is.

First, establish what `du` is even reporting, by comparing block count against apparent size:

```bash
for d in ~/.cache/tinygrad ~/.cache/pip ~/.local/share/Steam/steamapps/common/Stray ~/archive/ComfyUI ~/sessions; do
  b=$(du -sh "$d" | cut -f1); a=$(du -sh --apparent-size "$d" | cut -f1); echo "$d blocks=$b apparent=$a"
done
# tinygrad      blocks=14G    apparent=14G
# pip           blocks=2.6G   apparent=2.6G
# Stray         blocks=6.2G   apparent=6.2G
# ComfyUI       blocks=17G    apparent=16G
# sessions      blocks=8.9G   apparent=8.8G
```

`blocks == apparent` everywhere, so on this system `du` is **not** reporting compressed disk blocks. It is reporting file lengths. Never read a `du` total here as "space on disk"; always cross-check with `df` or `btrfs filesystem usage`.

How wrong it can be, measured (see sections 6 and 7): an unpacked-Python cache compressed **6.4x**, while game assets landed near **2x**. One overall ratio does not exist, which is why a single "du overstates by a third" figure is misleading. The honest rule is per-tree measurement.

`compsize` could not be used to get authoritative ratios: it hits `SEARCH_V2: Operation not permitted` on this kernel (btrfs-progs v7.1 against 7.3.3-100.fc43), even on directories the user owns, and it aborts entirely on the NFS mounts.

**Use `btrfs filesystem du -s` instead.** It works on this box, uses a different ioctl, and prints exactly what is needed:

```bash
btrfs filesystem du -s /home/moo/archive/installers
#      Total   Exclusive  Set shared  Filename
#   19.74GiB     19.74GiB       0.00B  /home/moo/archive/installers
```

`Total` is apparent, `Exclusive` is the real blocks on disk. Run this before any future cleanup instead of arguing from `du`. It also settles the per-file case, since it accepts a list, and it showed the ISO directory at 1:1 (19.74 GiB apparent, 19.74 GiB exclusive) because ISO images are already compressed.

## 4. The find: two Steam trees, one Steam

`du` showed Steam in two places at once. Confirming what that actually means:

```bash
ls -ld ~/.local/share/Steam ~/.var/app/com.valvesoftware.Steam
readlink -f ~/.local/share/Steam ~/.var/app/com.valvesoftware.Steam
rpm -q steam                     # steam-1.0.0.87-4.fc43.x86_64
which steam                      # /usr/bin/steam -> /usr/lib/steam/bin_steam.sh
flatpak list --app --columns=application
flatpak info com.valvesoftware.Steam
# error: com.valvesoftware.Steam/*unspecified*/*unspecified* not installed
```

Both paths are **real directories**, not symlinks, each with its own `libraryfolders.vdf` pointing at itself. But only the native install has a program:

| | Native | Flatpak |
|---|---|---|
| Program | rpm `steam-1.0.0.87-4.fc43` | **not installed** |
| Data | `~/.local/share/Steam`, 34 G | `~/.var/app/com.valvesoftware.Steam`, 32 G |
| Last activity | today, 6,778 files changed since 2026-11-01 | **2026-05-22**, six months stale |

This is the classic flatpak leftover: the app was removed without `--delete-data` (or "keep data" was accepted), so the sandbox data survived the uninstall. Cross-checking `~/.var/app/*` against `flatpak list` shows Steam is the **only** orphaned app directory. (`net.davidotek.pupgui2` is installed but has no data dir yet, which is harmless.)

### What is inside the orphan

```bash
du -sh ~/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/common/*
```

| Item | Size | Note |
|---|---|---|
| Hollow Knight: Silksong | 7.7 G | same size as the native copy, a duplicate |
| Rain World | 4.1 G | only copy, missing from native |
| A Space for the Unbound | 2.4 G | only copy, missing from native |
| Proton 8.0 | 2.3 G | superseded by Proton 11 natively |
| Proton Hotfix / Experimental / 10.0 / 9.0 / runtimes | ~6 G | all duplicated natively |
| Typer Shark! Deluxe | small | only copy |

Native library for comparison: Silksong, Skul, Stray, Dead Cells, Proton 9/10/11, runtimes.

### Are there saves to lose?

This decides whether deletion is free. Checked both places a Proton game stores data:

```bash
# Steam-side saves
du -sh ~/.var/app/com.valvesoftware.Steam/.local/share/Steam/userdata/1006385347
ls -la ~/.var/app/com.valvesoftware.Steam/.local/share/Steam/userdata/1006385347/312520

# Proton prefix saves
ls ~/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/compatdata/312520/pfx/drive_c/users/steamuser
find .../drive_c/users -type f -newermt 2026-04-01 \( -name '*.sav' -o -name '*.dat' -o -name '*.json' \)
```

Findings:

- `userdata/.../312520` and `.../1201270` are **4.0 K each**, containing only `remotecache.vdf`. No `remote/` save folder exists.
- The compatdata prefixes exist but are bare Proton skeletons: `Saved Games` is empty, `Documents` holds nothing, and the save-name `find` returned **zero** files.
- `Typer Shark` has no userdata dir at all.

So the orphan holds no saves. Deleting it costs the *installed copies* of Rain World, A Space for the Unbound and Typer Shark, all re-downloadable from the user's Steam library, and nothing irreplaceable.

Note on the app IDs, for future reference: 1030300 Silksong, 312520 Rain World, 1201270 A Space for the Unbound, 1332010 Stray, 588650 Dead Cells, 3450 Typer Shark, 1147560 Skul. Names come from `awk -F'"' '/"name"/ {print $4}'` over each `appmanifest_*.acf`; do not guess IDs from memory.

## 5. Reclaimable, ranked

`Apparent` is what `du` shows. `On disk` is what actually frees, and it is only known after measuring. Two rows are now measured, so the table no longer pretends they are equal.

| Item | Apparent | On disk (measured) | Risk |
|---|---|---|---|
| ~~Orphaned flatpak Steam tree~~ | 32 G | **15.0 GiB** | **done** (section 6) |
| ~~`uv` cache `~/.cache/uv`~~ | 48 G | **7.3 GiB** | **done** (section 7) |
| `archive/installers` | 20 G | unknown, probably near 1:1 | old installers, judgement call |
| tinygrad cache | 14 G | unknown | may be weights, check before deleting |
| `/var/tmp` buildah cache + ghidra | 4.2 G | unknown | disposable scratch |
| pip cache | 2.6 G | unknown, likely tiny (compressed wheels) | `pip cache purge` |
| `/root/models` | 57 G | near 1:1, model weights do not compress | user's call, not a cache |

## 6. Deletion performed: flatpak Steam orphan

Authorised by the user after the save-data check above. Safety checks first, then remove:

```bash
S=/home/moo/.var/app/com.valvesoftware.Steam
case "$S" in /home/moo/.var/app/com.valvesoftware.Steam) ;; *) exit 1 ;; esac
test -d "$S"
flatpak info com.valvesoftware.Steam >/dev/null 2>&1 && exit 1   # refuse if app reinstalled
findmnt -rn -T "$S"        # confirms no mount point or nested mount
time rm -rf --one-file-system "$S"
```

Result, measured:

| | Before | After |
|---|---|---|
| `df` used | 282 G (60%) | 267 G (57%) |
| `df` free | 189 G | 204 G |
| btrfs Used | 281.30 GiB | 266.28 GiB |

- **Freed 15.0 GiB on disk from 32 G of `du`**, so this tree compressed at roughly 47%. Game assets are already compressed, so `zstd:1` had almost nothing to squeeze. Do not expect the ~33% overall figure on game data.
- `rm -rf` took **4.055 s** (measured).
- `~/.var/app` now holds four dirs, all matching an installed flatpak. Native Steam is untouched at 34 G.

### Backup taken first

```bash
B=/home/moo/archive/steam-flatpak-orphan-backup-2026-11-20
tar -cf "$B/steam-flatpak-small-data.tar" -C "$S" \
  .local/share/Steam/userdata \
  .local/share/Steam/steamapps/appmanifest_*.acf \
  .local/share/Steam/steamapps/libraryfolders.vdf \
  config data
gzip -9 "$B/steam-flatpak-small-data.tar"
```

The result is `~/archive/steam-flatpak-orphan-backup-2026-11-20/steam-flatpak-small-data.tar.gz`, **6.9 MB, 178 entries** (160 in `userdata`). It holds the save metadata, the app manifests (a record of what was installed) and the library config, but not the 30 G of game files, since those are re-downloadable.

### Dead end worth remembering: `tar --exclude` with `-C dir .`

The first backup attempt used the natural form, `cd "$S"; tar -cf out.tar --exclude='.local/share/Steam/steamapps/common' ... .`. The excludes **did not match**, because with `-C` plus a `.` operand tar stores members as `./.local/...`, and the patterns were written without the `./`. The result was that tar began archiving all 32 G; it was killed after 180 s having written a 3.7 GB partial tar plus a 1.6 GB partial zst. Both were removed. The fix is to list the wanted paths explicitly instead of excluding the unwanted ones; that needs no pattern matching and cannot silently do the wrong thing.

Related trap: `pkill -f <pattern>` matches the `bash -c` command line running it, so cleaning up that job killed its own shell twice (exit 143). Use `pkill -f` on a pattern that cannot appear in the invoking command, or kill by PID.

## 7. Deletion performed: `uv` cache

Authorised after section 5. Checked for running `uv` processes first (`pgrep -af '/uv '`), then:

```bash
uv --version          # uv 0.11.6 (x86_64-unknown-linux-gnu)
time uv cache clean
# Clearing cache at: /home/moo/.cache/uv
# Removed 249355 files (46.5GiB)
# real 0m6.046s
```

Measured effect:

| | Before | After |
|---|---|---|
| `df` used | 267 G (57%) | 260 G (56%) |
| `df` free | 204 G | 210 G |
| btrfs Used | 266.19 GiB | 258.89 GiB |

**46.5 GiB apparent became 7.30 GiB on disk, a 6.4x compression ratio.** The cache was unpacked Python source and metadata, exactly the kind of data `zstd:1` eats. Repeated reads of `btrfs filesystem usage` minutes later showed 258.89 GiB, so this is real and not delayed-ref lag.

This is the correction to flag for the next audit: the "48 G `uv` cache" headline was **apparent size**, and the actual reclaimable amount was about 7 GiB. Sizing reclaim from `du` output alone would have oversold it by 6x. Game data behaves the opposite way (section 6, 32 G apparent to 15 GiB disk).

## 8. What was not done

- **Both cleanup targets were executed**: the flatpak Steam orphan (section 6) and the `uv` cache (section 7). Everything else listed in section 5 was left in place.
- **No whole-filesystem compression ratio**, because `compsize` is blocked by `SEARCH_V2: Operation not permitted` on this kernel. Two per-tree ratios were measured instead: 2.1x for the Steam tree, 6.4x for the `uv` cache.
- **No measurement of the remaining rows** in section 5. `archive/installers`, tinygrad, `/var/tmp` and the pip cache are still unknown on-disk sizes, and the pip cache is likely far smaller in real terms than its 2.6 G apparent figure.
- **No judgement on `archive/` or `/root/models`**, since those hold real data, not caches.
- **The native and flatpak Steam libraries were not compared file-by-file**, only by stated size and app IDs. This no longer matters, since the flatpak copy is gone.
- **No verification that a project still builds** after the `uv` cache clean. `uv` re-downloads on demand, so the first build after this will be slow, but that was not tested.

## Session outcome

| Step | Apparent | Freed on disk |
|---|---|---|
| Flatpak Steam orphan | 32 G | 15.0 GiB |
| `uv` cache clean | 46.5 GiB | 7.3 GiB |
| **Total** | **~79 G** | **22.3 GiB** |

Disk went from 282 G used / 189 G free (60%) to **260 G used / 210 G free (56%)**. A 79 G "reclaimable" headline delivered 22 GiB, which is the single most useful lesson here.

## 9. Appendix: what is in `archive/installers`

Inspected at the user's request. **19.74 GiB real on disk**, and unlike the caches it is 1:1 with apparent size, because ISO images are already compressed.

| File | Real | mtime | Identity |
|---|---|---|---|
| `iso/windows11-iot-enterptrise-25h2.iso` | 6.82 GiB | 2026-06-26 | Windows 11 IoT Enterprise 25H2 x64, label `CENA_X64FREO_EN-US_DV9`. Filename has a typo, `enterptrise` |
| `iso/ubuntu-24.04.4-desktop-amd64.iso` | 6.20 GiB | 2026-02-18 | official Ubuntu 24.04.4 LTS desktop, label `Ubuntu 24.04.4 LTS amd64`. Superseded point release |
| `iso/Tiny11Core-25H2-English-Pro-2026-07-05.iso` | 2.96 GiB | 2026-09-20 | Tiny11 Core, a community-debloated Windows 11 build (NTDEV). **Unofficial** image |
| `iso/rhre-20260209.iso` | 2.50 GiB | 2026-06-14 | GPT disk image, not ISO 9660: BIOS boot 1 M, EFI 50 M, two Linux fs (250 M + 2.2 G). Strings show `vmlinuz-6.17.10-100.fc41.x86_64`, so a Fedora 41 x86_64 system image. No label; purpose not identified |
| `Nusantara-v5.8-13-selene-Gapps-OFFICIAL-11052023-0904.zip` | 1.16 GiB | 2026-08-18 | Nusantara Project Android 13 custom ROM with GApps, codename `selene`. Likely tied to the Redmi work |
| `tsetup.7.1.3.tar.xz` | 75 MiB | 2026-09-02 | Telegram Desktop 7.1.3 tarball |
| `com.vivo.vhome_..._apk` | 32 MiB | 2026-07-27 | Vivo VHome APK from APKMirror |

How the identity was established, since none of it is in the filenames:

```bash
blkid -p iso/*.iso | grep LABEL        # volume labels
file -b iso/rhre-20260209.iso          # DOS/MBR boot sector, GPT, not ISO 9660
fdisk -l iso/rhre-20260209.iso         # partition layout
strings -n 6 iso/rhre-20260209.iso | grep -E 'vmlinuz'   # distro fingerprint
btrfs filesystem du -s iso/*.iso       # real on-disk size per file
```

Reclaimable here is real, not apparent: the Ubuntu ISO (6.20 GiB) is a superseded point release, and Tiny11 Core (2.96 GiB) duplicates the purpose of the official Windows image. Removing those two frees 9.16 GiB. Nothing was deleted; the user was asked first.

## References

No external sources were used. Every figure here came from on-box commands against the local filesystem. Related note: [[home-disk-usage-audit-and-log-retention-2026-11-06]] covers the `home` NixOS host, a different machine with different tooling (Nix, k3s, journald).
