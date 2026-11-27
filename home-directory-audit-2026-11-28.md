---
type: investigation
tags: [fedora, home, organization, audit, filesystem, btrfs, disk-usage, duplicates, android-sdk, oxigram, beets, net-diag, scripts, secrets, nfs]
created: 2026-11-28
last_verified: 2026-11-28
status: current
---

# `~` audit 2026-11-28: what is loose, what is duplicated, what would break if moved

**Repo/branch:** survey performed directly in `/home/moo` on the fedora workstation. This note
lives in `~/claude-research` on `master`. No files were moved, deleted, or renamed during the audit.

**Request:** "ls current dir" → "tree" → "organize dir", then the explicit scope choice *audit
report, no moves*. The move target for the eight loose scripts was confirmed as
`~/tools/probes/2026-11-28-net-diag/`.

**Outcome:** a written inventory of the visible home root (36 entries: 27 directories, 9 files),
a duplicate/reclaimable table worth roughly **9 GiB exclusive** on btrfs, a staged move plan that
has not been executed, and a list of things that must not move. This is a follow-up to
[[home-directory-reorg-projects-logs-probes-2026-11-27]], which did the first tidy pass.

## Time estimate

| Step | Time | How measured |
|---|---|---|
| Root `du` sweep, 27 local dirs (`nfs_photos` excluded) | **1.8 s** | `time` |
| `find` sweep for files >50M outside nfs/venvs/models | **5.6 s** (455 files) | `time` |
| `du` over `nfs_photos` (1.4 T over NFS) | **>60 s**, moved to background | harness timeout |
| `btrfs filesystem du` on 10 selected paths | a few seconds each, not individually timed | command returned inside its timeout |
| Whole audit including reading output | roughly 5 minutes wall clock | estimate, not a stopwatch |

The NFS sweep is the only slow step and it is also the one that does not matter for local disk
pressure: `nfs_photos` is a separate mount, not part of `/home`.

## Filesystem context

```
$ df -h /home/moo
/dev/nvme0n1p3  475G  245G  226G  53% /home

$ df -h /home/moo/nfs_photos
192.168.50.10:/mnt/data/photos  2.6T  1.4T  1.3T  52% /home/moo/nfs_photos
```

`/home` is a btrfs subvolume (`/dev/nvme0n1p3[/home]`, 474.4 G). `nfs_photos` is an autofs mount
over NFSv4 and its 1.4 T does **not** consume the 245 G. Space is not urgent (226 G free), so every
recommendation below is about navigability and duplicate confusion first, bytes second.

btrfs matters for the numbers: `du` reports apparent size, and the exclusive cost can be far lower.
The clearest case is the uv cache at **18.71 GiB apparent but 123 MiB exclusive**, because uv
hardlinks its archive into the venvs. Any "delete 19 G of cache" plan would free 123 MiB, not 19 G.

## 1. Inventory of the visible root

36 entries, newest first by mtime:

| Entry | Size (apparent) | btrfs exclusive | Last modified | Notes |
|---|---|---|---|---|
| `nfs_photos/` | 1.4 T | *(NFS)* | 2026-10-22 | separate NFS mount, not local |
| `archive/` | 38 G | 36.12 GiB | 2026-11-22 | 51 entries, deliberate cold storage |
| `venvs/` | 20 G | – | 2026-11-26 | beets, vllm, vllm312 |
| `projects/` | 9.8 G | – | 2026-11-27 | 10 repos/projects |
| `sessions/` | 8.9 G | 7.37 GiB | 2026-11-26 | 42 dated session dirs |
| `Downloads/` | 8.7 G | – | 2026-11-27 | 14 entries |
| `Music/` | 8.3 G | – | 2026-10-19 | 8 entries |
| `models/` | 7.4 G | – | 2026-11-26 | `ternary-bonsai-27b/` only |
| `Android/` | 2.9 G | – | 2026-10-14 | `Sdk/`, 2.73 GiB apparent / 2.51 GiB exclusive |
| `android-sdk/` | 2.6 G | 2.46 GiB | 2026-11-27 | 2.46 GiB exclusive |
| `src/` | 2.4 G | – | 2026-11-26 | oxigram + OpenRGB + llama + ani-cli |
| `Documents/` | 1.4 G | – | 2026-11-27 | 14 entries, 1.3 G is `Documents/archive/` |
| `tools/` | 1.3 G | – | 2026-11-27 | probes, ghidra, jdk |
| `go/` | 281 M | – | 2026-11-27 | `pkg/` |
| `gradle/` | 145 M | – | 2026-11-27 | `gradle-8.9/` |
| `Videos/` | 31 M | – | 2026-10-19 | music-videos, Screencasts |
| `Pictures/` | 31 M | – | 2026-11-17 | 16 images |
| `claude-research/` | 14 M | – | 2026-11-28 | 267 notes, git repo |
| `beets-music/` | 1.5 M | – | 2026-10-22 | library.db + 11 `.bak` |
| `nethome/` | 916 K | – | 2026-10-05 | router configs |
| `home-nixos/` | 620 K | – | 2026-11-28 | git repo |
| `local-session/` | 996 K | – | 2026-11-18 | git repo, 12 loose `.py` |
| `secrets/` | 80 K | – | 2026-10-19 | mode 700 |
| `logs/` | 4 K | – | 2026-11-27 | 2 files, one is 0 bytes |
| `Desktop/` | 0 | – | 2026-09-02 | empty, XDG |
| `Public/` | 0 | – | 2026-01-27 | empty, XDG |
| `Templates/` | 0 | – | 2026-01-27 | empty, XDG |

Plus 94 hidden directories and the 9 loose files below. Total root entries including hidden: 143.

Loose files, all in the root, all from today:

```
add_prune_timer.py   892 B   2026-11-28
collect_net2.sh     2215 B   2026-11-28
collect_net.sh      1867 B   2026-11-28
diag_tunnels.sh     1743 B   2026-11-28
dns_bench.py         896 B   2026-11-28
dns_one.py          1190 B   2026-11-28
dns_udp.py           992 B   2026-11-28
rm_netbird.py       1544 B   2026-11-28
CLAUDE.md           8296 B   2026-10-31
```

## 2. Where the local bytes actually are

`/home` holds 245 G. The visible directories above account for about 118 G; the rest is hidden.

| Path | Apparent | Exclusive | Comment |
|---|---|---|---|
| `.local/` | 59 G | – | Steam 33.25 GiB apparent / 29.95 GiB exclusive; containers 15 G; pnpm 1.6 G; claude 1.4 G; horizon-launcher 1.3 G |
| `.cache/` | 47 G | – | uv 18.71 GiB **apparent, 123 MiB exclusive**; tinygrad 14 G; pip 2.6 G; Brave 1.8 G; mozilla 1.5 G; huggingface 1.5 G; camoufox 1.4 G; playwright 1.3 G |
| `archive/` | 38 G | 36.12 GiB | largest single dir: `samsung-tv-t6500-2026-10` 9.6 G |
| `venvs/` | 20 G | – | three Python envs |
| `.npm/` | 5.1 G | – | toolchain cache |
| `.config/` | 6.4 G | – | |
| `.gradle/` | 2.4 G | – | |
| `.wine/` | 1.9 G | – | |

The `~/.cache` and `~/.local` trees are the real disk weight, but they are also the trees that must
not be touched casually: an agent dotdir or a Steam library moved by hand breaks tooling without an
error message. This audit recommends exactly zero moves inside them.

## 3. Findings, ranked by how much they matter

### F1. Eight loose diagnostic scripts in the root (zero risk, already scoped)

All eight were created today and nothing references them. Checks returned empty:

```
$ crontab -l | grep -E "prune|collect_net|diag_tunnels|dns_|rm_netbird"
(no output)

$ grep -rEl "add_prune_timer|collect_net|diag_tunnels|dns_bench|dns_one|dns_udp|rm_netbird" \
    ~/.bashrc ~/.bash_profile ~/.profile ~/.xsession ~/.config/autostart \
    ~/.config/systemd ~/.config/opencode ~/.claude
(no output)
```

Scope-answered target: `~/tools/probes/2026-11-28-net-diag/`. The existing `tools/probes/` holds
38 numbered probes flat, so a dated subdirectory keeps one session's network diagnostics together
instead of becoming `probe39..probe46` with no story.

### F2. Two Android SDK installs, both carrying a 2.0 G NDK (~5.2 GiB total, ~2.5 GiB reclaimable)

| | `Android/Sdk` | `android-sdk` |
|---|---|---|
| Size | 2.73 GiB apparent / 2.51 GiB exclusive | 2.46 GiB exclusive |
| mtime | 2026-10-14 | 2026-11-27 |
| NDK | `27.0.12077973` (2.0 G) | `27.0.12077973` (2.0 G) |
| build-tools | 35.0.0, 36.0.0 | 34.0.0, 35.0.0 |
| platforms | android-36, android-37, android-37.0 | android-35 |

Evidence that `android-sdk` is the live one:

```
$ grep sdk.dir projects/vpn-samu/local.properties
sdk.dir=/home/moo/android-sdk
```

Evidence that `Android/Sdk` was used at least once, and by what:

```
$ grep -o "[/A-Za-z0-9._-]*Android/Sdk[/A-Za-z0-9._-]*" .gradle/daemon/8.11.1/daemon-1078805.out.log | sort -u
/home/moo/Android/Sdk
/home/moo/Android/Sdk/build-tools/35.0.0
/home/moo/Android/Sdk/licenses
/home/moo/Android/Sdk/platforms/android-36
```

No Android Studio install exists (`rpm -qa | grep -i android` returns only `android-tools-37.0.0p1`),
no JetBrains Toolbox, and no `ANDROID_HOME`/`ANDROID_SDK_ROOT` in shell configs. So `Android/Sdk`
looks like a leftover from a manual or Toolbox-era SDK that one Gradle daemon happened to pick up
before `local.properties` was pointed at the newer tree. It is the single largest clean reclaim
after the two duplicates below.

### F3. The oxigram tree exists four times (~4 GiB of build output duplicated)

```
$ du -sh src/oxigram projects/oxigram/*
2.0G  src/oxigram
2.0G  projects/oxigram/oxigram-build
904K  projects/oxigram/oxigram-backup-180306
888K  projects/oxigram/oxigram-backup-173222
```

`src/oxigram` and `projects/oxigram/oxigram-build` are the same repository on the same branch,
checked out at **different commits**, both clean:

```
src/oxigram:                              projects/oxigram/oxigram-build:
  ref: refs/heads/forum-topics               ref: refs/heads/forum-topics
  56cba6765239cb26ea838ca633892f8b5eb5d8d2   c596cc0a682411db48567d5f94f5197a4434f278
  dirty=0                                    dirty=0
```

Nearly all of the 2.0 G in each is `target/` (Rust build output). `src/oxigram/target` alone is the
whole 2.0 G; the source is ~7 MB. The two `oxigram-backup-*` dirs are runtime data snapshots
(`oxigram.db`, `config.json`, `native-*`, port/lock files), under 1 MB each.

Related: [[oxigram-fork-build-on-fedora-2026-11-23]] describes the fork build.

### F4. A byte-identical 2.5 GiB album copy in Downloads

`Downloads/Coldplay - X&Y (2005 Pop) [Flac 24-192]` and `nfs_photos/music/Coldplay - X&Y` hold the
same 18 files with the same names and the same sizes. Track 01 is byte-identical:

```
$ sha256sum "Downloads/Coldplay - X&Y (2005 Pop) [Flac 24-192]/01. Coldplay - Square One.flac" \
            "nfs_photos/music/Coldplay - X&Y/01. Coldplay - Square One.flac"
761bf35b7e461abe718404520da8b06dc9758366d2ba737cf41ab66e704085f8
761bf35b7e461abe718404520da8b06dc9758366d2ba737cf41ab66e704085f8
```

The NFS copy is the one that belongs in the music library. The Downloads copy is 2.45 GiB exclusive
on the local disk and is the cheapest real space win in this audit.

### F5. `sessions/` is 8.9 G of dated working directories, several with build trees

42 dirs, 7.37 GiB exclusive. Top six: `2026-11-05-perses-dashboards-review` 1.6 G,
`2026-10-28-immich-env-tests` 1.6 G, `2026-10-27-evomem-timeout` 1.2 G, `2026-11-06-evomem-utcp`
1.1 G, `2026-10-28-nas-downloads-dedupe` 879 M, `2026-10-29-immich-effect-v4-live-test` 638 M.
Inside them: 7 `build/`, `target/`, or `dist/` dirs. These are evidence directories referenced by
claude-research notes, so they should not move; a retention decision (keep everything vs prune
build outputs only) is a separate conversation.

### F6. Eleven beets `.bak` snapshots, all from one afternoon

`beets-music/` holds 11 `library.db-before-*` files, each exactly 53248 bytes, all dated 2026-10-22,
plus the live `library.db` and `state.pickle`. Total 572 KB. The names show a chain of schema
migrations (multi_genre, relative_path, lyrics_metadata, remove_inherited_artpath, ...). Cheap to
keep, cheap to archive; they are only clutter at this size.

### F7. `nethome/` mixes router backups with six stage variants

```
mikrotik.rsc  8125 B   mikrotik-pppoe-cutover.rsc  2249 B   mikrotik-pppoe-rollback.rsc 1027 B
mikrotik-stage.rsc 1837 B   mikrotik-stage2.rsc 1078 B   mikrotik-stage3.rsc 813 B
mikrotik-stage-untagged.rsc 1471 B
nethome.xml 135681 B   nethome-bridge.xml 135663 B   original_vsol.xml 136034 B
onu.sh 1640 B   altos-tools/   backup/
```

Two complete router exports (`nethome.xml`, `nethome-bridge.xml`) and a third from the ONU
(`original_vsol.xml`), none referenced by scripts (the `.rsc` files are pasted into RouterOS by
hand). A `stages/` subdir would make the final configs obvious, but the payoff is small.

### F8. `local-session/` is a repo with one uncommitted file

```
$ git -C local-session status --porcelain
?? perses-homelab-monitoring/k8s/alerting.yaml
```

The repo mixes 12 loose helpers (`build_plan.py`, `categorize.py`, `scan_dupes.py`,
`restore_quarantine.py`, `verify_quarantine.py`, `make_payload.py`, `plan_organize.py`) with seven
`tiktok-bot-*.py`/`.md` files and two `.md` write-ups. The untracked `alerting.yaml` should be
committed or discarded before any reorganization touches the directory.

### F9. `projects/diskos` is fifteen clones under one roof

`projects/diskos/` (4.2 G, 3.96 GiB exclusive) contains 14 feature clones
(`diskos`, `diskos-autolocal`, `diskos-bootstate`, `diskos-dacvolkeys`, `diskos-debugpage`,
`diskos-disco-fixes`, `diskos-eqapps`, `diskos-feat-cmd-guard`, `diskos-feat-net-switches`,
`diskos-feat-no-phonehome`, `diskos-feat-round-home`, `diskos-feat-round-kb`,
`diskos-feat-round-lists`, `diskos-maxvol`, `diskos-reapply`, `diskos-settings-groups`,
`diskos-splashhold`, `diskos-stock-plus`, `diskos-testout`, `diskos-usbdebug`), each with its own
`.git`, plus ~15 `mq_ui.*` output dirs and `firmware-decompiled/`. This is the diskos workflow, not
junk, but it is the one subdirectory that would benefit from a `clones/` and `builds/` split.

### F10. Empty XDG dirs and an empty log

`Desktop/`, `Public/`, `Templates/` are empty and date from the original install. They are
standard XDG locations; apps write to them when asked to save or export, so removing them buys
nothing and can surprise a file dialog. `logs/ydotoold.log` is 0 bytes.

### F11. Secrets are plaintext but correctly permissioned

`~/secrets` is mode 700, files are mode 600:

```
drwx------ secrets
-rw------- age-recovery-key.txt
-rw------- cloudflare-tunnel-token.age     (age-encrypted)
-rw------- Mozilla-Recovery-Key_2026-09-06_<account>.txt
-rw------- ph_cookies.txt
drwx------ secrets/mikrotik
```

Also outside that dir: `~/Downloads/cookies.txt` (172 K) and `~/Downloads/hoodik-recovery-key.txt`.
Nothing is world-readable. This is an observation, not a finding to act on: the only real hardening
would be moving the two Downloads files into `~/secrets`, which is a security decision, not an
organization one.

### F12. `Documents/` carries its own 1.3 G archive

`Documents/archive` is 1.3 G (a PDF/eBook zip alone is 1.3 G), while the rest of Documents is small:
`story-collection` 50 M, `BRI` 35 M, then everything under 4 M. `Documents/Default Project` and
`Documents/claude` are empty. The two `B-691 ... (revised)` files sit in the Documents root, which
is consistent with the filing decision from yesterday.

### F13. `Music/BitChord` has uncommitted work

```
$ git -C Music/BitChord status --porcelain
 M app/src/main/java/com/music/bitchord/playback/audio/usb/UsbDirectAudioOutput.kt
 M app/src/main/java/com/music/bitchord/playback/audio/usb/UsbDirectDriver.kt
```

An application project living under `Music/`. Moving it under `projects/` would be more
consistent, but not while it is dirty.

### F14. `archive/` is healthy, just large

36.12 GiB exclusive, 51 entries, newest addition 2026-11-22 (`home-nixos`, `installers`, `models`,
`logs`), oldest surviving file from 2025-11-24 (`rocky9-cloud.qcow2`). It is doing its job. Worth
knowing that `archive/models/bonsai-2-27b-crack/Bonsai-2-27B-PQ2_0-CRACK.gguf` (7.2 G) and
`models/ternary-bonsai-27b/Ternary-Bonsai-2.5-27B-Uncensored-Q2_0-mtp.gguf` (7.9 G) are **different**
models, not duplicates.

## 4. Reclaimable, with honest btrfs numbers

| Action | Apparent | Exclusive | Risk |
|---|---|---|---|
| Delete `Downloads/Coldplay - X&Y ...` (NFS copy verified identical) | 2.5 G | 2.45 GiB | none, one hash spot-check + name/size sweep |
| `cargo clean` in `src/oxigram` | 2.0 G | ~1.88 GiB | rebuild cost only |
| Remove `projects/oxigram/oxigram-build` (older commit, clean tree) | 2.0 G | 1.90 GiB | loses that checkout; commits are not unique if pushed |
| Remove `Android/Sdk` (keep `android-sdk`) | 2.9 G | 2.51 GiB | medium, confirm no future platform-37 build needed |
| Empty `~/.local/share/Trash` | 221 M | 221 M | none, it is trash |
| Archive the 11 beets `.bak` | 572 K | 572 K | none |

Total if every row is approved: **~9 GiB exclusive**. That is 3.7 % of the 245 G used, so space is a
side benefit. The main gain is one obvious SDK, one obvious oxigram checkout, and a root without
loose scripts.

## 5. Staged plan (not executed)

Every move is a same-filesystem rename, `mv -n`, with an explicit skip log so a rerun is idempotent.
Same pattern as the 2026-11-27 script.

**Stage 0, zero risk, approved target**

```bash
mkdir -p /home/moo/tools/probes/2026-11-28-net-diag
cd /home/moo
for f in add_prune_timer.py collect_net.sh collect_net2.sh diag_tunnels.sh \
         dns_bench.py dns_one.py dns_udp.py rm_netbird.py; do
  mv -n "$f" tools/probes/2026-11-28-net-diag/ || echo "SKIP $f (absent or target exists)"
done
```

Leave `CLAUDE.md` in the root: it is read from `~/CLAUDE.md` by the agent tooling.

**Stage 1, low risk, needs a reference grep before each move**

1. `beets-music/library.db-before-*.bak` → `beets-music/backups/2026-10-22/`
2. `nethome/mikrotik-stage*.rsc` → `nethome/stages/` (keep `mikrotik.rsc` and both `.xml` exports in place)
3. Commit or discard `local-session/perses-homelab-monitoring/k8s/alerting.yaml`

**Stage 2, space, only after explicit confirmation**

1. Delete the Downloads Coldplay copy, keeping `nfs_photos/music/Coldplay - X&Y`.
2. `cargo clean` in `src/oxigram`, then decide which checkout survives:
   `src/oxigram` (newer commit, `56cba67`) or `projects/oxigram/oxigram-build` (`c596cc0`).
3. Remove `Android/Sdk` after confirming no project or archived build targets platform 37.

**Stage 3, do not do**

- Do not move any of the 94 hidden dirs. The ~50 agent dotdirs (`.qwen`, `.kode`, `.roo`, `.trae`,
  `.kiro`, ...) each carry a copied `skills/` pack and break silently when moved.
- Do not touch `venvs/`, `go/`, `gradle/`, `android-sdk/`, `models/`, `archive/`, or `nfs_photos/`.
- Do not remove `Desktop/`, `Public/`, `Templates/`.

## 6. Safety checks already performed

| Check | Command | Result |
|---|---|---|
| cron jobs referencing loose scripts | `crontab -l \| grep -E "prune\|collect_net\|diag_tunnels\|dns_\|rm_netbird"` | empty |
| shell/systemd/autostart references | `grep -rEl "<script names>" ~/.bashrc ~/.bash_profile ~/.profile ~/.xsession ~/.config/autostart ~/.config/systemd ~/.config/opencode ~/.claude` | empty |
| root symlinks | `find /home/moo -maxdepth 1 -type l` | only `.steampath`, `.steampid` |
| project repos dirty? | `git status --porcelain` per repo | only `Music/BitChord` (2) and `local-session` (1) |
| active SDK | `grep sdk.dir projects/vpn-samu/local.properties` | `android-sdk` |
| home filesystem | `df -h /home/moo` | btrfs, 226 G free |

## 7. What was not verified

- **Whether some other, non-obvious consumer uses `Android/Sdk`.** Only one Gradle daemon log
  mentions it; no Android Studio or Toolbox install was found, but a script or IDE outside
  `~/.config/systemd`, `~/.config/autostart`, and the shell rc files was not exhaustively searched.
- **Commit ancestry of the two oxigram checkouts.** Both are clean and on `forum-topics`, at
  different SHAs. Whether `c596cc0` is an ancestor of `56cba67` was not checked (`git merge-base
  --is-ancestor`), so "the build copy is strictly older" is an assumption from the timeline, not a
  verified fact.
- **Only track 01 of the Coldplay album was hashed.** The remaining 17 files match by name and size,
  which is strong evidence but not a byte-level proof for each.
- **NFS contents.** `nfs_photos` was measured for size only; nothing inside it was audited.
- **Whether `sessions/` entries are still needed.** A retention decision needs the owning notes,
  not a `du` table.
- **Real compression ratio of `archive/`.** Apparent 38 G vs 36.12 GiB exclusive suggests little
  reflink sharing, but per-file compression was not measured; `compsize` has failed with
  `SEARCH_V2: Operation not permitted` on this host before (see
  [[fedora43-btrfs-disk-usage-audit-steam-flatpak-orphan-2026-11-20]]).

## References

No web research contributed to this audit. Every number came from commands run on the host, shown
inline above. Related on-box notes: [[home-directory-reorg-projects-logs-probes-2026-11-27]],
[[fedora43-btrfs-disk-usage-audit-steam-flatpak-orphan-2026-11-20]],
[[home-disk-usage-audit-and-log-retention-2026-11-06]],
[[oxigram-fork-build-on-fedora-2026-11-23]].
