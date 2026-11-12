---
type: how-to
tags: [diskos, snowsky-disc, verification, apps-page, equalizer, settings, quick-settings, max-volume, working-mode, tinj, screenshots, upstream]
created: 2026-11-12
last_verified: 2026-11-12
status: current
---

# diskOS: device check of the 2026-11-11 build, and the choice-picker scroll fix

Repo `/home/moo/diskos/diskos`, branch `dev` at `0296c1f` (parent `4692679`; the fix commit is the only one added here). Hot-loaded `/usr/data/mq_ui` md5 `b32cc01086ad949d1c88a58875582501`, terminal theme (`theme_preset=3`), `eq_preset=0`, `max_vol=100` afterwards. Related: [[diskos-eq-how-it-works-and-upstream-1-2-2-port-2026-11-11]], [[diskos-settings-ui-round-buttons-theme-kit-keep-and-battery-qs-2026-11-11]], [[diskos-working-mode-auto-via-local-2026-11-11]], [[diskos-hotload-gotchas-test-outputs-usb-storage-reboot]].

Request: "verify on the Disc" — check the 2026-11-11 work that had never been looked at on hardware (Apps Equalizer tile, Equalizer preset list, battery on Quick Settings, round Max Volume controls, Working Mode rows). The Disc was off at first; it appeared on Wi-Fi a minute later (key SSH `ssh disc`, port 2222).

## What was checked on the Disc

| Screen | Result |
|---|---|
| Apps (swipe left from Home) | Four round tiles: Pet, USB DAC, Equalizer, Settings. The new Equalizer tile draws its three sliders correctly in the terminal theme. |
| Equalizer list (from the tile) | A preset list, not a cycler: Off, 10 stock presets, USER1..10; scrolls smoothly. |
| Applying a preset | Tapping Sibilance 1 set `eq_preset=9` and logged `eq 9 -> 0689000C0009`; the check mark moved. Set back to Off (`eq_preset=0`, `0689000C0000`). |
| Quick Settings (swipe down from top) | Battery at the bottom: icon plus `89%`. Tile rows end above it; no overlap. |
| Working Mode picker (Quick Settings > source) | Local Playback (check) with USB Audio under it, then USB DAC, Bluetooth Receiving, USB Storage, USB Debug ("Shell over the USB cable"). One-line descriptions. |
| Settings > Audio > Max Volume | Round chevrons and a round knob; value `100`; description fully visible ("Cap the maximum volume level (protects your ears / headphones)."). Two +10 taps went 100 → 120 and stopped there (row max); two -10 taps back to 100. `diskos.conf` followed each step. |
| Settings > Display > Theme | Long picker opens with `terminal` marked (fourth row) and the swatches draw. |
| Quick Settings > power off | Opens the "Power off?" dialog ("Closes the card safely, then switches the device off" / Cancel / Power off). Cancelled so the Disc stayed up for the remaining checks. |

## Device state afterwards

The Disc was left on the terminal theme, EQ Off, Max Volume 100. About 5 minutes after the last touch it dropped off Wi-Fi by itself: `ssh disc` answered "No route to host", port 2222 was closed and there was no ARP entry, with `stock_power_save=300` in `diskos.conf`. That is the stock idle power-save, so it had already powered itself off when asked to power it off; the shutdown could not be driven from the shell at that point. Expect the same after an idle check session: the device leaves the network without a toast.

## The bug the check found

Picking a preset rebuilt the Equalizer detail page at the **first row**: choosing Sibilance 1 scrolled back to Off, so the new check mark was off-screen. Opening a picker also always started at the top instead of at the saved choice — visible on Theme and Equalizer.

Cause: the fork ported upstream's `ST_CHOICE` row for Equalizer but not the small scroll bit that travels with it. Upstream `ui/settings.c` keeps the checked row in `sel` and calls `lv_obj_scroll_to_view(sel, LV_ANIM_OFF)` after the loop (`upstream/main` around line 1145, comment "every picker opens with its current choice in view").

Fix (`0296c1f`): the same `sel` capture and scroll-to-view in the fork's `ST_CHOICE` branch; explanation in `comments.md` under `ui/settings.c`, note in `CHANGELOG.md` under Fixed. No comments added to the source (repo rule).

Verified on the Disc after a hot-load: choosing Sibilance 1 keeps the row in view with the check mark; leaving and reopening the picker lands on Sibilance 1; Theme opens on `terminal`. Host tests (`CC=clang make run`, `make run-py`) and the cross-build pass; the binary md5 did not change when the source comment was removed again, so the running build matches the committed tree.

## Navigation method and gotchas

```bash
ssh disc                                   # key SSH, port 2222, Wi-Fi must be on
ssh disc '/usr/data/tinj swipe 300 180 60 180'   # Home > Apps (left)
ssh disc '/usr/data/tinj swipe 180 4 180 260'    # Quick Settings (down from top edge)
ssh disc '/usr/data/tinj swipe 8 180 220 180'    # back (right swipe from left edge)
ssh disc '/usr/data/tinj tap 108 250'            # tap the Equalizer tile
~/diskos/snowsky-shot.sh /tmp/opencode/x.png     # then read the PNG
flock /tmp/diskos-disc.lock ~/diskos/diskos-hotload.sh /home/moo/diskos/diskos/ui/mq_ui
```

- **The chevron tap is flaky; the edge back-swipe is not.** Tapping (18,180) often logged `TAP x=20 y=179` without leaving the page, while `swipe 8 180 220 180` always worked. Use the swipe when navigating blind; it is also the gesture that cannot hit a list row.
- **Row hit areas sit lower than the title text.** On Display, tapping the Theme title (`y≈182`) opened Appearance; tapping `y≈152` opened Theme. Aim at the value line or slightly above the title, and screenshot after every step instead of chaining blindly.
- **Take a screenshot before acting.** The Disc had just booted and the screen had moved between my first shot and first swipe, so the first commands landed on a page the user had opened (Debug Mode, then Settings > System).
- **A hot-load survives a reboot here**: `/usr/data/mq_ui` was still the last session's build (`4692679`, same md5 as the local `ui/mq_ui`) and the boot log showed the watchdog starting it, so no re-load was needed before the first checks. Confirm with `readlink /proc/$(pidof mq_ui)/exe` and an md5 comparison.
- The Equalizer tile opens the **preset list**, not Custom EQ, because the editor is view-only on V2.57 (see the EQ note).

## Not verified

- **USB Debug with a PC attached** — needs the USB-C cable. The image already ships the matching `payload/diskos-debug.sh` (md5 equal to the repo), so `usb-on`/`usb-status` will work.
- **USB Audio**: volume keys with Double click = Switch Track, hold-to-repeat, the `dacvol` volume path and the Max Volume cap while a computer streams. Needs the Disc as a USB DAC to this PC.
- **USB Storage** round trip and the restart-safe `src_pending` timer; **Bluetooth Receiving** switching; any theme other than terminal (the Apps page in the other kits is still unseen).
- **Max Volume on USB Audio is still open**: `ui_set_maxvol()` returns early while `dacvol_owns_volume()`, so lowering the cap does not clamp the current DAC level until the next volume change. The old "read 120 and would not move" is at least consistent with hitting the 120 row maximum (two +10 taps from 100 stop there); the cap-on-USB-Audio path itself was not exercised.

## Time estimate

About 15 minutes of device work, including the picker fix, a rebuild and hot-load, and two verification rounds. Most of it was navigation, not code.

## References

No external sources; upstream `b0hemia/diskos` `ui/settings.c` at `upstream/main` was read locally.
