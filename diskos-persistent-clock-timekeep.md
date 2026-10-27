---
type: troubleshooting
tags: [diskos, snowsky-disc, rtc, clock, hwclock, ntp, timezone, boot, timekeep]
created: 2026-10-27
last_verified: 2026-10-27
status: current
---

# diskOS: the Disc's clock "goes back to a random time" - how the clock is set at boot, and the last-good-time fix

Request: make the clock persistent, "sometimes it goes back to random time". Fork `dev`, commit `1a098a8` (`ui/timekeep.{c,h}`, glue in `ui/main.c`). Companion docs: [[diskos-hotload-gotchas-test-outputs-usb-storage-reboot]], [[diskos-persistent-debug-checkboxes]].

## What the Disc does with the clock (read from the device and the code)

```bash
ssh disc 'date; hwclock -r; hwclock -r -u; ls -l /dev/rtc0 /etc/localtime; cat /etc/init.d/S01time_correct /etc/init.d/S49ntp; cat /etc/ntp.conf'
```

- The RTC (`/dev/rtc0`, `10003000.rtc`) stores **local time** (WIB, UTC+7): `hwclock -r` printed 13:34:50, `hwclock -r -u` 20:34:50. `/etc/localtime -> /usr/data/localtime` (TZif, user-selectable in Settings).
- The kernel loads the RTC at boot as if it were UTC, so the system clock starts **7 h wrong**. Proof: files written by early init scripts have mtimes 7 h ahead (`ls --full-time`: `/tmp/.diskos_boot_select` 20:05:20 vs real boot 13:05).
- `/etc/init.d/S01time_correct`: `if year < 1980: date -s "2026-01-01 00:00:00"` - what an RTC that lost power turns into.
- `/etc/init.d/S49ntp`: `ntpd -g` with `*.cn.pool.ntp.org` servers; it can only help once Wi-Fi is up, and diskOS starts radios **off** every boot (`main.c`, see the Persistent debug doc), so it often never runs.
- diskOS (`ui/main.c`): `hwclock -s` at UI start (bounded to 6 s), then `hwclock -w` every 5 min and before a restart. The stock player saves the RTC only on its own power-off path.

So a failed or timed-out `hwclock -s` leaves the clock 7 h ahead and the next `hwclock -w` writes that into the RTC for good, and a power-lost RTC becomes 2026-01-01 with nothing to correct it. Not proven which of these produced the user's "random time"; the fix covers both, and logs enough to tell next time.

## Fix: keep the last good time in a file

`ui/timekeep.c`: `/usr/data/diskos_time` holds one epoch (atomic temp + fsync + rename; never written for a clock below 2026-01-02 or garbage). `timekeep_boot()` runs right after `hwclock -s`: (1) if the system clock differs from the RTC (read with `ioctl RTC_RD_TIME`, as local time) by more than 2 min, follow the RTC; (2) if the clock is more than 2 min behind the saved time, `settimeofday(saved)` and `hwclock -w`. A 30 s tick saves every 10 min and at once when the wall clock steps against `CLOCK_MONOTONIC` by more than 5 s (NTP, a hand-set time); also saved on Date & Time > Set, before a restart and before a shutdown. Every decision is logged:

```bash
ssh disc 'grep "clock:" /usr/data/diskos_boot.log; cat /usr/data/diskos_time'
#  clock: 1793083104 ok (saved 0)
#  clock: 1767200403 is behind the saved 1793083104, restoring the saved time
#  clock: stepped by 23 s (now 1793083157)
```

Trade-off: the restored time is behind real time by up to the save interval (10 min) plus the time the Disc was off; NTP (Wi-Fi on, e.g. with Persistent debug) steps the rest. A clock that jumps *forward* wrongly cannot be detected this way.

## Tests

```bash
cd ~/diskos/diskos/ui/tests && make -B timekeep_test CFLAGS='-g -O1 -Wall -Wextra' && ./timekeep_test   # timekeep_test: ok
```
Covers round trip, atomicity, rejects (1970, below the floor, garbage, overflow), malformed files, and the restore rule including the 7 h mix-up. (ASan/UBSan runtime libs are missing on this box, so the sanitizer flags in the Makefile fail to link here.)

On the Disc, simulating a power-lost RTC (ntpd stopped for the test, restarted after):

```bash
ssh disc '/etc/init.d/S49ntp stop; date -s "2026-01-01 00:00:00"; hwclock -w'   # wrong system clock AND wrong RTC
# restart mq_ui (hot-load) -> log: "clock: 1767200403 is behind the saved 1793083104, restoring the saved time"
ssh disc 'date; hwclock -r; /etc/init.d/S49ntp start'    # 13:38:30 in both (real time 13:38:54), ntpd stepped the last 23 s
```
Not tested: a real power loss or a reboot (the build is hot-loaded, so a reboot returns the flashed UI); `hwclock -s` actually failing.
