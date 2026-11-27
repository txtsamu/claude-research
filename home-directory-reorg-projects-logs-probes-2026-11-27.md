---
type: how-to
tags: [fedora, home, organization, filesystem, mv, projects, systemd, dotfiles, agent-config, diskos, immich, oxigram, ktflash, probes, cleanup]
created: 2026-11-27
last_verified: 2026-11-27
status: current
---

# Reorganize `~` into projects/, logs/, and tools/probes/ (fedora home dir)

**Repo/branch:** the moves were made directly in `/home/moo` on the user's fedora workstation. This
note lives in `~/claude-research` on `master`.

**Request:** "ls current dir" → "organize it" → "group those too", with the explicit scope choices
*root tidy only* and *file them, don't delete*.

**Outcome:** the visible home root went from **41 entries to 27**. Nine project directories moved
into `~/projects/`, the three oxigram trees collapsed into one group, two loose logs went to
`~/logs/`, the loose B-691 docx/pdf pair was filed into `~/Documents/`, 38 probe scripts moved into
`~/tools/probes/`, and `ktflash-repo` moved out of `scratch/` (the now-empty `scratch/` was removed).
Nothing was deleted. Every move was a same-filesystem rename, so the whole thing took under two
seconds of file I/O.

The interesting part is not the `mv`. It is deciding **what must not move**: the ~50 agent dotdirs
and the toolchain dirs (`venvs/`, `go/`, `gradle/`, `android-sdk/`).

## Time estimate

Measured from the script log timestamps, not guessed:

| Step | Time |
|---|---|
| Survey (`du`, empty-dir scan, ref grep) | ~10 s of command runtime |
| Safety checks (crontab, systemd, autostart, symlink scan) | ~2 s |
| Pass 1 (8 projects + 3 oxigram dirs + 4 files) | **~1 s** (`22:46:04` → `22:46:05`) |
| Pass 2 (38 probes + ktflash-repo + `rmdir`) | **<1 s** (`22:50:07` → `22:50:07`) |

Total file movement under **2 seconds**. The rest of the wall clock was inspection and reading
output, which was not timed per step.

## 1. Inventory before touching anything

```bash
du -sh /home/moo/*/ 2>/dev/null | sort -rh | head -40
```

Top of that table: `nfs_photos` 1.4T, `archive` 38G, `venvs` 20G, `sessions` 8.9G, `Downloads` 8.7G,
`Music` 8.3G, `models` 7.4G, `diskos` 4.2G, `Android` 2.9G, `immich` 2.7G, `android-sdk` 2.6G,
`src` 2.4G, `oxigram-build` 2.0G.

Then a scan for directories that look empty but are not:

```bash
for d in /home/moo/.[a-z]*; do
  [ -d "$d" ] || continue
  n=$(find "$d" -maxdepth 1 -mindepth 1 2>/dev/null | wc -l)
  sz=$(du -sh "$d" 2>/dev/null | cut -f1)
  if [ "$n" -le 1 ]; then echo "EMPTYISH $sz $d ($n entries)"; fi
done
```

About 50 dotdirs came back at exactly `152K`. Inspecting one explained why:

```bash
find /home/moo/.qwen -maxdepth 2 | head
# /home/moo/.qwen/skills/ask-matt
# /home/moo/.qwen/skills/code-review
# ...
du -sh /home/moo/.qwen/*
# 152K  /home/moo/.qwen/skills
```

They are **not junk**. Each one holds a copied `skills/` pack for a different agent CLI
(`.qwen`, `.kode`, `.roo`, `.trae`, `.kiro`, ...). Moving them would break those tools, so they were
left exactly where they are.

## 2. Safety checks before moving a single directory

A directory that a unit file points at can be moved without any error message and still break its
service. So check the references first:

```bash
crontab -l 2>/dev/null | grep -E "diskos|immich|route-manager|vm-bot|wrapper-v2|slip-gaji|vpn-samu|evomem|oxigram"
# no output

grep -rEl "/home/moo/(diskos|immich|route-manager|vm-bot|wrapper-v2|slip-gaji|vpn-samu|evomem-bridge|oxigram)" \
  ~/.config/systemd ~/.bashrc ~/.bash_profile ~/.profile ~/.xsession ~/.config/autostart 2>/dev/null
# no output

systemctl --user list-units --all --no-legend | grep -Ei "diskos|immich|vm-bot|vpn|oxigram"
# no output
```

Then absolute symlinks *into* the directories being moved, which would dangle afterwards:

```bash
for d in diskos immich route-manager vm-bot wrapper-v2 slip-gaji vpn-samu evomem-bridge oxigram-build; do
  find "/home/moo/$d" -maxdepth 4 -type l -lname "/home/moo/$d*" 2>/dev/null | head -3
done
# no output
```

And confirm no repo has uncommitted work that a move would make harder to find:

```bash
for d in diskos immich route-manager vm-bot wrapper-v2 slip-gaji vpn-samu evomem-bridge; do
  [ -d "/home/moo/$d/.git" ] && printf "%s git=%s\n" "$d" "$(git -C "/home/moo/$d" status --porcelain | wc -l)"
done
# immich git=0 / route-manager git=0 / vm-bot git=0 / wrapper-v2 git=0 / vpn-samu git=0
```

All clear.

## 3. Pass 1: projects, oxigram group, loose files, logs

Script at `/tmp/opencode/organize-home.sh`. Key decisions in it:

- `mv -n` everywhere, so an existing target is never silently overwritten.
- Explicit skip logging when a path is already absent, so a rerun is idempotent.
- Only files matching the B-691 glob are filed, nothing wildcarded across the root.

```bash
mkdir -p /home/moo/projects/oxigram /home/moo/logs

for d in diskos immich route-manager vm-bot wrapper-v2 slip-gaji vpn-samu evomem-bridge; do
  mv -n "/home/moo/$d" "/home/moo/projects/$d"
done

for d in oxigram-build oxigram-backup-173222 oxigram-backup-180306; do
  mv -n "/home/moo/$d" "/home/moo/projects/oxigram/$d"
done

mv -n /home/moo/B-691*.docx /home/moo/Documents/
mv -n /home/moo/B-691*.pdf  /home/moo/Documents/
mv -n /home/moo/ydotoold.log /home/moo/oxigram-build.log /home/moo/logs/
```

`oxigram-build` was grouped with the two `oxigram-backup-*` snapshots rather than left in the root,
so everything oxigram now sits under one parent.

## 4. Pass 2: probes and scratch

```bash
mkdir -p /home/moo/tools/probes
mv -n /home/moo/tools/probe*.sh /home/moo/tools/probes/
mv -n /home/moo/scratch/ktflash-repo /home/moo/projects/ktflash-repo
rmdir /home/moo/scratch
```

Two notes. The user said "26 probe scripts"; the actual count was **38** (`probe1.sh` through
`probe38.sh`, written 2026-11-13 between 17:17 and 17:52). And before moving them:

```bash
grep -h "home/moo\|source \|\./" /home/moo/tools/probe*.sh | sort -u
# no output: no cross-references, no absolute paths
```

They are standalone diagnostics, likely the Samsung TV probe series, so relocation is safe.

## 5. Final layout

```
~/projects/
├── diskos/              4.2G
├── immich/              2.7G
├── oxigram/
│   ├── oxigram-build/         2.0G
│   ├── oxigram-backup-173222/ 904K
│   └── oxigram-backup-180306/ 888K
├── route-manager/       178M
├── wrapper-v2/          252M
├── vm-bot/              151M
├── vpn-samu/            193M
├── slip-gaji/           9.7M
├── evomem-bridge/       56M
└── ktflash-repo/        (git, branch main)

~/logs/     oxigram-build.log, ydotoold.log
~/Documents/ B-691 - SMA Negeri 50 Jakarta - Olahraga - 28 November 2026 (revised).{docx,pdf}

~/tools/
├── probes/               38 probe*.sh
├── ghidra_12.1.4_PUBLIC/
├── jdk-21.0.12.1+1/
├── sdb-dl/
├── bin/                  (empty)
├── fix_icon.sh
├── rea-env.sh
└── tv_inject.py
```

Deliberately **not** moved: `venvs/`, `go/`, `gradle/`, `android-sdk/` (toolchains with baked-in
paths), `src/`, `tools/`, `models/` (workspaces and data), all `~/.[a-z]*` dotdirs, and the data
mounts (`nfs_photos`, `archive`, `sessions`, `Downloads`, `Music`, `Pictures`, `Videos`).

## 6. Verification, with the actual output

```bash
ls -1 /home/moo | grep -v '^\.' | wc -l
# 27        (was 41)

ls /home/moo/tools/probes | wc -l
# 38

git -C /home/moo/projects/ktflash-repo status --porcelain | wc -l
# 0
git -C /home/moo/projects/ktflash-repo rev-parse --abbrev-ref HEAD
# main

ls /home/moo/Documents | grep -i B-691
# B-691 - SMA Negeri 50 Jakarta - Olahraga - 28 November 2026 (revised).docx
# B-691 - SMA Negeri 50 Jakarta - Olahraga - 28 November 2026 (revised).pdf
```

Old paths confirmed gone for all nine moved directories, and `du -sh ~/projects/*` matched the sizes
measured before the move, which rules out a partial or failed rename.

## Gotchas

- **`oxigram-build` is a build tree, not a source tree.** CMake stores the configure-time absolute
  path inside `CMakeCache.txt` (and in generated Makefiles/`build.ninja`). After the move, an
  incremental build there will error or force a full reconfigure. A clean rebuild fixes it. Nothing
  else that moved carries baked-in absolute paths.
- **Do not move agent dotdirs.** Each holds a `skills/` pack; the CLIs resolve them from the literal
  `~/.<name>/` path.
- **`venvs/` was left in place on purpose.** A virtualenv's `bin/activate` and console scripts embed
  the absolute interpreter path, so relocating one silently breaks every environment inside it.
- **Same-filesystem rename is why this was instant.** `mv` across filesystems (into a bind mount, for
  instance) becomes a copy plus delete and can take minutes on 7G+ of data.
- **Dotdir proliferation is a separate problem.** The ~50 `152K` dirs are config, not clutter. Deduping
  them into one shared skills dir via symlinks was offered and declined, correctly: agent CLIs do not
  all follow symlinks.
- **`ls -la | wc -l` is a misleading "clutter" metric.** The root had ~180 total entries but only 41
  visible ones; the dotdirs are expected on a Linux desktop.

## What was not verified

- No service was started after the move. `immich` (a container stack), `vm-bot`, `wrapper-v2` and
  `route-manager` were checked only for path references, not brought up.
- No compose file in the moved projects contained an absolute `/home/moo/...` volume; the only hit
  was `immich/node_modules/.modules.yaml` (`storeDir: /home/moo/.local/share/pnpm/store/v11`), which
  is package-manager metadata outside the moved tree. Still, a container bind mount defined by a
  path relative to the compose file is assumed, not exercised.
- `oxigram-build` was not rebuilt, so the CMake cache breakage described above is predicted from how
  CMake behaves, not observed on this machine.
- None of the 38 probe scripts were executed from their new location.
- `~/tools/bin/`, `~/Desktop/`, `~/Templates/`, `~/Public/` were left untouched, so the "empty dirs"
  question is still open.

## Related

- [[fedora43-btrfs-disk-usage-audit-steam-flatpak-orphan-2026-11-20]] — the earlier disk-usage audit that
  explains the 1.4T `nfs_photos` mount and the 38G `archive`.
- [[home-disk-usage-audit-and-log-retention-2026-11-06]] — log retention policy; the new `~/logs/` now
  holds the two stray root logs that policy would otherwise sweep.
- [[oxigram-fork-build-on-fedora-2026-11-23]] — how `oxigram-build` was produced, and why its CMake
  cache is path-sensitive.
- [[ktflash-rust-toolkit-linux-kt02h20-reflash-2026-11-26]] — the project now living at
  `~/projects/ktflash-repo`.
