---
type: how-to
tags: [cosmic, cosmic-de, fedora, gdm, desktop-environment]
created: 2026-07-23
last_verified: 2026-07-23
status: current
---

# Installing COSMIC Desktop on Fedora 43 (Workstation)

**Date:** 2026-07-23
**Stack:** Fedora Linux 43 (Workstation Edition), GNOME 49 default session, GDM display manager

---

## 1. Context / request

User asked to switch their "current desktop environment to COSMIC DE from Pop!_OS." The box is actually **Fedora 43**, not Pop!_OS — COSMIC is developed by System76 for Pop!_OS but is also packaged upstream for Fedora as of Fedora 42/43. Confirmed with the user they wanted COSMIC installed on the existing Fedora system (not a distro switch), keeping GNOME as a fallback.

## 2. Pre-check

```bash
cat /etc/os-release        # Fedora Linux 43 (Workstation Edition)
echo $XDG_CURRENT_DESKTOP  # GNOME
which cosmic-session       # not found — not yet installed
```

## 3. Find the correct package group

Some install guides reference a group name `cosmic-desktop-environment`, which does **not** exist on Fedora 43. The real group name is `cosmic-desktop`:

```bash
dnf group list | grep -i cosmic
# cosmic-desktop              COSMIC Desktop                   no
# cosmic-desktop-apps         COSMIC Desktop Supplementary Applications  no
```

## 4. Install

```bash
sudo dnf group install -y cosmic-desktop
```

Pulled in 86 packages (~1.3.0release), including:
- `cosmic-session`, `cosmic-comp` (Wayland compositor), `cosmic-settings`, `cosmic-settings-daemon`
- `cosmic-files`, `cosmic-store`, `cosmic-term`, `cosmic-edit`, `cosmic-player`
- `cosmic-panel`, `cosmic-applets`, `cosmic-app-library`, `cosmic-launcher`, `cosmic-osd`, `cosmic-notifications`
- `cosmic-greeter` (COSMIC's own login greeter, installed but **not** enabled)
- KDE Frameworks 5/6 libs pulled in as deps (`kf5-*`, `kf6-*`) for Qt-based COSMIC components
- `greetd` + `greetd-selinux` (backing service for `cosmic-greeter`, not activated)

One benign scriptlet warning during install:
```
Failed to preset unit: File '/etc/systemd/system/display-manager.service' already exists
```
This just means GDM was already the active/enabled display manager, so the packaging didn't override it — expected and desired, since we want GDM to keep offering both sessions rather than switching greeters.

## 5. Verify the session is registered

```bash
ls /usr/share/wayland-sessions/
# cosmic.desktop  gnome.desktop  gnome-wayland.desktop  gnome-classic.desktop  gnome-classic-wayland.desktop

readlink -f /etc/systemd/system/display-manager.service
# /usr/lib/systemd/system/gdm.service

systemctl is-enabled gdm cosmic-greeter
# gdm: enabled
# cosmic-greeter: disabled
```

`cosmic.desktop` now shows up alongside the GNOME variants. GDM stayed the display manager, so no login-screen behavior changed — the new session is just an additional option in the picker.

## 6. How to actually switch

1. Log out of the current GNOME session.
2. On the GDM login screen, click the username, then the gear icon near the password field.
3. Select **COSMIC** from the session dropdown.
4. Log in.

GNOME remains fully installed and selectable the same way, so this is trivially reversible — just pick GNOME again next login. Nothing was removed.

## 7. Not done (optional follow-up)

Switching the greeter itself from GDM to `cosmic-greeter` (COSMIC's native login screen) was **not** performed — user only asked to add the COSMIC session, not replace the display manager. If wanted later:

```bash
sudo systemctl disable gdm
sudo systemctl enable cosmic-greeter
```

This is a bigger blast-radius change (affects login for all users/sessions) and should get its own explicit confirmation before doing it.

## Sources

- [How to Install COSMIC Desktop in Fedora Linux (Workstation)](https://www.debugpoint.com/install-cosmic-desktop-fedora/)
- [Changes/FedoraCOSMIC - Fedora Project Wiki](https://fedoraproject.org/wiki/Changes/FedoraCOSMIC)
