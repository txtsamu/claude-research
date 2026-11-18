---
type: build-log
tags: [diskos, architecture, refactor, deep-modules, card, cardclose, playerset, idlegov, transport, test-harness, podman, hot-load, snowsky-disc]
created: 2026-11-18
last_verified: 2026-11-18
status: current
---

# diskOS: six deep modules out of the composition root, and a declare-once test harness

An architecture review of `ui/` in `txtsamu/diskos` produced six deepening candidates. This is the build log of implementing all six: four in parallel worktrees, the harness last, then the merges, the harness rework, the cross-build, the push, and a hot-load onto the Disc. Commit range `e6bc3da..cf58a93` on `main`, pushed to `origin`.

## Time estimate

- Whole effort, architecture report to push: about 3 hours 5 minutes wall clock (report timestamp 20:18, push 23:24). Measured from shell timestamps.
- The four implementation branches (`card`, `playerset`, `transport`, `idle`) ran concurrently in separate git worktrees; the exact per-branch durations were not recorded.
- The harness branch ran alone after the merges; about 40 minutes is an estimate, not a recorded figure.
- Podman cross-build: a few minutes per run, not precisely timed; four runs total (coordinator 2, harness agent 2).
- Hot-load: under a minute end to end.

## What was asked

The user invoked the `improve-codebase-architecture` skill. The review walked the churn hot spots (`git log` ranked `ui/main.c` first, then `ui/tests/Makefile`, `ui/Makefile`, `ui/settings.c`, `ui/srcswitch.*`, `ui/modes.c`) with a fresh-context subagent, read `GLOSSARY.md` and both ADRs, and produced an HTML report in the temp dir (not committed). The user then said: do all of it, work in parallel with subagents, do not ask questions.

The six candidates:

1. One module owns the card's physical lifecycle (Strong).
2. The test harness gets an add-a-test interface (Strong, mechanical).
3. One card-close spine with two endings (Worth exploring).
4. The Player setting frames get a home (Worth exploring).
5. Transport commands get an identity (Speculative).
6. The idle machine gets a module (Speculative).

All six were implemented. ADR-0001 (switches go Via Local) and ADR-0002 (USB Debug is an overlay on Local) were not touched.

## What changed

Measured line counts after the work:

```
1801 ui/main.c          (was 2156, -355)
 268 ui/card.c          new: physical card facts and mutations
  52 ui/cardclose.c     new: shared drain, sync, unmount transaction
 238 ui/playerset.c     new: the fourteen Player setting frames and reapply
 136 ui/idlegov.c       new: power-key, backlight and saver decisions
  74 ui/transport.c     was 66: named command vocabulary added
```

- **card** (`ui/card.c`, env-seamed): mounted, exported, host-confirmed and player-guarded facts; mount with the filesystem preference; the release-ladder unmount (Player USB-Storage request, 40 x 100 ms retries, lazy-detach fallback, flush); the boot-time cold mount with its export rollback. `sdio` keeps the admission authority; `main.c` keeps only wiring. `power.h:53`'s forward declaration of a `main.c` function is gone.
- **cardclose** (`ui/cardclose.c`): quiesce is caller-owned, then drain, sync child, unmount. Power off and Restart keep their own endings (Player sleep frame plus protected recovery; flash arm plus reboot). One timeout set: `CARDCLOSE_DRAIN_MS 10000`, `CARDCLOSE_SYNC_MS 15000`. The only behavior change in the whole effort: the drain was 8 s in power and 10 s in Restart; it is now 10 s for both, the conservative value before power is cut.
- **playerset** (`ui/playerset.c`, 22-finger env): the fourteen `ui_set_*` implementations, fifteen pure frame builders with the value guards, the reapply order and its three tries. `outroute.c` no longer rebuilds the volume frame; it calls `playerset_frame_volume`.
- **transport** (`ui/transport.h`): named commands (`UI_TRANSPORT_*`) with one click mapping inline, one frame mapping in `transport.c`. The transport hex now exists only in `ipc.h` and `transport.c`. `ui_seek_to` stayed in `admit.c` on purpose: moving it would have broken `admit_test`'s link closure.
- **idlegov** (`ui/idlegov.c`): `powerkey_step`, `screen_frame_step`, the inject deferral, the foreign-brightness relevel decision, the 250 ms poll cadence and the saver ladder, with the caller owning the state struct and applying the decisions. Zero behavior change.
- Docs: `GLOSSARY.md` gained Card, Release ladder, Card close, Cold mount, Setting apply and Idle governor, and Restart now names the shared Card close. `CHANGELOG.md` records the split and the harness. `comments.md` gained or updated sections for every new file; the `ui/main.c` entry count was re-measured (580) rather than guessed.

## How the parallel work was done

Four worktrees were created off the same base (`e6bc3da`), one branch each: `arch/card` (candidates 1 and 3, one agent), `arch/playerset`, `arch/transport`, `arch/idle`. Agents were told: no comments in source, `comments.md` instead, host gates (`make run`, `make check`) green before every commit, no device access, no podman build, no rebase, commit on your branch only.

Predicted conflict points, and what actually conflicted: the `APP_SRCS` line in `ui/Makefile`, the run/clean lists in `ui/tests/Makefile`, the include block in `ui/main.c`, and adjacent `comments.md` index/section insertions. Everything else auto-merged.

Merge order: transport, idle, playerset, card, then the harness. `main` after each merge: suite green.

## The merge-glue incident (read this before scripting conflict resolution)

My first conflict-resolution script used a regex like `<<<<<<< HEAD\n(.*?)\n=======\n(.*?)\n>>>>>>> branch\n`. That pattern consumes the newline after the end marker. Replacement strings that did not restore that newline glued the resolved line to the next line.

- The playerset merge (commit `c3ea5ee`) ended up with `APP_SRCS := ... $(APP)/playerset.cAPP_SRCS += $(APP)/coverart...` on one line. `make` would parse the tail as part of the variable value, putting the tokens `APP_SRCS` and `+=` into the object list.
- The host suite could not catch it: `ui/Makefile` is only read by the podman cross-build. `make run` and `make check` were green on the broken commit.
- Caught during the card merge, confirmed with `git show c3ea5ee:ui/Makefile | grep "APP_SRCS +="`, then repaired by resetting to the clean idle merge (`7a10da3`) and redoing the playerset and card merges with boundary assertions: the `:=` line, a separate `+=` line, `SQLITE_FLAGS` on its own line, the run line followed by a recipe line, the comments.md index rows and `~~~` fences. The bad commit was never pushed and is dangling in the reflog only.

Lesson: after scripted conflict resolution, assert the line structure on every repaired boundary, and run the real cross-build before trusting the merge, not just the host suite.

## Harness rework (candidate 2)

- `ui/tests/Makefile` is now per-test declaration blocks (`TESTS += name`, `name_SRCS`, `name_DEPS`, `name_DEFS`, `_PRE`/`_POST`) expanded by one `$(eval $(call TEST_RULE,...))` template; `run`, its prerequisite list and `clean` all derive from `TESTS`. Adding a test is one block.
- A static pattern rule (`$(TESTS): %: $($*_SRCS)`) was tried and rejected by probe: prerequisites expand at parse time with `$*` empty, so binaries would never rebuild on source changes. The working form and the trap are in `comments.md`.
- Temp roots: per-test directories under `ui/tests/.tmp/<test>/` (35 tests), an absolute checkout path for `card_test` (production requires an absolute `PATH` entry), and `/tmp/diskos-cpt-<hash>` for the cover art pipeline because `art.c:122` stages in `/tmp` and `rename(2)` across devices fails with EXDEV. `ui/.gitignore` ignores `tests/.tmp/`.
- `ui/Makefile`'s `APP_SRCS` is a sorted wildcard minus nine explicitly excluded files (seven standalone host tools with their own `main()`, the profiling shim, `sqlite3.c`). The set is identical to the old hand-written list, 164 sources.

## Verification, with real output

Final tree, host suite:

```
--- vbus ---
PASS (0 failures)
RUN_EXIT=0
Ran 5 tests in 0.124s
OK
CHECK_EXIT=0
```

Cross-builds (podman builder, from `ui/`):

| State | mq_ui md5 | size | src_md5 |
|---|---|---|---|
| pre-harness (`4d7eddc`) | `0ccb960ae8ddf81218214114faf6c6df` | 4354212 | `49bf467b...` |
| harness merge (`2d60815`) | `e924f62a161c9c851a333524ddfcf18e` | 4354196 | `7b0e1f4c...` |
| final, with the LUN-path fix (`cf58a93`) | `80b0b0e1ef69b776a83f8e954a915061` | 4354196 | `a73787cf...` |

The harness delta is link order only: the same 164 files, sorted instead of the old hand order; concatenating the old order reproduces the baseline `src_md5`, the new order reproduces the after hash, and both sorted sets hash equal. The binary md5 changes because the objects link in a different sequence.

Hot-loaded the final artifact with the documented procedure (watchdog frozen for the swap, md5 staged first, `mq_player` untouched):

```
>> staged 80b0b0e1ef69b776a83f8e954a915061
ok=1 attempts=1
24771 /usr/data/mq_ui
1150 /usr/bin/mq_player
```

Device check after: `/proc/24771/exe` and `/usr/data/mq_ui` both `80b0b0e1...`, `mq_player` pid unchanged, boot log `player ready after 563 ms`, card mounted, journal `sd gate: opened at poll 1`. Library screen alive and taking taps.

## Gotchas

1. **Scripted conflict resolution eats the newline after the end marker** (see the incident above). Always restore it and assert boundaries.
2. **Shared test temp roots collide across concurrent checkouts.** `TDIR := /tmp/diskos_cfgtest` (and `ATDIR`) produced a stale-DB `uiread_test` failure, an `outroute_test` "no DAC" failure from another run's leftovers, and `dacvol_sys_test` flakes. The harness now uses per-test, per-checkout roots; verified with two full suites running at once in two checkouts (`CONCUR_A_EXIT=0`, `CONCUR_B_EXIT=0`).
3. **Link order changes the binary md5 without changing behavior.** The sorted glob did exactly that; the installer manifest pins the binary at flash time, so this only matters when the release artifact is rebuilt.
4. **Hot-loads do not survive a reboot.** `S97diskos_install` restores the flashed copy, so the Disc is back on `24d88617` (unmount without the fsync flush and without these refactors) after a power cycle. Re-hot-load after a reboot.
5. **A `%s` path snprintf without a return check** hid in `card.c:146` (format-truncation warning). Now an overlong LUN path is treated as exported, fail-closed, matching the function's other checks.
6. **The review report itself is ephemeral** (`/tmp/opencode/architecture-review-*.html`); the durable record is this note plus the module docs in `comments.md`.

## Not verified

- Device behavior of the refactored build beyond the UI coming up, painting, and taking taps. No full navigation, playback, USB mode or power-cycle exercise of the hot-loaded build.
- The 8 s to 10 s drain timeout change is not exercised on hardware. Its only proof is the host `cardclose_test` and the unchanged endings in `power_test` and `restart_test`.
- LVGL click delivery on the device is compile-verified only; host tests cannot drive LVGL events.
- The flashed image was not rebuilt: `payload/mq_ui` in the repo and the installer manifest still pin the previous build. The refactors exist on the Disc only as a hot-load until the next flash.

## Related notes

- [[diskos-card-module-card-close-spine-2026-11-18]]
- [[diskos-idle-machine-idlegov-extract-2026-11-18]]
- [[diskos-transport-command-vocabulary-2026-11-18]]
- [[diskos-build-harness-declare-once-tests-2026-11-18]]
- [[diskos-sd-clean-unmount-and-fsdetect-2026-11-17]]
- [[diskos-hotload-gotchas-test-outputs-usb-storage-reboot]]
- [[diskos-disc-hotload-watchdog-snowsky-logo-hang]]

## References

No external web sources were used. The method came from the repo's own documents (`agents/AGENTS.md`, `GLOSSARY.md`, `docs/adr/`, `docs/TOUR.md`) and the two hot-load notes linked above; the build and test procedures are in `ui/Makefile` and `ui/tests/Makefile`.
