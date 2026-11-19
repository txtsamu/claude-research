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
- No fix was applied, so no fix time is known.

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

Not established: which component holds the stale entry (MediaProvider's FUSE daemon, the kernel FUSE layer, or the f2fs lower file system), and whether a reboot clears it. No official bug report explains the mechanism.

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

Clearing Media Storage (Settings, or `pm clear com.google.android.providers.media.module`) deletes the index database `external.db` plus the provider's app data, then triggers a rescan of the volume. On Android 11 and later `external.db` lives in the Mainline module `com.google.android.providers.media.module`; before that it lived in `com.android.providers.media`.

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

## What to try (not yet tested)

Ordered by risk, none applied during this session:

1. Reboot the phone. Remounts the FUSE layer and drops any cached directory state. Cheapest and most likely to clear a listing artifact.
2. Restart MediaProvider only: `adb shell am force-stop com.google.android.providers.media.module` (the package exists alongside the legacy `com.android.providers.media`). Caveat: MediaProvider hosts the FUSE daemon on modern Android, so stopping it can leave the storage mount dead until the system respawns it. Reboot is the safer version of the same idea.
3. Clear the file manager app's cache. If the duplicate is painted from a cached listing in the app rather than from `readdir`, this alone fixes the display. It does not explain the `find` result though.
4. `adb shell pm clear com.google.android.providers.media.module` as a last resort. Rebuilds MediaStore from the files on disk. Files are not touched, but see "Impact of rebuilding MediaStore" for what is actually lost. It is not a fix for this symptom.

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

## Related

- [[redmi-note-12-pro-ruby-apple-music-192khz-jack-vs-usb-dac]]
- [[redmi-10-selene-dac-compat-and-dap-setup-research]]
