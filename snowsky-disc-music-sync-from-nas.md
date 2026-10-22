---
type: how-to
tags: [fiio, snowsky-disc, diskos, music, rsync, nas, nfs, fat32, fsck, dedup, flac]
created: 2026-10-19
last_verified: 2026-10-22
status: current
---

# Syncing the NAS music library to the Snowsky Disc (and cleaning duplicates)

Source: NAS `192.168.50.10:/mnt/data/photos/music` (NFS on fedora at `~/nfs_photos/music`, ~26 GB, ~830 audio files). Target: the Disc's SD card (FAT32, label `STB-STORAGE`, 59.5 GiB) under `Music/`.

## Sync recipe (USB Storage mode — not SSH)

The Disc has no rsync and its Wi-Fi is 2.4 GHz only; USB Storage exposes the card as a USB mass-storage disk.

1. On the Disc: Working Mode → **USB Storage**, cable to the PC. (Not from USB Audio directly — see the main Snowsky doc; the port stays in host role.)
2. `~/diskos/snowsky-sync.sh` — finds the card by label, mounts it with udisks (`udisksctl mount -b /dev/sdX1` → `/run/media/moo/STB-STORAGE`, options include `utf8`), prints a **dry run**.
3. `~/diskos/snowsky-sync.sh --apply` — runs it; then `udisksctl unmount -b /dev/sdX1`, on the Disc Working Mode → Local Playback (diskOS restarts after USB Storage), Settings → Rescan library.

Core command (the script uses `--exclude-from=~/diskos/snowsky-sync.exclude`):
```bash
/usr/bin/rsync -r --size-only --delete --itemize-changes --exclude-from=snowsky-sync.exclude \
  /home/moo/nfs_photos/music/ /run/media/moo/STB-STORAGE/Music/
```
- `--size-only`: FAT's 2 s timestamps vs. NAS mtimes would otherwise recopy everything.
- `--delete` without `--delete-excluded`: renamed files on the NAS lose their old names on the card; excluded files already on the card are left alone.
- Exclude file: dot-dirs/files, `*.url *.cnf *.sqlite *.mp4`, a 1 KB junk mp3, six duplicate files the user removed from the card, and `*Yiruma*` (kept on the NAS only).
- **Gotcha:** call `/usr/bin/rsync` — the rtk shell hook rewrote `rsync` output into a summary that hid deletions and most additions (first dry run showed 18 adds / 0 deletes; the real one 122 / 40).

## Mid-sync Disc reset → FAT repair

At 16:55:36 the Disc dropped off USB mid-write (kernel: `device offline error`, `lost async page write`, `fat_clusters_flush failed`; then `device descriptor read/64, error -110`). Its UI log showed only `storage: export confirmed` followed by a fresh boot — a hard reset (watchdog/power/cable undetermined). Keep the Disc charging during long syncs.

Recovery:
```bash
sudo fsck.vfat -n /dev/sda1        # read-only: 11 files with chains into free clusters, 490 MB orphan chains, dirty bit
# every affected file was in the batch being rewritten and present on the NAS -> safe to repair
sudo fsck.vfat -a -w /dev/sda1     # truncates the 11 to 0 bytes, frees orphans into FSCK0000.REC.. at the root
sudo fsck.vfat -n /dev/sda1        # clean
udisksctl mount -b /dev/sda1; rm /run/media/moo/STB-STORAGE/FSCK[0-9][0-9][0-9][0-9].REC
```
Then rerun the same rsync (whole-file copies replace the 17 zero-byte files), and verify everything both runs touched plus the fsck list by full MD5 against the NAS (137 files, 0 mismatches) before unmounting. Final `fsck.vfat -n` clean.

## Duplicate analysis (read-only first, list before delete)

Three tiers, used on both the card (song.db + file list over SSH) and the NAS (local Python with mutagen):
1. **Byte-identical** — MD5, hashed only for files whose sizes collide (cheap over NFS).
2. **Same decoded audio** — FLAC STREAMINFO MD5 (`mutagen.File(p).info.md5_signature`, or bytes 26–42 of the file) → same music even with different tags/art.
3. **Same title+artist, different audio** — compare STREAMINFO (rate/bits/samples→length), size→avg bitrate, Vorbis vendor string (`reference libFLAC x.y` vs `Lavf…` = ffmpeg re-encode), album/date tags. Distinguishes single vs. album masters, remasters, clean edits, and suspect rips (e.g. a 48 kHz/24-bit `Lavf` file with no album tag next to an official 44.1/16).

Card result: 15 removed (12 identical, 3 same-audio), then 3 same-master Skastra copies (kept the libFLAC singles), then all 22 Yiruma tracks. NAS result: 1 identical + 9 lower-res Telegram copies of YOASOBI *THE BOOK* (kept the 96 kHz/24-bit album) deleted; 7 album zips (each member matched name+size against its extracted folder) + a 25 MiB split-RAR part moved to `~/nfs_photos/music-archives/`.

Deleting on the card over SSH: diskOS's `rm` is a guard wrapper that refuses anything under `/tmp/sdcard` (protects against a stock-player `rm -rf` bug) yet exits 0 — use `/bin/busybox rm -f -- <exact path>` and verify with a re-listing.

## Library cleanup after deletions/renames

The scanner prunes rows whose files vanished — unless a skipped dot-directory blocked it: `.Trash-1000` (Linux file manager) and `Music/.thumbnails` both set `g_prune_blocked`. Fixed in the fork (`69e3f04`, `2008afd`: a dot-dir blocks only if songs are indexed under it). On older builds: delete those dirs (`/bin/busybox rm -rf`), then rescan. Check: `sqlite3 /usr/data/fiio/db/song.db 'select count(*) from SONG'` equals the audio-file count on the card (797 at the end).

## 2026-10-22 re-sync after the library reorganization

The NAS library was reorganized into `Artist/Album (Year)/NN - Title` the same day, so nearly every path changed: the dry run showed ~810 adds / ~885 deletes, i.e. a full ~26 GB re-copy (`--delete` removed the old layout first, then it wrote at ~16 MB/s, ~27 min). Added `/CLAUDE.md` to `snowsky-sync.exclude` (the library root now holds an agent-instructions file). `*Yiruma*` still skips that artist; a tag scan (mutagen, artist/albumartist/composer/album/title for `yiruma|이루마`) confirmed no Yiruma tracks live outside `Yiruma/`.

### Gotcha: case-variant folders collide on FAT
rsync exited 23 on every run: `mkstemp ".../RAN/HOP3 (2011)/..." failed: No such file or directory`, and `--delete` was skipped for some old dirs. Cause: the NAS had both `RAN/` (HOP3, tagged "RAN") and `Ran/` (3 albums, tagged "Ran"). FAT is case-insensitive, so rsync created and deleted the shared folder against itself. Check for this on the source before syncing:
```bash
cd ~/nfs_photos/music && python3 -I -c "
import os,collections
s=collections.defaultdict(set)
for d,ds,fs in os.walk('.'):
    for n in ds+fs: s[os.path.join(d,n).lower()].add(os.path.join(d,n))
print([v for v in s.values() if len(v)>1])"
```
Fix (beets, tag backup first at `~/music-tag-backup/ran-merge-2026-10-22.json`): find exact ids with `beet ls -a -f '$id|$albumartist|$album' albumartist:Ran` (a loose `albumartist:Ran` also matches Kuburan/Sarah Cothran, so use the ids), then
```bash
export BEETSDIR=$HOME/beets-music
beet modify -y 'albumartist:=Ran' artist=RAN albumartist=RAN      # items
beet modify -y -a 'id:188..190' albumartist=RAN                    # albums -> moves folders
beet write 'albumartist:=RAN'; /usr/bin/find . -depth -type d -empty -delete
```
(`rtk find` rejects `-empty -delete`; call `/usr/bin/find`.) Then rerun the sync: card 804 audio files = NAS 804 (minus Yiruma), `fsck.vfat -n` clean.

Leftover on the card: `Music/[Hi-Res][211201]YOASOBI - THE BOOK 2.../` holding only three excluded `*.url` ad shortcuts, so rsync cannot remove the dir (excluded files are kept). Harmless; delete by hand if the stock scanner trips on it.
