---
type: investigation
tags: [samsung, tizen, tv, root, dotnet, dotnet-launcher, aul, capabilities, tizen-source, armv7l, reverse-engineering]
created: 2026-10-23
last_verified: 2026-10-23
status: current
---

# Samsung TV root: the `dotnet-launcher` standalone invocation, solved from Tizen source

Device: Samsung **UA43T6500AKXXD** (2020 T6500, `20_KANTS2_FHD`, Tizen 5.5, armv7l,
kernel `4.1.10`, build `T-KTS2UABC-REL-202607281700`), 192.168.50.31.
Host: fedora, 192.168.50.20.

Follow-up to
[`samsung-tv-archive-root-dotnet-launcher-route.md`](samsung-tv-archive-root-dotnet-launcher-route.md),
which left one open item: the exact `dotnet-launcher` invocation that runs a managed
DLL *with* its file capabilities intact. That item is now answered — not by
decompiling the 61 KB binary, but by reading Samsung's published source for it.

## TL;DR

`dotnet-launcher --standalone <dll>` is gated by two `aul` calls that are fatal on
failure, and **both short-circuit on environment variables** (`AUL_APPID`,
`AUL_ROOT_PATH`). With those set, an unprivileged `uid=901` process can run a
managed assembly inside the cap-bearing launcher without app-service, without the
app database, and without a UI. That is the missing first step of the archive-root
chain on a TV that has no `/usr/bin/dotnet`.

## Where the answer came from

Samsung ships the real source in Tizen snapshot source RPMs. For Tizen 5.5:

```sh
BASE=https://download.tizen.org/snapshots/TIZEN/Tizen-5.5/Tizen-5.5-Unified/latest/repos/standard/source
curl -sLO $BASE/dotnet-launcher-3.1.0-1.src.rpm
curl -sLO $BASE/aul-0.23.7-1.src.rpm
rpm2cpio dotnet-launcher-3.1.0-1.src.rpm | cpio -idmv   # dotnet-launcher-3.1.0.tar.gz + .spec + .conf
rpm2cpio aul-0.23.7-1.src.rpm            | cpio -idmv   # aul-0.23.7.tar.gz + manifest + .spec
```

Extracted on fedora at `~/tv-src/dotnet-launcher-3.1.0` and `~/tv-src/aul-0.23.7`
(60 and ~300 files respectively). This is faster and more reliable than RE: five
minutes of reading versus a Ghidra session, and it is authoritative.

## Parity check: the live binary is this code

Two independent confirmations that the Tizen 5.5 source matches the TV binary
(exfiltrated earlier to `/tmp/dotnet-launcher`, 61,782 bytes, ELF 32-bit ARM, not
stripped):

```text
$ arm-linux-gnueabihf-nm -C /tmp/dotnet-launcher | grep -e " T main" -e Option
0000331c T main
0001a408 b PaddingOption
0001a3f0 b StandaloneOption

$ rea decompile /tmp/dotnet-launcher 0x331c --format json   # .normalized_result
void main(undefined4 param_1,undefined4 param_2)
{
  realMain(param_1,param_2,"default");
  return;
}
```

`realMain(argc, argv, "default")` is `NativeLauncher/hydra/hydra_main.cc`'s shape
(`dotnet-hydra-loader` → `dlopen` the launcher plugin → `realMain`), and
`StandaloneOption`/`PaddingOption` are the two file-static strings in
`NativeLauncher/launcher/exec/launcher.cc`. The binary also carries that file's
`_INFO` strings verbatim: `##### Run in standalone mode #####`, `AUL_APPID : %s`,
`Run in standalone mode`.

## What `--standalone` does (launcher.cc)

```c
static std::string StandaloneOption("--standalone");
for (int i = 1; i < argc; i++) {
    if (StandaloneOption.compare(argv[i]) == 0) { i++; standalonePath = argv[i]; }
    else if (PaddingOption.compare(argv[i]) == 0) { paddingExist = true; }
    else { vargs.push_back(argv[i]); }          // <-- every unknown arg is an app arg
}

std::unique_ptr<CoreRuntime> runtime(new CoreRuntime("standalone"));

if (AUL_R_OK == aul_app_get_appid_bypid(getpid(), appId, sizeof(appId))) {
    appRootPath = aul_get_app_root_path();
    if (appRootPath == nullptr) { _ERR("Fail to get application root path"); return -1; }
} else { _ERR("Fail to get app_id"); return -1; }     // <-- both gates are fatal
...
runtime->initialize(LaunchMode::launcher);
runtime->launch(appId, appRootPath, standalonePath, vargs.size(), &vargs[0]);
```

Points that matter:

- **The `__AUL_*` arguments need no decoding.** They are the app framework's own
  arguments, and `launcher.cc` treats every unrecognised argument as a plain app
  argument (`vargs`) forwarded to the assembly. The earlier session spent effort
  reconstructing the Tizen bundle encoding for `__AUL_ROOT_PATH__` etc.; that was
  unnecessary.
- **Standalone mode never calls `setuid`.** In app launches the process is already
  `uid=5001` because *app-service* execs it that way — not because the launcher
  drops privileges. Run the launcher yourself and the file capabilities
  (`cap_sys_admin…+eip`, verified earlier with `getcap`) are effective.
- `README.md` in the same tarball documents the intent: `--standalone [assembly
  path]` — "Run assembly with the current user environment."

## The unlock: both gates read environment variables (aul 0.23.7)

`src/pkginfo.c`:

```c
const char *__get_preinit_appid(void)
{
    if (!__appid) __appid = getenv("AUL_APPID");
    return __appid;
}

if (getpid() == pid) {                       /* in aul_app_get_appid_bypid_for_uid */
    preinit_appid = __get_preinit_appid();
    if (preinit_appid) { snprintf(appid, len, "%s", preinit_appid); return AUL_R_OK; }
}
```

`src/pkginfo.c` (`aul_get_preinit_root_path`) and `src/aul_path.c`
(`__get_path_from_db`):

```c
API const char *aul_get_preinit_root_path(void)
{
    if (!__root_path) __root_path = getenv("AUL_ROOT_PATH");
    return __root_path;
}

root_path = aul_get_preinit_root_path();
if (appid == NULL && root_path) {            /* taken before any app-DB lookup */
    snprintf(buf, ..., "%s%s%s", root_path, ..., dir_name ? dir_name : "");
    *path = strdup(buf); return AUL_R_OK;
}
```

So with `pid == getpid()` (always true for the launcher itself) and both variables
set, neither function ever talks to app-service or the app database.

## The invocation

```sh
AUL_APPID=samudntest01.DnTest \
AUL_ROOT_PATH=/home/owner/share/tmp/sdk_tools/probe \
/usr/bin/dotnet-launcher --standalone /home/owner/share/tmp/sdk_tools/probe/StandaloneProbe.dll
```

- Payload must target **netcoreapp3.0** — the TV only carries
  `Microsoft.NETCore.App/3.0.0`; upstream ships net6.0/netcoreapp3.1 payloads that
  will not load.
- `/usr/share/dotnet.tizen/framework/Tizen.Init.dll` must exist (the binary's own
  error string is `Failed to locate Tizen.Init.dll`) — unverified on this model,
  one `ls` away.
- The appid value itself only has to be a plausible string; it is used for
  `setCmdName`, `runtime->launch` and app-root derivation, not for an auth check.

### Test artifact (built, never executed)

`~/tv-src/standalone-probe/` on fedora: `probe.csproj` (`netcoreapp3.0`) and a
`Program.cs` that prints `Uid:`, `Gid:`, `CapEff:`, `CapBnd:`, the SMACK label from
`/proc/self/attr/current`, `argv[0]`, and both env vars. `dotnet build -c Release`
succeeds (host SDK 9.0.121, one `NETSDK1138` out-of-support warning).

Success criterion: `CapEff:` containing bit 21 (`0000000020000000` =
`cap_sys_admin`). Nothing has been run against the TV yet — it was powered off for
this whole session.

## Prior art: nobody has published this

Searched GitHub, the Tizen source mirrors and the published Samsung TV root
projects on 2026-10-23:

- **[chris-ritsen/samsung-tv-root](https://github.com/chris-ritsen/samsung-tv-root)**
  (`master`, pushed 2026-10-23T11:22Z): `src/samsung_tv_root/archive_root.py` runs
  **`/usr/bin/dotnet <payload>.dll`** and validates `getcap /usr/bin/dotnet` =
  `cap_setgid,cap_sys_admin`, expecting `/usr/share/dotnet.tizen/netcoreapp/`.
  Their TVs have the `dotnet` muxer; this model does not.
- **[DemonKingSwarn/samsung-tv-tizen-root](https://github.com/DemonKingSwarn/samsung-tv-tizen-root)**
  (QA55QEF1AULXL, Tizen 9.0, `T-RSLFUABC-0090-REL-202608061940`): same lever,
  `/usr/bin/dotnet` with caps plus `launchpad-starter`, full .NET 6 runtime.
- **[sebastianspicker/tiz0wn](https://github.com/sebastianspicker/tiz0wn)**: Remote
  PC/CIFS route and firmware static analysis; no `dotnet-launcher` work.
- The Tizen source itself is public but no write-up uses the `AUL_APPID` /
  `AUL_ROOT_PATH` preinit path to get capability-bearing managed code executed.

Conclusion: the `/usr/bin/dotnet` archive-root method is inapplicable to Tizen 5.5
T-series by construction, and the env-var route through `dotnet-launcher` appears to
be unpublished.

## Pitfalls

- **`sdb shell` exit codes are wrapper artefacts.** `launcher.cc` returns `-1` on
  the aul failures above, yet an injected command can still report `rc=0`. Judge by
  dlog (`_ERR("Fail to get app_id")`, `_INFO("AUL_APPID : %s")`), not by rc.
- **The TV's `dotnet-launcher` is a hydra dispatcher**, so a missing launcher
  plugin `.so` (the `dlopen` target) is a silent failure mode distinct from a bad
  invocation.
- Do not re-derive the `__AUL_*` bundle encoding; those are app arguments.

## Files

- `~/tv-src/dotnet-launcher-3.1.0-1.src.rpm`, `~/tv-src/aul-0.23.7-1.src.rpm`,
  extracted trees `~/tv-src/dotnet-launcher-3.1.0/`, `~/tv-src/aul-0.23.7/`
- `~/tv-src/archive_root.py` (upstream, for reference)
- `~/tv-src/standalone-probe/` — netcoreapp3.0 probe (`StandaloneProbe.dll`)
- `/tmp/dotnet-launcher` — the TV binary used for the parity check
- `/tmp/rea_dl_analyze.json`, `/tmp/rea_dl_main.json` — rea output

## Next step (deferred to next week)

Power the TV on, then one injection: confirm
`/usr/share/dotnet.tizen/framework/Tizen.Init.dll` exists, push the probe into
`/home/owner/share/tmp/sdk_tools/probe/`, run the invocation above, read `CapEff`
from the captured output or dlog.
