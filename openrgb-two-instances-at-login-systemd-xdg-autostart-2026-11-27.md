---
type: troubleshooting
tags: [openrgb, systemd, xdg-autostart, fedora, autostart, rgb, login, systemd-xdg-autostart-generator]
created: 2026-11-27
last_verified: 2026-11-27
status: current
---

# Two OpenRGB instances at login: a renamed autostart file still autostarts (2026-11-27)

Request: "help me investigate why there is 2 openRGB run at boot startup".

Host: Fedora 43, systemd `258.11-1.fc43`, OpenRGB `1.1+ (git14)` built locally at `/usr/local/bin/openrgb`. No repo involved; the whole story lives in `~/.config/autostart/` and `~/.config/OpenRGB/`.

## Symptom

Two processes, identical command line, same parent (`systemd --user`):

```
$ ps -eo pid,ppid,etime,cmd | grep -i openrgb | grep -v grep
   3367    1755       00:51 /usr/local/bin/openrgb --startminimized
   3368    1755       00:51 /usr/local/bin/openrgb --startminimized
```

`/proc/<pid>/cgroup` showed each one belonged to a different unit:

```
3367 -> app-OpenRGB.desktop.disabled@autostart.service
3368 -> app-OpenRGB@autostart.service
```

## Root cause: `.desktop.disabled` is not a way to disable an XDG autostart entry

`~/.config/autostart/` held two byte-identical files:

| File | mtime | Generated unit |
|---|---|---|
| `OpenRGB.desktop` | 2026-11-27 12:37:46 | `app-OpenRGB@autostart.service` |
| `OpenRGB.desktop.disabled` | 2026-10-20 08:30 (renamed 09:21) | `app-OpenRGB.desktop.disabled@autostart.service` |

On systemd 258, `systemd-xdg-autostart-generator` does **not** filter by the `.desktop` suffix. It walks the directory and keeps every entry that is a regular file:

```c
FOREACH_DIRENT(de, d, ...) {
        if (fstatat(dirfd(d), de->d_name, &st, 0) < 0) { ... continue; }

        if (!S_ISREG(st.st_mode)) {
                log_debug("%s/%s: not a regular file, ignoring.", *path, de->d_name);
                continue;
        }

        _cleanup_free_ char *name = xdg_autostart_service_translate_name(de->d_name);
```

That is the entire filter. Renaming the file to `*.desktop.disabled` only changes the generated unit name, so it still launches. Reproduced in a throwaway directory:

```bash
mkdir -p /tmp/xdgtest/out /tmp/xdgtest/autostart
cp ~/.config/autostart/OpenRGB.desktop /tmp/xdgtest/autostart/zzz-probe.desktop.off
XDG_CONFIG_HOME=/tmp/xdgtest /usr/lib/systemd/user-generators/systemd-xdg-autostart-generator /tmp/xdgtest/out
ls /tmp/xdgtest/out
# app-zzz\x2dprobe.desktop.off@autostart.service
```

The supported escape hatches are `Hidden=true` or `X-systemd-skip=true` inside the file, moving it out of the autostart directory, or masking the unit. A probe with `Hidden=true` generated no unit at all.

## Why `OpenRGB.desktop` keeps coming back

OpenRGB manages that file itself. `~/.config/OpenRGB/OpenRGB.json` had `AutoStart.enabled = true`, and the file header is OpenRGB's own banner. Its mtime was `12:37:46.76`, about two seconds after both processes started at `12:37:44`, so the running instance rewrote it on startup. Deleting it by hand while autostart is enabled only lasts until the next launch.

The binary ships the proper interface for this:

```
--autostart-check       Check if OpenRGB starting at login is enabled.
--autostart-enable      Enable OpenRGB to start at login. Requires arguments to give to OpenRGB at login.
--autostart-disable     Disable OpenRGB starting at login.
```

## Why the `.disabled` file existed

It was a leftover from [[gigabyte-b650m-k-argb-fan-no-light-openrgb-gbrgb]] (Oct 20, gotcha 4), where the autostart entry was renamed to stop OpenRGB resetting the colour at login. That rename changed nothing on systemd 258, so the unit kept running.

There is a second, older layer here. [[fedora-perf-audit-openrgb-i2c-dup-scan]] (July 2026) fixed a different two-process situation by editing the autostart entry to `--startminimized --nodetect --client 127.0.0.1:6742`, making the GUI a client of `openrgb-server.service`. That edit is gone: OpenRGB regenerated the file with plain `--startminimized`, because `AutoStart.custom_arguments` was empty. No `openrgb-server.service` exists any more either (`systemctl list-unit-files | grep -i openrgb` is empty), so the `Client` entry in `OpenRGB.json` was pointing at nothing.

## Side effects of running two instances

- Both processes launched in the same second, and the log filename is a second-resolution timestamp, so both wrote to the same `OpenRGB_20261127_123745.log`. The interleaved duplicate lines in that file are two writers, not a logging bug.
- `Client.clients` contained `127.0.0.1:6742`, the same port as the `Server` block, with nothing listening. Each instance retried every 10 seconds, filling the log with `Connection attempt failed`.

## Fix applied

Order matters: stop the remaining instance before editing `OpenRGB.json`, otherwise OpenRGB saves its in-memory settings on exit and clobbers the edit.

```bash
systemctl --user stop 'app-OpenRGB.desktop.disabled@autostart.service'
rm -f ~/.config/autostart/OpenRGB.desktop.disabled
systemctl --user daemon-reload
systemctl --user stop 'app-OpenRGB@autostart.service'
cp -a ~/.config/OpenRGB/OpenRGB.json ~/.config/OpenRGB/OpenRGB.json.bak-20261127
```

Then `Client.clients` was emptied in `~/.config/OpenRGB/OpenRGB.json`:

```json
"Client": {
    "clients": []
},
```

```bash
systemctl --user start 'app-OpenRGB@autostart.service'
```

Rollback: restore `OpenRGB.json.bak-20261127` and recreate the `.disabled` file if the old behaviour is ever needed.

## Verification

One process, one unit:

```
$ ps -eo pid,etime,cmd | grep -i openrgb | grep -v grep
  10781       00:12 /usr/local/bin/openrgb --startminimized

$ systemctl --user list-units --all | grep -i openrgb
  app-OpenRGB@autostart.service   loaded   active   running   OpenRGB

$ ls ~/.config/autostart/
OpenRGB.desktop  remmina-applet.desktop
```

The `xdg-desktop-autostart.target.wants` symlink for the deleted unit disappeared after `daemon-reload`; only `app-OpenRGB@autostart.service` remains.

The config edit survived the restart:

```
$ python3 -c "import json; print(json.load(open('/home/moo/.config/OpenRGB/OpenRGB.json'))['Client'])"
{'clients': []}
```

The new log (`OpenRGB_20261127_124848.log`) had exactly one connection attempt at `[5ms]` and nothing after it for the next 40 seconds, where the old log had one every 10 seconds. Device detection completed normally and registered the motherboard RGB controller.

## Gotchas

1. Do not disable an XDG autostart entry by renaming it on systemd 258. Use `Hidden=true`, move it out of `~/.config/autostart/`, or `systemctl --user mask <unit>`.
2. Every regular file in `~/.config/autostart/` becomes a unit, so editor backups (`*.bak`, `*~`) and renamed files all launch. Keep the directory clean.
3. Hand-editing `OpenRGB.desktop` does not stick while OpenRGB's own autostart is enabled, because OpenRGB rewrites the file from its settings. Pass the arguments through `--autostart-enable <args>` (or set `AutoStart.custom_arguments`) instead.
4. Stop OpenRGB before editing `OpenRGB.json`, or the exit-time save overwrites the change.
5. Two instances started in the same second share one log file, which makes the log look corrupted.

## Not verified

- The next login was not observed, since no reboot was performed. The reasoning is one file to one unit, but that is not an empirical result yet.
- The single `Connection attempt failed` at 5 ms after startup is unexplained. It does not repeat, so it is not the old 10-second loop.
- Whether any external workflow depended on the `127.0.0.1:6742` client entry. Nothing was listening on 6742, so there was nothing to connect to.

## Time estimate

Measured: the fix plus verification ran from `12:48:47` (service start) to `12:49:29` (clean log confirmed), about 42 seconds of wall clock. Investigation, including the generator probe and reading the systemd source, was roughly 10 minutes of command round trips (estimate, not measured). Total session about 15 minutes.

## References

- [systemd v258 `xdg-autostart-generator.c`](https://raw.githubusercontent.com/systemd/systemd/v258/src/xdg-autostart-generator/xdg-autostart-generator.c) — the `enumerate_xdg_autostart` loop and its `S_ISREG`-only filter.
- [systemd-xdg-autostart-generator man page](https://www.freedesktop.org/software/systemd/man/latest/systemd-xdg-autostart-generator.html) — `Hidden=`, `X-systemd-skip=`, and the other processed keys.
