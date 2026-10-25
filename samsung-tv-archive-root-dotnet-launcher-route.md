---
type: investigation
tags: [samsung, tizen, tv, root, sdb, dotnet, archive-root, capabilities, smack, uep, reverse-engineering]
created: 2026-10-23
last_verified: 2026-10-25
status: in-progress
---

# Samsung TV root: the archive-root (dotnet-launcher) route is viable on Tizen 5.5

> **Paths relocated (2026-10-25):** `~/kants2-exploit` → `~/archive/samsung-tv-t6500-2026-10/exploit-src/kants2-exploit`; `~/samsung-tv-root-src` → `~/archive/samsung-tv-t6500-2026-10/tooling/samsung-tv-root-src`.

Device: Samsung **UA43T6500AKXXD** (2020 T6500, `20_KANTS2_FHD`, Tizen 5.5, armv7l,
kernel `4.1.10`, build `T-KTS2UABC-REL-202607281700`), 192.168.50.31.

Follow-up to `samsung-tv-root-exploit-compatibility-probe.md` (which wrongly
dismissed the archive-root route) and `samsung-tv-remotepc-cifs-root-route.md`
(the working one-shot). This documents a **deterministic, no-UI userland root
route** that supersedes the Remote PC/CIFS route if the last step is closed.

## TL;DR

The `archive-root` method from `chris-ritsen/samsung-tv-root` (re-verified on
Tizen 9.0 by `DemonKingSwarn/samsung-tv-tizen-root`) **is viable on this Tizen
5.5 TV**. The earlier probe rejected it because it checks `/usr/bin/dotnet`,
which does not exist here — the actual capability-bearing launcher is
`/usr/bin/dotnet-launcher`. All prerequisites are present. The only open item is
the exact direct invocation of `dotnet-launcher` that runs a managed DLL *with*
`CAP_SYS_ADMIN` retained.

## The chain (from chris-ritsen + Swarn)

1. SDB package-name injection (SVE-2025-50109) → uid 901 sdk shell (already have).
2. Run a managed assembly through a binary carrying `cap_sys_admin`.
3. In managed code: `unshare(CLONE_NEWNS)` + `mount --make-rprivate /`, then
   bind-mount our own `public.pem` over `/usr/share/sdbd/public.pem` and our own
   `passwd` over `/etc/passwd`.
4. Invoke `/usr/sbin/sdbd-tarlauncher --package_name X -xzf <our.tar.gz>
   --to-command=/bin/sh` — it verifies the archive signature against the
   (bind-mounted) key and runs `launch.sh` **as root**.
5. `launch.sh` execs a root agent that calls back over an HMAC channel.

No kernel bug, no memory corruption, no signature forgery.

## Verified prerequisites on this TV

| prereq | state |
|---|---|
| `getcap /usr/bin/dotnet-launcher` | `cap_setgid,cap_setuid,cap_setpcap,cap_sys_chroot,cap_sys_ptrace,cap_sys_admin,cap_mac_override,cap_mac_admin +eip` ✅ |
| `getcap /usr/bin/dotnet-launcher-inhouse` | `cap_setgid,cap_setuid,cap_setpcap,cap_sys_chroot,cap_sys_ptrace,cap_sys_admin,cap_mac_override,cap_mac_admin +ei` ✅ |
| `getcap /usr/sbin/sdbd-tarlauncher` | `cap_setgid,cap_setuid +eip` ✅ |
| `tar --to-command` | supported ✅ |
| `/usr/share/sdbd/public.pem` | present (451 bytes) ✅ |
| .NET runtime | `3.0.0` only (`/usr/share/dotnet/shared/Microsoft.NETCore.App/3.0.0`); no `/usr/bin/dotnet`, no 3.1/6.0 |
| sdk shell `CapEff` | `0000000000000000` (empty), `CapBnd=0000003fffffffff` (full bounding set) |

`.NET 3.0` is the one real deviation from upstream: chris-ritsen ships net6.0 and
netcoreapp3.1 payloads. A netcoreapp3.0 build is required (the host .NET 9 SDK
builds netcoreapp3.0 fine — verified with a `captest` probe DLL).

## The blocker: caps are dropped by the app framework

Two ways to run managed code were tested:

1. **As a signed TPK app** (`samudntest01.DnTest`, `type="dotnet"`,
   `exec="dntest.dll"`). When launched, the app process reports
   `Uid: 5001`, `CapEff: 0000000000000000`, `CapBnd: 0000000300200040`.
   The app framework invokes `dotnet-launcher` with `__AUL_TARGET_UID__=5001`,
   and the resulting `setuid(5001)` clears all capabilities. **Dead end for
   caps**, but proves a plain `static int Main()` console assembly runs fine
   under `dotnet-launcher`.

2. **Directly as uid 901**: `dotnet-launcher <dll>` and
   `dotnet-launcher --standalone <dll>` both return `rc=0` but produce no output
   and do not execute the DLL's `Main` (no `HELLO` from the probe). The exact
   argument contract is not yet reverse-engineered.

### Captured launch format (from `/proc/<pid>/cmdline` of the running app)

```
dotnet-launcher samudntest01.DnTest --standalone /opt/usr/apps/samudntest01/bin/dntest.dll \
  `zaybxcwdveuftgsh` \
  __AUL_STARTTIME__ <b64> __AUL_TARGET_UID__ <b64=5001> __APP_SVC_PKG_NAME__ <b64> \
  __AUL_CALLER_PID__ <b64> __AUL_CALLER_UID__ <b64=5001> __K_RELOCATE_BELOW <b64> \
  __K_SPLASH_SCREEN <b64> Title <b64> IconPath <b64> USE_DISKCACHE <b64> \
  __AUL_HWACC__ <b64> __AUL_ROOT_PATH__ <b64=/opt/usr/apps/samudntest01> \
  __AUL_INTERNAL_POOL__ <b64> __AUL_API_VERSION__ <b64=5.5> __AUL_IS_GLOBAL__ <b64> \
  __AUL_INSTALLED_STORAGE__ <b64=internal>
```

argv[0] is the appid. The `__AUL_*` values are base64 of a Tizen bundle
(`<len><type><name><value>`). `--standalone <dll>` is the entry assembly.

## Next step (open)

Reverse-engineer `dotnet-launcher`'s argument handling (exfiltrate the 61 KB
binary and decompile with `rea`/Ghidra) to find the minimal direct invocation
that (a) runs the DLL's `Main`, and (b) does not `setuid`, so the file
capabilities survive. Candidate knobs: omit `__AUL_TARGET_UID__`, or pass it as
`0`; the magic token `` `zaybxcwdveuftgsh` ``; `__AUL_ROOT_PATH__` pointing at the
DLL's directory (so `runtimeconfig.json`/`deps.json` resolve).

### Progress so far on the invocation

- The `__AUL_*` values decode to a Tizen bundle entry:
  `<u32 total_len><u32 0x401><u32 name_len><name\0><u32 val_len><value\0>`,
  base64-encoded. A Python helper reconstructs them (e.g. `__AUL_ROOT_PATH__`
  for the staging dir).
- **argv[0] is the appid** (the app framework execs with argv[0] =
  `samudntest01.DnTest`, not `dotnet-launcher`). Running the binary directly
  (`argv[0]=dotnet-launcher`, args `captest --standalone <dll> …`) returns rc=0
  and runs nothing. Running with `exec -a captest …` (argv[0] set to the appid)
  changes the result to rc=1 — so argv[0] is parsed, and the launch is now
  attempted but still fails (missing token / more `__AUL_*` keys).
- The magic token `` `zaybxcwdveuftgsh` `` (literal backticks) is the next
  candidate to add; it must be escaped when the command passes through bash.
- `dotnet-launcher` logs to `/tmp/dotnet_error.<pid>.<ts>.log` (usually empty).

Then: rebuild `SamsungTvArchiveRoot.dll` for netcoreapp3.0, adapt
`archive_root.py` to use `dotnet-launcher` (or a tiny shim that execs it with the
right argv), and run the chain.

Then: rebuild `SamsungTvArchiveRoot.dll` for netcoreapp3.0, adapt
`archive_root.py` to use `dotnet-launcher` (or a tiny shim that execs it with the
right argv), and run the chain.

## Fallback (still works)

The Remote PC/CIFS route (`samsung-tv-remotepc-cifs-root-route.md`) already
produced a verified uid=0 callback. It is UI-driven (one Shared Folder click per
root) and the click toggles mount/unmount, so a clean re-trigger needs a fresh
RDP session. Keep it as the fallback.

## Files / artifacts

- `~/samsung-tv-root-src/` — chris-ritsen checkout (`src/samsung_tv_root/archive_root.py`,
  `payloads/common/SamsungTvArchiveRoot.cs`, `payloads/common31/`)
- `/tmp/swarn-root/` — `DemonKingSwarn/samsung-tv-tizen-root` checkout
  (`ROOTING-RESEARCH.md`, `tools/`, `evidence/`)
- `/tmp/captest/` — netcoreapp3.0 probe DLL (`Program.cs` prints `/proc/self/status`
  caps; pushed to `/home/owner/share/tmp/sdk_tools/captest/`)
- `~/kants2-exploit/` — `tvsh.py` (uid 901 injection shell), `tvshell.py` (TPK TCP
  shell), `rootlisten.py` (root callback catcher, port 4444), `dntest/`

## References

- [chris-ritsen/samsung-tv-root](https://github.com/chris-ritsen/samsung-tv-root) — archive-root method, payloads, root-agent protocol
- [DemonKingSwarn/samsung-tv-tizen-root](https://github.com/DemonKingSwarn/samsung-tv-tizen-root) — independent Tizen 9.0 reproduction + the three model adaptations (§6 of `ROOTING-RESEARCH.md`)
- [sebastianspicker/tiz0wn](https://github.com/sebastianspicker/tiz0wn) — Remote PC/CIFS route (fallback), Mali CVE dead ends
- [califio/MADBugs](https://github.com/califio/publications) — ntksys physmap chain, dead on this firmware
