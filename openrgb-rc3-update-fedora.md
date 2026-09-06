---
type: how-to
tags: [openrgb, fedora, rpm, versioning]
created: 2026-09-06
last_verified: 2026-09-06
status: current
---

# Updating OpenRGB on Fedora past a misleading version-string ordering

## Context

`openrgb` on the Fedora/COSMIC desktop box (see [[fedora-perf-audit-openrgb-i2c-dup-scan]] for the machine) was installed as a manually-downloaded, unsigned CI-built RPM (not from any enabled repo/COPR — `rpm -q --qf '%{VENDOR}...'` shows no real repo origin), at `1.0~rc2-3.20260126git74cbdcc.fc43` (Jan 26, 2026 git snapshot).

## Finding the latest build

OpenRGB doesn't have an official Fedora repo/COPR; upstream publishes CI-built RPMs straight from their own GitLab CI (`gitlab.com/CalcProgrammer1/OpenRGB`) via Codeberg releases. Latest at time of writing: **RC3 Hotfix 1** (`release_candidate_1.0rc3.1`, built 2026-08-23), `openrgb_1.0rc3.1_x86_64_f43_5e81e26.rpm`.

## The gotcha: `dnf upgrade` silently no-ops

```
$ sudo dnf upgrade -y openrgb_1.0rc3.1_x86_64_f43_5e81e26.rpm
Package "openrgb.x86_64" is already installed.
Nothing to do.
```

Not actually true — the new file is 7 months newer. The problem is upstream's own version string: the new RPM reports `Version: 0.9.2026^1.0rc3.1`, while the installed one is `1.0~rc2-3...`. RPM compares version segments left-to-right; the first segment `0` (new) sorts *below* `1` (installed), so `dnf`/`rpm` genuinely believe the new file is older, regardless of build date or content. Same epoch on both sides (`(none)`), so there's no epoch override to lean on either — this is a plain upstream packaging inconsistency between their own RC2 and RC3 tags, not anything wrong with the local install.

## Fix

Force the install past the version check, since the build date/commit confirm it really is newer:

```
sudo rpm -Uvh --force openrgb_1.0rc3.1_x86_64_f43_5e81e26.rpm
```

Cleanly replaced the old package (rpm's own "Cleaning up / removing" step handled the swap). Confirmed via `openrgb --version` — new commit `5e81e26` (2026-08-23), branch `rc3_hotfix`, vs. the old commit's Jan 26 build date.

## Note for later

There are separately-downloaded OpenRGB Effects/VisualMap plugin `.so` files (`~/Downloads/Archived/`) built against the old RC2 — worth checking they still load against RC3 (plugin ABI can break across RC boundaries) and re-downloading matching builds if they don't.
