---
type: investigation
tags: [diskos, snowsky-disc, volume, gain, loudness, usb-audio, spdif, ja11, wifi-interference, flash, release]
created: 2026-10-27
last_verified: 2026-10-27
status: current
---

# diskOS: "volume is quieter than the previous build", SPDIF vs USB Audio, the JA11 power check, a second flash, and promoting `dev` to `main`

Fork `txtsamu/diskos`, `dev` -> `main` at `eb7a963`. Companion docs: [[diskos-hotload-gotchas-test-outputs-usb-storage-reboot]], [[diskos-fork-consolidated-into-dev-branch]], [[diskos-usb-dac-exit-deadlock-roles-and-volume-fix]] (the per-mode volume slots), [[diskos-usb-audio-reverse-engineering-mq-player]].

## 1. "Loudness is lower than the previous build (40/120 used to be loud enough)"

Outcome: it went away after flashing the newest `dev` build and a clean cold boot (user: "somehow the loudness problem is gone"). The root cause was **not pinned down**; what was established:

- No code change touches loudness. `git diff cea2ca9 dev` (the Oct 22 flashed build vs `dev`) has no change to volume, gain, DRE, DAC filter, replay gain, max volume or the `a714` handling (`ui_set_volume` clamps to `max_vol` only when it is set and below 40; the BT route resend and `dac_volume_cb` do not apply to Local). The `outseq` refactor sends the same frames in the same order as `modes_local_init`. Nothing outside `ui/` changed either (`payload/`, installer), so the flashed image is the same. Use `rtk proxy git diff ...` when the output must be grepped: the rtk hook compacts plain `git diff`.
- Facts: volume command `0715000C<n>` is 0..120 in stock and upstream diskOS (`docs/COMMAND_MAP.md`, `RE_CATALOGUE.md`); `0711` max volume 0..120, DB `MAX_VOL=120`; DRE `0812` (0 = on); gain `0645` on V2.09 but `0649` on V2.28/V2.40/V2.57 (`fwcaps.c fw_gain_tag`), payload 0 = Low, 1 = High; replay gain `0718`. diskOS re-sends DRE, gain, filter and replay gain once per player (re)connect (`ui_reapply_audio`) and about 7 s later sends the boot route frames `0642 0`, `0666 6`, `0657 8`.
- The mechanism that fits (verified in `fiio_player.log`, effect inferred): every `0666 6` makes the player re-initialise the DAC (`dac_power_up`, `CS43131 INIT`). At the 15:55 boot, which started from a saved `OUT_DEV=3` (USB), the settings landed at 15:55:37 and the INIT came at 15:55:44, so the DAC chip could have lost gain/DRE/filter; the 14:49 boot had the INIT first and was fine. The same happens on each USB-to-Local switch and on each play from stopped (`CS43131 INIT` at 17:29:04). Gain goes through an MCU opcode that cannot be read from the Disc, so whether the INIT really resets it was never confirmed.
- Other state that differed: the Local slot (`SYSCONFIG.VOLUME`) reloaded at 33 at the 15:55 boot (usual 40-54) and was then raised; replay gain was toggled; an EQ preset 20 was toggled on and off in the UI log. `ICODEC HPOUTL GAIN` reads 0 while the Local output plays, so the headphone path is the external DAC, not the SoC codec.
- Not done: the proposed fix (re-send gain, DRE, filter, replay gain after every switch to Local) was NOT written, because the problem disappeared after the reflash. If it comes back after a boot that started on USB Audio, that is the first thing to try, and the quick test is to toggle the Quick Settings Gain tile off and on.

Read-only recipe used (all over key SSH, never grep the whole player log):

```bash
ssh disc 'sqlite3 /usr/data/fiio/db/sysconfig.db "SELECT VOLUME,AUDIO_VOLUME_SET,UAC_VOLUME,MAX_VOL,DRE_STATUS,FILTER_TYPE,SYS_REPLAY_GAIN,OUT_DEV FROM SYSCONFIG WHERE ID=1"'
ssh disc 'tail -n 4000 /usr/data/fiio/log/fiio_player.log | grep -E "set out device|out_dev=|CS43131 INIT|dac_power|dac filter"'
ssh disc 'grep -E "audio_gain|replay_gain|eq_" /usr/data/diskos.conf'
```

## 2. SPDIF Output while on USB Audio, then "no sound"

The Settings > SPDIF Output toggle (test builds only, never verified on this Disc) was switched on while the output was USB Audio: `17:29:00 set out device SPDIF_TX` + `dac_power_down`, then 1.5 s later `set out device I2S3_OUT` (internal) with no SPDIF audio ever played. That dropped the USB host role, so the JA11 vanished and the next USB Audio attempt found no card. The player then ran on the internal output while the user was listening on the JA11: "no sound" (the player showed `> playing`; the stream at `/proc/asound/card0/pcm3p` was advancing at 44.1 kHz). Fix for the user: select Working Mode > USB Audio again. Which code sent the second route frame was not found; leave SPDIF off. Open follow-up: block or handle the SPDIF toggle while the route is USB.

## 3. JA11 power check (read-only)

```bash
ssh disc 'cat /sys/class/usb_role/*/role; for d in /sys/bus/usb/devices/*; do [ -f $d/idVendor ] && echo $(basename $d) $(cat $d/idVendor):$(cat $d/idProduct) $(cat $d/product) maxpw=$(cat $d/bMaxPower); done; head -4 /proc/asound/cards; for r in 1 8; do i2cget -f -y 2 0x1a 0x0$r; done; dmesg | grep -iE "otg|usb 1-1"'
```

Healthy state: role `host`, `1-1 2972:0102 JadeAudio JA11` high speed, `card1 JA11`, SGM41513 `reg01=0x26` (OTG boost on) and `reg08=0xe0` (VBUS_STAT = OTG), `SGM41513_OTG_ON: OTG enabled, 5V output`, no disconnect or over-current lines, player `set out device USB_HOST` / `out_dev=3`, battery 4.21 V. The JA11 declares `bMaxPower` 98 mA in its USB descriptor (what it asks for, not a measurement). FiiO's page and reviews publish no current figure (only 30 mW + 30 mW into 32 ohm, SNR >= 115 dB).

## 4. "brrt" next to the music

With the JA11 as the output and Wi-Fi on (2.4 GHz, `ASUS`, kept on by Persistent debug), the user heard a "brrt". No report specific to the Disc or the JA11 turned up online; the known mechanism is Wi-Fi/GSM burst buzz demodulated in the audio circuit (Missouri S&T paper on buzz noise, Marantz guidance: change channel or go wired). Test: turn Wi-Fi off while playing. Options: untick Persistent debug, 5 GHz, keep the dongle and cable away from the antenna. Not confirmed whether it was the cause.

## 5. Second flash of `dev` (recipe that worked twice)

Set up once in the `dev` checkout: copy `usbboot` and `usbboot.manifest` from the old `diskos-stock-plus/vendor/linux-x86_64/` (git-ignored), `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`, then `./diskos-installer doctor`. Per flash:

```bash
cd ~/diskos/diskos/ui && podman run --rm --userns=keep-id -v "$PWD:/src:Z" localhost/diskos-ui-builder:latest \
  sh -c 'make clean >/dev/null; make -j4 CROSS=$CROSS EXTRA_CFLAGS=-DDISKOS_TEST_OUTPUTS'
cd .. && echo n | ./diskos-installer install --firmware ~/Downloads/SNOWSKY_DISC_update_20260909_v257.zip --variant public --ui ui/mq_ui --no-ota
#   builds + validates the image, then declines; check: sha256sum ui/mq_ui == SHA256= in `unsquashfs -cat ~/.local/share/diskos-installer/build/out.squashfs etc/diskos_manifest`
# Disc in mask-ROM mode (lsusb shows a108:eaef), then the same command with -y, in the background with systemd-inhibit,
# and watch the exact PID (never `pgrep -f` from the watcher itself: it matches its own command line):
kill -0 <pid>
```

Results: 14:56-15:16 (`3c3662b`, `0x600DF10C [F001] SUCCESS`, backup `g0009`) and 17:58-18:18 (`736cab7`, SUCCESS, `g0010`), 2 bad blocks skipped each time. After a flash a hot-loaded `/usr/data/mq_ui` from earlier is still there; it matched the flashed build both times, but check `md5sum`.

Operational lesson from this session: the auto-mode safety classifier went unavailable several times (Bash, MCP and Agent calls failed with "no verdict"); read-only file reads kept working, and background agents were killed after 10 consecutive misses. Retrying once is allowed; after that continue with work that does not need the classifier and wait for the user.

## 6. Promotion to `main`

On "I'm happy with the flash": docs first (`CHANGELOG.md` Unreleased section, Persistent debug in `docs/INSTALL.md`, Pet in `docs/TOUR.md`), then `git fetch; git merge-base --is-ancestor origin/main dev` (fast-forward, upstream v1.2.1 was `4cd4a60`), `git push origin dev; git push origin dev:main`. `main` = `dev` = `eb7a963`. Fork branches: `dev` and `main` only.
