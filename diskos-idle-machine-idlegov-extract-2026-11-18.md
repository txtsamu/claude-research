---
type: build-log
tags: [diskos, snowsky-disc, idlegov, backlight, power-key, screensaver, saver, main-loop, refactor, host-tests, subagents]
created: 2026-11-18
last_verified: 2026-11-18
status: current
---

# diskOS: the idle machine (power key / backlight / saver) extracted into idlegov (2026-11-18)

Request: as one of four parallel refactor agents, extract the idle machine from `ui/main.c`
into a host-testable module with ZERO behavior change. Worktree
`/home/moo/.local/share/opencode/worktree/c6e21f/arch-idle`, branch `arch/idle` (off `main`
at `e6bc3da`). One local commit, NOT pushed (the coordinator merges the four branches):

```
b292723 Idle: extract the power-key/backlight/saver machine into idlegov
```

Wall time: about 75 minutes end to end (reading the step/poll patterns ~25 min, module +
main.c rewrite ~20 min, test + Makefile wiring ~10 min, comments.md port ~15 min, full
`make check` runs ~5 min of that in background). All figures are measurements from the
session; the branch split is from the coordinator's design.

## What the machine was

Three inline blocks in the `ui/main.c` loop plus two pure steps with no test references:

- the driveable-key branch (`fw_power_key_driveable()`, V2.57): polls `ipc_screen_snapshot`,
  reconciles the player's own screen frames, defers a wake-press injection 300 ms,
  relevels foreign brightness every 250 ms
- the legacy two-pass brightness poll (pass 0: `ui_backlight_take_foreign`, pass 1: sysfs read)
- the saver timeout ladder (TMAP index to seconds, past_dim -> show saver + dim, then off;
  manual Sleep tile path with a 10 s default)
- state: `bl_state`, `powerkey_t pk`, `poweroff_inhibit`, `inject_pending`, the aa23/aa03
  sequence cursors, `last_activity`, `last_blpoll`, `g_manual_sleep`

## The module

Name chosen: **`idlegov`** (idle governor; matches the repo's short lowercase modules
bootstate/playreq/srcswitch). Files `ui/idlegov.h` + `ui/idlegov.c`, no LVGL, no sysfs;
pure C. Interface shape, facts in / decisions out, one clock fact per call site so the
caller keeps reading `lv_tick_get()` exactly where the old code read it:

```c
typedef struct { int seen; int player_off; unsigned off_seq; } idlegov_keys_t;
typedef struct {
    int bl_state;                     /* 0 awake, 1 dim, 2 off */
    idlegov_keys_t pk;
    unsigned scr_seq_seen, aa03_seq_seen, gen_seen, inject_for, inject_gen;
    int poweroff_inhibit, inject_pending;
    uint32_t inject_due, last_blpoll, last_activity;
    int manual_sleep; uint32_t manual_sleep_at;
} idlegov_t;

void idlegov_boot(idlegov_t *g, int boot_br, int startup_deferred, int written, uint32_t now);
void idlegov_screen(idlegov_t *g, int on, unsigned sq, unsigned pq, unsigned gen, uint32_t now, idlegov_screen_out_t *out);
int  idlegov_inject_pending(const idlegov_t *g, uint32_t now);
int  idlegov_inject_take(idlegov_t *g, int on, unsigned sq, unsigned pq, unsigned gen);
int  idlegov_blpoll_due(idlegov_t *g, uint32_t now);
int  idlegov_foreign_relevel(const idlegov_t *g, int cbr, int written);
int  idlegov_powerkey_pass(idlegov_t *g, int cbr, int ours, unsigned ours_seq, int dark, unsigned write_seq);
int  idlegov_powerkey_step(idlegov_keys_t *k, int cbr, int ours, unsigned ours_seq, int dark);
int  idlegov_screen_frame_step(int on, int bl_state, int *player_off, int poweroff_inhibit);
int  idlegov_touch_wake(idlegov_t *g, int any, uint32_t now);
void idlegov_saver(idlegov_t *g, uint32_t now, int in_saver, int saver_ok, int saver_secs, int off_secs, idlegov_saver_out_t *out);
```

`idlegov_screen_out_t {act, note_input}` and `idlegov_saver_out_t {show_saver, dim, off}`
carry the decisions the main loop applies (`ui_backlight`/`wake_backlight` sysfs writes stay
in `ui/settings.c`, LVGL effects stay in main.c). `main.c` holds a file-scope
`static idlegov_t g_idle` so `ui_request_sleep()` (called from the Quick Settings tile
callback) can arm the machine.

## Steps in order

1. Read `agents/AGENTS.md`, `GLOSSARY.md`, both ADRs, then the patterns to copy:
   `ui/power.c` (the `POWER_CORE_ONLY` host-testable core), `ui/restart.c`, `ui/bootstate.c`
   and their tests (`ui/tests/power_test.c` style: statics + assert + `puts("...: ok")`).
2. Wrote `ui/idlegov.h` / `ui/idlegov.c` by transcribing each original block statement by
   statement (the switch arms, the gen reset, the pass loop's adoption, the off_at math with
   the manual 10 s default, TMAP `{0,30,60,120,300}` and the 60/120 out-of-range defaults).
3. Rewrote the `ui/main.c` regions: include, `g_idle` + forwarder for
   `ui_request_sleep`, boot init via `idlegov_boot`, the two poll branches, the ladder, and
   the ~30 `bl_state`/`last_activity` reads elsewhere in the loop -> `g_idle.` members.
4. `cc -fsyntax-only -std=gnu11 -Wall -Wextra -D_GNU_SOURCE -DLV_CONF_INCLUDE_SIMPLE -I ui -I ui/third_party/freetype-2.13.3/include ui/main.c`
   -> exit 0, only the three pre-existing `-Wmisleading-indentation` warnings (lines 135/251/258,
   untouched code). The podman cross-build is forbidden for this branch, so this host syntax
   check plus the test suite is the compile verification for main.c.
5. Added `$(APP)/idlegov.c` to APP_SRCS in `ui/Makefile` (one name on the existing long line).
6. Wrote `ui/tests/idlegov_test.c` (12 test functions) and wired it the hand-wired way in
   `ui/tests/Makefile`: build rule after `power_test`, name in the `run:` prerequisite list,
   `@echo "--- idlegov ---"` + `./idlegov_test` run lines, name in `clean:`.
7. `make idlegov_test && ./idlegov_test` -> two assertion failures, both were wrong test
   scenarios, not module bugs (details below). Fixed the test; it passes.
8. Ported the `comments.md` entries for moved code from `## ui/main.c` to new
   `## ui/idlegov.h` / `## ui/idlegov.c` sections (alphabetical placement between handoff and
   home), updated the main.c entries whose code text changed (the apply arms, the due checks,
   `ui_request_sleep`, the boot call) with current line numbers, left the file's historical
   stale-number entries untouched as the file's own convention does.
9. `cd ui/tests && make run` then `make check` -> both exit 0. Committed.

## Gotchas learned while writing the test

- Feeding the screen-poll test a *decreasing* aa03 counter (`pq=9` then `pq=0`) is not a
  realistic snapshot sequence: any pq change re-arms the inhibit, so a subsequent sleep
  frame while inhibited correctly does NOT arm a press. The inhibit only clears on a
  generation change. The first assertion failure was the test fighting correct behavior.
- The second failure: after a gen reset the consumed sleep frame sets `player_off` back to 1
  in the same call (the frame's own meaning), so assert `player_off == 1`, not the
  reset value 0.
- The pass-0 `ui_backlight_take_foreign(&was_dark, &at_seq)` always overwrites the prefills
  with stale foreign values even when it returns -1; that quirk lives in
  `ui/settings.c:480` and is why the prefill/take pattern had to stay in the caller verbatim.
- `powerkey_step`'s "equal-level wake" case needs `ours_seq == off_seq` (no diskOS write
  since the sleep): a player writing the user's own level still wakes the screen, a diskOS
  write in between (`ours_seq != off_seq`) does not.

## What stayed inline in ui/main.c, and why

- `powerkey_defer_startup` (main.c:166): a one-shot boot-policy read of /proc/uptime and
  fwcaps; not per-turn machine logic, and moving it would drag fwcaps into the host-test
  closure for no testable decision.
- `power_key_inject` (main.c:179): the apply side (writes /dev/input), the machine only
  decides "send the press now".
- `dim_level` (main.c:212): the dim *value* picker (ui_effective_brightness + LVGL screen
  state); the machine outputs the DIM decision, the caller picks the level.
- The saver-wake inside the touch handler (`g_idle.bl_state && !g_idle.pk.player_off`):
  touch-input code, kept as direct struct member access.
- `kbinput_active`/`usbhid_poll`/`chargemode_*`/`power_tick` lines: other modules' polls;
  only their `g_idle.last_activity` writes go through the machine struct.
- All fact gathering: `ipc_screen_snapshot`, `read_int_file`, `ui_backlight_take_foreign`
  and the two-pass loop body.

## Verification (real output)

```
$ cd ui/tests && make idlegov_test && ./idlegov_test
idlegov_test: ok

$ make run; echo "run_exit=$?"    (full suite, filtered tail)
--- power ---
./power_test
power_test: ok
--- idlegov ---
./idlegov_test
idlegov_test: ok
...
run_exit=0

$ make check; echo "check_exit=$?"    (run + the python suites)
Ran 5 tests in 0.056s
OK
Ran 5 tests in 0.124s
OK
check_exit=0
```

One `make run` invocation failed at `outroute_test` (`usb_audio_without_a_dac_falls_back`),
a test whose binary does not compile or link anything from this branch's diff. It passed in
the two earlier full runs, standalone twice after, and in the final `make run` + `make check`
used for the commit. Best explanation: the tests hardcode `TDIR := /tmp/diskos_cfgtest`, so
a concurrent suite run from a sibling worktree (three other agents work the other branches)
can leave `outroute/card*/usbid` state behind and make the "no DAC found" case find one. Not
proven (no live process by the time I checked `ps`); if the flake recurs it belongs to the
coordinator's harness rework, not to idlegov.

## Not verified / honest limits

- No cross-build and no device run: the podman cross-build is forbidden on this branch and
  the physical Disc must not be touched. `ui/main.c` compiles only via the host
  `-fsyntax-only` check above; the target build and on-device behavior of the loop are
  reviewed, not executed.
- Two deliberate sub-millisecond tick-read consolidations, both bounded and unobservable:
  the 250 ms poll gate stores the same `now` it checked (the old code read the tick twice,
  check then store), and the INJECT arm uses the `now` passed into `idlegov_screen` instead
  of a fresh read inside the case arm. Everything timing-critical keeps its own fresh
  `lv_tick_get()` at the original position: the inject due check, the SF/PK wake
  `last_activity` stamps, the touch wake, and the ladder.
- The moved `g_manual_sleep` lost its `volatile` qualifier inside the machine struct; it is
  only ever touched from the main thread (the Sleep tile callback runs inside
  lv_timer_handler), so the qualifier was already unnecessary.

No external sources were used; everything came from reading this repo.

Related: [[diskos-transport-command-vocabulary-2026-11-18]],
[[diskos-sd-clean-unmount-and-fsdetect-2026-11-17]],
[[diskos-boot-starting-state-and-boot-net-errors-2026-11-10]],
[[diskos-lastfm-removal-terminal-cursor-and-subagent-worktrees]].
