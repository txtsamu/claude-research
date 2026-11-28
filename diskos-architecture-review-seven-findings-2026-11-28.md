---
type: build-log
tags: [diskos, snowsky-disc, architecture, refactor, subagents, worktrees, command-spawn, wifi, dhcp, playctl, gesture, coverart, sqlite, boot-splash, host-tests]
created: 2026-11-28
last_verified: 2026-11-28
status: current
---

# diskOS: implementing all seven architecture review findings with parallel agents

Repo: `txtsamu/diskos`, base `0a6918f` (build 8 release), integration branch `arch/deepen-2026-11-28`,
merged into `dev` at `a87980f`.

Input: `claude-research/2026-11-28-architecture-review.md` in the diskOS repo (untracked working copy, written 17:55).

## Time estimate

About 40 minutes wall clock from the first worktree (just before 18:02) to the final clean build at 18:42:39.
Measured anchors: the first finding commit landed at 18:10:05; the final clean `mq_ui` build finished at 18:42:39
and took 13 seconds (`18:42:26` to `18:42:39`). The per-finding agent times were not measured individually.

| Step | Time | Kind |
|---|---|---|
| Wave 1: command_spawn, musicdb split, gesture, coverart (parallel) | about 8 min to first commits | measured span |
| Wave 2: playctl, boot splash, then wifisup (partly parallel) | about 20 min | measured span |
| Merge conflicts and integration fixes | about 10 min | estimate |
| Final clean cross build | 13 s | measured |
| Full host suite `make -C ui/tests check` | under a minute | estimate, not timed |

## The request

"Check claude-research latest architecture review and work on that finding, spawn subagent to work on all tasks."

The review had six deepening opportunities plus a boot animation investigation:

1. Deepen `command_spawn` for bounded subprocesses and deferred reaping (top recommendation).
2. Extract Wi-Fi supervision and the DHCP lease state machine out of `wifi.c`.
3. Consolidate Playback Start and Book session dispatch out of `main.c`.
4. Add an injectable DB core to `musicdb` and split Playlists / M3U.
5. Close the leaky Cover art seam between `ui.c`, `main.c` and `coverart`.
6. Extract the touch and rim-scroll gesture router out of `main.c`.
7. Fix the cold-boot Home flash and splash stutter.

All seven were implemented.

## How the work was split

Seven git worktrees were created from `main`, each on its own branch, with `ui/third_party/out` copied in
(hardlinked then `touch`ed) so each agent could run the mipsel cross build. Wave 1 ran four agents with disjoint
files. Wave 2 ran the three that depend on the new spawn API or share `main.c` with wave 1.

```sh
git worktree add -b arch/w1-cmdspawn ../diskos-w1-cmdspawn main
cp -al ui/third_party/out ../diskos-w1-cmdspawn/ui/third_party/out
find ../diskos-w1-cmdspawn/ui/third_party/out -name '*.a' -exec touch {} +
```

The `touch` matters: a fresh checkout gives the build scripts newer mtimes than the prebuilt libraries, so
`make` would otherwise rebuild curl, mbedTLS and FreeType inside every worktree.

Each agent was told:

- its exact file ownership list, so merges stay tractable,
- no comments in source, no em dashes,
- run `make -C ui/tests check` and `make -C ui -j2` before committing,
- commit on its branch, never merge.

`main.c` was touched by five findings in different regions, so the merge order was fixed and each merge was
built and tested before the next.

## Finding 1: `command_spawn` (commit `dd54748`)

New interface in `ui/command_spawn.h`:

- `command_run(argv, timeout_ms)`, `command_wait`,
- `command_capture(...)`, `command_capture_shell(...)`,
- `command_child_start/poll/abort/exit/len/truncated`,
- `command_reap_sweep()`, `command_reap_add/free()`, `command_abort`, `command_run_kill`.

One spawn path: FD-clean, own process group, stdin `/dev/null`. Capture reads with `O_NONBLOCK`, so a grandchild
holding the pipe cannot stall the caller. The deferred reaper is swept from a new 100 ms timer in `main.c`.

Deleted: `bt.c` `g_bt_stuck[8]` and the exported `ui_run_cap_bounded`, `main.c` `g_defer_reap[16]` and
`ui_run_bounded`, `settings.c` `g_rst_reap[8]`, `power.c` `g_sync_lost`, `ota.c` `run_capture`, and
`dacvol_sys.c`'s private capture. `main.c` and `wifi.c` no longer import a capture helper from the Bluetooth
screen.

Test: `ui/tests/command_spawn_test.c`, 59 checks.

## Finding 2: `wifisup` (commit `49373ed`)

See the detailed note [[diskos-wifisup-extract-2026-11-28]]. `wifi.c` went from 1,232 to 711 lines; the radio
reconciliation, five-phase lease machine, `/proc` inspection, `udhcpc` signals and connectivity verdict moved
behind `struct wifisup_env`. Test: `ui/tests/wifisup_test.c`.

One regression found during integration review and fixed in `9b8a4c5`: the old listener used `fork` +
`prctl(PR_SET_PDEATHSIG, SIGTERM)`, but the new `posix_spawn` path cannot set that. A UI crash would leave a
stale `wpa_cli -a` listener appending duplicate events. Added `command_spawn_lifetime()` (fork, setpgid,
PDEATHSIG, `getppid` check, exec) and used it for the listener, with a test.

## Finding 3: `playctl` (commit `00d98ca`)

`ui/playctl.[ch]` now owns `ui_play_list`, `ui_play_favorite`, `ui_play_playlist`, `ui_queue_jump`,
`ui_play_plan`, `ui_play_song_by_path`, `ui_play_book`, the book migration gate and the Book single-mode
transaction. `main.c` keeps the `struct playctl_env` table only.

The failure path the review called out is now closed: `ui_play_book` snapshots the single-mode flag and the
previous Player mode, and on a failed reserved-slot play sends the previous mode back and restores the flag.
The duplicated reserved-slot reset is one `prepare_reserved()`.

Test: `ui/tests/playctl_test.c` (book failure rollback, success handoff, reserved reset, admission rejection).

## Finding 4: `mdb_core` + `playlistdb` (commit `7dae7ac`)

`ui/musicdb.c` went from 2,934 to 1,727 lines. `mdb_core.[ch]` owns the handles, the injectable path
(`mdb_core_set_path` before the first open), SD leases, WAL, busy timeouts, schema bootstrap and savepoints.
`playlistdb.[ch]` owns playlists, registry sync and M3U import/export with the suffix index.

The `#define sqlite3_open_v2(...)` plus `#include "../musicdb.c"` hack is gone from `m3u_test.c` and
`uiread_test.c`; they link normal objects. Grep still hits vendored `ui/sqlite3.c`, so exclude it:

```sh
grep -rn 'include "../musicdb.c"\|#define sqlite3_open_v2' ui/ --exclude=sqlite3.c
```

Tests: `mdb_core_test.c`, `playlistdb_test.c`, plus the repaired `m3u_test` and `uiread_test`.

## Finding 5: Cover art seam (commit `88c79ec`)

`coverart` now owns `coverart_art_key`, `coverart_sync` (IDLE, HOLD, LOADING, CLEAR), the token/generation
identity, the `title_ready` to `online_only` retry, and the two-slot `/tmp/{cover,thumb,backdrop}%d.bmp`
ping-pong. `nowplay_art_applied()` makes the next `nowplay_publish` fan out art, track and menu once, replacing
the hand-rolled fan-out in `main.c`. `ui.c` renders descriptors only and `ui_take_art_applied()` is gone.

Tests extended in `coverart_test.c` and `nowplay_test.c`.

## Finding 6: gesture router (commit `f59c0b6`)

`ui/gesture.[ch]` is pure C with no LVGL include. `main.c` fills a `gest_ctx_t` and dispatches `gest_result_t`
actions. Release stays two phase because `ui_np_seek_release()` decides whether the seek consumed the gesture.
The saver wake press is consumed at press time and its release is swallowed inside the module, matching the old
`woke` flag.

Test: `ui/tests/gesture_test.c`, 50 checks.

## Finding 7: boot splash (commit `e865491`)

`splash_start()` now runs after `bootstate_start()` and before `screen_show(start)` and the first
`lv_refr_now(NULL)`, so the first composited frame is the opaque splash and no Home pixel reaches `/dev/fb0`.
`splash_ready()` is called after the first main-loop `lv_timer_handler`; the fade needs minimum time, readiness
and `!bootstate_starting()`.

`splash_active()` holds back `wifisup_supervise()`, the SD coldplug, art retry, cover art prewarm and Album Wall
prewarm seed, and pauses the art timer. The timer resumes with one immediate poll after the fade. Watchdog
disarm, first-frame log, status poll and `hwclock -s` are not deferred.

Test: `ui/tests/splash_test.c` (fade predicate only; the panel behavior needs hardware).

## Merge conflicts

Four conflicts, all textual:

- `ui/tests/Makefile` four times. Resolution: keep every test block. Each agent appended in the same place.
- `ui/main.c` once: the gesture extraction had deleted the rim block, while `command_spawn` deleted
  `ui_run_bounded` in the same hunk. Resolution: keep neither.
- `ui/main.c` once: the splash gate `if(!splash_active()) wifi_supervise();` against the renamed
  `wifisup_supervise();`. Resolution: `if(!splash_active()) wifisup_supervise();`.

## Verification

Clean cross build in the integration worktree:

```console
$ make -C ui clean && make -C ui -j8
BUILD_EXIT=0
23 warnings
md5    0285566576f46c79279c0d029bf51803
sha256 04d9b65d70f30a8b2bb14fde58bbd2a63a10904c935e25cfb27bee3c1a475d6d
size   5528692
start 18:42:26, end 18:42:39
```

The baseline was 24 warnings; the split removed one unused-function warning. No new warning from any new file.

Host suite:

```console
$ make -C ui/tests check
TESTS_EXIT=0
84 PASS/ok/COMPLETE/ALL PASS lines
0 FAIL
54 test groups
```

Rebuilt in the main repo after merging to `dev` and reproduced the same md5. `dev` is pushed, `main` is
untouched at `0a6918f`.

Diff: 46 files, +5,308 / -2,758, 19 commits, 7 new host test binaries.

## Follow-up checkpoint `82ffa18`

A later review pass on `dev` found eight regressions from the merge and fixed them in one commit,
`82ffa18` "Fix regressions from arch/deepen-2026-11-28 and document dev checkpoint rule" (12 files,
+81 / -37). It also added the auto-commit-and-push checkpoint rule to `CLAUDE.md` and
`agents/AGENTS.md`.

- `ui/command_spawn.c`: `_GNU_SOURCE` guard; a `pass_fd == 3` dup dance through fd 255; the timeout path
  blocks `SIGALRM` across `command_abort`; `command_run` now fails on `ECHILD` instead of spinning to the
  timeout; `pipe2(O_CLOEXEC)`; and `child_probe_extra()`, which keeps the pipe open on `EAGAIN` and marks
  truncation when an extra byte arrives after the buffer filled exactly. The old code closed the pipe on
  `EAGAIN`, so `printf 'abc'; sleep; printf 'd'` into a 4 byte buffer was reported as an exact fit.
- `ui/main.c`: `wifisup_env_radio_down` became synchronous (`command_run(argv, 2000)`) so the next
  supervise tick sees the radio actually down; `wpa_cli` argv[0] fixed; `polls_set_paused(paused, art_held)`
  keeps the art timer paused while art is held even when the idle path later resumes the other poll timers;
  the art resume path skips the immediate poll while the screen is off.
- `ui/coverart.[ch]`: `coverart_take()` takes the current `online_art` setting instead of the value captured
  when the want was queued.
- `ui/gesture.c`: `library_letter_tick` is only set for a rim move inside the angular limit.
- `ui/nowplay.c`: an art apply that happens inside the `view` sink triggers exactly one republish instead of
  being dropped.
- `ui/ui.c`: `clear_art_state()` only signals art applied when something was actually cleared, which stops
  the publish loop, and `ui_art_poll()` reads `online_art` once and passes it to `coverart_take()`.
- Tests: three new `command_spawn` checks (delayed extra byte, cap 1 with empty output, fd plumbing), the
  `coverart_take` signature in `coverart_test.c`, and `sync_art_apply_inside_view_does_not_loop` in
  `nowplay_test.c`.

Re-verified on `dev` at `82ffa18`:

```console
$ make -C ui/tests check
TESTS_EXIT=0
84 PASS/ok/COMPLETE/ALL PASS lines
0 FAIL
54 test groups

$ make -C ui clean && make -C ui -j8
BUILD_EXIT=0 (20:12:14 to 20:12:26)
23 warnings, 0 errors
md5    21c3f99ca03d054b72a3a5526555fce7
sha256 84725ec323a6720decb984bbd8d41c7cbcc6666cea2e09b0ef68cdd37423e747
size   5528880
```

The three remaining warnings in touched files (`main.c:137`, `ui.c:102`, `ui.c:1694`) are pre-existing and
not in the changed hunks. The binary grew 188 bytes from the pre-fix `dev` build. `dev` and `origin/dev`
are level at `82ffa18`.

## Gotchas

- A worktree needs `ui/third_party/out` copied in, and the `.a` files must be newer than `build-http.sh` and
  `build-freetype.sh`, or the cross build tries to rebuild the vendored libraries in every tree.
- The cross compiler is not on the default PATH: `PATH=/opt/mipsel-n2008-musl-cross/bin:$PATH`.
- `make -C ui checkpunct` fails on the generated `ui/font_*.c` files, which contain U+2018/2019/201C/201D/2026
  in glyph comments. It also fails on `main` at `0a6918f`, so it is pre-existing, not a regression.
- `posix_spawn` cannot set `PR_SET_PDEATHSIG`. Anything that must die with the UI needs the fork-based
  `command_spawn_lifetime()`.
- `screens.h` now includes `playctl.h`, which includes `musicdb.h` and therefore `sqlite3.h`. It builds, but
  every `screens.h` consumer now sees SQLite declarations.

## Not verified

- Nothing was flashed. The Disc was offline the whole session (`No route to host`), so the build 8 boot check
  and every behavior change here are unverified on hardware.
- The splash-first-frame claim depends on the display controller and panel power-on timing; only a cold boot on
  the Disc can confirm no Home flash and no stutter.
- Real `udhcpc` signal delivery, `wpa_cli -a` event delivery and the Bluetooth-priority race were not exercised.
- Gesture feel, the cover art online retry on a real network, and the book rollback on a real Player failure
  were not run on device.
- The byte count grew from 5,527,756 to 5,528,692 (about 936 bytes).

## References

No external web sources contributed. The input and the conventions all came from the repo:

- `claude-research/2026-11-28-architecture-review.md` in the diskOS repo (the review being implemented).
- `docs/UI_ARCHITECTURE.md` (module and adapter conventions, updated in this session).
- `docs/adr/0001-working-mode-switches-go-via-local.md` and `docs/adr/0002-usb-debug-is-an-overlay-on-local.md`.
- Related notes: [[diskos-wifisup-extract-2026-11-28]],
  [[diskos-six-module-deepening-parallel-agents-merge-charging-fixes]],
  [[diskos-ui-deepening-six-modules-and-harness-2026-11-18]],
  [[diskos-codebase-audit-fixes-2026-11-28]].
