---
type: build-log
tags: [diskos, snowsky-disc, code-audit, concurrency, sqlite, performance, subagents, c, python]
created: 2026-11-28
last_verified: 2026-11-28
status: current
---

# diskOS: fixing the 25-category codebase audit with parallel agents

Repo: `txtsamu/diskos`, branch `main`, fix commit `5b25831` (40 files, +1372/−498).
Audit input: `claude-research/2026-11-28-codebase-audit.md` inside the repo (untracked working copy).

## Time estimate

Measured: the audit file was written at 04:48 WIB and the fix commit landed at 05:26:54 WIB, so
**about 38 minutes end to end** for 9 parallel agents plus integration.

| Step | Time | Kind |
|---|---|---|
| Nine fix agents (parallel, disjoint file ownership) | most of the 38 min | measured span, not per-agent |
| Batch-API follow-up + wiring (`mdb_song_paths`, `mdb_subtrack_present`) | inside the same span | measured span |
| Final `make -C ui -j4` (incremental, mipsel musl) | completed inside the 15 min tool timeout | not separately timed |
| Final `make -C ui/tests -j4 check` (ASan/UBSan + python) | completed inside the 25 min tool timeout | not separately timed |
| Installer suite `python3 -m unittest discover -s tests -q` | 30.7 s reported by unittest | measured |

The device build was not flashed, so no mask-ROM or hardware time applies.

## The request

The user pointed at the audit and asked for every finding to be fixed, with subagents used wherever
the work could run in parallel.

## What was done

The audit covers 25 categories: races, TOCTOU, deadlocks, leaks, corruption, fragmentation, N+1,
missing indexes, full scans, lock contention, long transactions, O(n²), HTTP timeouts, retry storms,
DST, floating point. Work was split by **file ownership**, not by category, so no two agents edited
the same file:

| Agent | Files | Main fixes |
|---|---|---|
| musicdb | `ui/musicdb.c/.h` | 10 indexes, `BEGIN IMMEDIATE` + savepoint helpers, rollback on every path, m3u reads before the transaction, export snapshots rows, join-based materialise, batched path APIs |
| scanner | `ui/scanner.c`, `ui/audiodur.h`, `ui/opustitle.c` | Opus NULL/underflow crash, parse outside the write transaction, 128-row batch commits, hoisted statements, reused 1 MB scratch |
| http | `ui/netart.c`, `weather.c`, `lyrics.c`, `ota.c`, `system.c` | `-t 1` plus poll/MONOTONIC wall-clock kills, `open` then `fstat`, monotonic backoff |
| proc | `ui/launcher.c`, `settings.c`, `ipc.c`, `config.c` | atomic pinned PID, signal-safe alarm, pre-fork `/proc/self/stat`, mutexed config, IPC backoff, Automatic timezone, streaming MD5 |
| main-time | `ui/main.c`, `power.c`, `timekeep.c`, `tama.c`, `tama_ui.c` | bounded/deferred reaps, capped retries, DST correction from the saved offset, monotonic pet timers |
| coverart | `ui/coverart.c/.h`, `sdio.c`, `card.c`, `folderbrowser.c` | foreground/prewarm decode claim + publish token, mutex off the decoder child, SD probes outside `g_mu` with a gate sequence |
| ui-misc | `dacvol/ui/saver/albumwall/wifi/i18n/touchdisc/lrc/playlistview/library` | `isfinite`, `lround`, capacity-aware Wi-Fi strings, allocation-free labels, O(1) playlist rows, binary lyric insert |
| usbboot | `src/usbboot/usbboot.c`, `src/launcher/diskos_launch.c` | heap dump buffer, 64-bit range check, checked `malloc`/`ftell`, rate guard |
| installer | `diskos_installer/flasher.py`, `imagebuild.py`, `state.py` | context-managed handles, `logf` in `finally`, wait after kill, Windows `getuid` |

Integration work done by the coordinator after the agents:

- Added `mdb_song_paths()` and `mdb_subtrack_present()` and wired `albumwall.c`, `library.c`,
  `folderbrowser.c` to them.
- Moved `aw_worker`'s 87 KB stack buffer (`ui/albumwall.c`) to file scope. The audit item was real
  and had fallen between two owners.
- Made the shared `g_bt_stuck` pool in `ui/bt.c` thread-safe, because weather and lyrics now call
  `ui_run_cap_bounded()` from their own threads.
- Reset the books-migration backoff on success.

## Verification

Cross build with the repo's configured toolchain (`ui/config.mk`):

```
$ make -C ui -j4
artifact: mq_ui
md5: 826a4931e6f59ca9bde793fa0c6bb770
size: 4365864
cc: mipsel-linux-musl-gcc (GCC) 11.2.0
```

Host suite (ASan + UBSan, plus the python harnesses):

```
$ make -C ui/tests -j4 check
...
make: Leaving directory '/home/moo/projects/diskos/diskos/ui/tests'
EXIT=0
49 PASS lines
```

Installer suite, identical to the pre-change baseline (the 9 known failures are `test_gui_theme`,
`test_windows_driver_setup` and `test_usbboot_transport`, unrelated):

```
$ python3 -m unittest discover -s tests -q
Ran 588 tests in 30.7s
FAILED (failures=2, errors=7, skipped=156)
```

The critical Opus crash was reproduced before the fix and re-run after. The crafted file has valid
`OpusHead` and malformed `OpusTags`:

```
badtags rc=1000 tags=(nil) len=0
badtags duration positive: ok
badtags tags cleared: ok
badtags len cleared: ok
rc==1 implies tags: ok
goodtags rc=1 tags=0x19238370 len=29
goodtags tags set: ok
goodtags title found: ok
```

Before, `ogg_read()` took `rc > 0` and called `comments_with_provenance(tags + 8, len - 8, ...)`,
i.e. address `0x8` with `0xFFFFFFF8` bytes. After, `ad_opus` enforces `result == 1 ⇒ tags != NULL`,
and the caller checks `tags && len >= 8` before any arithmetic.

Scanner behaviour, starting from a stock-shaped DB missing the migrated columns:

```
scanner: merged 305 songs, skipped 0 unreadable file(s), scan_err=0
scan done: done=305 total=305
goodtags title=abc
badtags duration=1000
vorbis title=xyz
cue tracks=2
cue offset2=1000
books=1
scanner: merged 303 songs, skipped 0 unreadable file(s), scan_err=0
scan done: done=303 total=303
rows after prune=303
all scanner checks ok
```

## Follow-up (same day, commit `a8f96db`)

The reviewer of the first pass asked for the remaining non-hardware items. Seven files changed:

- **1.3 shared connection:** the background readers named in the audit now use a dedicated
  `SQLITE_OPEN_READONLY` connection (`db_ro()`): `mdb_subtrack_count`, `mdb_subtrack_present`,
  `mdb_prewarm_next` and `mdb_song_accent`. The writer handle is main-thread only apart from
  single-statement reads that stay on `g_db`.
- **9.2 N+1 finish:** the two `CREATE TABLE IF NOT EXISTS` statements in `diskos_next_export_uid()`
  now run once per process instead of once per playlist inside the registry sync loop.

- **15.4 write errors:** `mdb_record_play()` and `mdb_set_song_accent()` now return `int`; the cover
  accent callback in `coverart.h` matches, and both callers log a failed write to `stderr` instead
  of discarding it. The two cover-art test fakes were updated to the new signature.
- **14.5 busy wait:** the main-thread `g_db` handle dropped from `sqlite3_busy_timeout(4000)` to
  `1000`. Scanner writes are now short 128-row batches, so the old 4 s ceiling was unnecessary.
- **11.2 `lower(PATH)`:** every remaining occurrence in `ui/musicdb.c` was removed (18 sites). This
  is equivalent because SQLite's default `LIKE` already folds ASCII, which is what `lower()` did.
  `grep -c 'lower('` is now 0 in that file. The suffix `%` scans remain, as documented.

Verification after the follow-up:

```
$ make -C ui -j4
artifact: mq_ui
md5: d48a201e784ae3433a297dd884baef9f
size: 4366520
BUILD_EXIT=0

$ make -C ui/tests -j4 check
UITESTS_EXIT=0
49 PASS lines
```

About 4 minutes measured (05:27 to 05:30 WIB).

## Follow-up 2 (same day, commit `fc88105`)

- **11.3 scanner prefix scan.** The scanner opens its own SQLite connection, so it now sets
  `PRAGMA case_sensitive_like=ON` there and rewrites every `/mnt/mmc/%` predicate as
  `PATH >= '/mnt/mmc/' AND PATH < '/mnt/mmc0'`. `EXPLAIN QUERY PLAN` on the pruning statement shows
  `SEARCH SONG USING COVERING INDEX diskos_song_path (PATH>? AND PATH<?)`. The suffix predicates keep
  `lower(PATH)` so `.M4B`/`.WAV` still match under the now case-sensitive `LIKE`.
- **New `scanner_test` host test.** It seeds a stock-shaped DB with an absent uppercase row and an
  outside-root row, scans lowercase and uppercase WAV/M4B files, then checks that the uppercase file
  and absent uppercase row are pruned, the M4B moved to `BOOKS`, and the outside-root row survives.
  A `SCANNER_TEST_ROOT` compile flag skips only the mountpoint check; the directory checks still run.
- **13.3 SD mount lock.** Added `SD_MOUNTING`. `sd_coldplug_begin()` sets the phase under
  `g_sd_mode_mu` and releases the mutex; `sd_coldplug_end()` reacquires it and returns the phase to
  `SD_LOCAL`. `sd_export_begin()` checks the phase after the timedlock and refuses with the existing
  "SD card is busy - try again" toast instead of waiting for the mount to finish.
  `sd_switch_pending()` and the refusal string include the new phase, and `card.c` is unchanged.

Verification:

```
$ make -C ui -j4
artifact: mq_ui
md5: 147c31f9c78e245e8538ba4d7e3f4f7a
size: 4366728
BUILD_EXIT=0

$ make -C ui/tests -j4 check
UITESTS_EXIT=0
```

`scanner_test` alone:

```
scanner: merged 3 songs, skipped 0 unreadable file(s), scan_err=0
scanner: merged 2 songs, skipped 0 unreadable file(s), scan_err=0
scanner mixed-case paths: ok
```

`sdio_test` alone ends with `sdio_test: ok`, including the new `mounting_reports_switch_pending`.

## Follow-up 3 (same day, commit `f162cf5`)

- **11.1 M3U suffix scan.** `import_m3u_file()` now runs one `SELECT PATH FROM SONG` and builds an
  in-memory suffix index before resolving entries. Every suffix after a `/` is hash-keyed with ASCII
  folding; the full path shares the same pool, so a match costs one probe and no per-key copy. A
  suffix seen in more than one row is ambiguous and is skipped, matching the old `LIMIT 2` rule.
  Budgets are 40,000 rows, 131,072 slots and a 4 MiB path pool; if any budget, allocation or SQL step
  fails, the index is freed and the old prepared `LIKE` path is used, so behaviour is preserved under
  memory pressure.
- **New `m3u_test`.** It builds the index directly and checks mixed-case relative lookup, a relative
  directory path, duplicate-basename ambiguity and a miss. It then imports an M3U with relative,
  mixed-case, absolute and ambiguous entries and checks the three expected members and that the
  ambiguous path was skipped.

```
--- m3u ---
  ok: suffix index built
  ok: mixed case relative lookup
  ok: relative directory lookup
  ok: duplicate basename is ambiguous
  ok: missing suffix is not found
  ok: three entries imported
  ok: playlist created
  ok: three members stored
  ok: mixed case path stored
  ok: relative path stored
  ok: exact path stored
  ok: ambiguous entry skipped
m3u_test: ALL PASS
```

Verification after the change:

```
$ make -C ui -j4
artifact: mq_ui
md5: 832dc185827e0521e1b843543dcf6246
size: 4368216
BUILD_EXIT=0

$ make -C ui/tests -j4 check
UITESTS_EXIT=0
```

## Regression fixes (commit `13b551a`)

The user reviewed the follow-ups, found regressions and fixed them. I reviewed each change, added
the missing lock in `mdb_song_accent_fresh()`, and re-verified.

- **Opus tag-only reads** no longer run `ad_opus_last()` when the caller asked for tags. The
  fallback stays for duration-only callers (`tags == NULL`), so the scanner's duration path is
  unchanged.
- **Cover art** re-checks the cache after taking the foreground decode lane, and prewarm skips a
  decode when `cache_has()` already has the entry. This closes the duplicate-decode window left by
  the claim/publish change.
- **Accent writes** serialize on `g_db_w_mu`; I added the same lock to
  `mdb_song_accent_fresh()` so its SELECT+UPDATE cannot interleave with a set.
- **`mdb_song_paths`** clears the output slots before opening the DB, so an open failure still
  returns empty strings instead of stale pointers.
- **OTA** reports a wall-clock timeout as failure even if the killed child happened to exit 0.
- **Power tick** retries the deferred `sync` reap, so a stuck child does not stay a zombie.
- **Scanner** does not reallocate the row buffer after a full batch flush.
- **SD phase** is `_Atomic`, and `sd_quiesce_end()` resumes from `SD_MOUNTING` as well as
  `SD_LOCAL`.
- **`sysconfig`** passes `-cmd '.timeout 3000'` to the `sqlite3` CLI, closing audit item 15.2.

Verification:

```
$ make -C ui -j4
artifact: mq_ui
md5: bea628e1afce6c414afce5aaa1055981
size: 4367560
BUILD_EXIT=0

$ make -C ui/tests -j4 check
UITESTS_EXIT=0
49 PASS lines
```

## Gotchas

- **`make check-theme` is stricter than it looks.** It flagged the new MD5 IV assignments
  (`st[0] = 0x67452301`) as theme colour constants. Moving the IV into a `static const uint32_t iv[4]`
  and `memcpy`-ing it avoids the regex without weakening the check. Any future code with
  `something[0] = 0x……` in `ui/*.c` will trip it.
- **The scanner's transaction change is a semantic change.** A cancelled or failed scan no longer
  rolls the whole library back. Completed 128-row batches stay; pruning still only runs on a full,
  successful walk, and rescans are idempotent. Schema migrations commit up front.
- **`cfg_get_str()` now returns a thread-local snapshot.** Current callers consume it immediately.
  Do not store the pointer across another `cfg_get_str()` call on the same thread.
- **The stock DB is shared with the FiiO player.** No table/column layout changed. That ruled out
  generated columns for suffix `LIKE '%/x'`, and WAL was not enabled.
- **Batch APIs are read-only.** `mdb_song_paths()` uses `WHERE ID IN (...)` in 400-ID chunks;
  `mdb_subtrack_present()` uses `PATH IN (...)` and matches `mdb_subtrack_count()` exactly.
- **Albumwall's 87 KB stack buffer was easy to miss** because the audit listed it under a category
  owned by the scanner agent, while the file belonged to the UI agent. The final pass caught it.

## Deliberately not fixed

- HTTP connection reuse (`18`): accepted, not fixed. See the decision below.


## Decision: HTTP connection reuse accepted (`18`)

Measured on the Disc over SSH on 2026-11-28, with three separate `wget` processes against the iTunes
search endpoint:

```
0.72 s   first request (DNS + TCP + TLS)
0.14 s   second request
0.18 s   third request
```

Keep-alive would save under 0.1 s per request after the first. `netart_have()` already checks the
album key before searching and misses are negatively cached, so the 2-4 calls only happen on a true
uncached album, not per track. The stock rootfs has libcurl 7.68 plus OpenSSL 1.1.1f, but they are
dynamic glibc builds and cannot be linked into the static musl `mq_ui`.

Decision: keep one `wget` per request, with the new `-t 1` and wall-clock deadlines. Adding
libcurl + mbedTLS would grow the static binary by roughly 0.5-1 MB and add CA/TLS maintenance for a
sub-100 ms saving. If this is revisited, the scope is one `http_get()` helper with a shared
connection cache and cancellation, ported to `netart`, `lyrics`, `weather`, `ota` and `system`.

## WAL enabled (branch `feat-db-wal`, commit `c6713fc`)

Device test on the Disc, 2026-11-28, about 15 minutes including one reboot:

- stock player: `libsqlite3.so.0.8.6` = 3.30.1; diskOS: statically linked 3.46.1; both support WAL
- `/usr/data` is UBIFS (`ubi1_0`, 67.6M, mounted `sync`)
- backed up `song.db` to `/tmp/sdcard/song.db.pre-wal` (md5 `0f5f5b9b...`, copy verified)
- `PRAGMA journal_mode=WAL` returned `wal`, `integrity_check` stayed `ok`
- a held write created `song.db-shm` (32 KB) and `song.db-wal` on UBIFS; both vanished after a clean
  close, which is normal
- after a reboot the mode was still `wal`; `mq_ui` and `mq_player` both reopened
  `song.db-wal`/`song.db-shm` themselves; 815 songs, `integrity_check` `ok`
- the stock library, stock playback and a diskOS playlist edit all worked

Code on the branch:

- `db()` sets `PRAGMA journal_mode=WAL` on first open; the scanner sets it on its own connection too
- `mdb_checkpoint()` runs `PRAGMA wal_checkpoint(PASSIVE)` on power-off and UI restart
- `m3u_test` asserts the test DB reports `wal`
- `uiread_test` was updated for WAL lock semantics: a held `BEGIN EXCLUSIVE` without a write does not
  block readers, so the lock test now holds a writer and the fixture creates the playlist registry
  tables it needs

Verification:

```
$ make -C ui -j4
artifact: mq_ui
md5: c9792b94dccb8f8d72d8ff86f709d551
size: 4367820
BUILD_EXIT=0

$ make -C ui/tests -j4 check
UITESTS_EXIT=0
49 PASS lines (m3u_test: journal mode is WAL)
```

The branch is not merged to `main` and the WAL build is not flashed yet.

## Not verified

No flash, no mask-ROM run, no on-device check of the DST fix, the SD export ordering or the scanner
on a real 30k-file card. The cross build and host suites are the only runtime evidence. ThreadSanitizer
was not available.

## References

No external web sources contributed; every claim came from the repo source, the audit file, or the
local test harnesses. Related notes: [[diskos-ultrareview-dev-to-main-findings-and-first-fixes]],
[[diskos-standards-review-25-commits-adrs-and-ui-naming-2026-11-12]],
[[diskos-six-module-deepening-parallel-agents-merge-charging-fixes]],
[[diskos-rust-rewrite-feasibility-2026-11-17]].
