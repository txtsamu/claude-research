---
type: build-log
tags: [diskos, ui, sd-card, power, restart, refactor, c, host-tests]
created: 2026-11-18
last_verified: 2026-11-18
status: current
---

# diskOS UI: one card module, one card-close spine

Repo `txtsamu/diskos`, branch `arch/card` (worktree `~/.local/share/opencode/worktree/c6e21f/arch-card`), base `e6bc3da`, work `71ba4b9` (local only, not pushed; the podman cross-build was deliberately not run and the device untouched). Parallel agents held the settings-sender, transport and idle branches; this one stayed inside the storage/card regions of `ui/main.c` plus `ui/power.*` and `ui/restart.*`.

The request had two halves. First: the card's physical facts and mutations were private helpers of the composition root `ui/main.c` (the fsync-after-unmount ladder, the /proc scan proving the running Player is delete-guarded, the configfs gadget readers, the cold-boot mount worker), while `ui/power.h:53` leaked the seam by forward-declaring `env_unmount_card`, a `main.c` function. Move all of it into one module behind the existing env seams. Second: `ui/power.c` and `ui/restart.c` each carried its own copy of the ordered close (quiesce, wait drained, spawn and watch a `sync` child, unmount) and the copies had drifted - `POWER_DRAIN_MS 8000` vs `RESTART_WRITERS_MS 10000`. Extract one transaction and unify the drain timeout to 10000 ms, the single intended behavior change.

## Time estimate

About 3 hours end to end (an estimate from the transcript cadence, not a timer). Roughly a third of it reading `agents/AGENTS.md`, `GLOSSARY.md`, ADRs 0001/0002, the existing seam modules and `comments.md`'s conventions before designing anything. Measured figures: `cc -fsyntax-only` on one module is under 5 s; a full `make -C ui/tests run` is about 90 s; `make check` (which re-runs `run`, then the Python tests) is about 4 min; I ran the pair four times green plus one deliberate from-clean rebuild.

## What changed

- **`ui/card.c` + `ui/card.h`: the card's physical lifecycle in one module.** Fact readers keep the shapes the existing seams want (`int fn(void)`), so they drop straight into `struct sd_env` and `struct launcher_env`: `card_mounted` (was `coldplug_mounted`, /proc/mounts), `card_exported_to_host` (was `sd_exported_to_host`, the fail-closed UDC+LUN gadget reader), `card_host_confirmed` (was `storage_host_confirmed`), `card_player_guarded` (was `storage_player_guarded`, the /proc environ PATH scan against the real `rmguard_dir_ok`). The close ladder `card_unmount` (was `env_unmount_card`) and the cold-boot worker moved in whole. Everything mutating or time-based goes through one new `struct card_env` (`umount`, `umount_lazy`, `mount`, `unmount_wait` = the 100 ms retry nap, `send_source`, `launch_status`, `fw_direct_mount`, `source_mode`, `writable`, `coldplug_begin`, `coldplug_end`), wired in `main.c` once. Every sysfs/proc/mount path is a `#ifndef`-overridable define (`CARD_PROC_ROOT`, `CARD_MNT`, `CARD_DEV`, `CARD_DEV_WHOLE`, `CARD_UEVENT`, `CARD_GADGET_DIR`, `CARD_LOG_PATH`), following the `vbus.c`/`outroute.c` pattern exactly.
- **The worker's per-iteration body became `card_coldplug_step(i, direct, &nudged)`.** The thread (`coldplug_thread`, real 0.5 s/3 s waits) stays on the device, but the decisions - fstype preference after `sdfs_detect`, the one-way uevent fallback at `i >= 10`, the post-mount export rollback - are now plain calls a host test can drive. The original called `sd_coldplug_end()` on every path of every iteration; the split had to preserve that mutex pairing exactly, and `card_coldplug_step` does (begin at entry, end at exit, act between).
- **`main.c` keeps only wiring.** The `g_sd_env`, `g_launcher_env` and `g_restart_env` tables now point at `card.h` functions; a new `g_card_env` table plus `card_set_env` sits beside them at init; the gate callback calls `card_coldplug_start()`; `ui_detect_source_mode` keeps `uac_bound` (the DAC gadget is not card state) but asks `card_exported_to_host` for the storage fact. The leaked `power.h:53` forward declaration is deleted. `main.c` dropped the pthread/dirent/sdfs includes that only served moved code (sys/mount.h stays - the env wiring names the libc `mount`/`umount`/`umount2`).
- **`ui/cardclose.c` + `ui/cardclose.h`: the shared close transaction.** Chosen home: its own small module, not folded into `card.c` - the card module is path facts and env-injected mutations, while the transaction is a time-stepped procedure over ops that each caller adapts from its own existing seam; folding them would couple the pure readers to a step machine. Interface: `struct cardclose_ops { drained, sync_start, sync_poll, sync_kill, unmount, now }` (all required except `unmount`), `cardclose_begin/tick/abort`, phases `OFF/DRAINING/SYNCING/DONE` plus four sticky terminal results (`DRAIN_TIMEOUT`, `SYNC_TIMEOUT`, `SYNC_FAILED`, `SPAWN_FAILED`) the callers map to their own failure words.
- **The quiesce step stayed with the callers, deliberately.** The brief said "quiesce then drain then sync then unmount", but restart's begin runs `stop_readers` and `save_clock` between quiesce and drain, and `quiesce_end` is caller-owned in every ending (power's `PW_PROTECTED` must keep the card closed). Owning quiesce in the transaction would have reordered restart's begin or double-ended quiesce. The spine owns everything from the drain on; both begins still call their quiesce first, so the walked order is unchanged.
- **`power.c` keeps `PW_*` and the endings.** The core adapts its `power_ops_t` members into a `cardclose_ops` stored inside `g_pw` and mirrors the transaction's DRAINING/SYNCING onto `PW_DRAIN`/`PW_SYNC`, so `power_test`'s phase assertions keep their meaning. `pw_fail` and the `PW_PROTECTED` recovery are untouched; the hand-off send still fires after the transaction's unmount ("US" order). `POWER_DRAIN_MS`/`POWER_SYNC_MS` left `power.h` for the transaction's `CARDCLOSE_DRAIN_MS 10000u` / `CARDCLOSE_SYNC_MS 15000u`.
- **`restart.c` keeps `RS_*`, the flash arm and the reboot.** Six one-line adapters wrap its own `restart_env` members into the transaction ops (`cc_sync_start` = `E->spawn("sync")` etc.), so the env's `spawn`/`wait`/`kill` keep serving both the sync child and the `hwclock` clock child exactly as before - including each caller's real spawn style, which the zero-behavior-change rule forbids me to unify away (restart really spawns `/bin/sh -c sync`, power really spawns `sync` directly; both stay).
- **Tests.** New `ui/tests/card_test.c` (release ladder busy-then-free via the USB-Storage request, EINVAL/ENOENT fast path, lazy-detach fallback and the still-busy report, fstype ordering after a REAL `sdfs_detect` - exfat/vfat preference, the EINVAL option retry, the cross-fstype fallback - the one-way uevent nudge, and the post-mount export rollback including the export that appears DURING the mount, which is the actual device race the rollback guards). New `ui/tests/cardclose_test.c` (unmount-after-sync ordering, the unified 10000 ms drain expiry with 8000 ms explicitly not enough, the 15000 ms sync timeout killing the child exactly once, sync/spawn failure without unmount, abort mid-sync, terminal-phase stickiness). `power_test.c` gained a drained knob plus drain-timeout, sync-timeout and spawn-failure cases; `restart_test.c` passed unchanged, which is the point of the adapter design.

## Two traps worth recording

**1. The ops table must outlive `cardclose_begin`.** `cardclose` stores the pointer (`E = ops`). My first `restart_begin`/`power_shutdown_begin` built `struct cardclose_ops cc` on the stack and passed it; ASan caught it on the first `restart_test` run (`stack-use-after-return ... frame restart_begin ... 'cc'`) - and only ASan, because the stack bytes often happen to survive. The fix is storage with function lifetime: `power.c` keeps its adapted table in `g_pw`, `restart.c` in a static. Any future module that hands an env/ops pointer to a step machine should do the same, and the comments.md entry for `cardclose.h` says so.

**2. `dacvol_sys_test` flakes on back-to-back suite runs, pre-existing.** The commit gate is `make run` then `make check`, and `check` re-runs `run`. Twice, the second run died in `dacvol_sys_test` - once as `wait_state(DACVOL_MIX_FAILED, 6000)` (main.c:125), once as `setup failed: DROP TABLE SONG;: no such table: SONG`. That test deliberately leaves background repair children running ("an unclean exit is repaired... the idle repair finishes the job"), and it wipes its own temp dir at start (`rm -rf $D && mkdir -p ...`), so stragglers from a just-finished run collide with the fresh one. Dead ends ruled out: not leftover state (the test wipes it), not my branch (its rule closure is `../dacvol_sys.c ../dacvol.c ../command_spawn.c dacvol_sys_test.c`, none touched; and a throwaway worktree at the base commit `e6bc3da` reproduced an intermittent failure on repeated runs too: first_rc=0, second_rc=0, third_rc=1). Recipe that works: give the stragglers a minute, then re-run. The `pkill` gotcha that cost a shell command: `pkill -f dacvol_sys_test` kills your own harness because the pattern matches your own command line - use `pkill -f 'dacvol_sys_te[s]t'`.

## Verification

From `ui/tests`, both gates green before the commit (and once more from `make clean`):

```text
$ make run   (exit 0)
--- restart ---
./restart_test
restart_test: ok
--- cardclose ---
./cardclose_test
cardclose_test: ok
--- card ---
./card_test
card_test: ok
--- power ---
./power_test
power_test: ok
...
$ make check  (exit 0)
COMPLETE storage_test.py
...
Ran 5 tests in 0.127s
OK
```

Not covered by the host gates and stated plainly: the podman MIPS cross-build was not run (per instructions) and the device was never touched. Mitigation: `cc -fsyntax-only -I. main.c`, `power.c` (both `POWER_CORE_ONLY` and full), `restart.c`, `card.c` and `cardclose.c` all pass on the host - `main.c` and full `power.c` include the LVGL headers, which turn out to be host-portable, so the whole composition root still type-checks its env tables. The `APP_SRCS` line in `ui/Makefile` gained `card.c` and `cardclose.c` (that line conflicts across branches by design; the coordinator resolves it). One sequence nuance kept rather than smoothed over: restart used to kill the `hwclock` clock child before the unmount; the transaction now completes the unmount first and restart kills the clock after, on the way to its ending - no test anchors that internal order and the clock child is unrelated to the card.

`comments.md`: new sections for `ui/card.c` (38 entries - the coldplug/export knowledge moved over from `ui/main.c` with anchors adapted, plus fresh entries for the ladder, the step split and the path defines), `ui/card.h`, `ui/cardclose.c`, `ui/cardclose.h`, `ui/tests/card_test.c`, `ui/tests/cardclose_test.c`; the `ui/main.c` index count adjusted (668 -> 637); the `power.c`/`power.h` entries that described the old inline spine now name the transaction; the drain-timeout unification and its rationale are documented under `cardclose.h`.

Glossary candidates for the coordinator (names only): **Card** (the physical microSD and its lifecycle module), **Card close** (the shared drain-sync-unmount transaction), **Release ladder** (the busy-card unmount sequence that asks the Player to enter USB Storage), **Cold mount** (the boot-window one-shot that mounts an already-inserted card).
