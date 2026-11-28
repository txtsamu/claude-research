---
type: build-log
tags: [diskos, snowsky-disc, audit, subagents, worktrees, sqlite, wifi, bluetooth, http, ota, timezone, playlists, installer]
created: 2026-11-28
last_verified: 2026-11-28
status: current
---

# Fix the 25 category audit on diskOS `dev` at `2f705ac`

Repo: `txtsamu/diskos`, branch `dev`, base commit `2f705ac`. The new audit is
`claude-research/2026-11-28-codebase-audit-dev-2f705ac.md` inside the repo. It covers 25 bug, concurrency, database
and reliability categories plus an installer portability bonus. The work was split into 11 file-disjoint branches so
subagents could fix and verify in parallel.

Result: `dev` is at `a3fa383`, pushed to `origin/dev`. 23 commits, 50 files, +1,384 / -379.

## Time estimate

Wall clock from the first `date` in the session to the final push:

| Step | Time | Kind |
|---|---|---|
| Create 11 worktrees and copy `ui/third_party/out` | about 2 min (`22:22` to `22:24`) | measured |
| 11 fix agents, in parallel, each cross build and host suite | about 19 min (`22:24` to `22:43`) | measured |
| Merge branches and resolve the one test Makefile overlap | about 5 min, overlapping the agents | measured |
| Clean cross build in the integration tree | about 1 min | measured |
| `make -C ui/tests check` (C and Python) | 34 s (`22:41:30` to `22:42:04`) | measured |
| Docs, final build in `dev`, push | about 3 min | measured |
| Total | about 25 min | measured |

The longest single agent was the database group. The rest overlapped almost completely because every agent owned a
different file set.

## Branch split

All branches start at `2f705ac` and were merged into `audit2/integrate`, then fast-forwarded into `dev`.

| Branch | Commit | Scope |
|---|---|---|
| `audit2/scanner` | `901b494` | scan teardown UAF, cue/iso leaks, CUE sizing, first-scan indexes |
| `audit2/db` | `17e4a93` | song-info read-only connection, re-runnable indexes, expression indexes, queue mutex, PEQ transaction, batched subtracks |
| `audit2/wifi` | `33054bf` | DHCP failure backoff, listener respawn backoff, `/proc` stat guard, `wifi_up.sh` reaping |
| `audit2/lifecycle` | `d0ca2e9` | cardclose re-entry refusal, sync orphan, checkpoint after quiesce |
| `audit2/bt` | `5e019ef` | bounded `bluetoothctl`, scan worker ownership, enable/disable marker |
| `audit2/net` | `d57ea22` | HTTP deadlines, low-speed floor, shared DNS/TLS sessions, OTA verifier timeout |
| `audit2/settings` | `1d23fc6` | TZ RTC clear, M3U import worker, shared suffix index, cached statements |
| `audit2/theme` | `f105399` | Bauhaus row decor O(n) instead of O(n²) |
| `audit2/clocks` | `49e3487` | monotonic mqueue wait and SD lock, netart clock age, config I/O outside lock, tx backoff |
| `audit2/misc` | `24a08e5` | launcher write clamp, tinj flip, monotonic timers, installer file closes |
| `audit2/misc2` | `7ca43b3` | `execv` after fork, reap pool, ISO batch presence, art dedupe, DAC retry cap |
| `audit2/integrate` | `a3fa383` | merges, `CHANGELOG.md`, `docs/UI_ARCHITECTURE.md`, `comments.md` |

## What changed

The full list is in `CHANGELOG.md` under Unreleased, Fixed. The important behavior changes:

- **Scanner:** `g_rows`, `g_cues` and `g_isos` are freed under `g_mu` before `g_active` clears, so a new scan cannot
  race the exiting thread. CUE sheets use `fstat` sizing. The first scan creates the same album, artist, album-artist,
  genre and playlist-name indexes that `mdb_core` creates.
- **Database:** the detached song-info worker reads through `mdb_core_db_ro()`. Index creation is idempotent and
  re-runs after a scan. Expression indexes cover `trim(ALBUM, ' ' || char(9,10,13))` and
  `COALESCE(ALBUM_ARTIST,ARTIST)`. `.m4b` tests use `lower(substr(PATH,-4))='.m4b'` with a matching index. The queue
  handle has its own mutex and `FULLMUTEX`. `mdb_core_close()` uses `sqlite3_close_v2()`. PEQ writes are transactional,
  `mdb_checkpoint()` uses `TRUNCATE`, and subtrack planning batches with a `VALUES` CTE.
- **Wi-Fi:** a persistent `FAILED` state backs off 1 s, 2 s, 4 s, 8 s, 16 s, 30 s. Before this, the 100 ms supervise
  loop still ran `wpa_cli status` every tick. The `wpa_cli -a` listener respawn backs off after quick exits. A truncated
  `/proc/<pid>/stat` line is rejected. `g_wifi_up_pid` is reaped by the existing 100 ms timer.
- **Bluetooth:** every `bluetoothctl` call has a finite timeout, from 2.5 s for `pidof bluetoothd` to 20 s for
  `devices`. The scan worker owns `g_scan_running` and a late result is discarded by generation. A disable marker plus a
  deferred enable timer stops a late teardown from killing a new enable.
- **HTTP and OTA:** a non-positive timeout becomes `max(60 s, cap / 8 KiB/s + 60 s)`, the low-speed guard is 1 KiB/s
  over 60 s, and `CURLSH` shares DNS and TLS sessions across the per-request threads. The OTA verifier gets 120 s.
- **Lifecycle:** `cardclose_begin()` returns `CARDCLOSE_BUSY` while draining or syncing. Callers arm the machine before
  touching the shared SD quiesce gate, so a refused power request cannot release a restart's quiesce. Checkpoints run
  after quiesce on both paths.
- **Settings and playlists:** returning to Automatic runs `hwclock -w -u` before unlinking `/usr/data/localtime`, and a
  failed theme reload restores the previous zone and RTC. The M3U import runs on a detached worker, reports through a
  200 ms timer, builds one suffix index per import, reuses prepared statements, and keeps `BEGIN IMMEDIATE` around the
  writes only.
- **Rest:** Bauhaus row decoration is O(n), netart treats a future mtime as expired and prunes outside the file lock,
  IPC receive uses `poll` and the transmit queue backs off 50 to 500 ms, the SD mode lock is monotonic, config writes
  leave `g_mu`, `command_spawn_lifetime()` uses `execv` and rejects relative paths, the reap pool is 32, cover art
  waits for a same-key prewarm, the folder browser batches ISO presence, DAC volume recovery is capped, the launcher
  write is clamped, `tinj` flips with `359 - x`, and the installer closes files before unlinking.

## Verification

Clean cross build in the `dev` tree:

```console
$ make -C ui clean
$ PATH=/opt/mipsel-n2008-musl-cross/bin:$PATH make -C ui -j12
...
artifact: mq_ui
md5: 157a0a0e3b713893ebaef4f4052ef67d
size: 5537452
src_md5: 5bfe44ccc162e15f0a023d34bf8b76bb
EXIT=0
```

23 warnings, 0 errors. The warnings are the same pre-existing set in `apps.c`, `bt.c`, `coverart_accent.c`,
`debug_ui.c`, `home.c`, `ipc.c`, `main.c`, `playlistdb.c`, `scanner.c`, `settings.c`, `ui.c` and `weather.c`.

Full host suite, including Python:

```console
$ make -C ui/tests -j12 check
...
EXIT=0
FAIL lines: 0
C test groups: 55
Python COMPLETE lines: 7
```

The new `netart_test` pins the future-mtime behavior and aborts against the old `netart.c`. The new
`command_spawn_test` covers the relative-path refusal and more than 16 reaped children. `coverart_test` covers the
same-key wait. `dacvol_test` covers the retry cap. `wifisup_test` covers the backoff and reset paths. `sdio_test` covers
the marker-failure rollback, and `tests/test_windows_flash.py` covers the bad-magic cleanup.

`git log --oneline 2f705ac..a3fa383` has 23 commits. `dev` and `origin/dev` are level at `a3fa383`.

## Gotchas

- Each worktree needs `ui/third_party/out` copied in, and the `.a` files must be newer than the build scripts. A fresh
  worktree will otherwise try to rebuild freetype and libcurl in every tree.
- The cross compiler is not on the default PATH: `PATH=/opt/mipsel-n2008-musl-cross/bin:$PATH`.
- The audit's suggested `lower(substr(PATH,-5))='.m4b'` is wrong: `substr(PATH,-5)` returns five characters such as
  `o.m4b`. The correct expression is `lower(substr(PATH,-4))='.m4b'`.
- The touch injector flip is `359 - x` and `359 - y`, not `360 - x`. Coordinates are 0..359, so `360` is one past the
  last valid index. `comments.md` had the stale `360` wording and was updated.
- `hwclock -w -u` is the write that makes the RTC agree with a system that has no `/usr/data/localtime`. Plain
  `hwclock -w` writes local time and would preserve the offset bug.
- The host suite runs C binaries and Python scripts. `make -C ui/tests run` covers only the C groups; use `check` for
  both.
- Merge overlap was limited to `ui/tests/Makefile` and auto-merged cleanly. File-disjoint grouping is what made 11
  agents practical.

## Not fixed, deliberately

These audit items remain open. They are real but need a larger change or device data that was not available:

- **`mdb_core_close()` is still never called at shutdown or restart.** The lifecycle agent declined to call it while
  detached art workers and `si_worker` can still hold a SQLite pointer. Closing the connection under them is a
  use-after-free risk. The fix needs a join or a worker shutdown barrier first.
- **`mdb_upnext()` still materializes the queue with `ROW_NUMBER()`.** Only the `LIST_SONG_0(PATH)` and
  `LIST_SONG_3(POS_ID)` indexes were added. Rewriting the query needs proof that the first-row status checks and the
  shuffle mapping stay identical.
- **`mdb_playlist_sync_registry()` still uses `BEGIN IMMEDIATE` on some read-only UI paths.** It lives in
  `playlistdb.c` and performs registry writes, so it cannot simply become `DEFERRED`.
- **No `UNIQUE(PEQ.STYLE_PRESET)` index.** Stock PEQ rows are not in the repo and duplicates are unverified. A UNIQUE
  index that fails would now prevent the DB from opening. The transaction fixes the lost-update race without that risk.
- **The M3U LIKE fallback is unchanged** when the shared suffix index cannot be built. Skipping it would change which
  entries resolve.
- **`fb_cue_seen` is still one query per backing file.** The `scan_cue_files()` callback has no batch form, and changing
  `scanner.c` was outside that branch.
- **The reap pool has a bounded residual.** If all 32 slots are full and a child stays in D-state past 200 ms,
  `command_abort()` returns without queueing it. Blocking longer would defeat the non-blocking contract.

## Not verified

- Nothing was flashed. The Disc was offline the whole session (`ssh disc` gave `No route to host`, and no
  `a108:eaef` device was on USB), so the previous `82ffa18` post-boot checks and every behavior change here are
  unverified on hardware.
- The Wi-Fi backoff cadence, the Bluetooth enable/disable ordering, the `hwclock -w -u` argument support, the M3U
  worker under a real SD walk, and the SD quiesce re-entry path were exercised only by host fakes and the cross build.
- No flash image or installer run was produced from this commit.

## References

No external web sources contributed. The input and conventions came from the repo:

- `claude-research/2026-11-28-codebase-audit-dev-2f705ac.md` in the diskOS repo (the audit being fixed).
- `agents/AGENTS.md` (no comments in source, parallel worktree habits, checkpoint rule).
- `docs/UI_ARCHITECTURE.md` and `comments.md` (module contracts and the comment relocation store, both updated).
- Related notes: [[diskos-codebase-audit-fixes-2026-11-28]],
  [[diskos-architecture-review-seven-findings-2026-11-28]], [[diskos-flash-dev-82ffa18-2026-11-28]].
