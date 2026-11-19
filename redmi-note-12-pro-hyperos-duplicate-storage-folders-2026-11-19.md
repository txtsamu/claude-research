---
type: investigation
tags: [android, hyperos, xiaomi, redmi-note-12-pro, ruby, adb, fuse, sdcard, duplicate-folders, storage, readdir]
created: 2026-11-19
last_verified: 2026-11-19
status: current
---

# Duplicate folder entries at the root of internal storage (Redmi Note 12 Pro, HyperOS 2)

The file manager showed the same folder twice, and opening either copy showed the same content. Diagnosis over `adb` shows the duplication is in the directory listing (two `readdir` entries for one inode), not on disk: no second directory exists, no data is duplicated, and 7 of the 42 root entries are affected.

## Time estimate

- Whole diagnosis: about 10 minutes of `adb shell` probes, in roughly 8 rounds of 1 to 3 commands.
- Each `adb shell` round trip: under a second on USB.
- The one slow command, `adb shell "ls -1R /sdcard | wc -l"` (184,602 lines), took long enough to be backgrounded and was **not timed**. Everything else is instant.
- The independent verification pass and the MediaStore web research ran in the background and were not timed.
- The `pm clear` attempt took under two minutes end to end, including roughly 20 seconds where `adb` lost the device. Not precisely timed.
- No fix succeeded, so no working fix time is known.

## Summary

- Device: Redmi Note 12 Pro 5G, codename `ruby`, Android 14 (SDK 34), HyperOS `OS2.0.18.0.UMOIDXM`. ADB authorized as the `shell` user, no root, bootloader locked.
- Seven names at `/storage/emulated/0` are returned twice by `readdir`: `Android`, `DCIM`, `Download`, `MIUI`, `Movies`, `Music`, `Pictures`. All other 35 entries appear once.
- Both copies of each pair resolve to the **same inode** (`DCIM` is 6889 twice, `Pictures` is 6886 twice, and so on). Same inode means one physical directory, so storage did not double and nothing was lost.
- It is not an `ls` bug: `find` on the real path (not the `/sdcard` symlink) also counts `DCIM` twice, and the count is stable over repeated calls.
- A newly created directory appears exactly once, so the duplication is attached to those specific pre-existing entries, not to the directory as a whole.
- Emulated storage here is **case-insensitive** (`DcIm` and `pictures` both resolve, and `mkdir ZZCase` followed by `mkdir zzcase` fails with `File exists`). So the "two dirs differing only in case" explanation is ruled out too.
- Only the root of internal storage is affected. `DCIM/`, `Download/`, `Android/`, `Pictures/`, `Music/`, `MIUI/`, `Movies/` each list cleanly with no duplicates inside.
- No official AOSP bug report was found. Community reports of the same symptom exist and all describe it as cosmetic, with one important warning: **deleting the "duplicate" deletes the real folder**, because both names point at the same inode.
- A second pass over the same device refuted the symlink explanation and found that two of the commonly suggested `adb` checks give false answers here: `ls -lid` cannot distinguish an alias from a duplicate on a case-insensitive volume, and `find /sdcard -maxdepth 1 -type l` reports the `/sdcard` mount alias itself. Details in "Verification of the symlink theory".
- `pm clear com.google.android.providers.media.module` was then actually run. It returned `Success`, restarted the provider process, and rebuilt nothing: the playlist row kept the same `_id` and all 7 duplicates remained. On this build MediaProvider is an APEX app, and `pm clear` wipes `/data/user/0/...`, not the live database in the APEX data area. See "Attempted rebuild".
- A cold boot does not clear it either. After `adb reboot`, a fresh FUSE daemon and a manual unlock, the listing is byte-identical: 35 visible dirents, the same 7 duplicated. See "Cold boot".

## Environment

```bash
adb devices -l                      # rcbqfat... device usb:1-4 product:ruby_id model:22101316G device:ruby
adb shell getprop ro.product.model  # 22101316G  (Redmi Note 12 Pro 5G, ruby)
adb shell getprop ro.build.version.release   # 14
adb shell getprop ro.build.version.sdk       # 34
adb shell getprop ro.mi.os.version.name      # OS2.0
adb shell getprop ro.build.version.incremental  # OS2.0.18.0.UMOIDXM
adb shell getprop persist.sys.fuse                      # true
adb shell getprop persist.sys.fuse.passthrough.enable   # true
adb shell getprop ro.fuse.bpf.is_running                # false
```

Mount entry:

```
/dev/fuse on /storage/emulated type fuse (rw,lazytime,nosuid,nodev,noexec,noatime,user_id=0,group_id=0,allow_other)
```

## Steps and evidence

### 1. List the root and count name occurrences

```bash
adb shell "ls -1a /sdcard | sort | uniq -c | sort -rn | head -12"
```

```
      2 Pictures
      2 Music
      2 Movies
      2 MIUI
      2 Download
      2 DCIM
      2 Android
      1 ramdump
      1 panoramas
      1 mpv
      1 blockcanary
      1 TachiyomiSY
```

Seven names, each exactly twice.

### 2. Rule out `ls` itself

`/sdcard` is a symlink (`/storage/self/primary`), and `find` does not follow a symlinked starting point, so the first attempt silently returned only the symlink itself. Using the real path:

```bash
adb shell "find /storage/emulated/0 -maxdepth 1 -name DCIM | wc -l"
# 2
adb shell "find /storage/emulated/0 -maxdepth 1 | wc -l"
# 43   (42 entries plus the root itself)
```

Two independent readers (`toybox ls`, `toybox find`) see the duplicate, so it is not an `ls` display quirk.

### 3. Confirm both entries are one directory

```bash
adb shell "ls -i1 /storage/emulated/0 | grep -E 'DCIM|Pictures'"
```

```
   6889 DCIM
   6889 DCIM
   6886 Pictures
   6886 Pictures
```

```bash
adb shell "for d in Android DCIM Download MIUI Movies Music Pictures Documents; do stat -c '%h %i %U %a %n' /storage/emulated/0/\$d; done"
```

```
5 6411 media_rw 2771 /storage/emulated/0/Android
12 6889 u0_a215 2770 /storage/emulated/0/DCIM
19 3661494 u0_a215 2770 /storage/emulated/0/Download
8 1463 u0_a215 2770 /storage/emulated/0/MIUI
5 6887 u0_a215 2770 /storage/emulated/0/Movies
5 2519544 u0_a215 2770 /storage/emulated/0/Music
23 6886 u0_a215 2770 /storage/emulated/0/Pictures
9 6890 u0_a215 2770 /storage/emulated/0/Documents
```

`Documents` is the control: single inode 6890, one listing, clean.

### 4. Rule out a transient cache race

```bash
adb shell "for i in 1 2 3 4 5; do ls -1 /storage/emulated/0 | grep -c -E '^(DCIM|Pictures|Android)\$' | tr '\n' ' '; done"
```

```
6 6 6 6 6
```

Six matches (3 names x 2) on every call, five times in a row. Deterministic, not a race between a cached and a live listing.

### 5. Rule out a newly created entry duplicating

```bash
adb shell "mkdir /storage/emulated/0/zzduptest9; ls -1 /storage/emulated/0 | grep -c zzduptest9"
# 1
```

A fresh directory lists once, so the duplication is tied to the older entries rather than to the parent directory's listing as a whole.

### 6. Rule out two case-variant directories

```bash
adb shell "ls -d /storage/emulated/0/DcIm 2>&1; ls -d /storage/emulated/0/pictures 2>&1"
# /storage/emulated/0/DcIm
# /storage/emulated/0/pictures
adb shell "mkdir /storage/emulated/0/ZZCase; mkdir /storage/emulated/0/zzcase"
# mkdir: '/storage/emulated/0/zzcase': File exists
```

Lookups are case-insensitive and the filesystem refuses a second case variant, so the lower filesystem cannot be holding both `DCIM` and `dcim`. Also, the raw bytes of both duplicate names are identical:

```bash
adb shell "ls -1 /storage/emulated/0 | grep -i '^dcim\$' | od -An -c"
#    D   C   I   M  \n   D   C   I   M  \n
```

### 7. Bound the scope to the root

```bash
adb shell "for d in DCIM Download Android Pictures Music MIUI Movies; do printf '%s: ' \$d; ls -1 /storage/emulated/0/\$d 2>/dev/null | sort | uniq -d | tr '\n' ' '; echo; done"
```

Every line came back empty. No duplicates below the root.

## Interpretation

Two `readdir` results for one name and one inode, only for a fixed set of seven entries, only at the emulated-storage root, deterministic across calls, unaffected by new entries. That is a listing-level artifact in the FUSE stack that serves `/storage/emulated/0`, not a filesystem object and not duplicated data.

Practical consequences:

- Disk usage is unchanged. Same inode, one folder.
- Any app that walks the directory (file managers, media scanners, `du`, backup tools) can see the folder twice.
- **Do not delete the extra copy.** Because both names point at the same inode, removing either one removes the folder. A Reddit reporter learned this the hard way (see References).

What was ruled out, with the evidence above: a second physical directory, a case-variant twin, dual apps or a second storage user (`/storage/emulated/` contains only `0` and `obb`), an external SD card (`sm list-volumes` shows only `emulated;0`), a second MTP volume, `ls` misprinting, and a race between cached and live results.

Not established: which component holds the stale entry (MediaProvider's FUSE daemon, the kernel FUSE layer, or the f2fs lower file system). No official bug report explains the mechanism.

Established after the first write-up: a reboot does not clear it, and `pm clear` on MediaProvider does not rebuild the store on this build. Both were tested, see below.

## Community reports found online

- Reddit, r/AndroidQuestions, "Duplicate folders in file manager": only the default Android folders duplicate, a manually created folder does not, and deleting one copy deletes both. Restarting the phone and reinstalling the file manager did not help for that reporter.
- Android Stack Exchange, "2 folders of same name in internal storage of Oneplus3": two folders with identical name and identical content, unanswered.
- Google Android Help community, "Woke up to lost data, filesystem shows each folder twice".
- XDA, "Why is Android phone's internal storage showing twice on PC in USB-MTP mode": a different surface (MTP exposing two volume IDs) but the same user-visible confusion.
- Syncthing forum, "Folders are displayed twice (Samsung)": gallery-level duplicates after a sync client was added.

The Reddit report is the closest match to what this device does: default folders only, both copies opening the same content, one delete removes both.

## Verification of the symlink theory

A plausible alternative explanation circulating online is that the duplicate is a symlink to the real folder, possibly created by a rogue app. A second independent pass over this device tested that, plus the two `adb` commands usually recommended to prove it.

### All seven names are real directories

```bash
adb shell 'for n in Android DCIM Download MIUI Movies Music Pictures; do d=$(find /storage/emulated/0 -maxdepth 1 -type d -name "$n" | wc -l); l=$(find /storage/emulated/0 -maxdepth 1 -type l -name "$n" | wc -l); echo "$n  dirs=$d  symlinks=$l"; done'
```

```
Android  dirs=2  symlinks=0
DCIM  dirs=2  symlinks=0
Download  dirs=2  symlinks=0
MIUI  dirs=2  symlinks=0
Movies  dirs=2  symlinks=0
Music  dirs=2  symlinks=0
Pictures  dirs=2  symlinks=0
```

`readlink` returns EINVAL (exit 1) for every one of them, and the FUSE layer refuses to create symlinks at that root even for the shell user:

```
ln: cannot create symbolic link from '/storage/emulated/0/qq_probe_t' to '/storage/emulated/0/qq_probe_l': Permission denied
```

### `ls -lid` is not a valid test here

```
adb shell "ls -lid /storage/emulated/0/qq_probe_dir; ls -lid /storage/emulated/0/QQ_PROBE_DIR; ls -lid /storage/emulated/0/Qq_PrObE_dIr"
4571407 ... /storage/emulated/0/qq_probe_dir
4571407 ... /storage/emulated/0/QQ_PROBE_DIR
4571407 ... /storage/emulated/0/Qq_PrObE_dIr
```

One scratch directory, three spellings, one inode. On a case-insensitive volume inode equality is guaranteed for any alias, so "same inode means one directory" proves nothing. It also fails in the opposite direction: without `-L`, `ls -lid /sdcard` reports the link itself (inode 227) instead of its target (inode 5399), which would make a genuine symlink look like a separate directory.

### `find /sdcard -maxdepth 1 -type l` is a false positive here

```bash
adb shell "find /sdcard -maxdepth 1 -type l"
# /sdcard
```

Toybox evaluates the start point and does not follow it, so the only "symlink" reported is the volume alias passed as the argument. On the real path, depths 1 and 2 contain zero symlinks. Likewise, `ls -l /sdcard | grep -- '->'` describes the alias, not the directory contents, so it "finds" a symlink that is not inside the listing at all.

### The listing is the only thing that is doubled

```bash
adb shell 'cd /storage/emulated/0 && set -- DCIM* && echo "argc=$#" && for a in "$@"; do echo "ARG:[$a]"; done'
# argc=2
# ARG:[DCIM]
# ARG:[DCIM]
```

A freshly created directory yields `argc=1`. Shell globbing expands from `readdir`, so the duplicate lives in the directory stream, and every name still resolves to one inode.

### Contents are not empty

| Folder | Entries | Size |
|---|---|---|
| `DCIM` | 10 | not measured |
| `Download` | 178 | 3,147,494 KB |
| `Pictures` | 21 | 139,270 KB |

So the "an alias reports 0 items" reading does not apply. Both rows of every pair open the populated directory.

**Risk:** there is no second object to remove. `rm -rf /storage/emulated/0/Download` deletes the only `Download`, all 178 entries and roughly 3 GB. That matches the user's fear that deleting one deletes both, but the mechanism is different: it deletes one thing, not two.

## Impact of rebuilding MediaStore

Clearing Media Storage (Settings, or `pm clear com.google.android.providers.media.module`) deletes the index database `external.db` plus the provider's app data, then triggers a rescan of the volume. On Android 11 and later `external.db` lives in the Mainline module `com.google.android.providers.media.module`; before that it lived in `com.android.providers.media`. Caveat for this device: the `pm clear` form does nothing here, see "Attempted rebuild" below. The list describes what a real rebuild costs.

### What survives

- Media files themselves, their bytes, and their EXIF/XMP metadata.
- Anything inside app-private storage.
- Cloud copies and Google Photos library state (that lives in the Photos app, not MediaStore).
- Playlists that exist as files (`.m3u`, `.m3u8`, `.pls`) on the volume, because the rescan re-adds them.

### What is lost, because it only existed as database rows

- **Row IDs.** `_id` values are assigned by the database and restart from scratch, so any app holding a MediaStore ID has a stale reference.
- **Playlists stored as rows** in `MediaStore.Audio.Playlists` rather than as files. Each row holds a name and a path, and there is no file to recover it from.
- **Trash state.** Since Android 11, trashed items are renamed to `.trashed-<expiry-epoch>-<name>` on disk with `is_trashed=1` and `date_expires` in the database. Drop the rows and the renamed files stay on disk as hidden dot-files with nothing scheduled to purge them.
- **`is_pending` rows** for in-flight writes, which can leave orphaned staging files.
- **Provenance fields** such as `owner_package_name`, `is_download` and the source/referrer URIs, which are recorded at insert time.
- **`date_added`**, recomputed at scan time for files without EXIF, which reshuffles "recently added" ordering.
- **Derived groupings** (album, artist, genre, `format`/`media_type` codes) are recomputed from tags, so mis-tagged files can land in different buckets than before.
- **Thumbnail caches** kept in the provider's own app data, so the first pass through any gallery re-decodes everything.

Unix timestamps on disk (`date_modified`) are unaffected. The forensic write-up on `external.db` documents the column set, the `.trashed-` rename scheme and the `is_trashed`/`date_expires` pair.

### Visible symptoms during and after the rebuild

- Gallery apps and file managers show few or no media until the scan progresses.
- Custom and even built-in ringtones and notification sounds can disappear from the picker until the system audio is re-indexed. A Stack Exchange report of exactly that needed a forced reindex, not just a reboot.
- MTP browsing from a PC looks sparse for the same reason.
- Sustained CPU and I/O load, some heat and battery drain, for the duration of the scan.

Timing is library-size dependent. One write-up quotes 5 to 30 minutes for a light library and hours for a very large one. On this device the numbers are: 2,619 images, 15 videos, 847 audio rows, one playlist row (the file `PlayMe.m3u8`, so nothing database-only to lose there), 162 GB used and 63 GB free. A previous recursive listing of the whole volume produced 184,602 lines, so expect a long scan and a slow first gallery open, not a five-minute job.

```bash
adb shell "for t in images video audio; do printf '%s ' \$t; content query --uri content://media/external/\$t/media --projection _id 2>/dev/null | wc -l; done"
# images 2619
# video 15
# audio 847
adb shell "content query --uri content://media/external/audio/playlists --projection _id:_display_name"
# Row: 0 _id=1000376972, _display_name=PlayMe.m3u8
```

### Bottom line for this case

A full MediaStore rebuild is the wrong tool for a cosmetic duplicate listing. It cannot repair a `readdir` artifact in the FUSE layer, and it costs the state above for no benefit. Reboot first, and leave the store alone.

## Attempted rebuild

Ran anyway, to see whether the artifact was database-backed. It is not.

Pre-checks, all clear:

```bash
adb shell "for t in images video; do printf 'trashed_%s ' \$t; content query --uri content://media/external/\$t/media --projection _id --where 'is_trashed=1' 2>&1 | grep -c '^Row:'; done"
# trashed_images 0
# trashed_video 0
adb shell "content query --uri content://media/external/file --projection _id --where 'is_pending=1' 2>&1 | grep -c '^Row:'"
# 0
```

No trashed or pending rows, so the database held nothing unrecoverable. Then:

```bash
adb shell pm clear com.google.android.providers.media.module
# Success
```

Immediately afterwards the provider had a new pid (3595 to 16717) and the storage was still mounted, but `adb` dropped off USB for a few seconds and came back as `transport_id=2`. The phone did not reboot (`/proc/uptime` still showed 17.5 days), so this was the FUSE daemon restart taking adbd down with it.

The result:

| Check | Before | After |
|---|---|---|
| Images | 2,619 | 2,619 |
| Videos | 15 | 15 |
| Audio | 847 | 847 |
| Playlist row | `_id=1000376972`, `PlayMe.m3u8` | **same `_id`** |
| Duplicate names at root | 7 | 7 |

The identical playlist `_id` is the decisive one. A rebuilt database that rescanned `PlayMe.m3u8` would have assigned a new rowid. It kept the old one, so the live database was never touched.

### Why `pm clear` was a no-op

MediaProvider on this build is an APEX module:

```
codePath=/apex/com.android.mediaprovider/priv-app/MediaProviderGoogle@372042780
dataDir=/data/user/0/com.google.android.providers.media.module
```

APEX modules keep their live state in the APEX data area, `/data/misc/apexdata/com.android.mediaprovider/`, while `pm clear` empties the ordinary `/data/user/0/...` data directory. The clear succeeded on the empty path and left the real `external.db` alone. Reading the APEX path to confirm directly is denied to the `shell` user, so this is a strong inference from the identical row IDs rather than a byte-level check.

A genuine rebuild would need the database file deleted, which needs root. This device has none: bootloader locked, `ro.debuggable=0`, no `su`. So `pm clear` is the strongest non-root option, and it is not a rebuild on this ROM.

## Cold boot

Rebooted with `adb reboot`, waited for `sys.boot_completed=1`, then unlocked the phone by hand (user 0 sits in `RUNNING_LOCKED` until the first unlock, so `/storage/emulated/0` lists nothing until then; that is normal and not data loss).

Result after a fresh boot, a fresh FUSE daemon and a newly unlocked user:

```
$ adb shell "ls -1 /storage/emulated/0 | wc -l; ls -1a /storage/emulated/0 | wc -l"
35
42
$ adb shell "ls -1 /storage/emulated/0 | sort | uniq -d"
Android
DCIM
Download
MIUI
Movies
Music
Pictures
```

Identical to the pre-reboot state: 35 visible dirents, 42 including dot entries, the same 7 duplicated, and the same media counts (2,619 images, 15 videos, 847 audio, 1 playlist).

So the artifact is not cached state in the running FUSE daemon. It survives a cold boot, which means it is reintroduced from below each time the volume is mounted.

### Where it comes from, and what is still unknown

The mount table shows one FUSE view for the volume and a direct f2fs mount of the same block device for `Android/data` and `Android/obb`:

```
3478 /storage/emulated             fuse
3571 /mnt/pass_through/0/emulated  f2fs
5940 /storage/emulated/0/Android/data  f2fs
6080 /storage/emulated/0/Android/obb   f2fs
```

Every non-`/storage/emulated` path (`/mnt/pass_through/0/emulated/0`, `/mnt/runtime/default/emulated/0`, `/mnt/user/0/emulated/0`, `/mnt/installer/0/emulated/0`) returns nothing readable to the `shell` user, and the bind mounts for `Android/data` and `Android/obb` cannot be walked upwards out of their own roots. So comparing the FUSE listing against the raw f2fs listing would need root, and without that the layer that duplicates the entries cannot be identified.

Best remaining hypothesis, stated as a hypothesis: the volume is case-insensitive, the seven affected names are exactly the directories that get written by apps with inconsistent casing, and an f2fs casefold directory can end up with a legacy dentry alongside a newer one. If `readdir` returns both and the FUSE layer reports the canonical name for both, the visible result is two identical rows for one inode. That would explain the specific seven, the stability across boots, and why untouched directories such as `Documents` are clean. It is unverified and would need `debugfs`/`fsck.f2fs` on the raw partition to settle.

## What to try

1. Reboot. **Tested, no effect.** See "Cold boot".
2. Restart MediaProvider only: `adb shell am force-stop com.google.android.providers.media.module`. Not worth trying. Note that the `pm clear` restart already took `adb` down for about 20 seconds; this is the same hazard with the same result.
3. Clear the file manager app's cache. Only relevant if the app paints a stale listing. The underlying `getdents` stream really is doubled, so this cannot be the whole story.
4. `adb shell pm clear com.google.android.providers.media.module`. **Tested, no-op on this build.** See "Attempted rebuild".
5. Root-level `fsck.f2fs` or a raw `getdents` on `/dev/block/dm-52`. The only route left that could both diagnose and repair the lower file system. It needs an unlocked bootloader, which wipes the device on Xiaomi and is not worth it for a cosmetic artifact.

## Second space theory

The owner's hypothesis: a Xiaomi second space (dual space) was created once and later deleted, and the duplicate folders are leftovers from that. Tested, and it does not explain the doubling.

### What the sources say about deleting a second space

- Xiaomi's own support page states that deleting the second space destroys all app data inside it, and that anything needed must be moved to the first space or a PC first.
- Users do report leftovers after deletion. A Reddit thread on storage staying full after removing a second space is a common shape of complaint, and a Xiaomiui housekeeping guide explicitly tells people to clear residual folders after deleting one.
- No report was found of a deleted second space producing duplicate folder *names* in the main space. The reports are about unreclaimed space and leftover cache, not about doubled listings.

### What the device shows

```
$ adb shell "pm list users"
Users:
	UserInfo{0:Owner:4c13} running
$ adb shell "ls -1 /storage/emulated/"
0
obb
$ adb shell "pm list packages | grep -iE 'secondspace|dualspace|second.space|multiuser'"
(no output)
$ adb shell "grep -c 999 /proc/self/mountinfo"
0
```

Only user 0 exists. There is no second-space package, no `999` mount, and no second entry under `/storage/emulated/`. The space is gone, not half-deleted.

### Why it cannot be the cause

A second space is a separate Android user with its own storage at `/storage/emulated/999`, not a second dentry inside user 0's directory. Deleting it can orphan bytes under `/data/media/999`, and it can leave caches behind, but it cannot make the same directory name appear twice in `/storage/emulated/0`.

Two physical directories with the same name, or the same name in different case, are also impossible here. The lower filesystem itself is case-insensitive, proven on the f2fs bind mount that bypasses FUSE entirely:

```
$ adb shell "mkdir /storage/emulated/0/Android/data/zzcaseA; mkdir /storage/emulated/0/Android/data/ZZCASEA"
mkdir: '/storage/emulated/0/Android/data/ZZCASEA': File exists
```

So casefold is a property of the f2fs directories, not something FUSE emulates on top. No pair of twin directories can exist to be listed.

What the second space may explain is *history*: those folders were created, migrated or restored at some point, which is why they exist and why their timestamps differ. It does not explain two rows for one inode.

### What remains unchecked

Whether orphaned bytes from the old `/data/media/999` still occupy space. Reading `/data/media` needs root. The observable proxy is `/data` usage: 161 GB used, 64 GB free on the 225 GB partition. If the owner ever sees unexplained usage that does not match the visible files, that is where it would be, and it is a storage problem rather than a listing problem.

## References

- [Reddit, r/AndroidQuestions: Duplicate folders in file manager](https://www.reddit.com/r/AndroidQuestions/comments/q7moys/duplicate_folders_in_file_manager/)
- [Android Stack Exchange: 2 folders of same name in internal storage of Oneplus3](https://android.stackexchange.com/questions/215075/2-folders-of-same-name-in-internal-storage-of-oneplus3)
- [Google Android Help community: Woke up to lost data, filesystem shows each folder twice](https://support.google.com/android/thread/205537249/woke-up-to-lost-data-filesystem-shows-each-folder-twice?hl=en)
- [XDA: Why is Android phone's internal storage showing twice on PC in USB-MTP mode](https://xdaforums.com/t/why-is-android-phones-internal-storage-showing-twice-on-pc-in-usb-mtp-mode.4480559/)
- [Syncthing forum: Folders are displayed twice (Samsung)](https://forum.syncthing.net/t/folders-are-displayed-twice-samsung/21384)
- [AOSP: FUSE passthrough](https://source.android.com/docs/core/storage/fuse-passthrough)
- [The Binary Hick: Android's external.db, everything old is new again](https://thebinaryhick.blog/2020/10/19/androids-external-db-everything-old-is-new-again/)
- [Android Stack Exchange: built-in notification tones gone after clearing Media Storage](https://android.stackexchange.com/questions/177165/all-the-built-in-notification-tones-are-now-gone-after-clearing-the-media-storag)
- [CitizenSide: What happens when you clear Android Media Storage data](https://citizenside.com/technology/what-happens-when-you-clear-android-media-storage-data/)
- [iPro+: How to rebuild your phone media database](https://blog.ipro.cc/how-to-rebuild-your-phone-media-database-when-the-gallery-is-broken-android-and-ios/)
- [Simple Gallery issue: support built-in trash of Android 11 and above](https://github.com/SimpleMobileTools/Simple-Gallery/issues/2343)
- [XDA: Android 11 has a hidden Recycle Bin for trashed photos and videos](https://www.xda-developers.com/android-11-hidden-recycle-bin-trashed-photos-videos/)
- [Android Developers: Access media files from shared storage](https://developer.android.com/training/data-storage/shared/media)
- [Xiaomi support: How to delete the Second space](https://www.mi.com/global/support/article/KA-716458/)
- [Xiaomi support: Does the second space take up the storage](https://www.mi.com/global/support/faq/details/KA-492586/)
- [Xiaomiui: Clean exits on MIUI, delete account data and remove leftovers](https://xiaomiui.net/clean-exits-on-miui-delete-account-data-revoke-tokens-and-remove-leftovers-66026/)
- [Reddit r/Xiaomi: storage still full after deleting second space](https://www.reddit.com/r/Xiaomi/comments/oln36w/storage_is_still_full_after_deleting_second_space/)
- [TechBone: Xiaomi delete Second Space](https://www.techbone.net/xiaomi/smartphone/delete-second-space)

## Related

- [[redmi-note-12-pro-ruby-apple-music-192khz-jack-vs-usb-dac]]
- [[redmi-10-selene-dac-compat-and-dap-setup-research]]
