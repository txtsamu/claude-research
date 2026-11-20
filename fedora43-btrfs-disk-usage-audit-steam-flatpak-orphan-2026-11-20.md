---
type: investigation
tags: [disk, btrfs, fedora43, compression, zstd, du, steam, flatpak, uv-cache, podman, disk-usage-audit]
created: 2026-11-20
last_verified: 2026-11-20
status: current
---

# Disk usage audit on the Fedora 43 desktop, and the orphaned flatpak Steam tree

Question: what fills the 475 GB NVMe on this workstation, and what is safe to reclaim? Result: 282 GB used (60%), 189 GB free, not urgent. The main finding is a 32 GB **orphaned flatpak Steam data tree** with no Steam app attached to it, plus 48 GB of `uv` cache. A secondary gotcha: on this box `du` totals overstate disk usage by about a third because btrfs compresses with `zstd:1`, so `du` must never be read as free space.

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

## 3. Gotcha: `du` overstates this disk by roughly a third

`du -x` sums to about 410 G (104 G root side + 306 G home side) while btrfs says 273.9 GiB is used. The ~33% gap is `compress=zstd:1` at work: `du` counts logical file blocks, btrfs stores them compressed. Consequences:

- Never read a `du` total on this box as "space on disk". Cross-check with `df` or `btrfs filesystem usage`.
- The inverse also holds: deleting 100 G of `du` numbers frees less than 100 G on disk.

The attempt to measure the real ratio with `compsize /home` failed. Running it without root hit `Operation not permitted` on root-owned files; running it through `sudo -n` reached the NFS photo mount and aborted with `/home/moo/nfs_photos/.../x.jpg: Not btrfs (or SEARCH_V2 unsupported)`. A clean measurement would need `compsize` pointed at one subvolume at a time with the NFS mounts excluded, or run while the NFS mounts are unmounted. So the one-third figure stays a derived estimate, not a measurement.

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

| Item | Logical | Risk |
|---|---|---|
| `uv` cache `~/.cache/uv` | 48 G | none, `uv cache prune` or `uv cache clean` |
| Orphaned flatpak Steam tree | 32 G | none, installs are re-downloadable, no saves present |
| `archive/installers` | 20 G | old installers, judgement call |
| tinygrad cache | 14 G | may be weights, check before deleting |
| `/var/tmp` buildah cache + ghidra | 4.2 G | disposable scratch |
| pip cache | 2.6 G | `pip cache purge` |
| `/root/models` | 57 G | user's call, not a cache |

Clearing the first six frees roughly 120 G of logical space, somewhere north of 75 G on disk after compression.

## 6. What was not done

- **Nothing was deleted.** This session was read-only inspection; the user was asked before any removal.
- **No precise compression ratio**, because `compsize` failed on the NFS mount (see section 3).
- **No judgement on `archive/` or `/root/models`**, since those hold real data, not caches.
- **The native and flatpak Steam libraries were not compared file-by-file**, only by stated size and app IDs. The 7.7 G Silksong pair is a strong duplicate signal but was not checksummed.

## References

No external sources were used. Every figure here came from on-box commands against the local filesystem. Related note: [[home-disk-usage-audit-and-log-retention-2026-11-06]] covers the `home` NixOS host, a different machine with different tooling (Nix, k3s, journald).
