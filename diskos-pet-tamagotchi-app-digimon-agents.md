---
type: how-to
tags: [diskos, snowsky-disc, pet, tamagotchi, digimon, apps, lvgl, subagents, canvas, screenshots]
created: 2026-10-27
last_verified: 2026-10-27
status: current
---

# diskOS "Pet": a Tamagotchi-style app on the Apps page, with Digimon characters

Request: "add feature to play tamagotchi on apps page", then "use popular digimon character". Fork `dev`: contract `0489bb3`, rules `37c4c13`, screen merge + polish `3c3662b`. Built by two subagents in parallel (rules / screen) against a header written first, then reviewed, merged, built and looked at on the Disc. Companion docs: [[diskos-lastfm-removal-terminal-cursor-and-subagent-worktrees]] (the worktree-base trap and the subagent rule), [[diskos-screenshots-over-key-ssh-and-terminal-home-layout]] (how the screenshots were taken).

## Design

- `ui/tama.h` is the contract (written by hand before spawning anyone): `tama_t` state, `tama_advance(now)` (wall-clock simulation, so the pet lives while the app is closed or the Disc is off, with the catch-up capped at 12 h), actions (`tama_feed_meal/snack`, `tama_play(won)`, `tama_clean`, `tama_heal`, `tama_set_asleep`), `tama_mood`, `tama_rand`, atomic `tama_save`/strict `tama_load`. State file: `/usr/data/diskos_tama` (text `key=value`, 18 keys).
- `ui/tama.c` (rules, pure C) + `ui/tests/tama_test.c`: all tuning numbers are `#define`s at the top. Hatch 3 min; baby 60 min, child 180, teen 360, so about 9 h to adult. Hunger empties in ~6.7 h awake; a mess about every 90 awake minutes (max 4); sickness rare (more likely with messes, hunger 0 or weight > 80); death after 12 h at hunger 0 or 24 h sick untreated. Adult form from `care`: below 34 form 0, below 67 form 1, else form 2.
- `ui/tama_ui.c` (screen): sprites are ASCII-art bitmaps in the source, scaled x4 onto an `lv_canvas` (`lv_draw_buf` ARGB8888, rows written through the buffer's own stride) in the accent / text colour, so the theme pass cannot recolour them. Stats are 5-pip meters (Food, Fun, Rest; a meter at 1 pip turns the warning colour). Actions: Feed (meal / snack), Play (best-of-3 "which hand?" using `tama_rand`), Clean, Sleep/Wake, Heal only while sick; egg: no actions; gone: "New egg". One 600 ms `lv_timer` exists only while the screen is visible (`tama_visible(1/0)` called from `transition()` in `screenmgr.c`, which also covers the screensaver); it flips the idle frame and every 30 s advances and refreshes; saves after every action, at most once a minute otherwise, and on leaving. `SCR_TAMA` gets figure slot 35 (33 stays retired). Apps tile "Pet" with the heart glyph (f004, which `font_icons_28` has).
- Characters (Agumon line, original hand-drawn pixel sprites, not ripped art): Digi-Egg, Botamon (baby), Koromon (child), Agumon (teen), adult by care: Numemon (poor) / Tyrannomon (average) / Greymon (great), a gravestone when gone. Mood overlays on every character: heart, drumstick, tear, z, sick plus and sweat drop, big Z, mess. The characters and names are Bandai trademarks: fine on a personal Disc, but keep it out of any upstream PR.

## How the parallel work went

The brief for each agent said to `git reset --hard dev` first (see the worktree-base trap doc: it did not recur). The rules agent reported its deviations honestly (the 10 h sleep cap only counts inside one long `tama_advance`, because there is no field for the sleep start; every action refuses in the order DEAD, ASLEEP, specific). The screen agent could not render anything and used a throwaway stub `tama.c` for its build (not committed); its last edit was only syntax-checked, so the merged tree was rebuilt here. Review checklist used: `git merge-base 0489bb3 <branch>` equals the dev tip; `git diff --stat` only touches the files owned; rerun the host tests; build with the pinned image (colour guard passes); look at it on the Disc.

## Looking at it without tapping through menus

Added a deep link `mq_ui pet` (next to `datetime` in `main.c`) and wrote test pets straight into the state file, then relaunched on that screen keeping the audio route:

```bash
ssh disc 'now=$(date +%s); printf "version=1\nstage=3\nform=0\nhunger=80\nhappy=80\nenergy=80\nweight=30\npoop=1\nsick=1\nasleep=0\ncare=50\nage_min=500\nstage_min=10\nstarve_min=0\nsick_min=0\nrng=12345\nborn=$((now-30000))\nlast=$now\n" > /usr/data/diskos_tama; killall -9 mq_ui; DISKOS_THEME_RELOAD=1 DISKOS_RELOAD_ROUTE=2 DISKOS_RELOAD_SRC=0 setsid /usr/data/mq_ui pet </dev/null >/usr/data/diskos_boot.log 2>&1 &'
# then a framebuffer screenshot (see the screenshot doc); stage 0..5, form 0..2 for adults
```

Gotcha that cost one batch: building that `printf` inside a double-quoted `ssh "..."` string with the `$((now-30000))` inside single quotes leaves the arithmetic literal, the file is invalid, `tama_load` rejects it and the screen silently starts a new egg (every shot showed the Digi-Egg). Use single quotes around the whole remote command and put `$((...))` in the printf's double-quoted format, as above. Remove `/usr/data/diskos_tama` afterwards (a fresh egg is then created on first open).

## Checked / not checked

Checked on the Disc with screenshots: Terminal, Default, Hi-Fi, Stone and Zine themes (five buttons fit in all, sprite stays one clean colour); egg, Botamon, Koromon, Agumon, Numemon, Tyrannomon, Greymon, gravestone + New egg; hungry (drumstick, red meter), mess, sick (+ Heal button), asleep (+ Wake button). Host: `tama_test`, `timekeep_test`, `outseq_test`, `config_test` pass; device build passes the colour guard. Fixed after looking: the Food/Fun/Rest groups were hard against the next label (now 100 px apart on a 300 px canvas). Not checked: actually tapping the buttons (feeding, the mini-game, evolving: a real hatch takes 3 min), the "It hatched!" and "Evolved into X!" toasts, that no timer survives leaving the screen, Bauhaus and Blueprint themes, and a real multi-hour life of the pet.
