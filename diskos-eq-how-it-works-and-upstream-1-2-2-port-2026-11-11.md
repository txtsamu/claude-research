---
type: investigation
tags: [diskos, snowsky-disc, equalizer, peq, custom-eq, eqcustom, apps-page, upstream, b0hemia, sqlite]
created: 2026-11-11
last_verified: 2026-11-11
status: current
---

# diskOS Equalizer: how it works on the fork, what upstream v1.2.2 changed, and what was ported (plus an Equalizer tile on Apps)

Repo `/home/moo/diskos/diskos`, branch `dev` at `4692679` (agent commit `b1fd225` plus mine; base `8e8f5a6`). Not pushed, not flashed; hot-loaded on the Disc. Related: [[diskos-working-mode-auto-via-local-2026-11-11]], [[diskos-srcswitch-source-mode-switch-extraction]]. In the repo: `docs/RE_CATALOGUE.md` section 3, `comments.md` (`ui/eqcustom.c`, `ui/musicdb.c`), `CHANGELOG.md`.

Request: "check how the current EQ works, check the main repo for EQ updates, and if there is an update put it on the apps page of my fork." The user chose "both": port the upstream EQ changes and add an Apps tile (confirmed by a question; "apps page" was taken to mean the in-UI Apps screen, `ui/apps.c`).

## How the EQ works on the fork

- Settings > Playback > Equalizer: 21 presets (Off, 10 stock presets, User 1 to 10). `apply_eq` calls `ui_eq_select`, which calls `ui_apply_eq` (`ui/main.c`), sending `0689000C<preset hex>` to the Player; `eq_preset` and `eq_last` are saved in `diskos.conf`. The Quick Settings EQ tile toggles off and back to `eq_last`.
- The EQ itself is a software parametric biquad cascade inside `mq_player` (not a DAC feature): coefficient calculation at 0x448144, cascade at 0x447ed0 / 0x4483a4 (docs/RE_CATALOGUE.md section 3).
- Custom bands live in the Player's SQLite song database, table `PEQ` (`STYLE_NAME, MASTER_GAIN, PARAMS_JSON, STYLE_PRESET`); user slots are `STYLE_PRESET` 11 to 20. `ui/eqcustom.c` is a 10-band editor (32 Hz to 16 kHz, plus or minus 12 dB, plus master); `mdb_set_peq` writes, `0689` selects.
- On V2.57 (the Disc's firmware) the editor is view-only: the Player's PEQ loader rejects and repairs bands above half its internal rate. Presets work; editing does not. The Disc had `eq_preset=0` (off).

## What upstream (b0hemia/diskos v1.2.2) changed

`git fetch upstream` (no merge), merge base `4cd4a60`. `git diff 4cd4a60 upstream/main -- ui/eqcustom.c` is 76 lines; no new EQ feature. Its CHANGELOG lists: Equalizer (and Saver Style) open a choice list instead of cycling; Custom EQ leaves room for longer titles; a failed Custom EQ read keeps the previous curve and slot and refuses editing. V2.57 stays view-only. Its Equalizer row is `ST_CHOICE` in `ui/settings.c`.

## What was ported (agent for eqcustom.c, me for the rest)

- `ui/eqcustom.c`: `g_curve_known` starts at 0; `load_slot_read` reads `mdb_get_peq` then `mdb_peq_is_graphic` and, on any failure, returns without touching the curve, slot or label; `load_slot` wraps it and toasts `EQ read failed, try again`; `set_slot` and `eqcustom_refresh` only move the slot after a successful read.
- `mdb_ui_read_begin` / `mdb_ui_read_end` did not exist in the fork. The agent ported just those two functions from upstream `musicdb.c` (about 30 lines, one SQLite `SAVEPOINT` plus a probe select so both reads see the same snapshot) instead of upstream's 700-line musicdb refactor. Side effect: each EQ slot read now first runs `mdb_playlist_sync_registry()`, which does nothing when the stock playlist index table is absent.
- New host test `ui/tests/uiread_test.c` (temporary SQLite file: missing db, nested begin/end, exclusive lock held by another connection, missing `SONG` table, missing `PEQ` table). A mutation of the probe query made four checks fail. `eqcustom.c` itself has no LVGL host stubs, so it is not covered.
- Settings: Equalizer is `ST_CHOICE`; `ui/tests/settings_baseline.tsv` updated (`Equalizer ST_CYCLER` to `ST_CHOICE`). `settings_tree_test.py` failed with `Equalizer changed type ST_CYCLER -> ST_CHOICE` until then.
- Apps: `ui/apps.c` has an Equalizer tile (three vertical sliders drawn with `lv_draw_rect`, same pattern as the USB DAC icon) whose callback is `settings_open_key("eq_preset")`, which opens the preset list. It opens the preset list rather than Custom EQ because the editor is view-only on V2.57.
- Not ported on purpose: upstream's title-room change. It measures the title after `kit_pass` and drops the editor 8 px below it; that only fits upstream's centred two-line header (`ui/ui.c`, `screens.h`, `theme.c`), and on the fork's single-line header it moves the default theme's editor down 15 px. The agent had ported it and flagged this; I restored the fork's original block and corrected `CHANGELOG.md` and `comments.md`.

## Commands

```bash
git fetch upstream && git log upstream/main --oneline -8
git diff 4cd4a60 upstream/main --stat -- ui/eqcustom.c ui/settings.c
git show upstream/main:CHANGELOG.md | grep -n -i "custom eq"
cd ui/tests && CC=clang make run && CC=clang make run-py     # all pass
cd .. && podman run --rm --userns=keep-id -v "$PWD:/src:Z" localhost/diskos-ui-builder:latest sh -c 'make CROSS=$CROSS EXTRA_CFLAGS=-DDISKOS_TEST_OUTPUTS'
flock /tmp/diskos-disc.lock ~/diskos/diskos-hotload.sh ui/mq_ui
```

Process notes: the agent and I shared one worktree (`~/diskos/diskos-eqapps`) with disjoint files and it staged only its own files by name. The agent's build md5 was for its commit in a throwaway worktree; the tree I built also had my uncommitted files.

## Not verified

- Nothing was seen on the Disc. My `tinj` touch commands did not move the screen after the hot-load (the taps were logged, the screenshots stayed on Home), so the new Apps tile, the preset list and the "EQ read failed" toast were not looked at. The user asked for the merge anyway.
- No EQ preset was applied or listened to; the Disc stayed on Off.

## Time estimate

| Step | Time |
|---|---|
| Reading the fork's EQ code and docs, fetching and diffing upstream | about 5 min |
| Agent: port eqcustom.c, the two musicdb functions, the new test | about 7 min (measured: 410 s) |
| My Apps tile, settings change, baseline, docs, tests, build, hot-load (in parallel with the agent) | about 6 min |

## References

- Upstream repository, v1.2.2: https://github.com/b0hemia/diskos (CHANGELOG.md and `ui/eqcustom.c` at `upstream/main`)
