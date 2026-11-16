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

## Not verified

- The user's exact 2026-11-14 silent skip (only-decoder, no output) is not proven fixed. It looks like the stock player's preload path and may still happen. The next occurrence should be captured with `/usr/data/fiio/log/fiio_player.log` around the timestamp.
- The fix is hot-loaded, not flashed. A reboot restores the flashed build from 2026-11-11; to keep it, flash with `--ui ui/mq_ui`.
- Up Next still uses the window-function query over the whole queue. It was fine at 814 songs; the newer branch's bounded rewrite was not ported.
- `CHANNELS` and `SONG_MIMETYPE` are 0/empty for all 814 songs and every `DURATION` is 0 in `SONG`. The UI computes durations separately, so this was not changed.

## References

- Internal: [[diskos-boot-starting-state-and-boot-net-errors-2026-11-10]], [[diskos-standards-review-25-commits-adrs-and-ui-naming-2026-11-12]], [[diskos-device-check-2026-11-12-and-choice-picker-scroll-fix]], [[fiio-snowsky-disc-diskos-flash-fedora]].
- Code: `ui/library.c`, `ui/musicdb.c`, `ui/shuffle.h`, `ui/tests/shuffle_test.c`, `ui/tests/uiread_test.c`.
