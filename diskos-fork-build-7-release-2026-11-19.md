---
type: how-to
tags: [diskos, release, github, fork, tag, mq_ui, cross-build, podman, snowsky-disc, stable]
created: 2026-11-19
last_verified: 2026-11-19
status: current
---

# Releasing a fork build of diskOS: build 7 as stable (2026-11-19)

The user asked: "release our latest fix as stable on my repo". This is the recipe actually used and the record of build 7. Repo `/home/moo/diskos/diskos` (fork `txtsamu/diskos`, remote `origin`), branch `main` at `cf58a93`, released as `v1.2.1-fork.7`.

Release: <https://github.com/txtsamu/diskos/releases/tag/v1.2.1-fork.7>

## Time estimate

- Whole session from device check to published release: about 6 minutes wall clock (09:33:38 check, 09:38:42 publish). Measured from shell timestamps.
- Clean podman cross-build: ended 09:37:46. The start was not stamped, so about 2 minutes is an estimate.
- Tag, push and release creation: under a minute.
- Verification download and hash check: a few seconds.

## What "release as stable" means in this fork

The fork has no release script and no CI release workflow. The established pattern, visible in `gh release list -R txtsamu/diskos`, is:

- A **lightweight** git tag `v1.2.1-fork.N` on the release commit on `main` (check with `git cat-file -t v1.2.1-fork.6`, which prints `commit`, not `tag`).
- A GitHub release marked stable (`--latest`, prerelease false).
- Two assets only: `mq_ui` and `SHA256SUMS`. No flash image, because `diskos_*.bin` embeds FiiO's root filesystem.
- Release notes live in the GitHub release body, not as a repo file. `CHANGELOG.md` keeps one `[Unreleased]` section and is not bumped per fork build.
- `build/stage-release.sh` is for the upstream installer packages (per-platform tarballs, Windows ZIP). It is not used for these fork UI releases.

## Steps, in order

### 1. Establish the target and the next version

```bash
cd /home/moo/diskos/diskos
git log --oneline -1                 # cf58a93 Changelog: record the test harness rework
git status -sb                       # clean
git tag -l 'v1.2.1-fork.*'           # highest was v1.2.1-fork.6
git log --oneline v1.2.1-fork.6..HEAD
```

That range contained the SD clean-unmount work (`05c4569`, `4ff4b27`, `15797a0`, `e6bc3da`) and the six module deepenings plus the harness rework (through `cf58a93`). Next number: `v1.2.1-fork.7`.

Check what changed so the notes describe the actual range, not memory:

```bash
git log --format='%h %s%n%b' 05c4569^..e6bc3da
gh release view v1.2.1-fork.6 -R txtsamu/diskos | head -60
```

The build 6 body shows the house shape: a stable line naming the firmware base and commit, Fixed / Changed sections, Verification with real hashes, Known issues, Assets with the install command.

### 2. Clean cross-build (do not trust the incremental artifact)

```bash
cd /home/moo/diskos/diskos/ui
podman run --rm --userns=keep-id -v "$PWD:/src:Z" localhost/diskos-ui-builder:latest \
  sh -c 'make clean >/dev/null 2>&1; make -j4 CROSS=$CROSS'
```

Result for build 7:

```
artifact: mq_ui
md5: 80b0b0e1ef69b776a83f8e954a915061
cc: mipsel-linux-musl-gcc (GCC) 11.2.0
src_md5: a73787cf0db377f9ffd57d710a4c386a
size: 4354196
```

The default `make` target is the **normal** build. Do not pass `-DDISKOS_TEST_OUTPUTS` for a stable release; that flag adds the SPDIF Output row and is test-only.

The clean build reproduced the binary already hot-loaded on the device, so the artifact was known-good rather than freshly unverified.

### 3. Stage the assets and checksums

```bash
mkdir -p /tmp/opencode/release-fork7
cp /home/moo/diskos/diskos/ui/mq_ui /tmp/opencode/release-fork7/mq_ui
cd /tmp/opencode/release-fork7
sha256sum mq_ui > SHA256SUMS
cat SHA256SUMS
```

```
7263832b9553c07749bebfac39c4336621ed8c008d68dc586aad1bdf5acd9417  mq_ui
```

The format is exactly `sha256sum` output with two spaces, matching build 5 and 6. A single-file checksum file is enough; `gh` stores it as an asset like any other.

### 4. Tag and push the tag

```bash
git tag v1.2.1-fork.7 cf58a93
git push origin v1.2.1-fork.7
git ls-remote --tags origin v1.2.1-fork.7
```

The tag must point at the commit the binary was built from. A lightweight tag matches the previous six tags; an annotated tag would also work but would differ from the house pattern.

### 5. Create the release as stable

Notes were written to `/tmp/opencode/release-fork7/notes.md`. Then:

```bash
gh release create v1.2.1-fork.7 -R txtsamu/diskos \
  --title "diskOS 1.2.1 fork build 7 (stable): clean SD unmount at power-off, six deeper UI modules" \
  --notes-file /tmp/opencode/release-fork7/notes.md \
  --latest \
  /tmp/opencode/release-fork7/mq_ui /tmp/opencode/release-fork7/SHA256SUMS
```

Use `-R txtsamu/diskos` explicitly. Omitting `-R` while the working directory has multiple remotes (`disco`, `origin`, `upstream`) risks publishing to the wrong repo.

The release body must state the exact binary identity:

- md5 `80b0b0e1ef69b776a83f8e954a915061`, 4354196 bytes.
- Normal build, no `-DDISKOS_TEST_OUTPUTS`.
- Source tag `v1.2.1-fork.7`, `main` at `cf58a93`.

### 6. Verify the published assets

```bash
rm -rf /tmp/opencode/verify-fork7 && mkdir -p /tmp/opencode/verify-fork7
cd /tmp/opencode/verify-fork7
gh release download v1.2.1-fork.7 -R txtsamu/diskos
sha256sum -c SHA256SUMS
md5sum mq_ui
stat -c '%s' mq_ui
gh release list -R txtsamu/diskos --limit 3
```

Result:

```
mq_ui: OK
80b0b0e1ef69b776a83f8e954a915061  mq_ui
4354196
```

`gh release list` marked `v1.2.1-fork.7` as **Latest**, and `gh release view --json isPrerelease` returned `false`. That is the proof it is published as stable, not just uploaded.

## What build 7 contains

User-facing fix:

- The microSD card is unmounted before power-off and before Restart. Neither path called `umount` before. The stock player holds the last track open, so the fix asks the player to release the card through its own USB Storage path, retries 40 times at 100 ms, lazy-detaches as a fallback, then flushes the block device with `fsync`. A failed unmount never blocks the shutdown.
- File system detection before mounting, so the failed exFAT probe and its four `exFAT-fs ... failed to mount! (-22)` lines per boot are gone.

Internal, with host tests:

- Six modules out of `ui/main.c`: `card`, `cardclose`, `playerset`, `idlegov`, named transport commands, and a declare-once test harness with per-test temp roots.
- `ui/main.c` 2156 to 1801 lines.
- One behaviour change: the shutdown drain timeout is 10 s in both power off and Restart; it was 8 s in power off.

The full build log is [[diskos-ui-deepening-six-modules-and-harness-2026-11-18]]; the SD fix is [[diskos-sd-clean-unmount-and-fsdetect-2026-11-17]].

## Gotchas

1. **Verify the tag type before following the house pattern.** `git cat-file -t <tag>` prints `commit` for a lightweight tag. Do not assume annotated.
2. **Clean-build for a release.** Link order now comes from a sorted glob, so an incremental object tree can produce a different md5 than a fresh build. The release notes quote the clean-built hash.
3. **The normal build hides SPDIF Output.** Passing `-DDISKOS_TEST_OUTPUTS` for a stable release would ship a row that build 6 deliberately removed from the stable binary.
4. **`gh release view --json isLatest` does not exist.** The field list rejects it; confirm the Latest marker with `gh release list` instead.
5. **`gh release download -p SHA256SUMS -O -` did not print the file.** Downloading to a directory and `cat`-ing worked. Not worth debugging for a one-file check.
6. **The release does not include a flash image.** Users run the installer with `--ui ./mq_ui` and their own firmware ZIP. Build 6 notes say the same.
7. **A hand-copied `mq_ui` is temporary.** `S97diskos_install` compares `/usr/data/mq_ui` against the image manifest at boot, so a hot-loaded binary is reverted on the next reboot unless installed through the installer.

## Device state at release time

The released binary was already running on the test Disc from the 2026-11-18 hot-load, and it survived the night without a restart:

```
80b0b0e1ef69b776a83f8e954a915061  /proc/24771/exe
80b0b0e1ef69b776a83f8e954a915061  /usr/data/mq_ui
24771 mq_ui    1150 mq_player
uptime 13:31
```

The flashed image still holds the previous build, so the Disc reverts to it on a power cycle unless build 7 is flashed.

## Not verified

- The final FAT warning proof is still open. The test card was already marked dirty, the bit was cleared once by hand, and no power-off/power-on cycle has been run since. `dmesg` on the current boot had already wrapped (247 lines, first timestamp at 7223 s), so it cannot answer the question.
- A hardware long-press power-off bypasses the UI and still marks the volume dirty.
- The 10 s drain timeout and the unmount retry ladder are host-tested only; the worst-case shutdown delay was not measured on hardware.
- No flashed image was built or attached for build 7.

## Related notes

- [[diskos-ui-deepening-six-modules-and-harness-2026-11-18]]
- [[diskos-sd-clean-unmount-and-fsdetect-2026-11-17]]
- [[diskos-hotload-gotchas-test-outputs-usb-storage-reboot]]
- [[diskos-disc-hotload-watchdog-snowsky-logo-hang]]
- [[diskos-build-harness-declare-once-tests-2026-11-18]]

## References

No external web sources were used. The release shape came from the repo's own history (`gh release view v1.2.1-fork.5`, `v1.2.1-fork.6`), `build/stage-release.sh`, and `docs/DEV_WORKFLOW.md`.
