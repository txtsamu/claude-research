---
type: how-to
tags: [diskos, snowsky-disc, screenshot, framebuffer, terminal-theme, layout, round-screen, lvgl]
created: 2026-10-27
last_verified: 2026-10-27
status: current
---

# diskOS: screenshots over key SSH, and the Terminal Home layout change they made possible

Request: on the Terminal theme, remove the `diskOS 1.2 | tty0` line, put the date centred right under the clock, and make the screen less cramped. Fork `dev`, commit `052a498` (`ui/theme_kits.c`, `term_home()`). Companion docs: [[diskos-hotload-gotchas-test-outputs-usb-storage-reboot]], [[diskos-stock-plus-round-screen-features-and-flash]] (round-glass geometry: only pixels within r=180 of (180,180) are visible, safe radius for controls about 166).

## Taking a screenshot of the Disc (no Debug Mode password needed)

`tools/diskos-shot.sh` needs `DISKOS_IP`/`DISKOS_PW` and password SSH. Over the key SSH `Host disc` the same capture works (the panel is 360x360, 32 bpp BGRA, mounted rotated 180; read the first framebuffer page, which is the visible one while `cat /sys/class/graphics/fb0/pan` prints `0,0`):

```bash
ssh disc 'cat /sys/class/graphics/fb0/pan'                    # 0,0 = page 0 is visible
ssh disc 'dd if=/dev/fb0 bs=518400 count=1 2>/dev/null' > raw
python3 -I - raw out.png <<'PY'
import sys
from PIL import Image
raw = open(sys.argv[1], "rb").read()[:518400]
Image.frombuffer("RGBA", (360, 360), raw, "raw", "BGRA").convert("RGB").rotate(180).save(sys.argv[2])
PY
```

A wrapper `shot.sh <out.png>` is kept in `~/sessions/2026-10-27-diskos-outseq/` with the before/after PNGs in `shots/`. Pillow is installed on the Fedora box (`python3 -I` from another directory avoids a stray module shadowing the stdlib).

To see a theme other than the one the user runs, switch it temporarily, keep the audio route, and restore it after:

```bash
ssh disc 'sed -i "s/^theme_preset=2/theme_preset=3/" /usr/data/diskos.conf'      # 0 halo, 1 something, 2 hi-fi, 3 terminal, 4 bauhaus, 5 blueprint, 6 stone, 7 zine
ssh disc 'killall -9 mq_ui; DISKOS_THEME_RELOAD=1 DISKOS_RELOAD_ROUTE=2 DISKOS_RELOAD_SRC=0 setsid /usr/data/mq_ui home </dev/null >/usr/data/diskos_boot.log 2>&1 &'
# ... shots ...
ssh disc 'sed -i "s/^theme_preset=3/theme_preset=2/" /usr/data/diskos.conf'      # restore, then relaunch the same way
```

`time_24h` is absent from the conf when it is the default (24 h): to test the 12-hour clock append `time_24h=0`, and delete that line afterwards. The cursor blink can be proven from screenshots: count accent-coloured pixels in the cursor's box across several shots; they alternate between two values (here 635 / 1259) when it blinks.

## The layout change

Before (`term-home-before.png`): banner at y 30, status 50, clock 70, `$ date` prompt 148, date 164 and weather 182 left-aligned at x 62, `$ now` 196 (touching the weather line), now-playing 212, keys 262 to 296.

After: banner and the `$ date` prompt removed; the stack is positioned from named constants (`TH_*` in `theme_kits.c`): status 34, clock 62, date 128 (centred, width 360), weather 148 (centred, width 300), `$ now` 194, now-playing line 210 (44 high), `[ library ] [ find ]` at 272, 32 high and 120 / 80 wide so the bottom corners sit at r~157 inside the 166 safe radius. The blinking cursor keeps its offset from the clock (`TH_CURSOR_DY` 14, it hangs a little below the digits, as before). Checked in 24-hour and 12-hour time (the "pm" label fits to the right of the cursor), on the Disc, with screenshots. Not checked: other weather strings (a very long condition text is truncated by `home_set_weather` against the label width), a state with no track playing, and other screen rotations. Other themes are untouched.
