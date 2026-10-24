---
type: investigation
tags: [samsung, tizen, launcher, home-key, app-operation-api, uid-5001, kants2, blocked]
created: 2026-10-24
last_verified: 2026-10-24
status: blocked
---

# Making a custom launcher the Home target on Samsung Tizen (KantS2)

Goal: the user's own launcher (`tvunlock02.Launcher`) should come up as the TV's
default UI on power-on and on the remote's **Home** button. Blocked on one syscall:
the Samsung app-operation API has to be called as the TV owner (uid 5001), and this
box refuses to let the root payload become uid 5001.

Companion docs: [samsung-tv-clean-launcher-curation.md](samsung-tv-clean-launcher-curation.md)
(what the launcher itself filters), [samsung-tv-uep-bypass-and-kants2-root.md](samsung-tv-uep-bypass-and-kants2-root.md)
(the root primitive this relies on).

## How the Home target actually works

Stock behaviour does not come from a script or a systemd unit: the TV asks a
per-user setting *what should open for the `main` operation*, and the answer on a
stock set is `com.samsung.tv.csfs` (Smart Hub). That setting is reachable through
Samsung's native library:

```
/usr/lib/libcapi-appfw-app-operation-tv.so.0
  app_operation_get_current_app(const char *operation, char **app_id)
  app_operation_set_current_app(const char *operation, const char *app_id)
  operation = "http://tizen.org/appcontrol/operation/main"
```

Crucially this must run as the **TV owner: uid 5001, gid 100, supplementary groups
dropped** — the preference being read/written belongs to that user, not to root and
not to the injection identity (uid 901). Source for the mechanism and the uid
requirement: `berteotti/custom-tv`, `docs/2-set-as-home.md` plus
`tools/home-routing/Program.cs` (its own doc admits that persistence of the setting
across a cold reboot was never verified on their test set — so that is still an open
question here too).

## Implementation

`payloads/home-set.*` (source in
[../samsung-tv-kants2-exploit/payloads/home-set.Program.cs](../samsung-tv-kants2-exploit/payloads/home-set.Program.cs)),
built as a netcoreapp3.0 console app like the other payloads:

- logs to TCP `192.168.50.20:4558` and to `/tmp/homeset.txt` (the launcher swallows stdout);
- reads the current Home target;
- with `set <appId> [expectedCurrent]` it refuses unless the current value matches
  the expectation, writes, reads back, and rolls back on mismatch;
- escalates to root first if it did not start as root (cred-patch fallback over
  `/dev/ntkhdma`), because `setuid(5001)` needs privilege.

Run it the usual way (staged in the app-private dir — `dotnet-launcher` silently
refuses a DLL under `/opt`):

```sh
M=/home/owner/share/tmp/sdk_tools/mali
AUL_APPID=samudntest01.Mali AUL_ROOT_PATH=$M \
  /usr/bin/dotnet-launcher --standalone $M/HomeSet.dll
```

## Result: blocked on setuid(5001)

Read-only run, 2026-10-24 20:04 (log from `/tmp/homeset.txt` on the TV):

```
20:04:32 start uid=0
20:04:32 setuid(5001) failed
20:04:32 HOMESET_END
```

So the payload does run with real root (`start uid=0` — the earlier fast-root path
was still in effect), and `setgid(100)` succeeded, but the uid change is refused.
That is consistent with Tizen's LSM stack (SMACK + security-manager/CyNara) rather
than with missing capabilities: the process already has `CapEff ffffffffffffffff`,
SMACK label `System`, and `setgid` to a plain group is allowed.

The payload has since been extended (built, **not yet executed on the TV**) with:

- `__errno_location()` logging and the SMACK label of the process (`/proc/self/attr/current`),
- a `setresuid(5001,5001,5001)` retry after the plain `setuid` failure,
- a fallback that continues and calls the API anyway, to measure whether the uid
  actually matters for `get_current_app`.

## Next step (deferred)

1. Run the errno build; capture the exact failure (`EPERM` vs `EACCES`) and the
   reported SMACK label.
2. If the syscall stays refused, bypass it entirely: the DMA primitive already gives
   arbitrary physical read/write, so patch the calling task's own `struct cred`
   `uid/gid/euid/egid/fsuid/fsgid` from 0 to 5001 in DRAM (the reverse of the
   escalation step, same layout, same DRAM-only safety envelope) and then call the
   API — no syscall involved.
3. Only then test the real question: does the Home target survive a power cycle?
   That needs a user-initiated power cycle (agent-level reboots are blocked).
4. Also unresolved: whether a cold boot can launch the launcher at all before root
   exists — UEP re-arms on boot, so any boot-time hook must be something a *signed*
   vendor unit already runs, not our own binary.
