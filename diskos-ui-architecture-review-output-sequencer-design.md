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

## 7. Next steps

1. Commit 1: create `ui/outseq.{c,h}`, move the `modes.c` `OUT_SEQ` table and `out_seq_send`, add `ui/tests/outseq_test.c` and the `Makefile` entries, and add `outseq.c` to `APP_SRCS`. User verifies on the Disc.
2. Then `source_send`, `route_analog`, `ui_route_bt` (check `ui_bt_codec_frame` can't fail on a validated MAC), play preambles, and the guard test.
3. Candidate 1 (Working Mode module) afterwards; it will absorb candidate 3.

## References

- [12 Common C Errors (edm2.com)](https://www.edm2.com/index.php/12_Common_C_Errors)
- [Common C errors (coddy.tech)](https://coddy.tech/docs/c/common-errors)
- [Top 10 mistakes in learning C (slideshare)](https://www.slideshare.net/slideshow/top-10-mistakes-in-learning-c-programming/271380426)
- [CERT C STR31-C mapping (MathWorks Polyspace)](https://www.mathworks.com/help/bugfinder/ref/certcstr31c.html)
- [Cracking the Code of Undefined Behavior (Electronic Design)](https://electronicdesign.com/technologies/embedded/software/article/55279429/trustinsoft-cracking-the-code-of-undefined-behavior-in-c-c)
- [Undefined behavior in C (coddy.tech)](https://coddy.tech/docs/c/undefined-behavior)
- Method: the `mattpocock-skills` plugin's `improve-codebase-architecture`, `codebase-design` (deep modules, seams, design-it-twice), `grilling` and `domain-modeling` skills.
