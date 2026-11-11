---
type: how-to
tags: [diskos, snowsky-disc, lvgl, theme-kit, kit_keep, settings, max-volume, quick-settings, battery, screenshot]
created: 2026-11-11
last_verified: 2026-11-11
status: current
---

# diskOS: round -10/+10 buttons on the Max Volume page, and a battery level on Quick Settings (and why the theme kit ate my styles)

Repo `/home/moo/diskos/diskos`, branch `dev` (commit `a095f55`, merged in `c964e99`). Not pushed, not flashed. Related: [[diskos-hotload-gotchas-test-outputs-usb-storage-reboot]].

## Requests (in order, from the user)

1. Settings > Audio > Max Volume: add buttons for -10 and +10 on each tap, not only the slider.
2. Make it look better, research on the internet; then "left/right arrows", then "make it circle instead of square", "fix slider knob too", then "the text underneath still cut".
3. Quick Settings: add a battery indicator.

Not solved: on USB Audio the Max Volume slider read 120 and would not move. By the time I looked it showed 30 (the user had moved it). `diskos.conf` said `max_vol=100`. `ui_set_maxvol` returns early while `dacvol_owns_volume()` (ui/main.c:301), so the slider never reaches the Player on USB Audio; the cap there is applied by `dacvol` through `max_vol` (`dacvol_env_user_cap`). Not chased further.

## Research

Searched for stepper-control guidance: NN/g says horizontal steppers (button each side of the value) usually beat vertical ones, which get crowded; 44 px is the usual minimum touch target, with invisible padding if the visible shape is smaller. So: left/right round buttons, 64 px plus 8 px extra click area. Sources under References.

## Implementation (ui/settings.c, ui/quicksettings.c, ui/screens.h, ui/home.c)

- `detail_maxvol_step_cb`: `v = get_val + dir*10`, clamped to the row's min/max, then `set_val` (writes `max_vol` and calls `apply_maxvol`) and `setting_detail_refresh()`.
- Buttons are `lv_button_create` with `remove_style_all`, 64x64, `LV_RADIUS_CIRCLE`, accent border, plus an `lv_line` chevron (two segments, `lv_point_precise_t`, rounded caps) so it does not depend on any font glyph.
- Slider moved to y +52, value label above it, description left at the standard `BOTTOM_MID, -40`.
- Quick Settings: `quicksettings_set_battery(batt, charging)` stores the values and paints a label (`LV_SYMBOL_BATTERY_*` plus percentage, `LV_SYMBOL_CHARGE` while charging); `home_set_status` calls it first, so the existing 5 s status poll feeds it. The label sits at the bottom (`LV_ALIGN_BOTTOM_MID, 0, -26`).

## Gotchas found with screenshots

Method: `flock /tmp/diskos-disc.lock ~/diskos/diskos-hotload.sh <mq_ui>`, then `~/diskos/snowsky-shot.sh out.png`, then read the PNG. A hot-load restarts the UI and returns to the home screen, so the user has to reopen the page each time; for Quick Settings I opened it myself: `ssh disc '/usr/data/tinj swipe 180 4 180 260'`.

- **The theme kit overrides your own widget styles.** The active theme (here the green terminal "hifi" kit) restyles every `lv_button`, slider and label after creation (`ui/theme_kits.c`, `kit_pass`/`kit_restyle`): buttons got radius 6 and no round shape, the knob radius 3, fonts remapped. My styles only stuck after `kit_keep(obj)` on the button, the slider and the value label (`#include "theme_kit.h"`). Without it the circle never drew.
- **`TF(UI_40)` rendered garbage digits** in this theme (a squiggle instead of "100"); `TF(UI_28)` renders correctly.
- **Slider knob size** comes from `pad_all` on `LV_PART_KNOB` (7 gives a 26 px circle on a 12 px track).
- **The kit draws a title** ("$ quick") at the top of Quick Settings, so my first battery label at the top overlapped it; it moved to the bottom, below the tile rows (layout ends around y 296).
- The description text near the bottom edge got cut on the Disc's screen when I placed it at `-10`; the standard `-40` is clear.

## Time estimate

Measured per iteration: edit, cross-build about 1 min, hot-load about 10 s, screenshot about 5 s. This work took about eight iterations (about 20 minutes with the user's requests arriving in between). A rerun with the final design known is about 5 minutes.

## References

- [Definition: The Input Stepper (NN/g)](https://nngroup.com/articles/input-steppers)
- [Stepper input UI design: the +/- quantity control done right (SetProduct)](https://www.setproduct.com/blog/stepper-ui-design)
- [Numeric stepper (eBay Playbook)](https://playbook.ebay.com/design-system/components/numeric-stepper)
