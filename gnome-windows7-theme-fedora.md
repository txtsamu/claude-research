---
type: how-to
tags: [gnome, gnome-shell, theming, fedora, wayland]
created: 2026-07-17
last_verified: 2026-07-20
status: current
---

# Theming Fedora GNOME to Look Like Windows 7

**Date:** 2026-07-17
**Stack:** Fedora Linux 43 (Workstation Edition), GNOME Shell 49.8, Wayland session

---

## 1. Reality check before starting

GNOME 4x actively resists this kind of theming. Modern GNOME apps (Files, Settings, and most default apps) use **libadwaita**, which hard-ignores GTK theme CSS by design — no theme, however good, restyles them. A "full Windows 7 desktop" isn't achievable on current GNOME. What *is* achievable:

- GTK theme → restyles older/non-libadwaita GTK3 (and some GTK4) apps
- Icon theme → works broadly, not blocked by libadwaita
- Cursor theme → works everywhere
- Taskbar / Start menu feel → via GNOME Shell extensions (Dash to Panel, ArcMenu), not a theme

None of the steps below need root except installing two small helper packages. Themes/icons/cursors/extensions all install per-user under `~`, which keeps blast radius small and is trivially reversible (`rm` the dirs, reset the `gsettings` keys).

---

## 2. Install helper packages

```bash
sudo dnf install -y gnome-tweaks gnome-extensions-app unzip
```

`gnome-tweaks` and `unzip` were already on this box; only `gnome-extensions-app` (Extensions manager GUI) needed installing.

---

## 3. Install the GTK/WM theme

[B00merang-Project/Windows-7](https://github.com/B00merang-Project/Windows-7) — GTK2/GTK3/GTK4 theme matching Windows 7's Aero look. Unmaintained since ~2018 but still functional for GTK3 apps.

```bash
mkdir -p ~/.themes ~/.icons

curl -sL -o Windows-7-gtk.zip \
  https://github.com/B00merang-Project/Windows-7/archive/refs/heads/master.zip
unzip -q Windows-7-gtk.zip
cp -r Windows-7-master ~/.themes/Windows-7
```

Confirm it shipped `gtk-2.0/`, `gtk-3.0/`, `gtk-4.0/`, `gnome-shell/`, and `metacity-1/` subfolders — the `gnome-shell/` folder is what the User Themes extension (step 6) picks up for shell chrome.

---

## 4. Install the icon theme

[B00merang-Artwork/Windows-7](https://github.com/B00merang-Artwork/Windows-7) — companion icon set, separate repo from the GTK theme.

```bash
curl -sL -o Windows-7-icons.zip \
  https://github.com/B00merang-Artwork/Windows-7/archive/refs/heads/master.zip

# both repos extract to the same top-level dir name ("Windows-7-master") —
# unzip into a scratch subdir first to avoid clobbering the GTK theme extract
mkdir icons-extract && cd icons-extract
unzip -q ../Windows-7-icons.zip
cd ..

cp -r icons-extract/Windows-7-master ~/.icons/Windows-7
```

---

## 5. Install a Windows 7 Aero cursor theme

Used [yeyushengfan258/Win7OS-cursors](https://github.com/yeyushengfan258/Win7OS-cursors) (actively maintained by a known GNOME theme author) over the older `lLexian/Windows-7-Aero-Cursors_Linux`, which looked stale.

**Gotcha:** the repo's default branch is `master`, not `main` — `archive/refs/heads/main.zip` 404s silently into a `404: Not Found` text file that `unzip` then chokes on. Check the actual default branch (`git ls-remote --symref <url> HEAD` or just look at the GitHub UI) before assuming.

```bash
curl -sL -o Win7OS-cursors.zip \
  https://github.com/yeyushengfan258/Win7OS-cursors/archive/refs/heads/master.zip
unzip -q Win7OS-cursors.zip
cd Win7OS-cursors-master
```

The repo ships a precompiled theme under `dist/` and an `install.sh` that branches on `$UID`:

```bash
# install.sh excerpt
if [ "$UID" -eq 0 ]; then
  DEST_DIR="/usr/share/icons"        # system-wide, root
else
  DEST_DIR="$HOME/.local/share/icons" # per-user
fi
cp -pr dist "$DEST_DIR/Win7OS-cursors"
```

Ran it as the normal user (no `sudo`) so it installed to `~/.local/share/icons/Win7OS-cursors` — no need for root here.

```bash
bash install.sh
```

---

## 6. Install GNOME Shell extensions without a browser

A real Windows-7-style taskbar and Start menu need extensions, normally installed by clicking "Install" on extensions.gnome.org in a browser with the GNOME Shell integration add-on. Did it headlessly instead using the site's JSON API + `gnome-extensions install`.

Extensions used:

| Extension | UUID | Purpose |
|---|---|---|
| User Themes | `user-theme@gnome-shell-extensions.gcampax.github.com` | Lets the shell load a theme from `~/.themes` for its own chrome (top bar, etc.) |
| Dash to Panel | `dash-to-panel@jderose9.github.com` | Merges dash + top bar into a Windows/KDE-style taskbar |
| ArcMenu | `arcmenu@arcmenu.com` | Configurable Start-menu replacement |

**Find the extension's numeric `pk` and confirm shell-version compatibility:**

```bash
curl -s "https://extensions.gnome.org/extension-query/?search=dash%20to%20panel"
```

Look for the `uuid`/`pk` pair, then check the `shell_version_map` includes your `gnome-shell --version` (here: `49`).

**Get the versioned download URL for your shell version:**

```bash
curl -s "https://extensions.gnome.org/extension-info/?pk=1160&shell_version=49"
```

**Gotcha:** some extensions' descriptions contain literal, unescaped control characters (raw `\n`), which breaks strict `json.loads` / `python3 -m json.tool` with `Invalid control character` or `Unterminated string` errors. Don't fight the parser — grep the field out directly instead:

```bash
grep -oE '"download_url": "[^"]*"' response.json
```

**Download and install:**

```bash
curl -sL -o dash-to-panel.zip \
  "https://extensions.gnome.org/download-extension/dash-to-panel@jderose9.github.com.shell-extension.zip?version_tag=69173"

gnome-extensions install --force dash-to-panel.zip
```

Repeated for all three UUIDs/pks (`user-theme` pk 19, `dash-to-panel` pk 1160, `arcmenu` pk 3628).

---

## 7. Apply everything with `gsettings`

GTK theme, icon theme, cursor theme, and window-manager theme take effect **immediately**, no restart:

```bash
gsettings set org.gnome.desktop.interface gtk-theme 'Windows-7'
gsettings set org.gnome.desktop.interface icon-theme 'Windows-7'
gsettings set org.gnome.desktop.interface cursor-theme 'Win7OS-cursors'
gsettings set org.gnome.desktop.wm.preferences theme 'Windows-7'
```

Enable the shell extensions (this key controls what loads on next shell start/login):

```bash
gsettings set org.gnome.shell enabled-extensions \
  "['background-logo@fedorahosted.org', 'user-theme@gnome-shell-extensions.gcampax.github.com', 'dash-to-panel@jderose9.github.com', 'arcmenu@arcmenu.com']"
```

`background-logo@fedorahosted.org` was already enabled (Fedora's default distro-logo extension) — included it in the list rather than overwriting it, since `gsettings set` on this key replaces the whole array.

Set the shell theme for the User Themes extension specifically — its schema isn't installed globally until the extension is actually loaded by the shell, so point `gsettings` at the extension's own schema dir:

```bash
gsettings --schemadir ~/.local/share/gnome-shell/extensions/user-theme@gnome-shell-extensions.gcampax.github.com/schemas \
  set org.gnome.shell.extensions.user-theme name 'Windows-7'
```

---

## 8. Fix ArcMenu's default layout — it doesn't look like Windows 7 out of the box

Enabling ArcMenu alone gets you the extension's **own** default "Arc Menu" layout: a single flat column (pinned apps, then places, then Software/Settings/Tweaks, then "All Apps" + search at the bottom). That's ArcMenu's native look, not a Windows 7 Start Menu — easy to miss since it still *looks* like a plausible Linux start menu at a glance.

ArcMenu ships several built-in layout presets, one of which is a literal Windows-7-style two-pane layout. List them and check the current value:

```bash
gsettings --schemadir ~/.local/share/gnome-shell/extensions/arcmenu@arcmenu.com/schemas \
  range org.gnome.shell.extensions.arcmenu menu-layout
```

```
enum
'11', 'arcmenu', 'az', 'brisk', 'budgie', 'chromebook', 'elementary', 'enterprise',
'gnome-menu', 'gnome-overview', 'insider', 'mint', 'plasma', 'pop', 'raven', 'redmond',
'runner', 'sleek', 'tognee', 'unity', 'whisker', 'windows', 'zest'
```

`'redmond'` mimics Windows 10/11; `'windows'` is the one that mimics Windows 7/XP specifically — pinned/frequent apps on the left, Computer/Documents/Pictures/Control Panel/shut-down on the right, search box along the bottom. Switch to it:

```bash
gsettings --schemadir ~/.local/share/gnome-shell/extensions/arcmenu@arcmenu.com/schemas \
  set org.gnome.shell.extensions.arcmenu menu-layout 'windows'
```

Applies live — no shell reload needed, just close and reopen the Start menu. All per-extension `gsettings` keys like this live under the extension's own schema dir, so `--schemadir` is required; there's no globally-registered `org.gnome.shell.extensions.arcmenu` schema until you point at it explicitly (same pattern as the User Themes key in step 7).

**Left as-is:** the Start button icon is ArcMenu's own logo, not a Windows orb — ArcMenu doesn't bundle a Windows-branded icon asset (avoids the trademark; confirmed by `find ~/.local/share/gnome-shell/extensions/arcmenu@arcmenu.com -iname '*win*'`, which only turned up layout code, no icon assets). To get an actual orb, `menu-button-icon` (a plain string key, same schema) accepts a path to any local image file — point it at a downloaded icon if you want one.

---

## 9. Gotcha: extensions don't hot-load on Wayland

`gnome-extensions install` just unpacks the zip to `~/.local/share/gnome-shell/extensions/<uuid>/` — it's a pure file operation and does **not** register the extension with the already-running shell process. On X11 you can force a reload with `Alt+F2` → `r`. **On Wayland there is no in-place shell restart** — confirmed this by finding `org.gnome.Shell.Extensions` on the session D-Bus (`busctl --user list | grep -i extensions`) had no live PID, only `(activatable)`, and `gnome-extensions list` kept omitting the newly-installed UUIDs even minutes after install.

The fix isn't a command — it's logging out and back in. Setting `enabled-extensions` via `gsettings` ahead of time (step 7) means the extensions activate automatically the moment the shell reloads, with no further action needed at login.

---

## 10. What's live immediately vs. what needs logout

| Change | When it applies |
|---|---|
| GTK theme, icon theme, cursor theme, WM theme | Immediately |
| Dash to Panel (taskbar), ArcMenu (Start menu), shell chrome via User Themes | After next login (Wayland has no live shell restart) |
| ArcMenu layout preset / icon / any other ArcMenu `gsettings` key | Immediately, once ArcMenu itself is loaded |

## 11. Known limitations

- libadwaita apps (Files, Settings, Text Editor, etc.) are not restyled — GNOME blocks this at the toolkit level, no extension or theme works around it.
- All three theme/icon/cursor source repos are third-party and largely unmaintained (B00merang since ~2018); expect visual glitches in newer apps and no upstream bug fixes.
- `Windows-7`, `Windows-7` (icons), and `Win7OS-cursors` are unsigned community projects pulled directly from GitHub archive zips, not distro packages — no integrity/signature verification beyond GitHub's own TLS.

---

## 12. Reverting back to stock GNOME

Per-user install locations mean this is a clean, low-risk `rm` + `gsettings` operation — no root, no package removal needed (the two `dnf`-installed helper packages, `gnome-tweaks` and `gnome-extensions-app`, are harmless to leave in place).

**Reset the interface/theme keys** (this resets each key to its schema default, e.g. back to `'Adwaita'`, rather than hardcoding the value — more robust if the distro default ever changes):

```bash
gsettings reset org.gnome.desktop.interface gtk-theme
gsettings reset org.gnome.desktop.interface icon-theme
gsettings reset org.gnome.desktop.interface cursor-theme
gsettings reset org.gnome.desktop.wm.preferences theme
```

**Disable the three added extensions**, keeping whatever was enabled before (here, just Fedora's own `background-logo@fedorahosted.org`):

```bash
gsettings set org.gnome.shell enabled-extensions "['background-logo@fedorahosted.org']"
```

**Remove the installed theme/icon/cursor/extension files:**

```bash
rm -rf ~/.themes/Windows-7
rm -rf ~/.icons/Windows-7
rm -rf ~/.local/share/icons/Win7OS-cursors
rm -rf ~/.local/share/gnome-shell/extensions/arcmenu@arcmenu.com
rm -rf ~/.local/share/gnome-shell/extensions/dash-to-panel@jderose9.github.com
rm -rf ~/.local/share/gnome-shell/extensions/user-theme@gnome-shell-extensions.gcampax.github.com
```

Same Wayland caveat as step 9, in reverse: the GTK/icon/cursor reset takes effect immediately, but the taskbar/Start-menu chrome from the shell extensions won't fully disappear from the *running* session until you log out and back in — the shell only re-reads `enabled-extensions` at load time.
