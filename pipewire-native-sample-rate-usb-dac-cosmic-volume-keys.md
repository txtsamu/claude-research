---
type: how-to
tags: [pipewire, fedora, cosmic, usb-dac, sample-rate, bit-perfect, resampling, volume-keys, cosmic-settings-daemon]
created: 2026-10-19
last_verified: 2026-10-19
status: current
---

# PipeWire: play at the file's native sample rate on a USB DAC (and the COSMIC volume-key breakage after restarting it)

Context: FiiO Snowsky Disc used as a USB DAC from the fedora desktop (Fedora 43, COSMIC). The Disc accepts 32–384 kHz (`S32_LE`, plus DSD), but everything arrived at 48 kHz.

## Diagnosis

```bash
pactl list sink-inputs | grep -E 'Sample Specification|application.name'   # cosmic-player: float32le 96000Hz
cat /proc/asound/DISC/pcm0p/sub0/hw_params                                  # rate: 48000  -> PC resamples 96k->48k
pw-metadata -n settings 0 | grep rate                                       # clock.allowed-rates = [ 48000 ]
grep -A8 Playback /proc/asound/DISC/stream0 | grep Rates                    # 32000 ... 384000
```

Fedora's default PipeWire graph only allows 48000, so every stream is resampled to 48 kHz.

## Fix

```bash
mkdir -p ~/.config/pipewire/pipewire.conf.d
cat > ~/.config/pipewire/pipewire.conf.d/10-allowed-rates.conf <<'EOF'
context.properties = {
    default.clock.allowed-rates = [ 44100 48000 88200 96000 176400 192000 352800 384000 ]
}
EOF
systemctl --user restart pipewire pipewire-pulse wireplumber
pw-metadata -n settings 0 | grep allowed-rates
```

Undo: delete the file and restart the same units.

## Gotchas found while verifying

1. **The rate only switches when the device starts from idle.** A stream already running stays at the old rate — pause ~3 s and play again (or change track).
2. **Any other stream on the same sink pins the rate.** A Firefox tab (even an X/Twitter page) kept an uncorked 48 kHz stream on the DAC; PipeWire won't change the clock under it. Move it off (`pactl move-sink-input <id> <other-sink>`) or close it. Firefox always plays at 48 kHz.
3. After both, verified end to end with a 96 kHz/24-bit FLAC in cosmic-player: PC `hw_params` 96000 → Disc capture 96000 (`UAC_SRATE=96000` in the Disc's player log) → Disc DAC 96000.
4. PipeWire's software volume still applies — for bit-perfect keep the sink at 100% and set loudness on the DAC.

## COSMIC volume keys stop working after restarting PipeWire

Symptom: keyboard volume keys did nothing. `journalctl --user` showed, from `cosmic-session`:

```
ERROR  Failed to raise volume: no active sink device to apply operation to
```

First occurrence right after the 13:18:08 PipeWire restart. Which component:

```bash
for b in cosmic-settings-daemon cosmic-osd; do echo "$b: $(strings $(command -v $b) | grep -c 'no active sink device')"; done
# cosmic-settings-daemon: 1   cosmic-osd: 0
```

`cosmic-settings-daemon` loses its PipeWire/Pulse connection and doesn't reconnect. Killing it does **not** make cosmic-session respawn it (checked with `ps -eo pid,comm | awk '$2 ~ /cosmic-settin/'` — note `pgrep -f` matches its own shell, and plain `pgrep` can't match names >15 chars). Relaunch it with the session's environment, copied from a sibling process:

```bash
OSD=$(ps -eo pid,comm | awk '$2=="cosmic-osd"{print $1}')
tr '\0' '\n' < /proc/$OSD/environ | grep -E '^(WAYLAND_DISPLAY|DISPLAY|DBUS_SESSION_BUS_ADDRESS|XDG_RUNTIME_DIR|XDG_SESSION_TYPE|XDG_CURRENT_DESKTOP)=' > cosmic.env
pkill -x cosmic-settings    # comm is truncated to 15 chars; only if it's still running
systemd-run --user --unit=cosmic-settings-daemon-relaunch --collect $(sed 's/^/--setenv=/' cosmic.env) /usr/bin/cosmic-settings-daemon
```

Lasts for the login session; next login cosmic-session starts it normally. Simplest alternative: log out and back in after restarting PipeWire.

## References

- [pipewire.conf(5) — `default.clock.allowed-rates` ("switched when devices are idle"), `pipewire.conf.d/` drop-in paths](https://docs.pipewire.org/page_man_pipewire_conf_5.html)
