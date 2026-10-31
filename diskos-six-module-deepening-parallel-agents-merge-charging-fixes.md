---
type: how-to
tags: [diskos, snowsky-disc, architecture, refactor, subagents, worktrees, merge, usb-audio, charging, hot-load, flash, outroute, playreq, sdio, sysconfig, booksess, coverart]
created: 2026-10-31
last_verified: 2026-10-31
status: current
---

# diskOS: architecture review, six parallel module deepenings, charging fixes, merge, hot-load and flash

Fork `txtsamu/diskos`, branch `dev`, from `4f28beb`. Companion docs: [[diskos-ui-architecture-review-output-sequencer-design]], [[diskos-session-and-play-admission-modules-parallel-agents]], [[diskos-hotload-gotchas-test-outputs-usb-storage-reboot]], [[diskos-disc-hotload-watchdog-snowsky-logo-hang]], [[fiio-snowsky-disc-diskos-flash-fedora]], [[diskos-usb-audio-headset-click-gestures-and-flash]], [[diskos-usb-dac-exit-deadlock-roles-and-volume-fix]].

**Status:** merged into `dev`, host tests and a clean cross-build pass, hot-loaded to the Disc (md5 `a60d9077…`, up on the first attempt). Flash of `344334e` started 12:17:55 (result at the end of this doc). **Nothing was exercised by hand on the Disc, and the charging fixes (merged afterwards at `dea3ce7`) are not in the flashed or hot-loaded build.**

## Time estimate

Measured this session unless marked (est.). Wall-clock, 2026-10-31, WIB.

| Step | Time |
|---|---|
| Two exploration agents (read-only, in parallel) | 6.2 and 7.6 min |
| Six refactor agents in separate worktrees (parallel) | 10.9 to 16 min each (cover art and the charging fix were cut off by the 5-hour usage limit and resumed; the resume took 3 to 4 min) |
| Merging six branches into `dev`, conflict by hand | about 25 min (est.; includes reading hunks) |
| Host tests (`make run` + `run-py`) on the merged tree | about 1 min (est.) |
| Clean cross-build in podman | 13.0 s (`real 0m12.994s`); an earlier "2 s build" was stale objects |
| Hot-load | 8.2 s |
| Image build only (`echo n \|`) | about 1 s |
| Flash | about 20 min (fixed 18 min writer wait, see [[fiio-snowsky-disc-diskos-flash-fedora]]) |

## 1. Find candidates (the `improve-codebase-architecture` skill)

Hot spots first: `git log -120 --name-only` showed `ui/main.c` in 58 of 120 commits, then `modes.c`, `session.c`, `outseq.c`, `srcswitch.c`. Two read-only Explore agents walked the cluster (modes/route/session/admit/srcswitch) and the rest of `ui/`. I spot-checked their claims before building the report (`admit_switch` failure path, the three play latches, the duplicated `sd_write_begin` prototype, 32 `theme_kit()->id` comparisons). The HTML report with before/after diagrams was written to the scratchpad (12 candidates, 6 Strong). One correction on the way: `grep` in this shell is ripgrep, so `grep -c 'a|b'` and `strcmp(` patterns misbehave; use `/usr/bin/grep` or `command grep -F`.

## 2. Six parallel refactors, one worktree each

Briefing rules that made the merge tractable: every agent starts with `git reset --hard dev` and confirms `git log --oneline -1` (a worktree agent starts from `main`, not the branch you are on); new code in new files; surgical edits to shared files; an ownership list and a do-not-touch list per agent (the other five clusters); no edits to `comments.md`/`GLOSSARY.md` (proposed text goes in the report); behaviour-preserving, with inconsistencies kept and reported rather than fixed. Plain `git` is rewritten by the rtk hook in agent sandboxes and gets refused: use `/usr/bin/git`.

| # | Branch | New module | What it absorbed |
|---|---|---|---|
| 1 | `worktree-agent-a05f438b8a0ed243e` | `outroute.c/h` | route state, BT sink MAC, route file, saved USB Audio preference, pause/switch/resume/recovery for all route kinds; deleted `modes.h`, `admit_switch`, `out_switch` |
| 2 | `…ab2bc5edcd0b7a753` | `playreq.c/h` | `g_play_pending` + 150-line failure state machine, the admit and session play latches |
| 3 | `…a6ad7ffd616a98626` | `sdio.c/h` (kept the name) | reader+writer admission, hold/revoke, launch verdict, storage phase machine, coldplug mutex |
| 4 | `…af77ce1bdf7d04d3c` | `sysconfig.c/h` | all `sysconfig.db` access (6 files, 2 mechanisms) |
| 5 | `…a9337c57faa4913d3` | `booksess.c/h` | audiobook session, sleep timer, EOC (moved from `main.c`) |
| 6 | `…a1a7b39dea62baad8` | `coverart.c/h`, `coverart_accent.c`, `coverart_prod.c` | cover/accent pipeline from `ui.c` and `saver.c`; accent math proven bit-identical on 28 golden covers |

Each agent ran host tests with `CC=clang` and most ran a podman cross-build. The new tests: `outroute_test` (33 scenarios), `playreq_test` (24), `sdio_test` (18), `sysconfig_test`, `booksess_test` (130+ checks), `coverart_test` and `coverart_pipeline_test`.

## 3. Merge into `dev` (order 5, 4, 2, 6, 3, 1)

```bash
cd ~/diskos/diskos && git switch dev
git merge --no-ff -m "Merge <branch>" <branch>      # one at a time; use /usr/bin/git inside rtk sessions
```
Conflicts were almost entirely textual. Recurring ones and their resolution:

- `ui/Makefile`: all branches edit the single long `APP_SRCS :=` line. Resolve by taking ours and appending the other side's new `$(APP)/<file>.c` tokens (script: take the token set difference). Candidate 6 used a second `APP_SRCS +=` line.
- `ui/tests/Makefile`: union of `run:` prerequisites, `clean:` and per-test rules. **Every test that links `session.c` now also needs `../outroute.c ../playreq.c ../playstate.c`**, and `storage_test.py` needs `outroute.c playreq.c playstate.c` on its link line (it `#include`s `sdio.c` and `srcswitch.c` itself).
- `main.c`: the two env tables (`struct sd_env` from #3 and `struct outroute_env` from #1) both sit in one initializer position; the shared closing `};` has to be duplicated. `admit_env.play_pending` became `play_recent` (#2). `session_clear_bt_mac()` + `route_state_remove()` became `outroute_bt_forget()` (#1).
- `srcswitch.c`: #1 deleted the route block and #3 deleted the SD block, so the conflict resolves to neither, leaving `int srcswitch_send_source(int mode){`.
- Leftover after the merge: `static int g_playing = 0;` in `main.c` (unused; removed).

Verification on the merged tree:

```bash
cd ~/diskos/diskos/ui/tests && CC=clang make run && CC=clang make run-py      # both rc=0
cd ~/diskos/diskos/ui && for f in $(ls *.c | grep -v 'font_\|sqlite3\|i18n_tables\|theme_kits'); do clang -fsyntax-only -std=gnu11 -D_GNU_SOURCE -DLV_CONF_INCLUDE_SIMPLE -DDISKOS_TEST_OUTPUTS -I. -Ilvgl $f; done
# clean cross-build on a COPY of ui/ (rtk's find ignores -delete: use /usr/bin/find)
cp -r ui ~/sessions/<dir>/xbuild/ui && cd ~/sessions/<dir>/xbuild/ui
/usr/bin/find . -name '*.o' -delete; /usr/bin/find . -name '*.d' -delete; rm -f mq_ui
podman run --rm -v "$PWD":/work:Z -w /work localhost/diskos-ui-builder \
  make -j8 CROSS=/opt/mipsel-n2008-musl-cross/bin/mipsel-linux-musl- EXTRA_CFLAGS=-DDISKOS_TEST_OUTPUTS
```
Result: `mq_ui` 4,302,596 bytes, sha256 `4dc2718d…`, md5 `a60d9077…`, 28 warnings (all of the old misleading-indentation / format-truncation kind). **Gotcha:** the first "clean" build took 2 s because the copied tree carried stale `.o` files; `find -delete` through rtk silently did nothing.

## 4. The charging problem ("won't charge after USB Audio to Local")

A read-only agent mapped the power state (details and ranked hypotheses in the agent report; sources: [[diskos-usb-dac-exit-deadlock-roles-and-volume-fix]], [[diskos-usb-audio-reverse-engineering-mq-player]], `~/diskos/re/usbhost_decomp.txt`, kernel `sgm41513_00.c`). The UI itself never writes charge or USB-role state; the Player does it on frame `0642` (0 none, 1 storage, 2 USB DAC, 5 USB host). Entering USB Audio: role to host, 5 V OTG boost on, charging off. Leaving (`0642 0`): boost off, charger IC charge-off (REG01 0x06), role back to device after a 1 s sleep; re-enabling is left to the Player's polling threads. Three fixes, one commit each (re-ported onto the merged tree after #1 moved the code):

- **A `703e481` (confirmed cause):** the 20 s no-DAC timeout fallback (and Player restart while waiting, failed and uncertain recovery) never cleared the saved `usb_audio_on`, so the next boot replayed USB Audio 15 s after start with a charger attached; the Disc then sourced 5 V for about 35 s with no DAC. Now cleared on every fall back to the internal DAC, and `bootusb_tick` skips the restore when `vbus_external_input()` (SGM41513 REG08 VBUS_STAT 1 to 6 via `/dev/i2c-2` addr 0x1a) says external power, failing closed when unreadable. New shared `ui/vbus.c`/`vbus.h` also serves `chargemode.c`.
- **B `cd59347` (real divergence, effect on charging a hypothesis):** Working Mode "Local" from the USB route sent the unsettled `SRC_LOCAL` burst; now `outroute_pick(OUT_INTERNAL, OUTROUTE_MODE)` like every other exit (pause, quiet wait, `0666 6`, 65 ms, `0642 0`, `0657 8`, resume).
- **C `fa442e6` (UNPROVEN guess):** 2 s after a successful exit from OUT_USB, re-send the Charging Limit frame `0808`. Possibly a no-op. Revert the commit to drop it.

Read-only checks to run on the Disc (`ssh disc`, port 2222; nothing was run this session):
```bash
ssh disc 'for r in 00 01 02 08; do echo -n "REG$r="; i2cget -f -y 2 0x1a 0x$r; done; cat /sys/class/usb_role/*/role /sys/class/udc/*/state'
ssh disc 'for d in /sys/class/power_supply/*; do echo $d; cat $d/status $d/current_now $d/capacity $d/online 2>/dev/null; done'
ssh disc 'dmesg | grep -i -E "sgm41513|aw35615|otg|vbus" | tail -20'
```
REG01: 0x16 charging, 0x06 charge off, 0x26 boost on; REG08 bits 7:5 = VBUS_STAT (0xe0 = OTG). Run in four states: Local with the charger in, in USB Audio, just after leaving with the charger replugged, just after leaving with it already plugged.

## 5. Hot-load and flash (recipes used)

Hot-load (watchdog-safe, per [[diskos-disc-hotload-watchdog-snowsky-logo-hang]]):
```bash
bash ~/diskos/diskos-hotload.sh ~/sessions/<dir>/xbuild/ui/mq_ui     # ">> staged <md5>", "ok=1 attempts=1"
ssh disc 'md5sum /usr/data/mq_ui; tail -15 /usr/data/diskos_boot.log; tail -3 /usr/data/fiio/log/process_failed.txt'
```
Checked: md5 equal to the local build, `mq_player` pid unchanged, log reaches "diskos reached main loop", no new `process_failed.txt` line.

Flash (Disc already in mask-ROM, `lsusb` showed `a108:eaef`):
```bash
cd ~/diskos/diskos-installer && ./diskos-installer doctor              # all green
echo n | ./diskos-installer install --firmware ~/Downloads/SNOWSKY_DISC_update_20260909_v257.zip --variant public --ui <mq_ui> --no-ota
unsquashfs -cat ~/.local/share/diskos-installer/build/out.squashfs etc/diskos_manifest | head -1     # SHA256= must equal sha256sum <mq_ui>
systemd-inhibit --what=sleep:idle ./diskos-installer install --firmware ... --variant public --ui <mq_ui> --no-ota -y > flash.log 2>&1
```
Image: `diskos_public.bin` 100,663,296 bytes, md5 `e7cb9d85…`. After `flash verified OK` the Disc stays in USB boot until power is cut.

## Decisions waiting for the user (behaviour kept, not changed)

1. BT/analog route changes (`outroute_to_bt/analog`, "leave paused") never resume or recover after a failed step; the output picker (`outroute_pick`, "recover") restores the internal DAC. After a failed BT switch the route is reset to Internal while the Player may still be on the BT path.
2. SD **writers** are admitted before any launch verdict and after a fault/hold until the next tick; readers are stricter.
3. `sqlite3` CLI reads in `main.c`/`wifi.c` can create an empty `sysconfig.db` if the file is missing (stock may then not build its schema). One-line fix: `-readonly` or an `[ -f ]` guard in `sysconfig_get_many_via`.
4. `ui_play_playlist`/`ui_play_plan`/`ui_play_book` call `admit_play_start(RESERVED_SLOT)` and then the list start, which on V2.40 (local route, not playing, no recent play) sends `0657` twice with a `0666` between. Unverified on a device.
5. Latent items in the book session (adopted resume skips the metadata wait, unthrottled sleep-pause retries, shutdown ignores the seek guard) and cover art (prewarm ring capacity 47, no accent for the album-wall queue path).
6. `theme_validate_and_save`, `sys_fetch_latest` and the `sys_ver_*` duplicates of `ota_ver_*` have no callers (deletion-test hits, not removed).

## References

- Repo docs used: `agents/AGENTS.md`, `GLOSSARY.md`, `comments.md` (new sections for `outroute`, `playreq`, `booksess`, `sysconfig`, `sdio`, `coverart`, `vbus` and their tests), `docs/DEV_WORKFLOW.md`.
- [[diskos-ui-architecture-review-output-sequencer-design]], [[diskos-session-and-play-admission-modules-parallel-agents]] (the earlier rounds of the same refactor).
