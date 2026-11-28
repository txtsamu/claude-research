---
type: build-log
tags: [diskos, snowsky-disc, wifi, wifisup, dhcp, wpa-cli, refactor, ports-and-adapters, host-tests]
created: 2026-11-28
last_verified: 2026-11-28
status: current
---

# Extract Wi-Fi supervision and DHCP policy into `wifisup`

## Time estimate

About 18 minutes total, measured from the base commit `3ba4f39` (18:17:53 +0700) to the implementation commit `49373ed` (18:35:45 +0700). The final incremental `mq_ui` build took 51 seconds, measured from the build log (`11:33:30Z` to `11:34:21Z`). The full host test suite was not separately timed.

## Context

Repository: `/home/moo/projects/diskos/diskos-w6-wifisup`, worktree on branch `arch/w6-wifisup`, base `3ba4f39`. The base already had the deepened `command_spawn` module, so this change could use bounded capture and spawned children instead of ad-hoc `system()` calls.

This implemented finding #2 in the architecture review (`claude-research/2026-11-28-architecture-review.md` in the diskOS repo): move the Wi-Fi radio policy and the five-phase DHCP lease state machine out of the 1,232-line LVGL screen `ui/wifi.c` into a host-testable module.

## What changed

New module: `ui/wifisup.c` and `ui/wifisup.h`.

The module owns:

- Radio intent and boot reconciliation: `wifisup_init_intent`, `wifi_reconcile_poll`, `wifi_reco_decide`, `read_saved_radios`, `wifi_rfkill_blocked`, `wifi_effective`, and the `RECO_SETTLE_MS` / `RECO_GIVEUP_MS` / `RECO_WINDOW_MS` windows.
- The lease state machine: `WIFISUP_LEASE_NONE`, `RELEASE`, `ACQUIRE`, `READY`, `FAILED`, with `/proc` inspection, `wpa_cli -a` event lines, `SIGUSR1` / `SIGUSR2` to `udhcpc`, and the 100 ms to 4 s backoff.
- Radio supervision `wifisup_supervise`, connectivity verdict `wifisup_connectivity`, and saved-network sanitizing `wifisup_sanitize_savenets`.

The module has no LVGL and no `system()` calls. Everything external arrives through `struct wifisup_env`: time, config, saved radio status, Player generation, shell capture and run, `wifi_up.sh` / `wifi_down.sh`, `wlan0` IPv4 state, process signals, the event helper spawn/poll/abort, and the UI side effects (`screen_is`, `scan_fill`, `info_refresh`, and the current SSID).

`ui/wifi.c` kept the LVGL picker and info screens, the connect and forget user actions, status parsing, scan ordering, and the radio object. It now calls `wifisup_*` for policy and exports five UI hooks (`wifi_ui_conn_active`, `wifi_ui_scan_active`, `wifi_ui_ssid`, `wifi_ui_scan_fill`, `wifi_ui_info_refresh`).

`ui/main.c` defines the device and UI adapter `g_wifisup_env`, calls `wifisup_set_env`, and uses `wifisup_init_intent()` and `wifisup_supervise()` at the old `wifi_init_intent()` / `wifi_supervise()` call sites. The `wifi_connectivity()` wrapper remains for `weather.c`.

## Verification

Host test suite:

```console
$ make -C ui/tests check
...
--- wifisup ---
radio reconcile (gen 1): accepted stock's Bluetooth-priority boot, wifi_on=0
radio reconcile (gen 1): saved Bluetooth off, released boot hold
wifisup_test: ok
...
make -C ui/tests check exit=0
```

Cross build:

```console
$ PATH=/opt/mipsel-n2008-musl-cross/bin:$PATH make -C ui -j2
...
artifact: mq_ui
md5: 239a359578d1c220fa4cb18f0c23b39c
size: 5527204
make ui exit=0
```

The only warning in the final build was the pre-existing `main.c:135` `-Wmisleading-indentation` in `ui_apply_swipe_thresh`, which is not part of this diff. `wifi.c`, `wifisup.c`, and the new test compile with no warnings.

Line count:

```console
$ wc -l ui/wifi.c
1232 ui/wifi.c     # before
$ wc -l ui/wifi.c
711 ui/wifi.c      # after
```

Commit:

```console
$ git show --stat --oneline 49373ed
49373ed wifi: extract supervision and lease policy into wifisup
 ui/main.c               |  96 +++++++-
 ui/tests/Makefile       |   6 +
 ui/tests/wifisup_test.c | 368 +++++++++++++++++++++++++++++
 ui/wifi.c               | 591 +++--------------------------------------------
 ui/wifi.h               |   5 +
 ui/wifisup.c            | 598 ++++++++++++++++++++++++++++++++++++++++++++++++
 ui/wifisup.h            |  78 +++++++
 7 files changed, 1184 insertions(+), 558 deletions(-)
```

The branch binary above was built on this branch alone. It was superseded when all seven findings were merged:
the integration build is 5,528,692 bytes, md5 `0285566576f46c79279c0d029bf51803`. The listener also gained back
`PR_SET_PDEATHSIG` through `command_spawn_lifetime()` after this note was written. See
[[diskos-architecture-review-seven-findings-2026-11-28]].

## Test design notes

`ui/tests/wifisup_test.c` uses a fake clock, a fake environment, a fake `/proc` tree, and a fake rfkill tree. The Makefile points `WIFISUP_PROC_ROOT`, `WIFISUP_RFKILL_ROOT`, and `WIFISUP_TMP_DIR` at `.tmp/wifisup_test`.

Covered cases:

- A valid initial boot lease (epoch 0, IP 1, idle) enters `READY` without a release or acquire signal.
- A network switch at epoch greater than 0 sends `SIGUSR2`, then `SIGUSR1`, then reaches `READY`.
- The first association wakes an idle `udhcpc` with exactly one `SIGUSR1`.
- `LEASE_NONE` is stepped on the 100 ms fast path and the actual status reads back off at 200, 400, 800, 1600, 3200, then 4000 ms.
- `DISCONNECTED` during `ACQUIRE` and during `RELEASE` moves to `FAILED`; a later `CONNECTED` retries.
- Bluetooth-priority boot reconciliation leaves `wifi_on=0` and never starts the radio.
- A saved Bluetooth-off record releases the boot hold and the radio starts.
- Connectivity returns `1` only for `READY` with matching intent epoch and Player generation, `-1` while unsettled, and `0` when Wi-Fi is off.

## Gotchas

- The lease retry reset compares the last input instant (`tick - inactive_time`). A fake clock that advances `now` but leaves `inactive_time` fixed looks like continuous user input and resets the backoff every step. The test therefore returns `now - input_at` from the fake, keeping the input instant constant.
- The event helper is now spawned with `command_spawn` through `/bin/sh -c "exec wpa_cli ... >/dev/null 2>&1"`. The old code used `fork`/`execl` with `PR_SET_PDEATHSIG`. Event parsing and the action script are unchanged, but the helper no longer dies with the UI parent if the UI is killed.
- `wifi_down.sh` is now started non-blocking and added to the shared deferred reap pool, per the task requirement. The old path blocked for up to 2 seconds.
- The module keeps the original `/proc` scans and rfkill read. On the host they are redirected with compile-time roots; on the device they read `/proc` and `/sys/class/rfkill`.

## Not verified

- No on-device Wi-Fi run. The build is cross-compiled only. Real `udhcpc` signal behavior, real `wpa_cli -a` event delivery, and the Bluetooth-priority race on hardware were not exercised.
- The event helper lifetime after a UI crash was not tested on the device.
- The test covers the policy state machine, not LVGL rendering or the radio widget.

## Related

- [[diskos-ui-deepening-six-modules-and-harness-2026-11-18]]
- [[diskos-srcswitch-source-mode-switch-extraction]]
- [[diskos-codebase-audit-fixes-2026-11-28]]
