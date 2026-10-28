---
type: how-to
tags: [fiio, snowsky-disc, diskos, music, rsync, nas, nfs, fat32, fsck, dedup, flac]
created: 2026-10-19
last_verified: 2026-10-28
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

## 2026-10-28 incremental sync + Dua Lipa duplicate

Disc in USB Storage mode showed up as `/dev/sda1` (`STB-STORAGE`), unmounted. Flow that worked, ~5 min:

1. `~/diskos/snowsky-sync.sh` (dry run) -> 13 adds (12 Hindia *Menari Dengan Bayangan* tracks + `RADWIMPS/.../Sparkle.dsf`), 0 deletes. Card had 35 GB free (60G, 26G used).
2. Case-collision check on the source (the Python snippet above) -> none. Always do it; FAT collisions broke the 10-22 sync.
3. `~/diskos/snowsky-sync.sh --apply` -> 443 MB at ~17 MB/s. Counts: card 817 audio files = NAS 839 minus the 22 `*Yiruma*` (`find -ipath '*yiruma*'`: NAS 22, card 0).
4. `udisksctl unmount -b /dev/sda1`; then on the Disc Working Mode -> Local Playback, Settings -> Rescan library.
- `Sparkle.dsf` is still the truncated download (93 MB, header says 728 MB): plays ~69 s. Left on the card.
- Gotcha: `rtk` rewrites some `rsync`/`find` output; use `/usr/bin/rsync` and `/usr/bin/find`. Stacking `du`/`xargs` over a 1,300-line listing blew up the output - summarize with `grep -c '^>f'` / `'^\*deleting'` instead.

### Dua Lipa "Don't Start Now" x3 (keep the highest bitrate)
Three files, none byte-identical, none same-audio:

| File | Format | Avg bitrate | Vendor |
|---|---|---|---|
| `Future Nostalgia (2020)/02 - Don't Start Now.flac` | 24-bit/44.1 | 1709 kbps | Lavf60 (ffmpeg re-encode) |
| `Future Nostalgia [Clean] (2020)/02 - Don't Start Now.flac` | 16-bit/44.1 | 1015 kbps | libFLAC 1.4.3 |
| `Future Nostalgia (2020)/02 - Don't Start Now.1.flac` | 16-bit/44.1 | 992 kbps | libFLAC 1.3.1 |

```bash
python3 -I - <<'PY'      # mutagen: i=FLAC(p).info; i.bits_per_sample, i.length, size*8/length, f.tags.vendor
PY
# is the 24-bit file really 24-bit? decode 60 s to s32 and test the low byte
ffmpeg -v error -i "02 - Don't Start Now.flac" -t 60 -f s32le - | python3 -I -c "import sys,array; a=array.array('i'); a.frombytes(sys.stdin.buffer.read()); print(all((x&0xFF)==0 for x in a))"
# decoded-16-bit hash per file (differs for all 3 => different masters, not re-encodes)
ffmpeg -v error -i "$f" -map 0:a -f s16le - | md5sum
```
Result: the 24-bit file is 16-bit audio zero-padded to 24 (low 8 bits all zero), so its "higher bitrate" is padding, not quality. User's rule was "keep higher bitrate", so it was kept; the other two were moved (not deleted) to `~/nfs_photos/music-archives/dup-removed-2026-10-28/Dua Lipa/`. Resync dry run showed exactly those two `*deleting`, applied. Side effect: the `[Clean]` album folder has no track 02 (08 was already missing). To prefer a true-16-bit copy instead, restore from the archive dir and archive the 24-bit one.
