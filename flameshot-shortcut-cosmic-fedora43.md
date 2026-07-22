---
type: how-to
tags: [flameshot, screenshot, cosmic, keyboard-shortcuts, fedora]
created: 2026-07-23
last_verified: 2026-07-23
status: current
---

# Binding Flameshot to Alt+Shift+S on COSMIC (Fedora 43)

**Date:** 2026-07-23
**Stack:** Fedora Linux 43 (Workstation Edition), COSMIC desktop (post cosmic-greeter switch, see [cosmic-de-install-fedora43.md](cosmic-de-install-fedora43.md))

## 1. Context

Follow-up to the COSMIC migration doc. User is now actually running COSMIC day-to-day (`XDG_CURRENT_DESKTOP=COSMIC` confirmed live) and wants a global shortcut, **Alt+Shift+S**, to launch Flameshot's capture UI.

## 2. Pre-checks

```bash
rpm -q flameshot
# flameshot-13.3.0-5.fc43.x86_64 — already installed

echo "$XDG_CURRENT_DESKTOP"
# COSMIC
```

## 3. How COSMIC stores keyboard shortcuts

Unlike GNOME (dconf/gsettings), COSMIC keeps shortcuts in RON (Rust Object Notation) files under `cosmic-config`:

- Built-in defaults (read-only, ships with the package): `/usr/share/cosmic/com.system76.CosmicSettings.Shortcuts/v1/defaults`
- User overrides/custom shortcuts (created on first custom bind): `$HOME/.config/cosmic/com.system76.CosmicSettings.Shortcuts/v1/custom`

On this machine the `custom` file didn't exist yet — no custom shortcuts had been added before.

### Checked for a keybind conflict first

Read through `defaults` (~80 bindings) before choosing Alt+Shift+S. Nothing uses that exact combo — the closest neighbors are `Super+Alt+s` (`System(ScreenReader)`) and `Alt+Shift+Tab` (`System(WindowSwitcherPrevious)`), neither of which collides. Confirmed safe to bind.

## 4. Tried to find the exact custom-shortcut RON syntax to script this directly — inconclusive

Wanted to just write the `custom` file directly (faster, scriptable), so looked for the "spawn a command" action variant:

- Web search + DeepWiki page for `pop-os/cosmic-comp` keyboard actions: confirms shortcuts route through `cosmic_settings_config::shortcuts::action::Action`, but didn't expose the actual enum variants.
- `gh search code "enum Action" repo:pop-os/cosmic-comp` found `src/config/key_bindings.rs`, but that file only defines a wrapper (`Private` / `Shortcut`) around the real enum, which lives in the separate `cosmic-settings-config` crate.
- That crate isn't a standalone GitHub repo (`pop-os/cosmic-settings-config` 404s) and isn't published on docs.rs under the expected path (404 there too) — it's likely vendored inside the `cosmic-settings` monorepo under a path `gh search code` didn't surface.
- Tried `strings` on the installed `/usr/bin/cosmic-comp` binary looking for a literal `Spawn` token (serde-derived enum variant names are normally baked into release binaries as static strings) — the binary is a stripped release build; grepped through ~70KB of string output without a clean hit, too unreliable to trust as a source for exact RON syntax.

**Decision: don't hand-edit the RON file blindly.** A malformed custom-shortcut entry risks the settings daemon failing to parse the whole `custom` file (losing any future custom shortcuts, not just this one), for a config format that GitHub issues (`pop-os/cosmic-epoch#1209`, `#2481`) suggest has been finicky across versions. Used the supported GUI flow instead — `cosmic-settings` 1.3.0 on this box is a mature release, well past the alpha builds those bug reports were about.

## 5. What was actually done

Walked through the officially supported path in **COSMIC Settings**:

1. Settings → Input Devices → Keyboard → Keyboard Shortcuts
2. **Custom** section at the bottom → **Add shortcut**
3. Name: `Flameshot`
4. Command: `flameshot gui`
5. Keybind: pressed **Alt+Shift+S**
6. Saved

`flameshot gui` is the standard invocation for Flameshot's interactive region-capture + annotation UI (as opposed to `flameshot screen` for a full/immediate capture).

## 6. Status

**User-side action, not yet verified from the shell.** Once confirmed working, the plan is to `cat $HOME/.config/cosmic/com.system76.CosmicSettings.Shortcuts/v1/custom` and record the actual generated RON syntax here — that closes the gap from section 4 and gives a copy-pasteable reference for adding future custom shortcuts (to this machine or others) without going through the GUI again.

## Sources

- [Pop!_OS 24.04 LTS COSMIC Keyboard Shortcuts — System76 Support](https://system76.com/support/articles/pop-cosmic-keyboard-shortcuts)
- [Custom keyboard shortcuts don't work · Issue #2481 · pop-os/cosmic-epoch](https://github.com/pop-os/cosmic-epoch/issues/2481)
- [Cosmic Settings can no longer alter keyboard shortcuts · Issue #1209 · pop-os/cosmic-epoch](https://github.com/pop-os/cosmic-epoch/issues/1209)
- [Keyboard Actions and Shortcuts — pop-os/cosmic-comp (DeepWiki)](https://deepwiki.com/pop-os/cosmic-comp/6.2-keyboard-actions-and-shortcuts)
