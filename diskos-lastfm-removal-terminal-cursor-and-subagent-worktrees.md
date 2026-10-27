---
type: how-to
tags: [diskos, snowsky-disc, lastfm, terminal-theme, cursor, lvgl, subagents, worktree, git]
created: 2026-10-27
last_verified: 2026-10-27
status: current
---

# diskOS: Terminal-theme Home cursor blink, Last.fm removal, and the subagent-worktree base trap

Fork `dev`: cursor fix `01912fa`, Last.fm removal `186b39e` + `0ab5be1` + `866e9b2`, test fix `9f09a6c`. Both tasks were run by two parallel subagents in separate worktrees (a standing rule now in `~/.claude/CLAUDE.md`). Companion docs: [[diskos-fork-consolidated-into-dev-branch]], [[diskos-persistent-clock-timekeep]].

## Terminal theme: the Home clock cursor did not blink

The Apps page title cursor is not an `lv_anim`: it is a small accent rectangle tagged `lv_obj_set_user_data(cur, &term_cursor_tag)` (`ui/theme_kits.c`, `term_title_cursor`). `kit_cursor_sync()` runs on every screen change, wake and backlight change (`screenmgr.c` `screen_show`, `main.c`), finds the tagged child of the current screen root with `term_cursor_for()`, and drives it with one shared 550 ms `lv_timer` (`term_cursor_tick`, toggles HIDDEN; paused when the screen or backlight is off; every entry or wake starts with the cursor on). The Home clock cursor is a different object (`g_term_cur`, built in `term_home()`) that never got the tag, so `term_cursor_for` found nothing on Home and the timer stayed paused. Fix: one line in `term_home`, `lv_obj_set_user_data(cur, (void *)&term_cursor_tag);`. Not checked on a screen: Terminal theme, Home, the block after the time should toggle about every 0.55 s.

## Last.fm removed

Deleted `ui/lastfm.c`, `ui/lastfm.h`, `ui/lastfm_ui.c`, `docs/tour/lastfm.png`; removed the Apps tile, the `SCR_LASTFM` screen (enum, root creation, `s_figure` slot 33 now commented "never reuse" so `SCR_DEBUG` stays 34), the `lastfm_init`/`lastfm_tick` timers in `main.c`, the two fixed theme roles `THEME_CLR_FIXED_LASTFM`/`_ON_LASTFM` (theme_presets.inc regenerated with `tools/gen_theme_presets.py`, `--check` passes; saved themes are keyed by role name and only editable roles are stored, so nothing breaks), Last.fm wording in Settings/System texts and in `README.md`, `docs/TOUR.md`, `docs/PRIVACY.md` (plus a short "no longer part of diskOS" note about leftover `lastfm_*` keys and `/usr/data/lastfm.queue`), `site/index.html`. Kept on purpose: `md5.c` (used by netart/settings), `cfg_begin`/`cfg_commit` (generic, tested), `CHANGELOG.md` and `docs/RELEASE_NOTES_1.2.1.md` (history), the unused glyph in the generated `font_icons_28.c`, and `payload/mq_ui` (a tracked prebuilt binary that a release rebuild refreshes). Check:

```bash
git grep -niE 'lastfm|last\.fm|scrobbl' -- . ':!ui/lvgl' ':!CHANGELOG.md' ':!docs/RELEASE_NOTES_1.2.1.md'   # only the PRIVACY note and the slot comment
strings ui/mq_ui | grep -ci 'last\.fm\|scrobbl'                                                         # 0
```

Leftover config keys on a device are harmless; no migration code was added.

## Found on the way: config_test was stale

`config_test` failed 2 of 7 (`overflow_rejected`, `txn_rollback`) because the settings store had been raised from 256 to 512 entries in `eac49b4` (Oct 22, Disco port) while the test still filled 256. Test updated to 512/511, 7/7 pass. Host tests on `dev` now: config 7/7, playstate, timekeep, outseq (18 + BT sink), outseq guard, ipc_guard. Sanitizer runtime libs are still missing on this box (the Makefile's `-fsanitize` flags need `CFLAGS=` overridden).

## The subagent-worktree base trap

`Agent(isolation: "worktree")` created the worktrees from `main` (`4cd4a60`, upstream v1.2.1), not from the branch the session was on (`dev`). The cursor agent therefore built and verified against Terminal-theme code from before the round-glass changes (its report even matched an old layout); its one-line commit still cherry-picked cleanly (`git cherry-pick -x 4488136`). The Last.fm agent was told to `git rebase --onto dev 4cd4a60` and redo its grep, because `dev` has files `main` lacks (`phonehome.h`, usbhid, chargemode, command_spawn, outseq, timekeep) and more Last.fm references. Both builds happened to be reproducible (md5 `e545e397...` from the agent and from `dev`). Detect it with `git merge-base dev <agent commit>` (should print the `dev` tip) and `git log --oneline -1` inside the worktree. The rule is written into `~/.claude/CLAUDE.md`: tell the agent to `git reset --hard <branch>` first. A `git diff` in this environment prints nothing to the terminal for some files; redirect it to a file and read that.

## Now Playing Vinyl art turned square (fix by a third subagent, `e152eec`)

Report: "some theme shows the artwork on the player screen as a square instead of a circle". The art's shape is the radius of the 148 px `cover` box (`clip_corner`, `cover_img` inside; `ui/ui.c` `build_nowplaying`). `ui_set_np_style()` sets it once: Vinyl = `COVER_D/2` (circle), Cover = 14, Bauhaus = 0. But `set_cover_fallback()` runs the theme kit's `np_cover_state` hook on every art change, after that, and three kits set their own radius there: Default 16 (`theme_kits.c:31`), Hi-Fi 2 (`:513`), Null 0 (`:2899`). So with Now Playing = Vinyl the disc was a circle until the first art loaded, then became a (rounded) square until the style was toggled again. Fix: after the kit hook, `if(g_np_vinyl && strcmp(theme_kit()->id, "bauhaus")) lv_obj_set_style_radius(cover, COVER_D/2, LV_PART_MAIN);` (4 lines, once per art change, no per-frame work). Check on the Disc: Settings > Display > Now Playing = Vinyl, Default / Hi-Fi / Null theme, play a track with art: the disc must stay round and spinning after the cover loads and across track changes.

Left alone on purpose (the agent's findings): Cover style is a rounded square by design in every kit but Terminal (hidden) and Bauhaus (flat half-screen slab); Zine draws square "paper" rectangles and Blueprint square crop marks around a round disc even in Vinyl (a possible follow-up if those read as "square"); the screensaver Vinyl style is a deliberate full-bleed square cover cropped by the round glass; Home's art thumb is already a circle. This time the agent was told to `git reset --hard dev` first, and its `git merge-base HEAD dev` matched the dev tip, so the worktree-base trap above did not recur.

Deploying while on the USB Audio route: a plain hot-load restarts the UI without the route (the saved `usb_audio_on=1` then re-runs the USB Audio switch 15 s later). Use a copy of the deploy script that launches `env DISKOS_THEME_RELOAD=1 DISKOS_RELOAD_ROUTE=2 DISKOS_RELOAD_SRC=0 setsid /usr/data/mq_ui`, which is what a theme change does; the log then shows `theme reload: kept route 2` and the player log has no new `set out device`.

## Deploy

`dev` `9f09a6c` (later `e152eec` with the Vinyl fix, md5 `9a610ef3...`), built with `-DDISKOS_TEST_OUTPUTS`, md5 `e545e39711f0f6662593b90039f5284d`, hot-loaded over key SSH; boot log shows `clock: ... ok (saved ...)`. Not flashed, so a reboot returns the flashed `stock-plus-disco` UI.
