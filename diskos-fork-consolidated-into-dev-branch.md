---
type: how-to
tags: [diskos, snowsky-disc, git, branches, fork, merge, hot-load, wrong-base]
created: 2026-10-27
last_verified: 2026-10-27
status: current
---

# diskOS fork: everything merged into one `dev` branch (and why work had been on the wrong base)

Fork `txtsamu/diskos` (clone `~/diskos/diskos`; remotes `origin` = fork, `upstream` = b0hemia/diskOS, `disco` = zmd22/diskos-disco). Companion docs: [[diskos-stock-plus-round-screen-features-and-flash]], [[diskos-persistent-debug-checkboxes]], [[diskos-ui-architecture-review-output-sequencer-design]].

## How it was found

The `outseq` refactor, the test builds and Persistent debug were done on `fix/usb-dac-workmode` (the Oct 19 line), while the build flashed on Oct 22 was `stock-plus-disco`. Hot-loaded builds therefore replaced the flashed UI with one that lacked the Oct 22 fixes. Checks that showed it:

```bash
cd ~/diskos/diskos
git remote -v                                    # origin = txtsamu/diskos, disco = zmd22/diskos-disco, upstream = b0hemia
gh repo list --json name,isFork,parent,pushedAt  # the fork and its parent
git ls-remote --heads origin                     # 4 branches: main, fix/usb-dac-workmode, stock-plus-disco, disco-with-fixes
git log --oneline fix/usb-dac-workmode..stock-plus-disco   # 19 commits missing from my base (hairline fix 3d9d2a3, round glass, DAC exit/volume, ...)
git log --oneline stock-plus-disco..9b3a7c7                 # 3 commits only on the old branch
git merge-base fix/usb-dac-workmode stock-plus-disco        # 83fd21d, the Oct 19 split
```

Past Claude sessions (`~/.claude/projects/-home-moo-diskos-diskos/*.jsonl`) were all on `fix/usb-dac-workmode`; the Oct 22 session that built `stock-plus-disco` used the `~/diskos/diskos-stock-plus` worktree, so later sessions never saw it.

## What was done

```bash
git switch -c dev stock-plus-disco
git merge --no-ff feat/persistent-debug     # brings fix/usb-dac-workmode + outseq + Persistent debug + picker order
# conflicts were list unions only: ui/Makefile APP_SRCS (+ outseq.c), ui/tests/Makefile, ui/main.c includes
python3 -I ui/tests/outseq_guard_test.py    # failed on one new literal: main.c dac_exit_begin 0642 0
#   -> outseq_gadget_none() (same must-land behaviour), commit "USB DAC ordered exit: send the gadget frame through outseq"
git merge -s ours --allow-unrelated-histories --no-ff disco-with-fixes feat-cmd-guard feat-no-phonehome \
    feat-round-home feat-round-kb feat-round-lists worktree-agent-*          # history kept, tree unchanged (checked)
for b in <all old tips>; do git merge-base --is-ancestor $b dev; done          # 21 of 21 reachable, before any deletion
git push -u origin dev
git push origin --delete disco-with-fixes fix/usb-dac-workmode stock-plus-disco
```

Result: the fork has `dev` (`1d9e894`, 317 commits, merge with 11 parents at the tip) and `main` (still upstream v1.2.1, GitHub default, untouched). No open PRs referenced the deleted branches.

## Workflow from here (the user's rule)

All work on `dev`. Push to `main` only when the user is satisfied with the flash result:

```bash
git push origin dev:main      # only after the user says the flashed build is good
```

(`main` is behind `dev` by history it does not share; a fast-forward works because `dev` contains `main`.)

## Build and deploy of `dev`

```bash
cd ~/diskos/diskos/ui
podman run --rm --userns=keep-id -v "$PWD:/src:Z" localhost/diskos-ui-builder:latest \
  sh -c 'make clean >/dev/null; make -j4 CROSS=$CROSS EXTRA_CFLAGS=-DDISKOS_TEST_OUTPUTS'   # md5 fe2ab28e…
# hot-load: copy of tools/diskos-deploy.sh with SSH=(ssh) and "root@$IP" -> disc (key login, Host disc 192.168.50.57:2222)
```

Host tests on `dev`: `outseq_test` 18 sequences + Bluetooth sink OK, `outseq_guard_test.py` OK, `ipc_guard_test` OK. Not run: ASan/UBSan (missing runtime libs), a flash of this build. The local branches (`fix/usb-dac-workmode`, `refactor/outseq`, `feat/persistent-debug`, `feat-*`, `worktree-agent-*`) and the side worktrees still exist locally; they are all contained in `dev`.
