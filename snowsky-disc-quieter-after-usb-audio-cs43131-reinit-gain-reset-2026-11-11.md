---
type: troubleshooting
tags: [snowsky-disc, diskos, cs43131, gain, usb-audio, dac-power, mq_player, outroute, mcu]
created: 2026-11-11
last_verified: 2026-11-11
status: current
---

# Snowsky Disc: after using USB Audio, the 4.4 mm output is much quieter until Gain is toggled (CS43131 re-init resets Gain)

Repo `/home/moo/diskos/diskos`, branch `dev` (commit `8e8f5a6`, worktree `~/diskos/diskos-reapply`, branch `fix/reapply-after-usb`). Not pushed. Flashed image on the Disc is `c964e99`; the fix was hot-loaded and verified by the user, but is not in a flashed image yet. Related: [[snowsky-disc-quieter-sound-dac-filter-nos-sysconfig-db-2026-11-11]] (an earlier, different quiet-sound cause), [[diskos-usb-audio-volume-keys-double-click-and-hold-2026-11-11]].

## Symptom (user report)

Attach a USB DAC (USB Audio), play, unplug it (the Disc falls back to Local Playback), plug a 4.4 mm balanced headset and play: much quieter than Local Playback after a fresh boot. A reboot fixes it.

## Findings

1. **Toggling Gain fixes it.** In Quick Settings, tap the Gain tile off and on (or Settings > Audio > Gain, Low then High); the loudness returned. That is the evidence that the lost state is the gain, and that re-sending it is enough.
2. The Player log (`/usr/data/fiio/log/fiio_player.log`) shows, on every return from USB to the internal DAC: `pcm_control_interface_out.c: set out device I2S3_OUT!`, `dac_control.c: dac_power_up`, `dac_control.c: CS43131 INIT`; and on the way out: `set out device USB_HOST!` then `dac_power_down`.
3. `strings /usr/bin/mq_player` shows `cs43131_init` plus one init per chip (`cs43131_letf_positive_init`, `cs43131_letf_negetive_init`, `cs43131_right_positive_init`, `cs43131_right_nagetive_init`), `cs43131_filter_set`, `cs43131_sample_write`, `dac_power_down deferred (CS43131 I2C config in progress)`, and `player_handle_set_gain` (it only stores `echo_sys_config.gain`). docs/RE_CATALOGUE.md lists `SET_GAIN` among the MCU/SPI name-commands, so Gain lives in the on-board MCU, not in the CS43131 registers.
4. diskOS sends Gain, DRE, DAC Filter and ReplayGain only at boot and after a Player restart (`reapply_sends` in `ui/main.c`). Nothing re-sent them after the route came back, so they stayed at the hardware defaults.
5. The repo already had the same problem solved for the charge limit: `charge_limit_reapply` fires a short time after leaving USB, but only if the route is internal and idle and the Player generation is unchanged (`ui/outroute.c`, `charge_limit_reapply_tick`).

Inference (not observed): the MCU or the analog stage resets while the DACs power down for USB, and the Player does not re-send `SET_GAIN` after `CS43131 INIT`. I did not read any DAC registers (no CS43131 register map, and reading unknown registers could clear status bits). Whether the filter, DRE and ReplayGain also reset was not measured; they are re-sent as well because it is idempotent.

## Fix

`ui/main.c`, `env_charge_limit_reapply` (the callback the route code already calls after leaving USB) now also does:

```c
ui_set_dre(cfg_get_int("audio_dre", 1));
ui_set_gain(cfg_get_int("audio_gain", 0));
ui_set_dac_filter(cfg_get_int("audio_filter", 1));
```

The existing tests in `ui/tests/outroute_test.c` (`charge_limit_reapply_*`) cover the timing and gating. Commands run: `cd ui/tests && CC=clang make run && CC=clang make run-py`, cross-build in the podman builder, `flock /tmp/diskos-disc.lock ~/diskos/diskos-hotload.sh ui/mq_ui`, then the user repeated the USB Audio round trip without touching Gain: as loud as after boot.

## Not covered

- Leaving the stock USB DAC mode (source mode 1, `srcswitch_send_source`) does not go through this callback; I did not test whether it resets Gain too.
- The first quiet report earlier the same day was blamed on the DAC Filter (NOS); it may have been this same effect, since USB Audio round trips preceded it. The filter was fixed by the user and the sound improved after a reboot, which clears both.

## Time estimate

About 10 minutes: 2 minutes to read the logs and symbols, 3 minutes to wait for the user's gain test, 2 minutes edit plus tests plus build (about 1 minute of that is the build), 10 seconds hot-load, then the user's retest.

## References

No external sources were used.
