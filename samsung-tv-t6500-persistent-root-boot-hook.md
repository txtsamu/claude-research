---
type: how-to
tags: [samsung, tizen, kants2, t6500, persistence, root, profile.d, raw-block, uep, sdb]
created: 2026-10-25
last_verified: 2026-10-25
status: current
---

# Persistent root on the T6500: same-size raw-block patch of a boot-sourced profile.d script

Target: `UA43T6500AKXXD`, Samsung KantS2 / Novatek NT72172, Tizen 5.5, kernel 4.1.10 armv7,
firmware tag `20_KANTS2_FHD`.

**Result:** the TV executes root code **~1 s after every power-on** — no USB stick, no
computer, no sdb, no exploit. Verified on a real cold boot: `=== boot entry uptime=1s uid=0
ctx=_` followed by the full debloat re-apply. Root is no longer "on demand".

Companion docs: [samsung-tv-uep-bypass-and-kants2-root.md](samsung-tv-uep-bypass-and-kants2-root.md)
(root chain, UEP state word, debloat passes),
[samsung-tv-t6500-debloat-cold-boot-persistence.md](samsung-tv-t6500-debloat-cold-boot-persistence.md)
(the per-layer survival matrix this doc turns into automation).

## Where the idea comes from

[`cfloinc/samsung-q70t-tizen-root`](https://github.com/cfloinc/samsung-q70t-tizen-root) —
field notes on a `QN65Q70TAFXZA` (2020 Q70T, `20_NIKEM_QTV`, Tizen 6.0, `T-NKMAKUC-2743.0`).
Their `persistent-hook/` kit patches a vendor `/etc/profile.d` script **in place, at the raw
block level, at exactly the same byte length**, and gets a root hook at every boot because
`tizen-system-env.service` *sources* that directory as root.

That is the missing piece this project had been calling impossible: `/` is read-only vdfs and
refuses remount even as root, but the **block device underneath** is writable from a root
shell, and a same-size in-place edit changes no filesystem metadata at all.

## The chain

```
tizen-system-env.service        (active at boot: RequiredBy=ac.service, WantedBy=basic.target)
 └─ ExecStart=/usr/bin/env -i sh -c 'source /etc/profile'      (runs as root)
     └─ /etc/profile:66   for i in /etc/profile.d/*.sh; do . "$i"; done
         └─ /etc/profile.d/bash_prompt_custom.sh   <- patched in place (776 B)
             └─ [ -e /run/.tvroot-hook ] || ( wait for /opt/hermes/boot.sh; \
                  /bin/sh -c "$(cat /opt/hermes/boot.sh)" ) &      <- by CONTENT, UEP-safe
```

Two things to keep in mind: the hook must never `execve()` an unsigned file (UEP is armed at
boot — `[uep][bash] the file is NOT signed!!`), and everything it launches must be
backgrounded with `</dev/null` or it inherits the boot shell's descriptors.

`systemctl is-enabled tizen-system-env.service` answers **`disabled`** on this build and that
is a red herring: the enabling symlink ships inside the image at
`/usr/lib/systemd/system/basic.target.wants/tizen-system-env.service`. Confirm with
`systemctl show tizen-system-env.service -p ActiveState,WantedBy,RequiredBy` (`active` /
`basic.target` / `ac.service`) and with `/run/tizen-system-env`, which its ExecStart rewrites
on every boot.

## Preconditions, measured on this TV (2026-10-25)

| check | result |
|---|---|
| `tizen-system-env.service` | `ActiveState=active`, `SubState=exited`, `RequiredBy=ac.service`, `WantedBy=basic.target`; `/run/tizen-system-env` present |
| `/etc/profile` loop | line 66 `for i in /etc/profile.d/*.sh ; do … . "$i" …` |
| carrier file | `/etc/profile.d/bash_prompt_custom.sh`, **776 bytes**, sha256 `effe97f8…25e33c` — *byte-identical to the Q70T's own vendor file*, marker `alias lr="ls -ltrZ"` at offset **629** |
| rootfs device | `/dev/mmcblk0p18` (`root=/dev/mmcblk0p18 … rootfstype=vdfs ro`), `brw-rw---- root disk`, **opens O_WRONLY from a root shell** |
| rw partitions | `/opt` (p21), `/mnt/systemrw` (p20), `/mnt/drm` (p17) — vdfs rw, survive reboot |
| UEP at boot | armed; `sh /tmp/u.sh` → `[uep][bash] the file is NOT signed!!` |

Note the carrier file being identical across the two models: upstream's `SIZE`, `MARKER_OFF`
and `ORIG_SHA` constants are directly reusable. Addresses and block offsets are still per
device — never copy those.

## Locating the live copy

A device-wide search for the marker inside an injected command **wedges `sdbd`** (the capture
times out, the shell never returns, port 26101 keeps accepting TCP but `sdb connect` fails
until a mains power cycle). Run it detached instead, results into a file on `/opt`, and poll:

```sh
nohup sh -c '/bin/sh -c "$(cat /home/owner/share/tmp/sdk_tools/mali/scan_payload.sh)"' \
      </dev/null >/dev/null 2>&1 &
```

Payload body: `grep -abo 'alias lr="ls -ltrZ"' /dev/mmcblk0p18 > /opt/hermes/hits.txt`, then for
each hit `blk = (off-629)/512`. Result on this TV: **one hit only**, byte `523 973 237` =
512-block **1023384, block-offset 0** (the file starts block-aligned; the marker sits 629 bytes
into it). Verified by reading the block back: those 776 bytes hash to the vendor sha, so there
is no stale duplicate to disambiguate.

Do **not** hash candidates with `dd bs=1 skip=<huge>` — it reads byte-at-a-time and never
finishes. Convert to `dd bs=512 skip=<blk>` and trim inside the buffer.

## Building the patch

Upstream's `persistent-hook/build-patch.py` appends a hook fragment to *your own* vendor file
and pads with `#` so the result is exactly the original length; it walks a compaction ladder
(full body → minus alias lines → minus the whole `if [ "$PS1" ] … fi` prompt block) and refuses
to emit anything that fails `sh -n`.

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

## The write, and how each step was verified

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
flash changed, while `sha256sum /etc/profile.d/bash_prompt_custom.sh` after
`echo 3 > /proc/sys/vm/drop_caches` proves the **filesystem** now serves the patched bytes. If
that check fails the script restores the backup and reports the restore hash.

## What runs at boot

`/opt/hermes/boot.sh` (guarded by `/run/.tvroot-boot`, every payload passed by content):

1. log `uptime`, `uid`, SMACK label;
2. `sleep 20`, then run `debloat2.sh` (unit markers, 13 `pkgcmd -D` deactivations, stop +
   runtime-mask pass, service census);
3. run `debloat3_boot.sh` — the kill/deactivate half of `debloat3.sh` only;
4. **delayed stop pass A** at ~+70 s and **pass B** ~20 s later, then a per-unit census.

Pass 2 alone is not enough. `media-analytics-service`, `contents-recognition-service`,
`vision-data-recognition-service` and `kpi-logging` are restarted by their `.path`/`.timer`
triggers and by dependencies after the first stop, and a `/dev/null` runtime mask does not stop
an already-running unit — only prevent the next start. Upstream's kit solves it with one pass
at uptime 31 s; two passes plus a settle beat the triggers here.

`debloat3.sh` itself is **not boot-safe**: its verification section calls `app_launcher -s
<pkg>`, which *launches* the app rather than querying it, so the boot variant drops that half
and only does `pkgcmd -k` + `pkgcmd -D`.

## Cold-boot proof (first boot after the write, no host involved)

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
held 18 masks again; the launcher (`Clean Home`) came up normally and `:8001/api/v2/` answered,
so the patch is invisible to the user. The only failed unit is the vendor
`vdca-update.service` ("Check emp update of vdca.pem"), unrelated to this work.

## Rollback

```sh
sh /opt/hermes/rollback.sh
# restores the 2 blocks from /opt/hermes/backup/rootfs-p18-blk1023384-2.bin
# (sha 7d0f116e…), drops caches and prints the file sha
```

Worst case if the patch is ever wrong is a broken prompt/alias script, not a boot failure —
`tizen-system-env.service` only consumes the environment it produces. A **firmware update**
rewrites `/etc` and silently removes the hook; re-derive the block offset and re-verify the
vendor hash before re-applying.

## Gotchas

- **`sdb push` refuses `/opt/…`** (`You cannot push files to this path`). Push to
  `sdk_toolpath` and `cp` from the TV side as root.
- **Do not `reboot` from the host agent** — the tooling blocks system-reboot commands
  outright, and `reboot -f` from the injection prints `Must be root.` even at `uid=0`
  (systemctl/logind gating on SMACK `System`), although the box has reset when called that way.
  Pulling the wall is the reliable trigger.
- **`/proc/sysrq-trigger` does not exist** on this kernel, so there is no soft fallback.
- **Injection identity is not stable.** Two consecutive boots answered `uid=901(sdk)`; one
  boot after a FastRoot session answered `Uid: 0 0 0 0`, `CapEff ffffffffffffffff` from the
  unwrapped injection with UEP still armed and `/etc/profile.d` unpatched. Print `id -u`
  before choosing a chain and never assume either state.
- Root at boot does **not** mean UEP is off: the hook runs as root but unsigned `execve` is
  still refused, so every payload stays content-as-data.

## Files

TV (`/opt/hermes/`): `boot.sh`, `debloat2.sh`, `debloat3_boot.sh`, `rollback.sh`,
`backup/rootfs-p18-blk1023384-2.bin`, `backup/location.txt`, `boot.log`, `apply.log`.

Control host (`moo@fedora`, also committed under `samsung-tv-kants2-exploit/persistent-hook/`):
`build-patch.py`, `hook-fragment.sh`, `apply_hook.sh`, `boot.sh`, `debloat3_boot.sh`,
`rollback.sh`, `vendor-bash_prompt_custom.sh`.

## References

- [cfloinc/samsung-q70t-tizen-root](https://github.com/cfloinc/samsung-q70t-tizen-root) — the
  upstream `persistent-hook/` kit and `docs/methodology/08-boot-chain-and-persistence.md`
- [docs/methodology/06-uep.md](https://github.com/cfloinc/samsung-q70t-tizen-root/blob/main/docs/methodology/06-uep.md)
  — why only content-as-data works
- [chris-ritsen/samsung-tv-root](https://github.com/chris-ritsen/samsung-tv-root) — the
  `archive-root` route and the honest "root and UEP changes remain volatile" framing
