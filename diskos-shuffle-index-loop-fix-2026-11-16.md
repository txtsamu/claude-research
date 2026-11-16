---
type: troubleshooting
tags: [diskos, snowsky-disc, shuffle, mq_player, mq_ui, infinite-loop, sqlite, hotload, host-tests]
created: 2026-11-16
last_verified: 2026-11-16
status: current
---

# diskOS: Shuffle start past the player's queue hangs the stock player (2026-11-16)

Repo `/home/moo/diskos/diskos`, branch `main` (also pushed `dev`), commit `94de427` on top of `5d5093a`. Related: [[diskos-boot-starting-state-and-boot-net-errors-2026-11-10]], [[diskos-standards-review-25-commits-adrs-and-ui-naming-2026-11-12]], [[fiio-snowsky-disc-diskos-flash-fedora]].

## Request

The user said songs play after boot, but tapping Shuffle in the Songs screen "crashes" the device: "it keeps playing next song but no music playing like skipping track over and over". The session goal was broader: find bugs and weird behavior on the device, fix them, commit, push, and summarize.

## What the device showed first

The Disc was reachable over key SSH on port 2222 and healthy: 24 minutes uptime, `mq_ui` and `mq_player` alive, no fatal-signal, OOM, or watchdog restart in `/usr/data/diskos_boot.log`, `/usr/data/diskos_journal.log`, or `/usr/data/fiio/log/process_failed.txt` (last restart entry Oct 31). A normal Songs > Shuffle at 09:47 worked: frame `play(build) type=1 pos=26`, 814-song queue, "Aku Tenang" played, Up Next opened fine.

The previous crash evidence was in `fiio_player.log` from 2026-11-14: at 14:12:03-14:12:25 the player advanced six tracks every 3-5 seconds with `init handler only decoder!` and no `init handler all`, then a 4:26 track reached `position > duration` with no audible output. That is the user's "skipping with no music" pattern. It is the stock player's preload path, not a UI process crash.

## Confirmed bug: an out-of-range play-list index hangs the player

While probing the shuffle start index, this frame on an 814-song list:

```text
0100001003E70001   (type 1, index 999)
```

sent the stock player into an infinite loop:

```text
play song, query sql: select POS_ID from LIST_SONG_3 where ID = 0
play song, do sql: drop table LIST_SONG_3
```

`grep -c "drop table LIST_SONG_3"` went from 193 to 857 in about 40 seconds. `mq_player` stayed alive and PCM kept its last state, but no new track started. A pause (`0201000C0000`) and a valid list play (`0100001000000001`) did not break it; only a reboot recovered. This is severe: any stale start index can hang playback until power-cycle.

The UI risk was in `ui/library.c`:

```c
int pos = 1;
if(mode == 1 && g_count > 1 && lt != 2) pos = 1 + (rand() % g_count);
```

`g_count` is the UI's loaded count. The player's source list is `LIST_SONG_0`. The two can differ after a scan, a removed file, or a busy DB, and the UI then sends an index the player does not have.

## Fix (commit 94de427)

- New `ui/shuffle.h`: `shuffle_start(mode, list_type, shown, player_rows, r)` returns 1 for sequential, artist plans, and fewer than two rows. Otherwise it clamps the random start to `min(shown, player_rows)`.
- `ui/musicdb.c`/`.h`: `mdb_player_list_count()` reads `COUNT(*) FROM LIST_SONG_0` over the existing read-only connection. Zero means unknown, busy, or no list yet.
- `ui/library.c`: `play_list_mode()` now calls `shuffle_start(mode, lt, g_count, mdb_player_list_count(), (unsigned)rand())`. Albums and artists keep their existing paths.
- `comments.md`: both sections explain the hang and the fallback.
- Tests: `ui/tests/shuffle_test.c` (13 checks) and a `LIST_SONG_0` count case in `ui/tests/uiread_test.c`; both wired into the Makefile.

The clamp keeps a random start when the counts agree, and falls back to 1 when the player count is unavailable, so the UI can no longer send an index past the player's list.

## Verification

Host suite:

```text
make -C ui/tests run    exit 0
PASS shuffle (0 failures)
uiread_test: ALL PASS
```

Cross-build with the pinned builder:

```text
podman run --rm --userns=keep-id -v "$PWD:/src:Z" localhost/diskos-ui-builder:latest \
  sh -c 'cd /src/ui && CROSS=/opt/mipsel-n2008-musl-cross/bin/mipsel-linux-musl- make'
artifact: mq_ui
md5: 8bbb8acb083362f5b9dc4435967f32e2
size: 4343272
```

Hot-load and device check:

```text
diskos-hotload.sh ui/mq_ui     -> ok=1 attempts=1
readlink /proc/$(pidof mq_ui)/exe -> /usr/data/mq_ui
md5sum /usr/data/mq_ui           -> 8bbb8acb083362f5b9dc4435967f32e2
Songs > Shuffle                  -> play(build) type=1 pos=216 (814 rows)
player log                       -> init handler all, audio_track_create ok
/proc/asound/card0/pcm3p/sub0/status -> state: RUNNING
```

Final device state: 9 minutes uptime after the recovery reboot, new UI running, `PLAY_MODE=1`, `PLAY_GAP=0`, PCM RUNNING, no test tools left on the device.

## Gotchas

- `scp` fails with this dropbear (`/usr/libexec/sftp-server: not found`). Use `ssh disc 'cat file' > local`.
- The builder's compiler is not on `PATH`; use `/opt/mipsel-n2008-musl-cross/bin/mipsel-linux-musl-`.
- `ui/mqsend.c` has no built binary and no Makefile target. Build it in the same container for one-off frames.
- An invalid play-list frame hangs the stock player. Only a reboot recovered; pause and a valid play did not.
- I set `PLAY_GAP=1` while testing gapless and restored it to 0. The player DB and the UI config both showed 1 at one point.

## Follow-up: why DURATION was 0

The stock `song.db` had no `TITLE_TAG` column and every metadata column was 0. That is the stock player's scanner schema. diskOS's scanner (`ui/scanner.c`) adds `TITLE_TAG`, computes `DURATION` with `audio_duration_ms_cancel()` from `audiodur.h`, and writes it. It had not run on this database.

Quick Settings > Rescan ran it:

```text
scanner: merged 815 songs, skipped 0 unreadable file(s), scan_err=0
```

After the scan: `TITLE_TAG` exists, `DURATION` is filled for 813 of 815 rows (max 964400 ms), and the count rose from 814 to 815 because the scan indexed one Opus file the stock DB did not have. `SAMPLE_RATE`, `BIT_PER_SAMPLE`, `CHANNELS` and `BIT_RATE` stay 0 because `INS_SONG` hardcodes them and the UI reads playback format elsewhere. PCM stayed RUNNING during the scan.

Two rows stayed at 0, and both files had valid durations in ffprobe: the 969 KB CBR MP3 is 60.481 s, the 4.2 MB Opus is 249.588 s. The parser had two gaps:

- `ad_mp3()` only used a Xing/Info or VBRI header. A CBR file with neither returned 0.
- `ad_opus()` required the OpusTags packet to end on the last segment of its page, rejected granule 0 on a page where no packet completed, and rejected packets over 5760 samples. This file has the tags and the first audio packet on the same page, granule 0 on that page, and a 32-frame 640 ms packet.

Commit `548c3c8` fixes both:

- MP3 without a VBR header falls back to `(end - first_frame) * 8 / first_frame_bitrate`.
- Opus allows the tags packet to end early, allows granule 0 with a pending packet, and calls a new `ad_opus_last()` fallback when the strict walk returns 0 or `AD_DEFERRED`. That fallback reads the last CRC-valid page of the same serial and uses `(granule - pre_skip) * 1000 / 48000`.

Host check against ffmpeg-generated FLAC, Opus, Vorbis, M4A, WAV, AIFF and three MP3 variants: every parser result was within 33 ms of ffprobe (25 ms for Opus due to pre-skip). The two problem files: MP3 60473 ms (ffprobe 60481), Opus 249581 ms (ffprobe 249587).

Rebuilt UI `e35dc510361771cdb060b203f158266b` (4345304 bytes), hot-loaded, Quick Settings > Rescan (`scanner: merged 815 songs`), and the zeros went from 2 to 0: the MP3 and Opus rows now hold 60473 and 249581 ms.

## Release: v1.2.1-fork.5

`main` and `dev` are at `ade7ee1` (the changelog commit on top of `548c3c8`). Tag `v1.2.1-fork.5` is pushed and the GitHub release is live as Latest, not a prerelease:

- https://github.com/txtsamu/diskos/releases/tag/v1.2.1-fork.5
- Title: `diskOS 1.2.1 fork build 5 (stable): Shuffle hang and duration fixes`
- Assets: `mq_ui` (4346184 bytes, md5 `2557afb5f30364cb4a45a0289796575d`, built with `-DDISKOS_TEST_OUTPUTS`) and `SHA256SUMS`; `sha256sum -c` passes.
- The attached binary and the device build are the same source; the device build was made without the test-only UI rows.

The installer built a public image from the same source (`diskos_public.bin`, 100663392 bytes, md5 `a0cf4071b69032824310333bc5e76fb0`) and the flash was running when the release was published. Update this section with the flash result.

## Not verified

- The user's exact 2026-11-14 silent skip (only-decoder, no output) is not proven fixed. It looks like the stock player's preload path and may still happen. The next occurrence should be captured with `/usr/data/fiio/log/fiio_player.log` around the timestamp.
- The fix is hot-loaded, not flashed. A reboot restores the flashed build from 2026-11-11; to keep it, flash with `--ui ui/mq_ui`.
- Up Next still uses the window-function query over the whole queue. It was fine at 814 songs; the newer branch's bounded rewrite was not ported.
- The duration parser has no host fixture test. It was checked against ffmpeg-generated files and the two real files, not fuzzed or tried against truncated/corrupt Ogg pages.
- After the rescan the library has 815 songs. The extra one is the Opus file the stock DB was missing; this was a side effect of the rescan, not a code change.

## References

- Internal: [[diskos-boot-starting-state-and-boot-net-errors-2026-11-10]], [[diskos-standards-review-25-commits-adrs-and-ui-naming-2026-11-12]], [[diskos-device-check-2026-11-12-and-choice-picker-scroll-fix]], [[fiio-snowsky-disc-diskos-flash-fedora]].
- Code: `ui/library.c`, `ui/musicdb.c`, `ui/shuffle.h`, `ui/tests/shuffle_test.c`, `ui/tests/uiread_test.c`.
