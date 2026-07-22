---
type: how-to
tags: [cosmic, cosmic-de, fedora, gdm, desktop-environment, gnome-removal]
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

---

## Part 2: switching the default session + fully removing GNOME (2026-07-23, same day)

Follow-up request: make COSMIC the actual default (not just an option next to GNOME in GDM), and safely `dnf remove` GNOME entirely — "safely" meaning don't break shared system infrastructure that COSMIC or other apps still rely on.

### Investigation before touching anything

Checked what the `gnome-desktop` dnf environment group actually declares as mandatory:

```bash
dnf group info gnome-desktop
```

Mandatory packages included `polkit` alongside `gdm`, `gnome-shell`, `nautilus`, `gnome-control-center`, etc. **`polkit` mandatory in the GNOME group does not mean it's GNOME-specific** — a blind `dnf group remove gnome-desktop` would be dangerous. Verified via reverse-dependency queries before removing anything:

```bash
dnf repoquery --installed --whatrequires polkit
# accountsservice, cockpit-packagekit, cosmic-initial-setup, dnf5daemon-server,
# gnome-initial-setup, gnome-shell, gvfs, libvirt-daemon-common, libvirt-dbus,
# malcontent, mediawriter, ModemManager, pcsc-lite, polkit-pkla-compat, realmd,
# rtkit, tuned, udisks2
```
`polkit` is required by core system services (udisks2, libvirt, ModemManager, even COSMIC's own `cosmic-initial-setup`) — **must never be removed**. dnf's solver protects packages still required elsewhere, but better to know this up front than trust that blindly.

Also checked, and confirmed **must keep** (all still required by things unrelated to gnome-shell, including COSMIC itself):

```bash
dnf repoquery --installed --whatrequires gnome-keyring   # NetworkManager-vpnc-gnome, gnome-keyring-pam
dnf repoquery --installed --whatrequires gvfs             # cosmic-files itself requires gvfs!
dnf repoquery --installed --whatrequires gsettings-desktop-schemas  # huge list, used by non-GNOME GTK apps too
```

Web research confirmed the same conclusion independently: COSMIC has no keyring of its own and relies on `gnome-keyring` for saved passwords/SSH keys, and needs `gvfs` for network-share mounting in Cosmic Files. COSMIC does ship its own portal (`xdg-desktop-portal-cosmic`), so `xdg-desktop-portal-gnome` specifically (not the shared `-gtk`/common portal packages) is a safe removal candidate, though it wasn't in the actual removal set below since it wasn't a hard dependency of gnome-shell/gdm.

### Dry-run the actual removal before running it for real

`gnome-shell` turned out to be a **protected package** — `dnf remove gnome-shell gdm` refused outright:
```
Problem: The operation would result in removing the following protected packages: gnome-shell
```

Traced the protection to a file, not a hardcoded dnf rule:
```bash
rpm -qf /etc/dnf/protected.d/fedora-workstation.conf
# fedora-release-identity-workstation-43-27.noarch
cat /etc/dnf/protected.d/fedora-workstation.conf
# NetworkManager
# gnome-shell
```
So Fedora Workstation's identity package is what pins `gnome-shell` (and `NetworkManager`, untouched here) against removal. Fedora ships a proper first-class fix for this since COSMIC became an official spin: an identity package to swap to.

```bash
dnf repoquery --qf '%{name}' 'fedora-release-identity-*'
# ...fedora-release-identity-cosmic, fedora-release-identity-cosmic-atomic, ...
```

Dry-ran the identity swap (`--assumeno`, nothing committed):
```bash
dnf swap fedora-release-identity-workstation fedora-release-identity-cosmic --assumeno
```
Small, low-risk transaction: removes/installs two ~2KB identity packages, downgrades `fedora-release-common` and `fedora-release-workstation` by two build numbers (43-27 → 43-25, pure branding/config metapackages, no functional impact). This is the officially-supported way to re-identify the box as a COSMIC install and lift the gnome-shell protection.

Then previewed the *actual* GNOME removal cascade without committing to the identity swap yet, by temporarily bypassing the protection list for the dry run only:
```bash
dnf remove gnome-shell gdm --setopt=protected_packages= --assumeno
```
Result: clean 24-package removal —
`gdm`, `gnome-shell`, `gnome-browser-connector`, `gnome-classic-session`, `gnome-initial-setup`,
`gnome-session-wayland-session`, `gnome-shell-extension-{appindicator,background-logo,apps-menu,common,launch-new-instance,places-menu,window-list}`,
`system-config-printer`, `gcr`, `gnome-session`, `gnome-shell-common`, `python3-pam`,
`qt6-qtwayland(-adwaita-decoration)`, `xmodmap`, `xorg-x11-xauth`, `xorg-x11-xinit`, `xrdb`.

Notably `gdm` itself `Requires: gnome-shell` on Fedora (GDM embeds gnome-shell to render its own greeter), which is *why* removing gnome-shell forces gdm out too — this lines up exactly with wanting `cosmic-greeter` as the replacement login manager anyway.

One side-effect worth flagging to the user: `system-config-printer` (the printer-settings GUI) depends on gnome-shell and gets removed as a result. Printing itself (CUPS) is unaffected — only that particular GUI goes away (`localhost:631` or COSMIC's own settings remain as alternatives).

Confirmed **nothing shared gets touched**: no `polkit`, `gvfs`, `gnome-keyring`, `gsettings-desktop-schemas`, or `NetworkManager` in the removal list. Matches the reverse-dependency check above.

### Switching the display manager (done)

Before removing `gdm`, made `cosmic-greeter` the active display manager, so the box is never in a state with zero configured greeter. Checked `cosmic-greeter.service` first:
```ini
[Install]
Alias=display-manager.service
```
Confirmed backed by `greetd` (already installed) with a working `/etc/greetd/cosmic-greeter.toml`, and `cosmic.desktop` session file present.

**Mishap + immediate fix, worth remembering:** ran these in the wrong order —
```bash
sudo systemctl enable cosmic-greeter.service   # FAILED — symlink already existed → gdm.service
sudo systemctl disable gdm.service             # this REMOVED the display-manager.service symlink entirely
```
`enable` refuses to overwrite an existing `display-manager.service` symlink, but `disable gdm.service` unconditionally deletes it if it's the target — even though `cosmic-greeter` wasn't enabled yet. **Net result for a few seconds: no display manager configured at all** (a reboot in that window would have dropped to a text console with no GUI login). Caught immediately via `readlink -f`/`ls -la` on the symlink and fixed by re-running:
```bash
sudo systemctl enable cosmic-greeter.service
# Created symlink '/etc/systemd/system/display-manager.service' → '.../cosmic-greeter.service'
```
**Lesson for next time:** when switching display managers on systemd + Alias=display-manager.service units, always `enable <new>` *before* `disable <old>` isn't actually sufficient either (enable refuses if the symlink exists) — the safe sequence is `disable <old>` immediately followed, in the same breath, by `enable <new>`, with a verification `readlink` in between, never leaving a gap. Don't run these as two separately-reviewed steps.

Current state after Part 2 (as of this writeup): `cosmic-greeter` is the enabled/active-on-next-boot display manager; `gdm.service` is disabled but not removed and still running the *current* live session (nothing was restarted — the logged-in GNOME session was left untouched to avoid killing an active session, including the terminal this work was done from). `gnome-shell`/`gdm`/dependents are **not yet removed** — no package removal has happened yet.

### Deliberate checkpoint before removing packages

Chose not to run the actual `dnf remove` (or even restart `display-manager.service`) in the same session as enabling `cosmic-greeter`, because the single biggest real risk in the whole operation is discovering `cosmic-greeter` doesn't start cleanly *after* `gdm`/`gnome-shell` are already gone, with no fallback login path left. Asked the user to log out/reboot on their own first, confirm COSMIC's greeter + session actually work end to end (login screen renders, session picker defaults to COSMIC, panel/launcher/files/settings/terminal all load, network + a keyring-backed credential prompt work), and only then come back to run:

```bash
sudo dnf swap fedora-release-identity-workstation fedora-release-identity-cosmic
sudo dnf remove gnome-shell gdm
```

If the test fails, recovery is trivial and was already spelled out to the user: switch to a TTY (Ctrl+Alt+F3), and flip the symlink back —
```bash
sudo systemctl disable cosmic-greeter.service
sudo systemctl enable gdm.service
```
— since at that point nothing has actually been removed yet, this is fully reversible.

**Status: awaiting user's manual test of the COSMIC login before the package-removal step is executed.** This doc will get a Part 3 (or an update to this section) once that happens.

## Sources (Part 2)

- [Remove Gnome DE from Workstation edition — Fedora Discussion](https://discussion.fedoraproject.org/t/remove-gnome-de-from-workstation-edition/146355)
- [GNOME Keyring on COSMIC — Fedora Discussion](https://discussion.fedoraproject.org/t/gnome-keyring-on-cosmic/161243)
- [xdg-desktop-portal-cosmic — Fedora Packages](https://packages.fedoraproject.org/pkgs/xdg-desktop-portal-cosmic/)
