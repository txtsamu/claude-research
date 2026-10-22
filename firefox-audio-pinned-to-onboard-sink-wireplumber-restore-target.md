---
type: troubleshooting
tags: [pipewire, wireplumber, firefox, usb-dac, fiio-ja11, stream-restore, fedora]
created: 2026-10-22
last_verified: 2026-10-22
status: current
---

# Firefox audio plays on onboard speakers instead of the USB DAC (WirePlumber restore-target)

## Symptom

System default sink is the FiiO JadeAudio JA11 (USB DAC), but Firefox sound comes out of the onboard Realtek ALC897 output. Other apps (Telegram etc.) follow the DAC fine.

## Diagnosis (in order)

1. Default vs. actual routing:
   ```bash
   wpctl status          # Sinks: * marks default (JA11); Streams: shows Firefox linked to "ALC897 Analog"
   pactl get-default-sink
   ```
   Default was the DAC, but Firefox's stream was linked to `ALC897 Analog:playback_FL/FR`.
2. Per-stream metadata showed an explicit pin:
   ```bash
   pw-dump | python3 -c '...'   # dump PipeWire:Interface:Metadata
   ```
   The `default` metadata had `{'subject': 87, 'key': 'target.object', 'type': 'Spa:Id', 'value': 68}` — node 87 = Firefox stream, node 68 = `alsa_output.pci-0000_15_00.6.analog-stereo` (onboard).
3. Why it kept coming back — WirePlumber's persisted state:
   ```bash
   grep -n Firefox ~/.local/state/wireplumber/stream-properties
   # Output/Audio:application.name:Firefox={"mute":false, "volume":1.000000, "target":"alsa_output.pci-0000_15_00.6.analog-stereo", ...}
   ```
   `node.stream.restore-target` is `true` (default) in `sm-settings`, so WirePlumber re-applies that stored `target` every time a Firefox output stream starts, overriding the default sink.
4. No user WirePlumber config exists (`~/.config/wireplumber` missing), so this is stock behaviour, not a local override.

## Fix (one-time)

```bash
cd ~/.local/state/wireplumber
cp stream-properties /path/to/backup/stream-properties.bak
pw-metadata -n default -d 87 target.object     # 87 = Firefox stream node id from wpctl status
wpctl status                                   # Firefox now linked to JadeAudio JA11:playback_FL/FR
```

Deleting the metadata key made WirePlumber rewrite `stream-properties` itself — the `"target"` field was gone afterwards, so no manual file edit was needed. Firefox then followed the default sink.

## Why it probably happened

WirePlumber stores a stream's target whenever that stream is *manually moved* to a different sink (pavucontrol, COSMIC sound settings, `pactl move-sink-input`, ...), keyed by `application.name`, and restores it on the next stream. So at some point Firefox's output was moved to the onboard sink — plausibly while the DAC was unplugged/asleep/not yet enumerated. I could not confirm which; no source describes the "moved while the default was unavailable" case explicitly.

## If it recurs — options

- Disable restore for Firefox only, via a WirePlumber stream rule setting `state.restore-target = false` matched on `application.name = "Firefox"` (documented in the WirePlumber stream configuration page).
- Disable globally: set `node.stream.restore-target` to `false` in WirePlumber settings.
- Optionally `linking.follow-default-target = true` (already true here) makes default-targeted streams follow default changes, but it does not help once a per-stream stored target exists.

Not tested across a Firefox restart at time of writing.

## References

- [WirePlumber — Well-known settings](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/settings.html) — `node.stream.restore-target`, `node.restore-default-targets`, `linking.follow-default-target`
- [WirePlumber — Stream configuration](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/stream.html) — `stream.rules`, `state.restore-target`
- [Arch forum thread on stored stream targets](https://bbs.archlinux.org/viewtopic.php?id=277286) — community report of the restore-stream behaviour (older file name `restore-stream`; on this WirePlumber it is `stream-properties`)
