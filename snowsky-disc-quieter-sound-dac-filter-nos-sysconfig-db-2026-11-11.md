---
type: troubleshooting
tags: [snowsky-disc, cs43131, dac-filter, nos, sysconfig-db, mq_player, loudness, diskos]
created: 2026-11-11
last_verified: 2026-11-11
status: current
---

# Snowsky Disc: internal playback sounded quieter, DAC Filter had been switched to NOS (how to read the Player's own settings)

Context: diskOS (hot-loaded builds) on a Snowsky Disc, V2.57. The user reported that internal/Local playback "sounds different", then "quieter", then, after a restart, "louder than the hot-loaded build". Related: [[diskos-usb-audio-volume-keys-double-click-and-hold-2026-11-11]].

**Finding:** the DAC Filter setting had been stepped through all six options and left on **NOS** (`audio_filter=4`); the stock default is index 1, **Slow LL**. After the user set it back (`audio_filter=1`) and restarted, it sounded louder again. Volume (58), Max Volume (100) and Gain (High) were the same in both states, so I cannot prove NOS alone explains a loudness change; it is the only audio setting that differed. I told the user that.

## How to read the state (all over ssh)

```bash
ssh disc 'grep -E "audio_filter|audio_gain|max_vol|replay_gain|usb_audio_on|src_mode" /usr/data/diskos.conf'
ssh disc 'diff /usr/data/diskos.conf.stone-backup /usr/data/diskos.conf'     # older copy from 2026-10-20 on this Disc
ssh disc 'sqlite3 -header /usr/data/fiio/db/sysconfig.db "select VOLUME,MAX_VOL,AUDIO_VOLUME_SET,FILTER_TYPE,DRE_STATUS,UAC_VOLUME from SYSCONFIG;"'
ssh disc 'grep -E "dac filter|dac_power|CS43131 INIT|bits_per_sample" /usr/data/fiio/log/fiio_player.log | tail -n 20'
ssh disc 'cat /proc/asound/cards; cat /proc/asound/card0/pcm0p/sub0/status'      # one card = no USB DAC; "closed" = nothing playing
```

- The stock Player keeps its settings in `/usr/data/fiio/db/sysconfig.db`, table `SYSCONFIG` (one row; columns include VOLUME, MAX_VOL, BALANCE_VOL, FILTER_TYPE, DRE_STATUS, UAC_VOLUME, AUDIO_VOLUME_SET).
- The Player log prints `dac_control.c: 398> dac filter reg:N` on every filter change, with timestamps. Seven changes within about a minute (reg 64, 192, 64, 32, 2, 0, 128 on 19:48 to 19:49) is what tapping through the cycler looks like. The log cannot say who tapped.
- Option labels (ui/settings.c): DAC Filter `Fast LL, Slow LL, Slow PC, Fast PC, NOS, Wideband` (index 0 to 5, default 1); Gain `Low, High`; ReplayGain `Off, Track, Album`.
- The diskOS config has no timestamps, and `audio_filter` and `max_vol` did not exist in the 2026-10-20 backup, so there is no earlier copy to compare for those.
- The Disc has a 3.5 mm and a 4.4 mm balanced output driven by four CS43131 DACs (docs/HARDWARE.md); diskOS has no 3.5 vs 4.4 selector and no jack-detect signal that I could find (the ALSA mixer shows only the internal codec). Whether the hardware switches by itself is unverified.

## What did not help / was ruled out

- diskOS's own volume code (`dacvol`) only runs on the USB Audio route; it does not touch the internal route's filter, gain or EQ.
- Player volume went up (47 at 18:03, 58 later), so a lower volume was not the cause.

## Time estimate

About 5 minutes of reading logs and the database (each query takes under a second). Not a repeated procedure, so no per-step figures.

## References

No external sources were used.
