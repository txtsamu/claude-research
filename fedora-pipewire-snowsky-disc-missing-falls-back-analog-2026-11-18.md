---
type: troubleshooting
tags: [snowsky-disc, fiio, usb-audio, pipewire, wireplumber, fedora, alsa, dac, audio-routing]
created: 2026-11-18
last_verified: 2026-11-18
status: current
---

# Fedora 43: FiiO SnowSky Disc missing from audio output, PipeWire fell back to onboard analog

User report: "audio output is not connected to my DAC snowsky" on the Fedora workstation, not the DiskOS player. The DAC was not offered as an output.

## Short version

Nothing in PipeWire was misconfigured. The DAC had dropped off the USB bus twice (`usb 1-4: USB disconnect`), so there was no ALSA card and therefore no PipeWire sink for it. With the configured USB sink absent, PipeWire fell back to its next choice, the onboard `ALC897` analog output. After the device re-enumerated, WirePlumber created the sink, restored it as default, and playback worked. Two 30 second test playbacks and a 100 second poll showed no further drops.

## Time estimate

About 6 minutes: 2 minutes of layer-by-layer checks, 2 minutes of playback test plus a 100 second stability poll, 2 minutes to write this up. The 100 second wait dominates.

## Diagnostic order that actually narrows it

Walk the layers in order. Each step tells you which layer owns the fault, so you never end up restarting PipeWire for a cable problem.

1. Is it on the USB bus at all?

```bash
lsusb | grep -i 2972            # FiiO vendor id
lsusb -t                        # shows the driver bound per interface
for d in /sys/bus/usb/devices/*; do [ -f $d/idVendor ] && echo "$(basename $d) $(cat $d/idVendor):$(cat $d/idProduct) $(cat $d/manufacturer 2>/dev/null) | $(cat $d/product 2>/dev/null)"; done
```

Related trick when `lsusb` and `lsusb -t` disagree: `lsusb` reads a cached device list, so run it twice or prefer the sysfs loop. On this box the short listing was missing the DAC while `lsusb -t` already showed `Dev 006, Class=Audio, Driver=snd-usb-audio`.

2. Did the kernel create an ALSA card?

```bash
cat /proc/asound/cards
aplay -l
ls -d /sys/class/sound/card*
```

The DAC should be `3 [DISC]: USB-Audio - SNOWSKY DISC`. If it is absent here, the problem is below PipeWire and no amount of `systemctl --user restart pipewire` will help.

3. Does PipeWire/WirePlumber have a device and sink for that card?

```bash
pactl list short cards
pactl list short sinks
wpctl status
```

4. What is the default, and does it survive?

```bash
pactl get-default-sink
wpctl get-volume @DEFAULT_AUDIO_SINK@
cat ~/.local/state/wireplumber/default-nodes
```

5. Prove audio actually flows, do not assume:

```bash
ffmpeg -hide_banner -loglevel error -f lavfi -i "sine=frequency=440:duration=30" -ar 48000 -ac 2 /tmp/tone.wav -y
paplay /tmp/tone.wav &
for i in $(seq 1 6); do sleep 5; pactl list short sinks | grep -i snowsky; done
```

Note `paplay` cannot open `.m4a`/AAC (`Failed to open audio file`); convert to WAV first. That failure looks like an audio bug but is just a missing codec in libsndfile.

6. Watch for the drop while you test:

```bash
journalctl -k -f | grep -E "usb 1-4|snd-usb"
```

## Evidence collected

Boot log for the DAC's bus position (`1-4`), three connects and two disconnects:

```
20:41:32 usb 1-4: new high-speed USB device number 5 using xhci_hcd
20:41:32 usb 1-4: New USB device found, idVendor=2972, idProduct=0158, bcdDevice= 1.00
20:41:32 usb 1-4: Product: SNOWSKY DISC
20:41:33 usbcore: registered new interface driver snd-usb-audio
20:44:26 usb 1-4: USB disconnect, device number 5
20:44:26 pipewire[5048]: spa.alsa: front:3p: snd_pcm_drop: No such device
20:44:37 usb 1-4: new high-speed USB device number 6 using xhci_hcd
20:45:55 usb 1-4: USB disconnect, device number 6
20:45:56 usb 1-4: new high-speed USB device number 7 using xhci_hcd
```

During the window with no device, `pactl` showed exactly the confusing state:

```
Default Sink: alsa_output.pci-0000_15_00.6.analog-stereo
53  alsa_output.pci-0000_15_00.6.analog-stereo   RUNNING
164 alsa_output.pci-0000_03_00.1.hdmi-stereo     SUSPENDED
```

Cards: only the three HDA ones, no `card 3`. That is the whole symptom: no USB card, so the default sink is the onboard analog one. `journalctl` for PipeWire and WirePlumber showed no errors, no "device disabled", no profile rejection. Nothing to fix.

After re-enumeration:

```
 3 [DISC]: USB-Audio - SNOWSKY DISC
397 alsa_output.usb-FiiO_SNOWSKY_DISC-00.analog-stereo  PipeWire  s32le 2ch 48000Hz  RUNNING
default = alsa_output.usb-FiiO_SNOWSKY_DISC-00.analog-stereo
Active Profile: output:analog-stereo
Mute: no, Volume: 50%
```

WirePlumber already had the right preference saved, so it came back on its own:

```ini
[default-nodes]
default.configured.audio.sink=alsa_output.usb-FiiO_SNOWSKY_DISC-00.analog-stereo
default.configured.audio.sink.0=alsa_output.pci-0000_15_00.6.analog-stereo
```

That `.0` line is the fallback, which is why the sound moved to the speakers instead of going silent.

Hardware capability from `/proc/asound/card3/stream0`, while running: S32_LE and `DSD_U32_BE`, 32/44.1/48/88.2/96/176.4/192/352.8/384 kHz, adaptive endpoint, 250 us packet interval. So the DAC was being used at 48 kHz, and can go much higher.

## Stability check

Playback of a 30 second 440 Hz tone to the default sink ran clean with no journal output. A 100 second poll of `devnum`, `card3`, and the sink count returned a steady `7 / DISC / 1` with zero USB events. No quirk (`quirk_flags`), no autosuspend involvement (`power/control=on`), no xhci resets or `error -71` lines anywhere in the boot log.

## Cause of the disconnects: not determined

Two drops in four minutes, then stable. The 20:44:26 one had an 11 second gap before re-enumeration, which looks like a physical reseat. The 20:45:55 one re-enumerated in under a second, which looks device-initiated. Both are plausible; I did not watch the port at the moment of the drop, so I am not going to guess between cable, port power, or a device-side reset.

If it recurs, in this order:

```bash
watch -n1 'lsusb | grep 2972'      # is it still enumerated?
journalctl -k -f | grep -E "usb 1-4|snd-usb|xhci"
grep . /sys/bus/usb/devices/1-4/power/{control,runtime_status,autosuspend_delay_ms}
```

Then move it off any hub or front-panel header to a rear port wired straight to the chipset, and swap the cable. A CS43131 amp on a bus-powered 50 mA descriptor is a plausible brownout candidate under load, but that is a hypothesis, not a measurement.

## What was verified vs not

Verified: device enumeration, ALSA card creation, PipeWire device/sink creation, default sink restoration, real 30 second playback, 100 second stability, hardware rate list, absence of kernel USB errors.

Not verified: whether the user now hears audio from that DAC (headphone output and the device's own input selector/volume knob are outside software reach), what physically caused each disconnect, and behaviour after a reboot or suspend.

Related: [[snowsky-disc-quieter-after-usb-audio-cs43131-reinit-gain-reset-2026-11-11]], [[snowsky-disc-quieter-sound-dac-filter-nos-sysconfig-db-2026-11-11]], [[fiio-snowsky-disc-diskos-flash-fedora]], [[snowsky-disc-usb-dac-uac2-android-and-firmware-decompile]]

## References

No external sources were used; everything came from on-box kernel logs, sysfs, `/proc/asound`, and PipeWire tooling.
