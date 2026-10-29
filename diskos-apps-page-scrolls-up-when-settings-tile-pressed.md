---
type: troubleshooting
tags: [diskos, snowsky-disc, lvgl, apps, scroll-on-focus, touch, input-injection, evdev, hot-load]
created: 2026-10-29
last_verified: 2026-10-29
status: current
---

# diskOS: the Apps page jumps up by itself when the Settings tile is touched

## Symptom
On the Apps page (Terminal theme, preset 3; not theme specific) touching the **Settings** tile made the whole page scroll up before Settings opened.
Pet and USB DAC tiles did not do it.

## Reproduce without a finger (reusable)
The Disc's touch panel is `cst816t` on `/dev/input/event1`, multitouch protocol B (ABS_MT_SLOT 47, TRACKING_ID 57, POSITION_X 53, POSITION_Y 54, BTN_TOUCH 330).
Writing events to that node injects a touch. The panel is mounted rotated 180 degrees, so RAW coordinates are `(x, 360 - y)` of the screen (x untouched in practice for centred tiles).
No `sendevent` on the Disc, so a small static mipsel tool was built with the toolchain already inside the builder image:

```
# tap.c: press at X1 Y1, optional drag to X2 Y2, total MS, one 16-byte struct input_event {u32 sec; u32 usec; u16 type, code; s32 value;} per write
podman run --rm --userns=keep-id -v "$PWD:/w:Z" --entrypoint /opt/mipsel-n2008-musl-cross/bin/mipsel-linux-musl-gcc \
  localhost/diskos-ui-builder -static -Os -o /w/tap /w/tap.c
ssh disc 'cat > /tmp/tap && chmod +x /tmp/tap' < tap          # scp does not work: no sftp-server on the Disc
ssh disc '/tmp/tap 180 180 120'                                # tap: wakes the screen
ssh disc '/tmp/tap 60 180 300 180 200'                         # raw x rising = swipe left on screen: Home -> Apps
( ssh disc '/tmp/tap 180 114 3000' & ); sleep 1.2; ~/diskos/snowsky-shot.sh press.png   # hold the Settings tile (screen y 246 -> raw 114) and screenshot mid-press
```
Press, wait, screenshot: the list was 24 px higher while the finger was down (heart icon y 118 -> 94), and Settings opened on release.
Source file: the 25 lines of `tap.c` are trivial to rewrite from the comment above; the event order per press is SLOT 0, TRACKING_ID n, X, Y, BTN_TOUCH 1, SYN; release is SLOT 0, TRACKING_ID -1, BTN_TOUCH 0, SYN.

## Root cause
- `lv_button_create` sets `LV_OBJ_FLAG_SCROLL_ON_FOCUS` (`ui/lvgl/src/widgets/button/lv_button.c:67`).
- `indev_click_focus` (`lv_indev.c`) sends `LV_EVENT_FOCUSED` to the pressed object when it differs from the last pressed one, **even with no group** (the "object not in group" branch); the object event handler (`lv_obj.c:800`) then calls `lv_obj_scroll_to_view_recursive`.
- "In view" is measured against the parent's content area, which excludes padding. `apps_create` gives the list `pad_bottom = UI_LIST_PAD_BOTTOM (44)` so the last row can scroll clear of the bezel. With three tiles the content is 2 x 118 + 10 = 246 px + 44 pad = 290 against a 266 px viewport, so there is exactly 24 px of scroll. The Settings tile (last row, bottom at screen y 320) sits below the content area's bottom (340 - 44 = 296), so LVGL scrolled by 24 px to "show" it.
- Pet and USB DAC (first row) are inside the content area, so nothing moved.

Ruled out on the way: a drag/throw (the injected press never moved); `scroll_limit` noise; the transform-scale press style (`lv_obj_get_scroll_bottom` uses untransformed coords); the rim-scroll gesture in `main.c` (it only starts in the outer 146-182 px band); `lv_group` focus (the app has no groups); `lv_obj_readjust_scroll` (it only fixes over-scroll); the theme kit (no scroll calls, and `click_origin_cb` only records the press point).

## Fix
`ui/apps.c`, `make_tile_ex`: `lv_obj_clear_flag(r, LV_OBJ_FLAG_SCROLL_ON_FOCUS);` on each tile. Commit "Apps: touching the Settings tile no longer scrolls the page up" on `dev`.
Verified on the Disc after a rebuild and `~/diskos/diskos-hotload.sh ui/mq_ui`: same press test, the list stays put (heart icon y 118 before, during and after), only the Settings tile dips (its press scale), then Settings opens.

## Where else this could bite
Any `lv_button` (or `lv_obj` with the flag) inside a scrollable list that has bottom padding, when its row sits in the padded strip. Other lists (library, playlist, settings rows) use their own row objects; check them with the same press test if a similar "page nudges on touch" report comes in.

## References
- LVGL source vendored at `ui/lvgl/src` (files and lines above); no external source was needed.
