---
type: investigation
tags: [diskos, snowsky-disc, boot, ipc, starting-state, wifi, timezone, ota, phonehome, dhcp, ssh]
created: 2026-11-10
last_verified: 2026-11-10
status: current
---

# diskOS boot: "Starting" state instead of player errors, and what the boot-time "internet errors" really are (2026-11-10)

Repo `/home/moo/diskos/diskos`, branch `dev`. Two requests after the user enabled debug on the Disc: "check the logs error on internet and see if we can fix it" and "the player error at the start is annoying because I don't know if the system is still booting". Related: [[diskos-persistent-debug-checkboxes]], [[diskos-hotload-gotchas-test-outputs-usb-storage-reboot]], [[diskos-disc-hotload-watchdog-snowsky-logo-hang]], [[fiio-snowsky-disc-diskos-flash-fedora]].

## Time estimate

Measured: reaching the Disc and first log pass about 5 min; the internet diagnosis agent 8.6 min (518 s, 45 tool calls); the boot-state agent 14 min (844 s, 73 tool calls: code, host tests, podman build, hot-loads, screenshots); my verification (tests, diff, merge) about 2 min. A flash for a real cold-boot check is not done: see "Not verified".

## Step 0: the Disc had a new address

`ssh disc` failed with `No route to host`: DHCP moved the Disc from 192.168.50.57 to 192.168.50.29 (lease time 1800 s). Found by scanning the LAN and comparing host keys, not by trusting the new address:

```bash
nmap -p 2222,22 --open 192.168.50.0/24        # 192.168.50.29 had 2222 open (dropbear)
ssh-keygen -F '[192.168.50.57]:2222'           # known entry (ed25519 AAAAC3...IArsW2zU...)
ssh-keyscan -p 2222 192.168.50.29              # same ed25519 key => same device
cp ~/.ssh/config ~/.ssh/config.bak-20261110
sed -i '/^Host disc$/,/^Host /{s/HostName 192.168.50.57/HostName 192.168.50.29/}' ~/.ssh/config
ssh-keyscan -p 2222 -t ed25519 192.168.50.29 | sed 's/^192.168.50.29/[192.168.50.29]:2222/' >> ~/.ssh/known_hosts
```

Still DHCP: a MikroTik static lease for the Disc's MAC would make it permanent (not done).

## Logs: what was and was not an error (this boot, 17:26)

Pulled with `ssh disc 'grep -n -i -E "error|fail..." /usr/data/diskos_boot.log'`, `fiio_player.log`, `dmesg`, `diskos_journal.log`. `diskos_boot.log` accumulates across boots, so most "errors" were repeats. No player/UI restart since 10-31 (`/usr/data/fiio/log/process_failed.txt`). Persistent debug was on (`pdbg=1`, `diskos-debug.sh status`: SSH=on KEYSSH=on).

### Boot-time "internet" errors: all harmless, none needs a code fix

| Error | Cause | Evidence | Action |
|---|---|---|---|
| `set_local_time.c: get timezone failed` x5 within about 25 ms | Boot race: the stock player runs `curl ipinfo.io/timezone` (popen, 5 tries) before the default route and DNS exist, and never retries | Disc has working internet now: `curl -s -m 8 ipinfo.io/timezone` gave `Asia/Jakarta` in 0.37 s. Timing: failures start 0.25-1.04 s after the IP event, the 5 successes in all logs came 1.5-5.7 s after it. Not reproduced (needs a reboot) | none; saved timezone persists |
| `util.c:431 read route buf fail` | Same race; also fires after Wi-Fi reconnects (154 times on 10-31) | `ip route show default | awk` returns nothing until udhcpc adds the route | none |
| `ota_update.c ... get_ota_server_version fail`, `get bt ota server version: 0` | Intentional: diskOS "Block FiiO update checks" (`block_fiio_checks=1`) maps `discpick.fiio.net` and `fiio-bluetooth.fiio.net` to 127.0.0.1 in `/etc/hosts` (`ui/phonehome.c`) | vendor server alive: `curl -sI https://discpick.fiio.net/ota_patch_user.json` gave 200 with JSON. `/usr/data/fiio/ota_patch.json` is 0 bytes | leave; turning the block off would remove the errors and restore phone-home |
| `ls: /etc/product_version/*/: No such file or directory`, `check product is , start wifi config` | Stock `/usr/bin/wifi_up.sh` bug (no subdirectory in `/etc/product_version/`); only effect is DHCP hostname `FIIO_` | rootfs is read-only squashfs | ignore |
| `Failed to kill daemon: No such file or directory` | `avahi-autoipd -k` in `/usr/share/udhcpc/default.script`, no autoipd running | `strings /usr/sbin/avahi-autoipd` | ignore |

Other stock-player boot noise, same on 11-07 and earlier, not new: `mount failed with exit code 255, retry use ntfs`, `out_dev=USB_HOST_NULL not support` / `audio_track_create error` / `start_local error`, `work mode NULL`; `dmesg`: `I/O error` on `mtdblock_bbt_ro4/ro7` (read-only partitions), a burst of `[dhd] ... failed -23` while the Wi-Fi chip starts (it then connects fine).

Side facts: the stock player overwrites the user's timezone file when ipinfo succeeds (`/usr/data/localtime` equals Asia/Jakarta, diskOS `tz_idx=11` is Bangkok; same offset, no visible effect). If the noise matters, Settings > System > Automatic Time off stops the ipinfo/NTP calls (the clock then relies on the RTC). A diskOS-side timezone re-fetch was rejected: it would add an ipinfo request, against the no-phone-home policy. Dead ends not pursued: patching `default.script`/`wifi_up.sh` (read-only rootfs, needs a reflash for no real gain).

## The "player error at the start": a Starting state

Cause (code + `diskos_journal.log`): the UI starts at u=7.3 s, the launcher execs the stock Player at u=9.4 s, the SD gate opens at u=9.6 s. In that window `local_playback_allowed()` is false, so taps got "SD card is not ready" / "Return to local playback first" / "Player is starting - try again", home showed "Not Playing / Library", and the log said `mq_open /player fail` and `ipc: player busy ... waits`.

Fix (branch `feat/boot-starting-state`, commit `38ac605`, fast-forwarded into `dev`, not pushed; 19 files, +309/-25):

- New `ui/bootstate.c/.h`: one predicate `bootstate_starting()`, true from UI start until `ipc_player_up()` and `sd_gate_settled()` are both true (real signals). Latched, so a later Player restart is not "starting". Give-up after `IPC_BOOT_HOLD_MS` (30 s, the existing IPC hold) so real failures still surface. Logs `boot: player ready after N ms` or `boot: gave up waiting after N ms (player up|not up, SD gate settled|pending)`.
- `ipc.c`: `mq_open /player fail` with ENOENT now reads `ipc: player not up yet, waiting for /player`; `player busy` now means the queue is open but full.
- `admit.c`, `sdio.c`, `transport.c`: the not-ready reasons go through `bootstate_reason()` and show "Starting up..." while the state is on; `toast.c` does not re-show it while visible; `home.c` shows "Starting..." / "Please wait" in the capsule when there is no track.
- `main.c` arms it after `ipc_start()` (skipped on a theme-reload relaunch), a 200 ms tick ends it and forces a home refresh.
- Docs: `comments.md`, `GLOSSARY.md` (repo rule: no comments in source).

Build and verify (commands):

```bash
cd ui/tests && CC=clang make run && CC=clang make run-py        # host tests, rc=0 both (re-run by me on the branch)
cd ui && podman run --rm --userns=keep-id -v "$PWD:/src:Z" localhost/diskos-ui-builder:latest \
  sh -c 'make CROSS=$CROSS EXTRA_CFLAGS=-DDISKOS_TEST_OUTPUTS'   # md5 fdd1c95e8016993e2e2a08ae6e9aaa17
~/diskos/diskos-hotload.sh ui/mq_ui                              # only after uptime >= 45 s and "reached main loop"
~/diskos/snowsky-shot.sh out.png                                 # screenshots
```

On the Disc (hot-loaded, no reboot): real build logged `boot: player ready after 705 ms` (Player was already up). To see the indicator a scratch build forced the Player signal to "never up": home showed "Starting... / Please wait", and after 30 s the log line `boot: gave up waiting after 30134 ms (player not up, SD gate settled)` and home returned to "Not Playing / Library". Screenshots in the session scratchpad (`.../scratchpad/shots/`).

## Follow-up: show the boot animation until ready (user request, same day)

The user asked to "just show the diskOS boot animation until it's ready to start playing" instead of the "Starting..." capsule. Branch `feat/splash-until-ready` (worktree `~/diskos/diskos-splashhold`), fast-forwarded into `dev` (`0f3c5a5`); `ui/splash.c` + `comments.md` only.

- The splash was a one-shot 2.4 s animation (`splash_start()` in `main.c`, after `bootstate_start()`). It is now two stages on the same integer timeline: stage 0 = t 0..1500 ms (ring drawn, light swept, hub warm, wordmark fully in), stage 1 = t 1500..2400 ms (wordmark fade, hub opens onto Home). When stage 0 ends, `splash_stage_done()` asks `bootstate_starting()`: if still starting it replays stage 0 (`splash_run(0, SP_INTRO)`, counted in `g_sp.replays`), else it runs stage 1 once and deletes the splash. Replay is bounded by bootstate's 30 s give-up. When everything is ready on the first pass the two linear stages add up to the old 2400 ms.
- Test on the Disc (hot-load only, never a reboot): real build, Player already up: `splash: 62 frames drawn in 2451 ms (0 intro replays while starting)` (the old one-shot was about 2427 ms). Scratch build with `.player_up` forced to a function returning 0 (temporary edit in `main.c`, reverted with `git checkout`): `boot: gave up waiting after 30042 ms (player not up, SD gate settled)` then `splash: 921 frames drawn in 31346 ms (19 intro replays while starting)`. Screenshots (`.../scratchpad/shots/anim-1.png`, `anim-3.png`) show the animation mid-loop: rings, spectrum light at a different angle in each frame, glowing hub, "diskOS" wordmark.
- Gotcha: with a charger attached the charging screen ("Charging / Tap to continue") is shown over the splash at boot, so screenshots only show it; the animation still runs underneath. To see it, dismiss the overlay during the loop: `ssh disc '/usr/data/tinj tap 180 180'`.
- Gotcha: a loop of 19 replays plus 3-4 screenshots goes past the Bash tool's foreground limit (it got moved to the background); run it with `run_in_background`.
- The "Starting..." capsule on Home and the "Starting up..." toast stay: they cover a theme-reload relaunch (no splash) and the moment after the splash if the 30 s give-up has not passed.
- Not verified: a real cold boot with the flashed build. Host tests were not re-run for this step: `splash.c` is not part of them, and the earlier full run was on the parent commit. The replay restarts from t=0, so the ring redraws and the wordmark re-fades on each pass (a visible replay, not a smooth loop); a smoother pulse would be a design change.
- The real build is hot-loaded on the Disc (md5 `07b0cd2cf24b3e727e17b276e0920ea0`) until the next reboot.

## Not verified

- A real cold boot with a missing Player queue and an unsettled SD gate: a hot-load lasts only until the next reboot, so the flashed `mq_ui` is still the old one. Flash `dev` (recipe in [[fiio-snowsky-disc-diskos-flash-fedora]]) and watch the first 10 s.
- The "Starting up..." toast on hardware (host tests only; tapping play would really control playback).
- Translations: the three new strings fall back to English (`strings.tsv`, `i18n_tables.c` not regenerated).
- Controls are not disabled during the window; commands still queue and deliver once the Player queue appears.
- The boot-race explanation for the timezone failures is supported by timing, not reproduced.

## References

- Internal: [[diskos-persistent-debug-checkboxes]], [[diskos-hotload-gotchas-test-outputs-usb-storage-reboot]], [[diskos-disc-hotload-watchdog-snowsky-logo-hang]], [[fiio-snowsky-disc-diskos-flash-fedora]]; repo `docs/PRIVACY.md` and `ui/phonehome.c` (what the block does). No external sources were used.
