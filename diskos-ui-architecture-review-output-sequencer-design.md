---
type: investigation
tags: [diskos, snowsky-disc, ui, c, architecture, refactor, working-mode, output-route, ipc, outseq, design-it-twice, c-audit]
created: 2026-10-27
last_verified: 2026-10-27
status: current
---

# diskOS `ui/` architecture review: the `outseq` output sequencer design, plus a C-mistakes audit

Repo `/home/moo/diskos/diskos` (fork `txtsamu/diskos`), branch `fix/usb-dac-workmode`. C firmware UI (LVGL) that drives the stock `mq_player` over an IPC frame channel. **Outcome: a design only, no refactor code written yet.** The first implementation commit is still to do. Two small things were committed: a `bt.c` bug fix and a `GLOSSARY.md`. Companion docs: [[diskos-usb-dac-exit-deadlock-roles-and-volume-fix]], [[diskos-usb-audio-reverse-engineering-mq-player]].

## 1. Finding the hot spots (no glossary, no ADRs existed)

```bash
cd /home/moo/diskos/diskos
git log --oneline | head -80
git log --name-only --pretty=format: -150 | grep -v '^$' | sort | uniq -c | sort -rn | head -40
git log --since=2026-09-01 --name-only --pretty=format: | grep -v '^$' | sort | uniq -c | sort -rn | head -15
wc -l ui/*.c ui/*.h | sort -rn | head -40     # ignore font_*.c and sqlite3.c (generated / vendored)
ls GLOSSARY.md docs/adr                        # neither existed
```

- `ui/main.c` is 4055 lines and the most-changed file (17 of the last 150 commits), followed by `modes.c`, `settings.c`, `scanner.c`, `bt.c`.
- Recent commit subjects are all about Working Mode and output routing ("pass through Local instead of refusing USB Audio exits", "keep the player's USB output route across the UI re-launch", "BT route: only while Local source").
- Host tests: `ui/tests/Makefile` builds only `config_test` and `playstate_test`. `storage_test.py` and `transport_test.py` slice `main.c` text between comment markers and compile the fragment. Nothing tests `modes.c`, the BT route or the route state machine.

An Explore sub-agent read the hot spots and returned seven candidates. Spot-checks with grep confirmed most of its claims. One was **wrong and dropped**: "the Local-and-not-BT predicate is duplicated 5 times" (`grep` found it once, at `main.c:1658`).

| # | Candidate | Strength |
|---|---|---|
| 1 | One Working Mode module for source mode + output route (`main.c:626-833` vs `modes.c:14-415`, which call each other) | Strong |
| 2 | Output sequencer owning the IPC frame ordering (this doc) | Strong |
| 3 | One admission rule for "may a route/mode change run now?" | Worth exploring |
| 4 | One module deciding what survives restart / theme re-launch (5 persistence channels) | Worth exploring |
| 5 | Pull the SD handoff state machine out of `main.c` | Worth exploring |
| 6 | Boot/reconnect coordinator on one clock | Worth exploring |
| 7 | One Bluetooth sink probe | Speculative |

The user chose to go by my recommended order: 2, then 1 (absorbing 3), then 4, then 6.

## 2. Why candidate 2 (facts read from the code)

Routing frames (`0666` out device, `0642` gadget/USB port role, `0657` player work mode, `06c1` BT init, `0818` BT-RX prep) are hand-sequenced in five places:

- `ui/modes.c:61-124` has `OUT_SEQ[]`, `out_seq_send(t, full)` and `modes_local_init(with_gadget)`. `out_seq_send` returns 0, -1 (the `0666` was refused, nothing changed) or -2 (the route moved but the tail failed).
- `ui/main.c:727-747` `source_send(mode)`: `0666 6`, then per mode `0642 0`/`0657 8`, `0642 2`/`0657 1`, `0818 0`/`0642 0`/`0657 6`, `0642 1`/`0657 8`.
- `ui/main.c:591-609` `route_analog`: `0666 6`, `0657 8`.
- `ui/main.c:549-590` `ui_route_bt`: `0666 6`, `0642 0`, `0657 8`, `06c1 0`, `0666 2`, `0657 8`, then the `06b3` codec frame. Only `0666 6`, `0666 2` and the codec frame abort on failure; the rest are ignored. `modes_output_reset()` is called after the 5th frame (`0666 2`).
- Bare `0657 8` re-asserts at `main.c:1619, 1658, 1808`; play preambles `modes_local_init(0)` at `1574, 1637`; boot init `modes_local_init(1)` at `1415`.

Inconsistencies that a refactor must preserve or consciously change:

- `modes.c` sleeps 65 ms between `0666` and `0642` for Internal/SPDIF. `source_send(0)` sends the same frames with no sleep.
- In `modes_local_init` the boot form sends the gadget frame *before* `0666` for Internal/SPDIF, the opposite order to `out_seq_send`.
- State reset happens at different steps: after frame 1 in `source_send`, after frame 5 in `ui_route_bt`.
- The hard-won rules ("`0666` into a live stream killed mq_player", "`0666` not followed by `0657 8` leaves NO_WORK_MODE") live only in `modes.c` comments. The BT path does not use them.

Counting frame literals: `grep -c '"06[0-9a-f][0-9a-f]000C' ui/main.c` gives about 20 raw routing frame literals in `main.c`.

## 3. Decisions made in the grilling loop (with the user)

| Q | Decision |
|---|---|
| Scope | Synchronous frames only. LVGL timers (`osw_tick`, `usbw_tick`, recovery, unplug watch) and the pause/seek/resume ritual stay in `modes.c`/`main.c`. |
| Seam | `ipc_send_cmd` (already the one place frames leave the UI). Tests link a recording fake of it (link-time substitution, like `config_test`/`playstate_test`), not an ops struct. |
| Behaviour | Strictly behaviour-preserving, per-step data (must-land / best-effort, settle, route-moved step). Behaviour changes are separate, individually device-tested commits. |
| Verification | One caller moved per commit, in this order: `modes.c` table, `source_send`, `route_analog`, `ui_route_bt`, play preambles. The user verifies on the Disc between steps. Each commit message has a side-by-side old/new frame table. |
| State | Stateless sequencer. Result `OK` / `REFUSED` / `MOVED`. `g_out_route` stays in `modes.c`. |
| Vocabulary | Callers state intent; no routing frame literal outside `outseq.c`. The BT sink request takes a pre-built `06b3` codec frame so `outseq` doesn't depend on `bt.c`. |
| Name/file | `ui/outseq.{c,h}`, no LVGL include. Needs adding to `APP_SRCS` in `ui/Makefile` (line 33). |
| Tests | `outseq_test.c` in `ui/tests/Makefile run`, ASan+UBSan: golden frame lists, failure injected at every step, settle measured with `clock_gettime`. A final-commit guard test fails if `0666000C`/`0642000C`/`0657000C`/`06c1000C`/`0818000C` appear outside `outseq.c`. |
| REFUSED | Means "the caller keeps its recorded state", not "nothing was sent". `route_analog` can send `0666 6`, fail on `0657 8`, and still return REFUSED. |
| Codec frame | Built **before** any frame is sent. Today it is built after the route already moved (a failure left the Player rerouted and paused). This is the one intentional behaviour change; it needs a check that `ui_bt_codec_frame` (`bt.c:340`) can't fail on a validated 17-char MAC. |

## 4. Interface: design-it-twice (four parallel sub-agents, one constraint each)

All were read-only `Explore` agents given the same inventory and the glossary; each returned header, call sites, hidden implementation, test fake and trade-offs.

- **A, one entry point** `outseq_run(const outseq_req_t*)` with a tagged `kind`. Smallest interface, but callers must know which fields each kind reads and `.gadget` means different things per kind. Untyped dispatch: the depth is cosmetic.
- **B, step tables** (plans, runner, 6 builders, 6 one-shots; 5 types, 3 generic functions). Failure arbitration is in one runner, but no caller composes plans, so the interface is wider than any caller needs.
- **C, common-caller default** (7 named typed functions; the 5 most frequent sites are void one-liners). The `rc != REFUSED -> modes_output_reset()` line is still hand-written at 2 sites and the Local-and-not-BT gate stays in callers (policy, not sequence).
- **D, ops struct** (`send` + `delay_us` passed to every function, like `power_ops_t` in `power.c`). Its real argument is asserting the settle position; that is achievable without injection by timestamping calls in the fake. Eleven call sites would carry a pointer that is always the same.

**Chosen: C, with B's table-and-runner kept private inside `outseq.c`.**

```c
typedef enum { OUTSEQ_OK = 0, OUTSEQ_REFUSED = -1, OUTSEQ_MOVED = -2 } outseq_rc;  /* rc < 0 still means failure */
typedef enum { OUTSEQ_FULL, OUTSEQ_QUICK } outseq_form_t;  /* QUICK = Settings SPDIF toggle: no settle, no gadget frame */

outseq_rc outseq_route(outseq_route_t target, outseq_form_t form);  /* also the "restore Internal" recovery call */
outseq_rc outseq_local_boot(outseq_route_t current);
void      outseq_local_preamble(outseq_route_t current);            /* best effort; both callers ignore the result */
void      outseq_assert_workmode(void);
outseq_rc outseq_source(outseq_src_t mode);
outseq_rc outseq_analog(void);
outseq_rc outseq_bt_sink(const char *codec_frame);                  /* caller builds the 06b3 frame */
```

Minor accepted deviations (all four designs hit them): an invalid source mode now sends nothing (it used to send `0666 6` + reset, then fail; `ui_set_source_mode` already rejects `mode<0||mode>3` at `main.c:782`); the state reset happens after the sequence rather than between frames (invisible unless another thread reads `g_out_route` mid-sequence; not checked).

## 5. C-mistakes audit of `ui/*.c`

Search first (queries: "common mistakes beginners make in C programming"; "SEI CERT C coding standard common pitfalls strncpy snprintf buffer overflow format string"; "C undefined behavior common bugs ..."). The results were thin: mostly secondary sources, and the CERT wiki pages themselves did not come back, so the `strncpy`-doesn't-terminate point is from general knowledge, not the sources. The checklist: `=` vs `==`, string `==`, unchecked return values (`fopen`/`scanf`/`malloc`), unbounded `strcpy`/`sprintf`, missing NUL, uninitialised variables, use after free, leaks, magic numbers, signed overflow.

Scoped to app sources (65 files; vendored `sqlite3.c`, generated `font_*.c`, `i18n_tables.c`, `theme_kits.c` excluded):

```bash
cd /home/moo/diskos/diskos/ui
SRC=$(ls *.c | grep -v '^font_\|^sqlite3\|^i18n_tables\|^theme_kits')
grep -nE '\b(strcpy|strcat|sprintf|vsprintf|gets)\s*\(' $SRC
grep -nE '\bstrncpy\s*\(' $SRC
grep -nE '\b(scanf|sscanf|fscanf)\s*\(' $SRC
grep -nE '\b(system|popen)\s*\(' $SRC
grep -nE '=\s*(malloc|calloc|realloc)\(' $SRC       # then sed -n 'N,N+3p' each hit for the NULL check
grep -nE '(if|while) ?\([^=!<>()]*[^-=!<>+*/|&^%]=[^=][^()]*\)' $SRC | grep -vE 'for ?\('
```

(A first attempt at the `=`-in-condition regex failed with `Invalid range end`; the version above, with `-` placed first in the bracket, ran and found nothing.)

Verified safe (each hit's destination size was read, not assumed): `datetime.c:80-83` sprintf into exactly-sized buffers (correct, zero slack for `years`/`hours`/`mins`), `home.c:176` guarded by `strlen < sizeof`, `home.c:374-382` (80-byte buffer, max ~27 bytes), `ipc.c:376-379,643,655` (same capacity, `unescape` always NUL-terminates), `opustitle_worker.c:139,173` (guarded by the length check at `:233`), `theme_kit.c:23-28` (size-guarded, `calloc`ed), `wifi.c:438,535` (constants into larger buffers), `ui.c:152` (correct `strncpy` idiom), every `malloc` site read. The `system()`/`popen()` command builders are protected: `lyrics.c` percent-encodes title and artist (`lyrics.c:433-434`, `urlenc` keeps only alnum, `-`, `_`, `.`), `netart.c` encodes the query and allowlists the artwork URL (https only, host must end `.mzstatic.com`, `safe_art_url`), `weather.c` sanitises the location, and `bt.c` validates MACs with `bt_mac_valid` before every command that embeds one (checked at lines 548, 592, 605, 706).

**Real bug found and fixed** (`ui/bt.c:713`): `val[96]` uninitialised, `sscanf` return unchecked. When the `Name:` line has no value the buffer stays unwritten and `info_row("Name", val)` showed stack garbage. Reproduction of the `sscanf` behaviour:

```c
char val[96] = "UNSET";
sscanf("\nAlias: x", "%95[^\n]", val);   // rc=0, val still "UNSET"
sscanf("", "%95[^\n]", val);             // rc=-1, val still "UNSET"
```

Fix: `if(p && sscanf(p+6, "%95[^\n]", val) == 1) info_row("Name", val);` (commit `a46e73b`). Not compiled on this machine: the LVGL headers aren't in the checkout, so only the `sscanf` behaviour was tested standalone.

Other observations (not fixed): the build uses `-Wall` only (`ui/Makefile:21-23`); adding `-Wextra -Wformat=2` would catch the unchecked-return class. 19 `atoi` calls without error checks, mostly on own config/`/proc` data. Raw frame literals are the repo's dominant "magic number" instance, which is what `outseq` removes.

## 6. What was committed and pushed

```bash
git add ui/bt.c && git commit        # a46e73b  Bluetooth info: skip the Name row when sscanf matches nothing
git add GLOSSARY.md && git commit    # 9b3a7c7  Add GLOSSARY.md (Disc, Player, Source mode, Working Mode, Output route,
                                     #          USB Audio, Player work mode, Gadget, Output sequence)
git push origin fix/usb-dac-workmode # fast-forward; also published 270c7b4 (theme-change fix), which was unpushed
```

`GLOSSARY.md` defines **Output route** as including a Bluetooth sink, although the code tracks it separately (`g_route_mac` vs `g_out_route`), because the sequencer treats it as a route. `.claude/` is untracked and was left out.

## 7. Next task: implement `outseq`, one caller per commit

**Start of session.** Read this doc and `/home/moo/diskos/diskos/GLOSSARY.md`. Don't re-open the decisions in section 3; they are settled with the user. Work in `/home/moo/diskos/diskos`. Recommended: branch `refactor/outseq` from `fix/usb-dac-workmode` (HEAD `9b3a7c7` when this was written). Use the vocabulary from `GLOSSARY.md` and the design terms (module, interface, seam, adapter, depth, locality) in comments and commit messages. Do **one commit per step, then stop and let the user verify on the Disc before the next one** (section 3, "Verification"). Never combine a behaviour change with a move.

### Golden sequences (transcribed from the code on 2026-10-27; re-read the cited lines before relying on them)

`P` = pause `0201000C0000` (stays with callers, never in `outseq`). "must" = failure stops the sequence, "ign" = failure ignored, "soft" = failure remembered and the sequence continues (result is not OK).

| Sequence | Frames in order | Source |
|---|---|---|
| Route INTERNAL, full | `0666000C0006` (must, route-moved) · usleep 65000 · `0642000C0000` (must) · `0657000C0008` (must) | `modes.c:65,116-124` |
| Route SPDIF, full | `0666000C0004` · usleep 65000 · `0642000C0000` · `0657000C0008` | `modes.c:66` |
| Route USB, full | `0666000C0003` · (no sleep) · `0642000C0005` · `0657000C0008` | `modes.c:67` |
| Route any, quick | route frame (must, route-moved) · `0657000C0008` (must) | `modes.c:118` (`full=0`) |
| Local init, boot (`with_gadget=1`), INTERNAL/SPDIF | `0642000C0000` (must) · `0666` route (must) · `0657000C0008` (soft) | `modes.c:95-104` |
| Local init, boot, USB | `0666000C0003` (must) · `0642000C0005` (soft) · `0657000C0008` (soft) | `modes.c:98-102` |
| Local init, preamble (`with_gadget=0`), INTERNAL/SPDIF | `0666` route (soft) · `0657000C0008` (soft) | same |
| Local init, preamble, USB | `0666000C0003` (soft) · `0642000C0005` (soft) · `0657000C0008` (soft) | same |
| Source LOCAL | `0666000C0006` (must, route-moved) · `0642000C0000` · `0657000C0008` | `main.c:727-733` |
| Source USB DAC | `0666000C0006` · `0642000C0002` · `0657000C0001` | `main.c:734-738` |
| Source BT receiving | `0666000C0006` · `0818000C0000` · `0642000C0000` · `0657000C0006` (a failed `0818` skips `0642`) | `main.c:739-741` |
| Source USB storage | `0666000C0006` · `0642000C0001` · `0657000C0008` | `main.c:742-744` |
| Analog (leave BT) | `0666000C0006` (must) · `0657000C0008` (must); no route-moved step | `main.c:600-601` |
| BT sink (after `P`) | `0666000C0006` (must) · `0642000C0000` (ign) · `0657000C0008` (ign) · `06c1000C0000` (ign) · `0666000C0002` (must, route-moved, the 5th frame) · `0657000C0008` (ign) · caller-built `06b3` codec frame (must) | `main.c:570-579` |
| Work-mode re-assert | `0657000C0008` (ign) | `main.c:1619, 1658, 1808` |

Callers keep: the pause/seek/resume ritual, `0715` volume, the Local-and-not-BT gate (`ui_get_source_mode()==0 && !g_route_mac[0]`), the `modes_output_reset()` call (`if(rc != OUTSEQ_REFUSED)` at `source_send` and `ui_route_bt`), all toasts and all LVGL timers.

### Step 1 (first commit): `outseq` module + the sequences `modes.c` already owns

1. Create `ui/outseq.h` / `ui/outseq.c`. No LVGL include. `modes.h` and `ipc.h` are both LVGL-free (`ipc.h` only includes `<stdint.h>`, `modes.h` includes nothing), so `outseq.c` may include `ipc.h` for `ipc_send_cmd`. Define `outseq_route_t` (`OUTSEQ_INTERNAL=0, OUTSEQ_SPDIF=1, OUTSEQ_USB=2`) and add a `_Static_assert` in `modes.c` that the values equal `OUT_INTERNAL/OUT_SPDIF/OUT_USB` (`modes.h:10`). The header only declares what exists at this step; it grows with each later commit.
2. Interface for this step: `outseq_rc`, `outseq_form_t`, `outseq_route()`, `outseq_local_boot()`, `outseq_local_preamble()` (signatures in section 4). Internally: a private step table `{frame, settle_us, policy MUST|SOFT|IGNORE, is_route_moved}` and one runner returning `OK`/`REFUSED`/`MOVED`. A failure at or before the route-moved step is REFUSED, after it MOVED. A sequence with no route-moved step returns only OK or REFUSED. Also keep `usleep` real.
3. In `ui/modes.c`: delete `OUT_SEQ[]`, `OUT_WORKMODE` (`OUT_PAUSE` stays) and `out_seq_send`. Call `outseq_route()` from `out_run`, `out_recover_tick` and `usbw_tick`'s fallback. Map the old results one to one: old `-1` is `OUTSEQ_REFUSED`, old `-2` is `OUTSEQ_MOVED`, old `0` is `OUTSEQ_OK`. **Keep `modes_local_init(with_gadget)` as a thin shim** that calls `outseq_local_boot` / `outseq_local_preamble` with `modes_output_route()`, so `main.c` is untouched in this commit (its callers at `main.c:1415, 1574, 1637` move in the final step).
4. Add `$(APP)/outseq.c` to `APP_SRCS` in `ui/Makefile` (line 33; the build-id md5 at line 70 already covers all `*.h`).
5. Add `ui/tests/outseq_test.c` and, in `ui/tests/Makefile`, an `outseq_test` target (`$(CC) $(CFLAGS) -I.. ../outseq.c outseq_test.c -o $@`, no `ipc.c`) plus `./outseq_test` in `run`/`clean`. The test file defines its own `int ipc_send_cmd(const char *frame)`: log `{frame, clock_gettime(CLOCK_MONOTONIC)}`, return -1 when the call index equals `fail_at`. Cases: every row of the table above that belongs to this step, **plus failure injected at each frame index** asserting the exact frames sent so far, the result, and (for SOFT steps) that the sequence continues. Assert the INTERNAL/SPDIF settle with the timestamps (gap between the `0666` and `0642` frames at least 65 ms; no gap for USB). Don't intercept `usleep`.
6. Commit message: a side-by-side table of the old `OUT_SEQ`/`out_seq_send`/`modes_local_init` frames and the new table (frame, settle, policy, route-moved) so the reviewer can verify by eye.

**Acceptance for step 1:** `make -C ui/tests run` is green under ASan/UBSan; `grep -n 'OUT_SEQ\|out_seq_send' ui/modes.c` returns nothing; the Docker device build succeeds (`docs/DEV_WORKFLOW.md` section 1: `docker build -t diskos-ui-builder .` then `docker run --rm -u "$(id -u):$(id -g)" -v "$PWD:/src" diskos-ui-builder`); then the **user** deploys (`tools/diskos-deploy.sh`) and checks on the Disc: boot reaches Local playback (boot init), play from idle (preamble), switching Working Mode between Local / USB DAC / BT Receiving / USB Storage. SPDIF and USB Audio rows only exist in a `make EXTRA_CFLAGS=-DDISKOS_TEST_OUTPUTS` build; test those there.

### Later steps (one commit each, same acceptance pattern)

2. `source_send` (`main.c:727`) calls `outseq_source(mode)`; keep `if(rc != OUTSEQ_REFUSED) modes_output_reset();` in the caller. Add the table rows and tests.
3. `route_analog` (`main.c:591`) calls `outseq_analog()`; the caller keeps `g_route_mac` set on failure so a retry runs.
4. `ui_route_bt` (`main.c:549`) calls `outseq_bt_sink(codec_frame)`. **Before this step**, read `ui_bt_codec_frame` (`bt.c:340`) and confirm it can't fail on a validated 17-char MAC; build the frame **before** pausing and sending (the one intentional behaviour change, decision Q11), and say so in the commit message.
5. Play preambles and re-asserts: replace the bare `ipc_send_cmd("0657000C0008")` at `main.c:1619, 1658, 1808` with `outseq_assert_workmode()`, and the `modes_local_init` callers at `1415, 1574, 1637` with `outseq_local_boot()` / `outseq_local_preamble()`; delete the shim.
6. Guard test (final commit only): a small Python unittest in `ui/tests/` that fails if any of `0666000C`, `0642000C`, `0657000C`, `06c1000C`, `0818000C` appears in `ui/*.c` other than `outseq.c`. Keep it a plain scan, not a slice of `main.c`.

### Open checks to do along the way

- Whether any non-main thread reads `g_out_route` (the state reset now happens after the sequence, not between frames). At the time of writing, only `main.c` and `modes.c` call `modes_output_route()`, and the threads in those files are `coldplug_thread` (`main.c:2783`) and the codec probe/scan workers in `bt.c`; confirm none of them reach it.
- Whether to also add `-Wextra -Wformat=2` to `ui/Makefile` (separate commit, would surface unchecked-return warnings).
- After step 6: candidate 1 (Working Mode module) is next and absorbs candidate 3; then 4, then 6 (section 1 table). Update this doc's `last_verified` and add a result section when each step lands.

**Prompt to resume** (paste into a new session): "Continue the diskOS outseq refactor. Read `~/claude-research/diskos-ui-architecture-review-output-sequencer-design.md` section 7 and `GLOSSARY.md` in `/home/moo/diskos/diskos`, then do Step 1 only and stop for my device test."

## 8. Result: Step 1 landed (2026-10-27), waiting for the device test

Branch `refactor/outseq` (from `9b3a7c7`), commit `2c1feb0` (local, not pushed). New `ui/outseq.{c,h}`, `modes.c` rewired (`OUT_SEQ`, `OUT_WORKMODE`, `out_seq_send` deleted; `modes_local_init` is now a shim), `ui/Makefile` `APP_SRCS`, `ui/tests/outseq_test.c` + target.

Checks run on the Fedora box:

```bash
cd /home/moo/diskos/diskos/ui/tests
make -B outseq_test CFLAGS='-g -O1 -Wall -Wextra' && ./outseq_test      # outseq_test: 12 sequences ok
# mutation check: strip the 65 ms settle from a copy of outseq.c and rebuild the test against it -> Assertion `gap >= 0.065' failed
cd .. && gcc -fsyntax-only -std=gnu11 -D_GNU_SOURCE -DLV_CONF_INCLUDE_SIMPLE -I. -Ilvgl \
   -Ithird_party/freetype-2.13.3/include -Wall modes.c                   # also with -DDISKOS_TEST_OUTPUTS; clean
grep -n 'OUT_SEQ\|out_seq_send' modes.c                                 # nothing
```

**Not done, because the box can't:** (1) `make -C ui/tests run` fails to link on this machine even for the old `config_test`: `/usr/lib64/libasan.so.8.0.0` and `libubsan.so.1.0.0` are missing (the `libasan.so` is under `/usr/lib/gcc/x86_64-redhat-linux/15/` but `-static-libasan` also fails, no `libasan.a`), so the ASan/UBSan run in the acceptance list was skipped; the test builds and passes without sanitizers. (2) No `docker` here (only `podman`), so the device build was not run; `modes.c` and `outseq.c` do pass a host `-fsyntax-only` with the vendored LVGL.

Things that came up while doing it:

- The `_Static_assert` comparing the two anonymous enums triggers `-Wenum-compare`; cast both sides to `int`.
- The test's golden table is `{n, soft_from, moved_idx, settle_after}` per row; a first regex edit scrambled the columns and the test (correctly) failed with "1 frames sent, want 3". Rewrote the table by hand.
- `outseq_local_preamble` is `void`, so `modes_local_init(0)` now returns 0 instead of -1 on a failed send; both callers (`main.c:1574, 1637`) ignore it.

**Next:** the user deploys (`tools/diskos-deploy.sh`) and checks boot into Local playback, play from idle, and switching Working Mode between Local / USB DAC / BT Receiving / USB Storage (SPDIF and USB Audio only in a `-DDISKOS_TEST_OUTPUTS` build). Then Step 2 (`source_send` to `outseq_source`).

### Step 2 landed (2026-10-27): `source_send` -> `outseq_source`

Commit `e6687ce` on `refactor/outseq` (local), stacked on Step 1 **before** the user had device-tested Step 1 (the user said "continue"). `source_send` (`main.c:727`) is now `rc = outseq_source(mode); if(rc != OUTSEQ_REFUSED) modes_output_reset(); return rc < 0 ? -1 : 0;`. Four `SRC_*` step tables in `outseq.c` (all MUST, route-moved = the first `0666 6`). `outseq_test` is at 16 sequences, green (no sanitizers, see above); `main.c` and `modes.c` pass the host `-fsyntax-only`. Deviation: an invalid mode now sends nothing and does not reset the route. Device check: switch Working Mode Local / USB DAC / BT Receiving / USB Storage and back (the storage return path also goes through `source_send`). Next: Step 3, `route_analog` -> `outseq_analog()`.

### Step 3 landed (2026-10-27): `route_analog` -> `outseq_analog`

Local commit on `refactor/outseq` after `e6687ce`. `route_analog` (`main.c:592`) now does `if(outseq_analog() != OUTSEQ_OK) return -1;` in place of the two raw frames; pause/seek/resume and the `g_route_mac` cleanup stay in the caller. `ANALOG[]` = `0666 6` MUST, `0657 8` MUST, no route-moved step, so failures are always REFUSED. `outseq_test` at 17 sequences, green; `main.c` host `-fsyntax-only` clean. Device check: with a BT sink routed, switch back to the internal DAC (and the startup-recovery path at `main.c:1328`, `route_analog(1)`). Next: Step 4, `ui_route_bt` -> `outseq_bt_sink`, which first needs the `ui_bt_codec_frame` (`bt.c:340`) can't-fail check.

### Step 4 landed (2026-10-27): `ui_route_bt` -> `outseq_bt_sink`

Local commit on `refactor/outseq` after `8e2f672`. The can't-fail check was done first: `main.c:553-558` admits only 17-char uppercase hex with `:` at i%3==2 (a subset of `bt_mac_valid`, `bt.c:470`), and `bt_codec_frame_value` writes 29 chars into the 48-byte `f`, so `ui_bt_codec_frame` (`bt.c:340`) cannot fail there. The frame is now built after the `ui_player_settling()` check and before the pause (the one intentional behaviour change). `outseq.c` gained an `IGNORE` policy (failure doesn't affect the result, unlike `SOFT`) and `outseq_bt_sink(codec_frame)` with the seven frames from the golden table, the dynamic codec frame as the last MUST step. Dedicated test `check_bt_sink` (failure at each index: REFUSED at 0 and 4, OK at 1-3 and 5, MOVED at 6; NULL/empty frame sends nothing); the test log's frame buffer had to grow from 16 to 48 bytes. Host `-fsyntax-only` of `main.c` shows 4 `-Wmisleading-indentation` warnings that are also present on the untouched tree. Device check: route to a BT sink from Local (playing and paused), then back to analog, and the BT auto-route on connect. Next: Step 5, bare `0657 8` re-asserts and the `modes_local_init` callers, then delete the shim.

### Steps 5 and 6 landed (2026-10-27): the refactor is code-complete

Local commits on `refactor/outseq`: `00d257c` (Step 5), `29c5fc4` (Step 6). Step 5: the three bare `0657 8` re-asserts in `main.c` call `outseq_assert_workmode()` (one `IGNORE` step); boot init calls `outseq_local_boot(modes_output_route())`, the two play preambles `outseq_local_preamble(modes_output_route())`; `modes_local_init` (modes.c/.h) deleted. Step 6: `ui/tests/outseq_guard_test.py` (wired into `make -C ui/tests run`) fails if `0666000C`/`0642000C`/`0657000C`/`06c1000C`/`0818000C` appears in `ui/*.c|*.h` outside `outseq.c`; checked by appending a stray literal to `modes.c` (fails), then restoring it. After Step 5 `grep -nE '(0666|0642|0657|06c1|0818)000C' *.c *.h | grep -v '^outseq.c'` in `ui/` returns nothing.

Open checks, answered:

- **Does any non-main thread read `g_out_route`?** No. The only threads are `coldplug_thread` (`main.c:2652`, body only touches SD/launcher state), the BT codec probe and `scan_worker` (`bt.c`). `modes_output_route`/`modes_output_reset` are called only from `main.c` and `modes.c` main-thread paths (grep, 25 hits), and none of the `source_send`/`ui_route_bt`/`route_analog` callers is inside a thread body. So moving the state reset from between frames to after the sequence is not observable.
- **`-Wextra -Wformat=2` in `ui/Makefile`:** not done (separate commit, still open). `main.c` already has 4 `-Wmisleading-indentation` warnings under `-Wall`, unrelated to this work.

Final state: 6 code commits on `refactor/outseq` (`2c1feb0`, `e6687ce`, `8e2f672`, `48d2fb2`, `00d257c`, `29c5fc4`), **local, not pushed, not device-tested** (the user chose to continue without testing between steps). Not run on this machine: ASan/UBSan (runtime libs missing) and the Docker device build (no `docker`, only `podman`). Before merging: build with the Docker builder, deploy with `tools/diskos-deploy.sh`, and check boot into Local, play from idle, Working Mode Local / USB DAC / BT Receiving / USB Storage and back, BT route and back to analog, plus SPDIF/USB Audio in a `-DDISKOS_TEST_OUTPUTS` build. If something misbehaves, the per-step commits make `git bisect` straightforward; each commit message has the old/new frame table. Next in the plan: candidate 1 (one Working Mode module, absorbing candidate 3), then 4, then 6.

### Where the work lives now (2026-10-27, later the same day)

**The `outseq` commits are on the fork's `dev` branch, not on `refactor/outseq`.** The whole refactor had been done on the older `fix/usb-dac-workmode` line, which did not contain the Oct 22 `stock-plus-disco` fixes that were flashed to the Disc (see [[diskos-fork-consolidated-into-dev-branch]]). `dev` was built from `stock-plus-disco` and `feat/persistent-debug` (which holds all six `outseq` commits plus later work) was merged in, so the original SHAs (`2c1feb0` ... `29c5fc4`) are still in `dev`'s history. `refactor/outseq`, `fix/usb-dac-workmode`, `stock-plus-disco` and `disco-with-fixes` no longer exist on GitHub. Work from `dev` from now on; the "Prompt to resume" above should say `dev`, not `refactor/outseq`.

What changed in the module when it met `stock-plus-disco`:

- One more routing frame appeared: `dac_exit_begin` (USB DAC ordered exit) sends `0642 0` first. The guard test caught it; it is now `outseq_gadget_none()` (one MUST step, REFUSED on failure), commit `8aebeab`. `outseq_test` is at 18 sequences plus the Bluetooth sink.
- The other frames in `modes.c`/`main.c` were byte-identical on `stock-plus-disco`, so the golden table in section 7 still holds.
- Merge conflicts were list unions only (`ui/Makefile` APP_SRCS, `ui/tests/Makefile`, the includes in `main.c`).

Device status: the dev build (`fe2ab28e...`, with `-DDISKOS_TEST_OUTPUTS`) is hot-loaded; not flashed, so it is not yet verified through a reboot. Still open from this doc: `-Wextra -Wformat=2`, candidates 1, 4 and 6.

## References

- [12 Common C Errors (edm2.com)](https://www.edm2.com/index.php/12_Common_C_Errors)
- [Common C errors (coddy.tech)](https://coddy.tech/docs/c/common-errors)
- [Top 10 mistakes in learning C (slideshare)](https://www.slideshare.net/slideshow/top-10-mistakes-in-learning-c-programming/271380426)
- [CERT C STR31-C mapping (MathWorks Polyspace)](https://www.mathworks.com/help/bugfinder/ref/certcstr31c.html)
- [Cracking the Code of Undefined Behavior (Electronic Design)](https://electronicdesign.com/technologies/embedded/software/article/55279429/trustinsoft-cracking-the-code-of-undefined-behavior-in-c-c)
- [Undefined behavior in C (coddy.tech)](https://coddy.tech/docs/c/undefined-behavior)
- Method: the `mattpocock-skills` plugin's `improve-codebase-architecture`, `codebase-design` (deep modules, seams, design-it-twice), `grilling` and `domain-modeling` skills.
