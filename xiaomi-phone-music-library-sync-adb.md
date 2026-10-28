---
type: how-to
tags: [xiaomi, android, adb, music, nas, nfs, sync]
created: 2026-10-28
last_verified: 2026-10-28
status: current
---

# Syncing the NAS music library to the Xiaomi phone over adb

Phone: Xiaomi `22101316G` (codename `ruby`), USB debugging on, adb serial `rcbqfat495jbu4vw`. Library on the phone: `/sdcard/Music/music` (same `Artist/Album (Year)/NN - Title` layout as the NAS `~/nfs_photos/music`), plus `/sdcard/Music/Telegram`. Players installed: VLC, (Poweramp lyrics add-on), BitChord benchmark build.

## Steps
1. Detect: `lsusb | grep -i xiaomi`; `adb devices -l` (must say `device`, not `unauthorized`). No MTP mount appears under `/run/user/1000/gvfs` when only adb is enabled - fine, use adb.
2. Free space / current state: `adb shell 'df -h /sdcard | tail -1; find /sdcard/Music/music -type f | wc -l'` (72G free, 847 files, 26 GB).
3. There is no rsync/adb-sync on the phone, so compare manifests by relative path + size:
```bash
adb shell 'cd /sdcard/Music/music && find . -type f -printf "%s\t%P\n"' | sort -t$'\t' -k2 > phone.tsv
# NAS side: os.walk ~/nfs_photos/music, skip dot-dirs, *.url *.cnf *.sqlite, root CLAUDE.md -> {relpath: size}
# add = on NAS not phone; changed = size differs; phone-only = on phone not NAS
```
The phone gets the whole library **including Yiruma** (the `*Yiruma*` exclude in `snowsky-sync.exclude` is Disc-only).
4. Copy: for new/changed files `adb push "<NAS file>" "/sdcard/Music/music/<relpath>"` (adb push creates no parent dirs - `adb shell mkdir -p` first). 2026-10-28 there were 0 to push.
5. Mirror deletions with `adb shell "rm -v -- '<path>'"` - mind apostrophes in titles (use double quotes around the remote command, escaped quotes inside).
6. Rescan in the player (VLC/Poweramp): `rm` does not update MediaStore, so deleted tracks may linger until a rescan or reboot.

## 2026-10-28 result
Phone was already identical to the NAS (NAS 842 files, phone 845): 0 adds, 0 size changes. Removed the 2 Dua Lipa "Don't Start Now" duplicates (see [snowsky-disc-music-sync-from-nas.md](snowsky-disc-music-sync-from-nas.md)); the phone-only `CLAUDE.md` (agent-instructions file from an earlier sync) was left in place. Final: 843 files.
