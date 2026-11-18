---
type: build-log
tags: [diskos, snowsky-disc, make, build-harness, tests, refactor, worktrees, subagents, exdev]
created: 2026-11-18
last_verified: 2026-11-18
status: current
---

# diskOS build harness: declare-once tests, per-test temp roots, globbed APP_SRCS

Repo: `diskos` (fork `txtsamu/diskos`), branch `arch/harness` (worktree
`~/.local/share/opencode/worktree/c6e21f/arch-harness`, base `main` at `e39e94a`),
commit `9bb96da` — "Harness: declare each host test once, per-test temp roots, glob
APP_SRCS". Session run as a subagent of the main coordinator session; the coordinator
handled GLOSSARY/CHANGELOG in the primary checkout, this session did the build-harness
work in its own worktree.

The request: `ui/tests/Makefile` was the second-most-changed file in the repo (40 touches
in two months) because every test was a hand-written rule whose name reappeared in four
places (build rule, run prerequisite list, run body, clean list). Two shared temp roots
`/tmp/diskos_cfgtest` and `/tmp/diskos_arttest` let two checkouts running the suite at the
same time clobber each other (stale uiread DB, leftover outroute state breaking the
"no DAC present" expectation, a leaked repair child wiping dacvol's dir). And `ui/Makefile`'s
APP_SRCS was one 3.3 kB hand-maintained line that parallel work kept conflicting on.

## Time estimate

- Total session: about 2 h wall clock (estimate — background builds overlapped with file
  edits and verification runs).
- Baseline `make run` of the untouched suite: about 20 min, measured from artifact mtimes
  21:35 to 21:56 local.
- Each podman device build (baseline and after): about 10 min each (measured manifest
  timestamps; run twice).
- One `make check` (36 C tests + 9 python tests) with binaries cached: roughly 2 to 4 min
  (estimate); from a clean tree add the compile pass, a few minutes more.
- Two concurrent full suite runs (the isolation proof): about the same as one cached run,
  overlapped (measured: both finished within a couple of minutes of each other).

## What was done

### 1. Declare-once test harness (ui/tests/Makefile, 242 -> 254 lines)

Every test is now ONE block: `TESTS += <name>` plus whichever of `<name>_SRCS` (compiled
closure), `_DEPS` (rebuild triggers: headers, `#included` .c files, helper binaries),
`_OBJS` (linked objects), `_DEFS`, `_FLAGS`, `_LIBS`, `_PRE` (run-time setup shell) and
`_POST` it needs. Everything else derives from those names:

```make
TESTS := $(sort $(TESTS))

define TEST_RULE
$(1): $(sort $($(1)_SRCS)) $(sort $($(1)_DEPS)) $($(1)_OBJS)
	$$(CC) $$(CFLAGS) $($(1)_FLAGS) $($(1)_DEFS) -I.. $(sort $($(1)_SRCS)) $($(1)_OBJS) $($(1)_LIBS) -o $$@
endef
$(foreach t,$(TESTS),$(eval $(call TEST_RULE,$(t))))
```

`run:` is one unrolled shell line over the sorted `TESTS` list (wipe + recreate the test's
temp root, run `_PRE` if set, run the binary, run `_POST` if set — outseq's python guard
rides on `_POST`), `clean` is `rm -f $(TESTS) sqlite3_host.o` plus the temp trees, and
`run`'s prerequisite list is `$(TESTS)`. Adding a test is exactly its block; proved by
adding a `zz_dummy_test` block + a trivial .c, running the suite (37th section, passed,
exit 0), then removing both.

**The trap that forced the `$(eval $(call))` template:** a static pattern rule
(`$(TESTS): %: $(sort $($*_SRCS)) ...`) compiles and links fine but its PREREQUISITE list
is expanded once at parse time with `$*` empty, so `$( $*_SRCS )` silently expands to
nothing — `make -n` showed correct commands (the recipe binds `$*` at execution) but the
binaries had NO prerequisites and would never rebuild on source changes. Verified with a
minimal probe:

```
$(TESTS): %: $(sort $($*_SRCS))
	@echo "STATIC-COMPUTED $@ prereqs=[$^]"     # -> prereqs=[]

$(eval $(call TEST_RULE,$(t))) template        # -> prereqs=[a.c b.c c.c]
```

### 2. Per-test temp roots

The shared `/tmp/diskos_cfgtest` + `/tmp/diskos_arttest` are gone. Every test's `-D` paths
now point into its own root, wiped and recreated by the run rule before the test runs
(idempotent back-to-back). Three root FLAVOURS, all forced by production code that must
not change:

- **Relative `.tmp/<test name>`** (35 tests): `config.c` renames through a `char tmp[64]`
  (`CFG_PATH + ".tmp"`), and `coverart_job_t.out` is `char[40]` (`coverart.h`), so a deep
  absolute worktree path truncates where the old short `/tmp` path fit. Relative paths are
  checkout-location independent and stay ~30-45 chars.
- **Absolute `<checkout>/ui/tests/.tmp/card_test/card`** for card_test only: `card.c`'s
  `card_player_guarded()` accepts a player only if its environ PATH entry starts with
  `/`, so the fake guard dir the test plants must be absolute. All its buffers
  (`p[320]`, `guardpath[400]`, rmguard's `p[256]`) fit the long path.
- **`/tmp/diskos-cpt-<md5-8-of-tests-dir>`** for coverart_pipeline_test only: `art.c`
  stages decode output in a hardcoded `mkdtemp("/tmp/.diskos-artdec-XXXXXX")` and then
  `rename(2)`s the staged files onto the job destinations — and `/tmp` is a different
  filesystem from the checkout (stat: device 50 vs 51), so those renames fail with EXDEV.
  Its CA_TMP space stays under `/tmp`, per-checkout by hash, wiped by its `_PRE`,
  removed by clean; 24 chars total keeps the 40-byte job struct in budget. This is the one
  documented deviation from "everything under ui/tests/.tmp" — physics, not preference.

`ui/.gitignore` (the file that already ignores the built test binaries via `tests/*_test`)
gained `tests/.tmp/`.

### 3. Globbed APP_SRCS (ui/Makefile)

The 3.3 kB hand-maintained line became:

```make
APP_EXCLUDE := $(APP)/fbshot.c $(APP)/mqcap.c $(APP)/mqfeed.c $(APP)/mqsend.c $(APP)/prof.c $(APP)/psend.c $(APP)/sqlite3.c $(APP)/touchcap.c $(APP)/touchdisc.c
APP_SRCS := $(filter-out $(APP_EXCLUDE),$(sort $(wildcard $(APP)/*.c)))
```

The exclusion list is exactly the on-disk set that the old APP_SRCS never contained
(verified by `comm` of the old list vs `find ui -maxdepth 1 -name '*.c'`): seven
standalone host utilities (each has its own `main()`), `prof.c` (a 53-line
`DISKOS_PROFILE`-gated shim), and `sqlite3.c` (compiled separately with SQLITE_FLAGS).
`md5.c`, `i18n_tables.c` and the generated `font_*.c` ARE app sources and stay in the glob;
`ui/lvgl/` and `ui/third_party/` are directories a top-level `*.c` glob never matches.
Reasons live in comments.md (no comments in Makefiles — house rule).

### 4. Two genuinely-hardcoded C paths (the sanctioned exceptions)

- `ui/tests/config_test.c:12` had `#define TDIR "/tmp/diskos_cfgtest"` UNGUARDED and
  ACTIVE — the test reads the conf file back and chmods the dir itself, so it must follow
  the same root the Makefile points `config.c` at. Now `#ifndef TDIR`-guarded with the
  harness passing `-DTDIR='"<root>"'`.
- `ui/tests/playreq_test.c`'s `/tmp/diskos_cfgtest/pcm` fallback was already `#ifndef`
  guarded and overridden — left untouched, worth knowing it exists for hand compiles.
- `art.c:122`'s `/tmp` staging stage is hardcoded in PRODUCTION code — NOT touched
  (device build must not change); the Makefile routes around it instead (EXDEV, above).

## Verification (real commands, real outputs)

1. `cd ui/tests && make clean && make run` — exit 0, all 36 tests green.
2. `make check` (suite again + 9 python tests) — `CHECK_EXIT=0`; run twice on the final
   tree, the second run proving back-to-back idempotency.
3. Determinism: `make -n CC=cc run` twice — `md5sum` both dumps identical (`9ee21612`).
4. Old-vs-new command equivalence: dumped `make -n CC=cc run` from the old Makefile (via
   `git show HEAD:ui/tests/Makefile` in a copied tree) and the new one, joined continuation
   lines, normalised the temp roots, compared token multisets per target: all 37 shared
   targets (36 tests + sqlite3_host.o) IDENTICAL; the only deltas are config_test's new
   `-DTDIR` token and the artdec_fake output path.
5. Two concurrent checkouts: copied the tree to `/tmp/opencode/checkout-b`, `make clean`
   in both, ran `make run` in both simultaneously — `CONCUR_A_EXIT=0` and
   `CONCUR_B_EXIT=0`, with two separate `/tmp/diskos-cpt-<hash>` roots present afterward.
6. Device build, before and after, from `ui/`:
   `podman run --rm --userns=keep-id -v "$PWD:/src:Z" localhost/diskos-ui-builder:latest`
   (both after `make -C ui clean`):

   | | baseline (old Makefile) | after (glob) |
   |---|---|---|
   | exit | 0 | 0 |
   | mq_ui md5 | 0ccb960ae8ddf81218214114faf6c6df | e924f62a161c9c851a333524ddfcf18e |
   | size | 4354212 | 4354196 |
   | src_md5 | 49bf467b67b33a4e0ec6d6fc53d16c00 | 7b0e1f4c61f98788eeba91dc9dc9bd52 |

   Both md5 changes are fully explained by source-list ORDER and nothing else, proven two
   ways: (a) the object set is identical — 164 sources, `set(old) == set(new)`, same count
   of linked objects in both link lines (166 each); (b) content-order invariance —
   `md5(cat)` over the OLD list order reproduces the baseline src_md5 exactly, over the
   NEW order reproduces the after src_md5 exactly, and both SORTED produce the SAME hash.
   The sorted link order changes layout (16 bytes of section padding), hence the mq_ui
   md5/size delta.

## Gotchas

- **Never use computed prerequisites in a static pattern rule.** They expand at parse time
  with an empty stem and vanish silently; the recipes still work, so the breakage is
  invisible until you notice a stale binary. `$(eval $(call))` per target is the fix.
- **Makefile-only edits do not rebuild test binaries** (the Makefile is not a prerequisite,
  same as before the refactor) — `make clean` between harness iterations, or a stale
  binary silently runs with old defines.
- **Pin the workdir on every shell call.** One diagnostic round ran without a workdir and
  landed in the DEFAULT directory (`~/diskos/diskos`, the coordinator's checkout), so the
  "stale binary" I chased for ~20 min was another checkout's file. Side effects there,
  disclosed to the coordinator: `touch`ed `ui/tests/coverart_pipeline_test.c` twice
  (content unchanged), deleted and rebuilt its gitignored test binary, and ran that
  binary once (it wrote stale shared-`/tmp` state). No tracked content changed.
- **Path budgets in production code decide temp-root placement**, not preference:
  `tmp[64]` (config.c), `out[40]` (coverart.h), `p[0]=='/'` (card.c environ check),
  `rename(2)` from a hardcoded `/tmp` stage (art.c, EXDEV).
- Two shell quoting bites: `$(...)` inside a double-quoted `git commit -m` gets
  substituted by the shell (fixed with `--amend` and single quotes), and `sed 's|\$\(APP\)/||'`
  does not strip because `\$` and `\(\)` are the wrong escapes for BRE.

## Not verified

- The physical device: never touched (as required). The device build is proven only by
  the two podman cross-builds.
- The OLD harness's concurrent failure was not reproduced on demand (it is
  timing-dependent; the premise came from flakes already observed that day). What is
  proven is the new harness surviving the two-checkout concurrency test.
- The podman builder image's entrypoint internals (what it runs beyond the visible make).
- On-device `/tmp` vs `/usr/data` filesystem layout vs art.c's rename flow — noted as a
  question, deliberately not investigated (would touch production code for a harness task).

## References

None — this was entirely local work against the repo and toolchain; no web sources
contributed to the diagnosis or the fix.

Related: [[diskos-card-module-card-close-spine-2026-11-18]],
[[diskos-idle-machine-idlegov-extract-2026-11-18]],
[[diskos-transport-command-vocabulary-2026-11-18]],
[[diskos-lastfm-removal-terminal-cursor-and-subagent-worktrees]],
[[diskos-strip-comments-from-source-into-comments-md]],
[[diskos-session-and-play-admission-modules-parallel-agents]].
