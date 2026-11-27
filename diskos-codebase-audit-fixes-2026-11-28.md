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

- WAL mode: changes the persistent journal mode of the DB the stock player opens; needs an on-device
  compatibility check.
- HTTP connection reuse: each request still spawns `wget`; an in-process HTTP/TLS client is a
  separate project. Timeouts now bound the worst case.
- `mount()`/`umount()` under `g_sd_mode_mu`: narrowing it safely needs an explicit MOUNTING phase
  in the SD state machine, otherwise an export can race a local mount.
- Suffix `LIKE '%/x'` and `lower(PATH) LIKE '%.ext'` full scans: need a stored basename/suffix column,
  which changes the shared table layout.

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
