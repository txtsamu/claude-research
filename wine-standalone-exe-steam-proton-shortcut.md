---
type: how-to
tags: [wine, wine-wow64, fedora, proton, steam, non-steam-game, pulseaudio, alsa, mmdevapi, gaming, python-vdf]
created: 2026-09-08
last_verified: 2026-09-08
status: current
---

# Running a standalone (pre-extracted) Windows .exe game on Fedora: Wine launch, diagnosing silent audio loss, and adding it to Steam as a Proton shortcut

## Context

Had a Windows game already unpacked to a plain directory (no installer — just `Game.exe`, its DLLs, and data files sitting there, e.g. from a backup/torrent extraction). Goal: get it running on Fedora 43 (KDE/Wayland via COSMIC, X11 via XWayland, `DISPLAY=:1`), with sound.

General shape of this recipe: (1) sanity-check the exe and Wine's 32-bit prereqs, (2) launch and confirm the window renders, (3) if audio is silent, diagnose with `WINEDEBUG`, (4) fix — either a system Wine symlink fix, or sidestep the whole system-Wine stack by launching through Steam's bundled Proton via a hand-added non-Steam shortcut.

## Step 1 — Confirm it's a Wine target and check prereqs

```sh
file Game.exe
# PE32 executable for MS Windows 5.00 (GUI), Intel i386, 4 sections   <- 32-bit, needs Wine

wine --version                      # wine-11.0 (Staging) here
which wine wine64 protontricks lutris innoextract steam
```

Per the game's own Linux notes (when it has any — this one pointed at `WINE.md` in its upstream repo), the two things worth checking on Fedora before even launching:

```sh
rpm -qa --qf '%{NAME}.%{ARCH}\n' | grep -iE 'mesa-libGL\.i686|vulkan-loader\.i686'
# want both mesa-libGL.i686 and vulkan-loader.i686 present (Fedora's equivalent of
# Debian's libgl1:i386 / libvulkan1:i386) — install with:
#   sudo dnf install mesa-libGL.i686 vulkan-loader.i686
```

## Step 2 — Launch and confirm the window actually renders

Run it backgrounded so the tool call doesn't block, capture full output to a log, track the PID numerically (see the pitfall below about `pkill -f` before you reach for it):

```sh
cd "/path/to/Game Directory"
DISPLAY=:1 wine Game.exe > /tmp/wine.log 2>&1 &
WINEPID=$!
sleep 6
pgrep -af 'Game\.exe' | grep -v bash     # confirm the wine process is actually up
DISPLAY=:1 wmctrl -l                     # confirm a window titled after the game exists
```

If the window shows up in `wmctrl -l`, video/input is fine — move on. Ignore `fixme:`/`err:mmdevapi` noise in the log at this stage unless there's literally no sound.

**Pitfall:** don't `pkill -f Game.exe` to clean up — if your shell command line itself contains the literal string `Game.exe` (e.g. because you're echoing the path), `pkill -f` matches *your own invoking shell* too and kills the command that's running it. Kill by the numeric `$WINEPID` instead: `kill "$WINEPID"`.

## Step 3 — No sound: diagnose with WINEDEBUG

```sh
DISPLAY=:1 WINEDEBUG=+pulse,+alsa,+mmdevapi,warn+module wine Game.exe > /tmp/wine_debug.log 2>&1 &
WINEPID=$!; sleep 5; kill "$WINEPID"

grep -iE 'pulse|alsa|mmdevapi|driver' /tmp/wine_debug.log | grep -vi winediag
```

Symptom seen here:

```
mmdevapi:load_driver Unable to load L"winepulse.drv": 126
mmdevapi:load_driver Unable to load L"winealsa.drv": 126
mmdevapi:init_driver No driver from L"pulse,alsa,oss,coreaudio" could be initialized.
module:load_dll Failed to load module L"winepulse.drv"; status=c0000135   # STATUS_DLL_NOT_FOUND
```

Before assuming it's a config problem, rule out the audio server itself:

```sh
pactl info            # confirms PipeWire/pulse socket is reachable at all
aplay -l               # confirms ALSA sees real hardware
rpm -qa --qf '%{NAME}.%{ARCH}\n' | grep -iE '^(pulseaudio-libs|alsa-lib|pipewire-libs|pipewire-alsa)\.'
# want the .i686 variant of each installed too, not just .x86_64
```

If those are all fine but Wine still can't load its own driver modules, it's Wine's own file layout that's broken, not the host audio stack.

## Root cause found: Fedora's wine-wow64 lib vs lib64 split

Fedora 43 packages Wine 11 (wine-wow64 architecture) so the bulk of the 32-bit Windows-side DLLs come from `wine-core.x86_64` and land under:

```
/usr/lib64/wine-wow64/wine/i386-windows/     (818 files — kernel32, d3d9, etc.)
```

...but the separate `wine-pulseaudio.i686` and `wine-alsa.i686` subpackages (which is where `winepulse.drv`/`winealsa.drv` actually live) install to the **32-bit-arch multilib path** instead:

```
/usr/lib/wine-wow64/wine/i386-windows/       (only 2 files: winepulse.drv, winealsa.drv)
/usr/lib/wine-wow64/wine/i386-unix/          (their .so unixlib companions)
```

The `wine64` binary only searches `/usr/lib64/...` for this build, so the audio drivers are simply invisible to it — silent, total audio loss, while everything else (video, input) works fine because those DLLs *do* live under `/usr/lib64`. Confirmed via:

```sh
rpm -qf /usr/lib/wine-wow64/wine/i386-windows/winepulse.drv
# wine-pulseaudio-11.0-2.fc43.i686
ls /usr/lib64/wine-wow64/wine/i386-windows/*.drv     # winepulse.drv / winealsa.drv absent here
ls /usr/lib64/wine-wow64/wine/i386-unix/ 2>&1         # directory doesn't even exist
```

Also checked and ruled out along the way (kept here since they're the standard suspects and worth ruling out fast next time): `wineboot -u` (doesn't repopulate these — they were never prefix-copied in the first place, that's normal), SELinux AVC denials (`getenforce` was `Enforcing` but `sudo -n ausearch -m avc -ts recent` showed nothing), and `HKCU\Software\Wine\Drivers` / `DllOverrides` registry overrides (none set).

### Fix A — symlink the driver files into the path Wine actually searches (system-wide fix)

```sh
sudo mkdir -p /usr/lib64/wine-wow64/wine/i386-unix
sudo ln -s /usr/lib/wine-wow64/wine/i386-windows/winepulse.drv /usr/lib64/wine-wow64/wine/i386-windows/winepulse.drv
sudo ln -s /usr/lib/wine-wow64/wine/i386-windows/winealsa.drv  /usr/lib64/wine-wow64/wine/i386-windows/winealsa.drv
sudo ln -s /usr/lib/wine-wow64/wine/i386-unix/winepulse.so     /usr/lib64/wine-wow64/wine/i386-unix/winepulse.so
sudo ln -s /usr/lib/wine-wow64/wine/i386-unix/winealsa.so      /usr/lib64/wine-wow64/wine/i386-unix/winealsa.so
```

Fixes audio for every 32-bit Wine app using the system Wine install, not just one game. Reversible (`sudo rm` the four symlinks). Not yet reported upstream as a Fedora bug as of this writeup — worth filing if it's still present after a Wine package update.

### Fix B — sidestep it entirely: run through Steam's bundled Proton instead

Proton ships its own complete, correctly-pathed Wine build, unaffected by the distro packaging split above. No `sudo` needed. Chosen over Fix A in this session (user preference — "Both" was offered too).

**Add it as a non-Steam shortcut without touching the Steam GUI, safely:**

Steam's `shortcuts.vdf` is a binary VDF. Don't hand-roll the binary format — use the `vdf` Python package (well-tested, round-trips cleanly) in a throwaway venv so nothing gets installed system-wide:

```sh
python3 -m venv /tmp/vdfenv
/tmp/vdfenv/bin/pip install vdf
```

Find the right Steam install and userdata folder first — check *both* if native and Flatpak Steam are installed, and go with whichever `shortcuts.vdf` was modified more recently (i.e. actually in use):

```sh
ls ~/.local/share/Steam/userdata/*/config/shortcuts.vdf
ls ~/.var/app/com.valvesoftware.Steam/.local/share/Steam/userdata/*/config/shortcuts.vdf
stat --format '%Y %n' ~/.local/share/Steam/userdata/*/config/shortcuts.vdf \
                       ~/.var/app/com.valvesoftware.Steam/.local/share/Steam/userdata/*/config/shortcuts.vdf
```

**Always back up before writing:**

```sh
cp ~/.local/share/Steam/userdata/<id>/config/shortcuts.vdf /tmp/shortcuts.vdf.bak
```

Read the existing file first (don't guess the schema — copy the shape of whatever real entry is already in there, e.g. an existing non-Steam game the user added by hand through the GUI) then append a new entry and write back:

```python
import vdf, collections

path = '/home/USER/.local/share/Steam/userdata/<id>/config/shortcuts.vdf'
with open(path, 'rb') as f:
    d = vdf.binary_load(f, mapper=collections.OrderedDict)

shortcuts = d['shortcuts']
next_idx = str(max((int(k) for k in shortcuts.keys()), default=-1) + 1)

game_dir = '/absolute/path/to/Game Directory'
exe_path = game_dir + '/Game.exe'

shortcuts[next_idx] = collections.OrderedDict([
    ('appid', -1590212000),                 # any unique int32 — see note below
    ('AppName', 'Display Name'),
    ('Exe', '"' + exe_path + '"'),          # literal quotes ARE part of the stored string
    ('StartDir', game_dir + '/'),           # NOT quoted, trailing slash
    ('icon', ''), ('ShortcutPath', ''), ('LaunchOptions', ''),
    ('IsHidden', 0), ('AllowDesktopConfig', 1), ('AllowOverlay', 1),
    ('OpenVR', 0), ('Devkit', 0), ('DevkitGameID', ''), ('DevkitOverrideAppID', 0),
    ('LastPlayTime', 0), ('FlatpakAppID', ''), ('sortas', ''),
    ('tags', collections.OrderedDict()),
])

with open(path, 'wb') as f:
    vdf.binary_dump(d, f)
```

Verify by reading it back before trusting it:

```python
import vdf, json
with open(path, 'rb') as f:
    print(json.dumps(vdf.binary_load(f), indent=2, default=str))
```

**Note on `appid`:** Steam's "real" non-Steam-game id is a specific CRC32 of `exe + AppName`, OR'd with `0x80000000`, then stored signed. I tried to reverse it from an existing entry to also pre-populate `config.vdf`'s `CompatToolMapping` (so the Proton version would already be set) — my reimplementation didn't match Steam's actual stored id for the existing entry, so I didn't trust it enough to write into `CompatToolMapping` blind (a wrong key there is just a harmless orphaned entry, but not worth the risk of writing unverified data into a file with unrelated existing config). **Any unique int works fine for the `appid` field in `shortcuts.vdf` itself** — the game shows up and launches regardless. What you lose by not matching Steam's exact algorithm is auto-fetched grid art and not being able to pre-set the Proton version from outside Steam — not a blocker, just means one manual step:

1. Launch Steam, **Library → Non-Steam Games** — the new entry shows up immediately (no restart needed, or restart Steam if it doesn't).
2. Right-click → **Properties → Compatibility** → check **"Force the use of a specific Steam Play compatibility tool"** → pick a Proton version.
3. **Play.**

## Notes on secrets

No real secrets in this doc's originals — home directory paths use a placeholder `USER`/generic paths above; nothing here is a credential, hostname, or public IP per the repo's [secrets policy](README.md#secrets-policy).
