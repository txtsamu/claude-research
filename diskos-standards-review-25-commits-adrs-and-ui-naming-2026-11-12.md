---
type: investigation
tags: [diskos, code-review, standards, adr, glossary, agents, skills, matt-pocock, opencode, host-tests, libasan, refactor]
created: 2026-11-12
last_verified: 2026-11-12
status: current
---

# diskOS: standards review of the 25-commit dev branch, ADRs, and the UI naming pass (2026-11-12)

Repo `/home/moo/diskos/diskos`, branch `dev`. Started at `0296c1f` (22 commits ahead of `origin/dev` at `4847ca1`), ended at `5d5093a` (25 ahead), pushed `4847ca1..5d5093a`. Related: [[diskos-device-check-2026-11-12-and-choice-picker-scroll-fix]], [[diskos-working-mode-auto-via-local-2026-11-11]], [[diskos-usb-debug-source-menu-serial-no-ethernet-2026-11-10]], [[diskos-boot-starting-state-and-boot-net-errors-2026-11-10]], [[diskos-eq-how-it-works-and-upstream-1-2-2-port-2026-11-11]].

## Requests

Two threads in one session: install `npx skills@latest add mattpocock/skills` into opencode, then recommend and apply the right skills for this codebase until the code review was clean. The last request added a standing rule: every session is documented here and pushed.

## Skills installed

```sh
npx skills@latest add mattpocock/skills -g -a opencode --all
```

- **38 of 39** skills installed to `~/.agents/skills/`; opencode reads that shared directory directly (there is no `~/.config/opencode/skill/` symlink). The CLI detected OpenCode and installed non-interactively.
- One upstream skill was skipped: `in-progress/software-factory/SKILL.md` fails YAML parsing (`Nested mappings are not allowed in compact mappings`).
- Collision: the pack's `handoff` (compact the conversation into a document) replaced agentmemory's existing `handoff` (resume the last session). The old one was restored as **`agentmemory-handoff`** with its `name:` field updated, so both exist.
- Skills with `disable-model-invocation: true` (`ask-matt`, `handoff`, `pr`, `to-spec`, …) are meant to be invoked explicitly, not auto-selected.
- Recommended for diskOS and used here: `code-review`, `domain-modeling`, `diagnosing-bugs`, `codebase-design`, `grilling`, `wizard`, `pr`, `retro`, `improve-codebase-architecture`, `tdd`. Skipped as irrelevant: `setup-pre-commit`, `setup-ts-deep-modules`, `migrate-to-shoehorn`, `scaffold-exercises`, `git-guardrails-claude-code` (Claude Code hooks).

## Review of the 25-commit range

`code-review` over `git diff origin/dev...HEAD`: **22 commits, 65 files, +5065/−470**. The Spec axis was skipped because the range has no issue references and no spec file; only the Standards axis ran.

| Severity | Finding | Where |
|---|---|---|
| hard | Doc said "Settings > Controls"; the page is **System > Volume Keys** | `docs/USB_AUDIO_VOLUME.md:10`, `ui/settings.c:757` |
| hard | Splash doc called it "a timed reveal, not a boot-progress indicator"; the splash now replays while `bootstate_starting()` | `docs/DESIGN_SYSTEM.md:106`, `ui/splash.c:224` |
| hard | `usb-on` exit codes 2–6 were a contract between the script and `usbdbg.c`, documented nowhere | `payload/diskos-debug.sh:283-297`, `ui/usbdbg.c:10` |
| smell | `now_ms() ? now_ms() : 1` repeated five times | `ui/srcswitch.c:89,108`, `ui/dacvol.c:264,278,376` |
| smell | Bare mode numbers `0/1/2/3` next to named 4/5; picker row order was a hidden invariant | `ui/srcswitch.c:236-249`, `ui/modes.c:33-34` |
| smell | Stock gadget list duplicated across C and shell | `ui/main.c:395`, `payload/diskos-debug.sh:172` |
| smell | Card number recovered by scanning digits off the end of a path string | `ui/outroute.c:231-239` |
| smell | `lv` shadowed the LVGL prefix; page-list size was a magic `2` | `ui/settings.c:1193,935` |
| smell | Four `leave_*` fields travelled together through every `dacvol` function | `ui/dacvol.c:38-40` |
| nit | Stray double blank line | `ui/eqcustom.c:300` |

The no-comments rule passed: the added lines contained only shebangs, SPDX headers, `#error`, and Python docstrings.

## Fixes

### `26e8a20` — docs and ADRs

- `docs/USB_AUDIO_VOLUME.md`: path corrected to **Settings > System > Volume Keys**.
- `docs/DESIGN_SYSTEM.md`: splash sequence rewritten from the code — intro 0–1500 ms repeats while starting; light 150–1000, hub 650–1300, wordmark 950–1400 (fade 1740–1900), reveal 1800–2350, finish 2400; give-up at `IPC_BOOT_HOLD_MS` 30 s. Removed the false "not a boot-progress indicator" line.
- `docs/USB_DEBUG.md`: new **`usb-on` exit codes** table (0 success, 1 usage/old script, 2 stock gadget, 3 no UDC, 4 bind, 5 setup, 6 no tty, 127 not found) matching `usbdbg.c`.
- New `docs/adr/0001-working-mode-switches-go-via-local.md` and `docs/adr/0002-usb-debug-is-an-overlay-on-local.md`; **Via Local** added to `GLOSSARY.md`; ADR directory linked from `docs/README.md`.

### `827b29e` — UI naming, no behaviour change

- `ui/now.h` adds `now_nonzero()`; all five sentinels use it.
- `SRCSWITCH_MODE_LOCAL/USB_DAC/BT_RECEIVING/USB_STORAGE` added beside the existing DEBUG/AUDIO defines; `srcswitch.c` uses them.
- `MODES[]` uses designated initializers keyed by the mode values, so picker order cannot drift from the protocol numbers.
- `PAGE_LIST_MAIN/SUB/COUNT` enum replaces the magic `2` and the `lv` loop variable.
- `dacvol` leave fields grouped into one `S.leave` struct.

### `5d5093a` — drift guard

`ui/tests/gadget_list_test.py` parses the C array in `ui/main.c` and the shell loop in `payload/diskos-debug.sh`, compares them, and is wired into `PY_COMPLETE`. A deliberately mismatched copy fails with `gadget lists differ: C [...] vs shell [...]`.

## Verification

```text
make -C ui/tests check
EXIT:0
C assertions: 210
Python completions: 7
  boot_probe boot_select font_coverage gadget_list launcher settings_tree storage
outseq_guard: Ran 5 tests — OK
rmguard:      Ran 5 tests — OK
```

Every changed UI file also passed:

```sh
cc -fsyntax-only -std=gnu11 -Wall -Wextra -Werror -D_GNU_SOURCE \
   -DLV_CONF_INCLUDE_SIMPLE -I. -I./lvgl <file>
```

`srcswitch.c`, `dacvol.c` and `modes.c` were also clean under `-fanalyzer`. `settings.c` still has two pre-existing `-Wmisleading-indentation` warnings (`if(v < 0) v = 0; if(v > 40) v = 40;`, lines 582 and 612); they are not from this work and the project builds with `-Wall` only.

### Host `libasan` workaround

This Fedora 43 host has GCC 15.3.1 but no `libasan` package: `/usr/lib/gcc/x86_64-redhat-linux/15/libasan.so` is a linker script pointing at a missing `/usr/lib64/libasan.so.8.0.0`, so any fresh `-fsanitize=address` link fails. The prebuilt test binaries run, but `boot_probe_test.py` and `storage_test.py` build temp binaries and fail.

Workaround used: borrow the runtime from the Freedesktop flatpak and add it to the link and load paths.

```sh
FP=$(dirname "$(find /var/lib/flatpak/runtime/org.freedesktop.Platform -name libasan.so.8.0.0 | head -1)")
mkdir -p /tmp/opencode/asanlib
ln -sf "$FP/libasan.so.8.0.0" /tmp/opencode/asanlib/libasan.so
ln -sf "$FP/libasan.so.8.0.0" /tmp/opencode/asanlib/libasan.so.8
ln -sf "$FP/libasan.so.8.0.0" /tmp/opencode/asanlib/libasan.so.8.0.0
ln -sf "$FP/libubsan.so.1.0.0" /tmp/opencode/asanlib/libubsan.so
ln -sf "$FP/libubsan.so.1.0.0" /tmp/opencode/asanlib/libubsan.so.1
ln -sf "$FP/libubsan.so.1.0.0" /tmp/opencode/asanlib/libubsan.so.1.0.0
printf '#!/bin/sh\nexec /usr/bin/cc -L/tmp/opencode/asanlib "$@"\n' > /tmp/opencode/cc-asan
chmod +x /tmp/opencode/cc-asan
LD_LIBRARY_PATH=/tmp/opencode/asanlib make -C ui/tests check CC=/tmp/opencode/cc-asan
```

The temp directory was removed after the session; recreate it the same way.

## Push

`git push origin dev` moved `origin/dev` from `4847ca1` to `5d5093a` (fast-forward, 25 commits). All three new commits are signed off with `git commit -s`.

## Gotchas

- **VS Code showed 2 pending changes while `diskos` was clean.** The workspace is `/home/moo/diskos`, which contains 21 worktrees; the SCM badge summed two untracked files in sibling worktrees: `diskos-disco-fixes/vendor/linux-x86_64/usbboot.manifest` and `diskos-testout/ui/build.err`. Both were moved to `/tmp/opencode/cleanup-backup/` (recoverable) rather than deleted. To show only the main repo, open `/home/moo/diskos/diskos` or set `git.autoRepositoryDetection` to `openEditors`.
- **Cancelling a background subagent** is possible through the local opencode server: read the password from `~/.config/opencode/service.json`, then `POST http://127.0.0.1:<port>/api/session/<id>/interrupt` with basic auth `opencode:<password>`. The port is on the `opencode serve --service` process.
- **Skill locations:** `~/.agents/skills/` is the shared install target; `npx skills@latest list -g --json` reports the agent list and source.
- **`code-review` needs a spec for its second axis.** Without one, run Standards only and say so; do not invent the spec from commit messages.
- The full mipsel link cannot be run on this host: no Docker and no `mipsel-linux-musl-gcc`.

## Not verified

- Hardware: cold boot with the new `S99usbserial` one-shot hook, a flashed image, USB DAC / Storage / USB Audio entered **after** USB Debug, macOS/Windows enumeration.
- A full `mq_ui` cross-build (see above); verification is host tests plus syntax/static analysis.

## Standing instruction

From 2026-11-12 the user wants **every session documented in `~/claude-research` and pushed**. This file is the first under that rule. The rule is also recorded in `~/.claude/CLAUDE.md` and `~/.config/opencode/AGENTS.md` so both agents pick it up.
