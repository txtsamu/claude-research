---
type: how-to
tags: [fiio, snowsky-disc, diskos, dap, ingenic, x2000, mask-rom, flashing, squashfs, udev, fedora, usb-dac, uac, podman, cross-compile, deadlock, ghidra]
created: 2026-10-19
last_verified: 2026-10-19
status: current
---

# Flashing diskOS onto a FiiO Snowsky Disc from Fedora 43

Installed [diskOS](https://github.com/b0hemia/diskos) **v1.2.1** (Public variant) onto a FiiO Snowsky Disc DAP running stock firmware **V2.57**, from the Fedora 43 desktop, using the CLI installer. Flash succeeded and verified (`result: 0x600DF10C [F001] SUCCESS`).

One real snag: the **bundled `mksquashfs` in the v1.2.1 Linux release crashes with SIGFPE** on this host, failing the installer's LZO self-check (E104). Fix was to move the bundled squashfs tools aside so the installer falls back to Fedora's system `squashfs-tools`.

## Prerequisites

- Official, unmodified FiiO firmware ZIP matching the version currently on the Disc. Supported bases: V2.09, V2.28, V2.40, V2.57. Used: `~/Downloads/SNOWSKY_DISC_update_20260909_v257.zip` (V2.57).
  - The on-device writer refuses to write (nothing touched) if the Disc's kernel/recovery doesn't match the selected firmware.
- Python ≥ 3.8 (had 3.14.7), `libusb1`, `squashfs-tools` (Fedora's 4.6.1 has LZO). `python3-tkinter` only needed for the GUI — skipped, used CLI.
- Good USB cable, ~20 min uninterrupted, host must not sleep (the installer uses `systemd-inhibit` itself).

## Steps

### 1. Put the Disc in mask-ROM (flash) mode

Power off, hold **Volume Down**, plug in USB. Screen stays black. Check:

```bash
lsusb | grep -i ingenic
# Bus 001 Device 015: ID a108:eaef Ingenic Semiconductor Co.,Ltd Ingenic USB BOOT DEVICE
```

### 2. Download + verify the installer

```bash
mkdir -p ~/diskos && cd ~/diskos
gh release download v1.2.1 -R b0hemia/diskos -p 'diskos-installer-linux-x86_64.tar.gz' -p SHA256SUMS
cat SHA256SUMS; sha256sum diskos-installer-linux-x86_64.tar.gz
# linux tarball: d4e0a37a01061235810a0ff817868faacbf692ccd67a4588c868d4b91267bca9 (matched)
tar xzf diskos-installer-linux-x86_64.tar.gz
cd diskos-installer
```

(`grep linux SHA256SUMS | sha256sum -c -` reported "no properly formatted checksum lines" — that was the rtk output-filter hook mangling the pipe, not a bad file; compared manually instead.)

### 3. Setup (no sudo)

```bash
./install.sh            # creates .venv, installs pyusb + pycryptodome
./diskos-installer doctor
```

Doctor reported two failures:

```
✗   squashfs LZO pack/extract check: FAILED - [E104] ... using '.../vendor/linux-x86_64/mksquashfs'
✗ device: this user cannot open it (/dev/bus/usb/001/015) - USB permissions
```

### 4. Fix E104 — bundled mksquashfs crashes

Reproduced the installer's exact check by hand:

```bash
S=$SCRATCH/sq; mkdir -p $S/src
head -c 300000 /dev/zero | tr '\0' 'a' > $S/src/p.bin
vendor/linux-x86_64/mksquashfs $S/src $S/p.sqfs -comp lzo -b 131072 -no-xattrs -all-root -noappend -processors 1
# ... 100% ... Floating point exception (core dumped)   rc=136
```

Same command with Fedora's `/usr/sbin/mksquashfs` + `unsquashfs` → rc=0, round-trip bytes identical. Not disk space (`/tmp` had 31G free).

`diskos_installer/bundle.py:native()` prefers a vendored tool if the file *exists* (even if broken), and only falls back to the system copy on PATH for squashfs tools when the vendored file is **absent**. So:

```bash
cd vendor/linux-x86_64
mv mksquashfs mksquashfs.broken
mv unsquashfs unsquashfs.broken   # keep both tools from the same (system) version
```

Doctor then showed `mksquashfs: /usr/bin/mksquashfs (system)` and `squashfs LZO pack/extract check: OK`.

### 5. Fix USB permissions — udev rule

```bash
sudo cp udev/70-diskos-maskrom.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Rule content: `SUBSYSTEM=="usb", ATTR{idVendor}=="a108", ATTR{idProduct}=="eaef", MODE="0660", TAG+="uaccess"`. No replug was needed — `getfacl /dev/bus/usb/001/015` showed `user:moo:rw-` right after the trigger. Doctor now all green.

### 6. Flash

```bash
./diskos-installer install \
  --firmware ~/Downloads/SNOWSKY_DISC_update_20260909_v257.zip \
  --variant public -y > flash.log 2>&1
```

Sequence in the log:

1. Extract stock rootfs (`stock_rootfs.squashfs`, 80,596,992 bytes).
2. Build `diskos_public.bin` (100,663,296 bytes = 96 MiB, 768 NAND blocks).
3. Stage the stock rootfs as backup `g0001` (committed only after the base check passes).
4. Mask-ROM flash: start 12:02:45, `usbboot exit=0` at 12:22:52 (~20 min).

Result:

```
scan: bad-blocks-found=2 list=[128, 522]
writer capacity: 768 blocks (image needs 768)
write: skipped=2 retried=0 worst=0
result: 0x600DF10C [F001] SUCCESS
✓ flash verified OK
backup g0001: committed
✓ diskOS flashed and verified. Power-cycle the device to boot it.
```

The 2 bad blocks are normal factory NAND bad blocks; the writer skips them.

Then: unplug, power on — diskOS installs itself on first boot.

## Why the flash takes ~20 minutes (and shows no real progress)

From `diskos_installer/flasher.py`: `usbboot` uploads the SPL + writer (`my_write6_dram.bin`) + image into the Disc's DRAM, starts the writer, then **waits a fixed `FLASH_WAIT` = 1080 s (18 min)** and only then reads a DONE marker back. There is no early-completion polling — the "Xm30s elapsed" lines are just a host-side timer. The writer itself hashes the ~96 MiB image and ~25 MiB of base partitions (firmware-base gate), then scans/erases/programs/verifies 768 blocks. Hard ceiling is the wait + 15 min (E303 if exceeded). If an outcome is ever unknown (E301–E303, E310, E321): leave the Disc powered + connected ≥25 min, don't retry, follow `RECOVERY.txt`.

## Backups / restore

- Saved stock rootfs: `~/.local/share/diskos-installer/stock/g0001/` — keep a copy of it.
- State: `~/.local/share/diskos-installer/state.json` (`phase: flash-verified`, `variant: public`).
- Use stock UI without reflashing: **Settings > System > Default UI > Stock**; hold **Volume Up** at power-on to boot the other UI once.
- Full removal: `./diskos-installer restore-stock` (or `restore-stock --firmware <zip>` if the saved backup is damaged).
- Updates 1.2.x: app-only OTA via **Settings > System > Update diskOS**; some fixes need a full reflash.

## USB DAC mode is broken in 1.2.1 — community patch review + own build

**Symptom** ([issue #24](https://github.com/b0hemia/diskos/issues/24), open as of 2026-10-19, reported on exactly 1.2.1 + V2.57): in diskOS's *USB DAC* work mode the PC sees the Disc as a sound card and "plays", but the Disc is silent. Stock FiiO UI's DAC mode works. No upstream fix released (latest upstream commit = the 1.2.1 release).

**Workaround without any build:** hold **Volume Up** at power-on to boot the stock UI once (or set Settings > System > Default UI > Stock) and use its USB DAC mode.

### Root cause + community patch

A user (zmd22, maintainer of the "diskOS Disco" fork) attached `usb-dac-workmode.tar.gz` to the issue: `usb-dac-workmode.patch` + a full `main.c`.

In `ui/main.c:source_send()`, source mode 1 (USB DAC) sent `0642000C0002` (USB gadget selector = UAC) and then `0657000C0008` — player work-mode **8 = Local playback**. Per the repo's own `docs/COMMAND_MAP.md` 0657 table, **1 = USB DAC**. With 8, the UAC gadget binds and the host streams, but the player never reads the incoming audio. Patch changes it to `0657000C0001`.

Review:

```bash
cd ~/diskos
gh repo fork b0hemia/diskos --clone=true --remote=true      # -> github.com/txtsamu/diskos, cloned to ~/diskos/diskos
mkdir -p patch-usb-dac && cd patch-usb-dac                  # untrusted download, own dir
curl -sSL -o usb-dac-workmode.tar.gz https://github.com/user-attachments/files/33457078/usb-dac-workmode.tar.gz
tar tzvf usb-dac-workmode.tar.gz && tar xzf usb-dac-workmode.tar.gz
cd ../diskos && git checkout -b fix/usb-dac-workmode
git apply --check ../patch-usb-dac/usb-dac-workmode.patch && git am ../patch-usb-dac/usb-dac-workmode.patch
/usr/bin/diff -q ui/main.c ../patch-usb-dac/main.c          # identical -> tarball main.c hides nothing extra
```

- Patch is a one-value change (+ comment); applies cleanly to v1.2.1 (`4cd4a60`); matches the documented 0657 mode table. Verdict: correct.
- Audited every other `0657000C0008` sender for paths that could re-send mode 8 while in USB DAC mode and silently undo the fix: the boot-time local init (`main.c` ~1304), play preambles (~1505, ~1568), book play (~1739) and type-5 play (~1551/1590) are all gated on `ui_get_source_mode() == 0`. `route_analog` is reached only from BT disconnect paths.
- **Gap found:** `ui_route_bt()` (called by the 3 s BT auto-route poll in `ui/bt.c`, connect completion, and tapping a connected device) is **not** gated on source mode. Harmless before the patch (mode was 8 anyway); after it, a BT headset connecting while in USB DAC mode would send `0657 8` and silence the DAC. Added a second commit:

```c
    if(ui_get_source_mode() != 0) return -1;            /* BT routing re-sends 0657 8: in USB DAC / BT-receive it would drop the player out of that work-mode */
```

Branch `fix/usb-dac-workmode` in `~/diskos/diskos`: `e07dfee` (community patch, author preserved via `git am`) + `54175a1` (BT guard).

### Building mq_ui

Upstream builds the UI with a pinned musl-cross-make toolchain (GCC 11.2.0, musl 1.2.6, binutils 2.44, MIPS32r2 FP64 NaN2008) via `ui/Dockerfile`. Run with rootless Podman instead of Docker:

```bash
cd ~/diskos/diskos/ui
podman build -t diskos-ui-builder .                         # compiles GCC from source; ~1 h on this box
podman run --rm --userns=keep-id -v "$PWD:/src:Z" diskos-ui-builder   # -> static mipsel ui/mq_ui
```

With rootless Podman use `--userns=keep-id` (not Docker's `-u "$(id -u):$(id -g)"`) so the output files stay owned by you; `:Z` relabels the bind mount for SELinux.

Result: `ui/mq_ui`, `ELF 32-bit LSB executable, MIPS, MIPS32 rel2, statically linked, stripped`, 4,285,004 bytes, md5 `78cf146954c4200a289a1f7511baa942`. Copy kept at `~/diskos/mq_ui.usb-dac-fix`.

**Reproducibility check (worth doing):** built the *unpatched* v1.2.1 tree in a throwaway worktree and compared it with the release's bundled binary:

```bash
cd ~/diskos/diskos && git worktree add ../diskos-upstream 4cd4a60
cd ../diskos-upstream/ui && podman run --rm --userns=keep-id -v "$PWD:/src:Z" diskos-ui-builder
md5sum mq_ui ~/diskos/diskos-installer/payload/mq_ui
# c3c602c010276aa3c7285aec8518b109  both -> byte-identical
cd ~/diskos/diskos && git worktree remove --force ../diskos-upstream
```

The build is bit-for-bit reproducible, so the local toolchain matches upstream's and the patched binary differs from the official one *only* by the two commits. Branch pushed to the fork: `txtsamu/diskos` `fix/usb-dac-workmode`.

### Getting a custom mq_ui onto the Disc

From `docs/DEV_WORKFLOW.md`:

1. **Temporary test (no reflash):** Settings > System > Debug Mode shows IP + one-time SSH password.
   ```bash
   ssh root@<ip> 'cat > /usr/data/mq_ui.new && chmod 755 /usr/data/mq_ui.new && md5sum /usr/data/mq_ui.new' < mq_ui
   md5sum mq_ui                                              # must match
   ssh root@<ip> 'mv /usr/data/mq_ui.new /usr/data/mq_ui'
   ssh root@<ip> 'killall -9 mq_ui; setsid /usr/data/mq_ui </dev/null >/usr/data/diskos_boot.log 2>&1 &'
   ```
   Never kill `mq_player` (MCU hard-reboots the device). Relaunch must be `setsid` + detached or the `fiio_init.sh` watchdog respawns stock `/usr/bin/mq_ui`. On reboot, `S97diskos_install` re-verifies `/usr/data/mq_ui` against the SHA-256 manifest baked into the rootfs and restores the flashed build — so a hand-pushed binary does not survive a restart.
2. **Permanent:** reflash with the custom binary (another ~20 min mask-ROM write; manifest is generated for it):
   ```bash
   cd ~/diskos/diskos-installer
   ./diskos-installer install --firmware ~/Downloads/SNOWSKY_DISC_update_20260909_v257.zip --ui ~/diskos/diskos/ui/mq_ui --variant public
   ```
   This rewrites only the main rootfs partition (the same one the first flash replaced). Kernel, recovery kernel and recovery rootfs are only *checked* (hashes recorded under `base` in `stock/g0001/stock.json`), never written. FiiO's stock UI/player still live inside the diskOS image, so Vol-Up boot / Default UI > Stock keep working. Backup integrity check: `sha256sum ~/.local/share/diskos-installer/stock/g0001/stock.bin` must equal `stock.sha256` (`e75d85bd…`).

Easier than the manual commands — the repo ships a safe deploy script (polls until the new build is confirmed running before pruning stock, leaves stock as fallback otherwise):

```bash
cd ~/diskos/diskos
DISKOS_IP=<ip> DISKOS_PW='<debug-mode-pw>' bash tools/diskos-deploy.sh ~/diskos/mq_ui.usb-dac-fix
# >> deployed OK: /usr/data/mq_ui running; mq_player alive
```

### Testing the DAC fix on the device

Hot-loaded the patched build; verified the running binary with `md5sum /proc/$(pidof mq_ui)/exe`.

- First "still no sound" was **not** the fix: `lsusb` on the PC showed no Disc at all (Disc UDC state `suspended/full-speed` = no host configured it). After reconnecting, the PC enumerated `2972:0158 FiiO SNOWSKY DISC` but PipeWire's default sink was still the onboard ALC897, so nothing was sent to the Disc.
- Proof the fix works: quiet tone straight to the Disc sink while watching the Disc side:
  ```bash
  paplay --device=alsa_output.usb-FiiO_SNOWSKY_DISC-00.analog-stereo tone.wav &
  ssh root@<ip> 'head -1 /proc/asound/card1/pcm0c/sub0/status; for f in /proc/asound/card0/pcm*p/sub0/status; do head -1 $f; done'
  # card1 pcm0c (UAC capture from PC): RUNNING ; card0 pcm3p (internal DAC, I2S3): RUNNING
  ```
  Player log shows `work:UAC, work mode=UAC` (`work_mode=1`), versus `LOCALPLAYER` before the patch.
- Then `pactl set-default-sink alsa_output.usb-FiiO_SNOWSKY_DISC-00.analog-stereo` → user confirmed audio in IEMs on the Disc's headphone jack.

### Second bug the fix exposes: leaving USB DAC mode can wedge mq_player

After the PC cable was pulled, the UI got `ipc_send_cmd '06xx…' failed: Resource temporarily unavailable` on every command and later showed "Player didn't respond". The `/player` POSIX message queue was full: `mq_recv_thread` in mq_player sat in `futex_wait`. Player log:

```
12:48:32.767 player_capture.c: close_pcm_capture_thread enter      <- never prints "exit"
12:48:37.075 EVENT_USB_STATE_DISCONNECTED ... UAC_SRATE=0 ... reopen capture dev! / reopen capture dev ok!
```

Decompiled with Ghidra (see [diskos-usb-audio-reverse-engineering-mq-player.md](diskos-usb-audio-reverse-engineering-mq-player.md) for the setup): `close_pcm_capture_thread` (0x4614bc) sets capture state 2 and `pthread_join`s; the capture thread (0x460b40) is blocked in a read from an **idle** host (connected, PipeWire suspended), so it hasn't seen 2. The unplug fires `reopen_capture_dev` (0x461644), which sets state **3** without checking for a pending close; the reopen at rate 0 fails into state 5 (sleep 100 ms forever). The join never returns, and it runs on the player's only command thread. Latent FiiO V2.57 bug; old diskOS never entered real UAC mode, so it couldn't hit it.

Safe order: unplug first (thread already in state 5, polling every 100 ms), then switch mode — the close completes. Guard committed in diskOS (`eda12f4`): leaving source mode 1 is refused with "Unplug the USB cable first" while `/sys/class/udc/*/state` reads `configured`. Observed UDC states: `not attached` (fresh boot, no gadget), `powered` (cable in, not enumerated), `configured` (host attached), `suspended` (gadget bound, host gone/asleep).

Recovery when it happens: only a reboot (`ssh root@<ip> 'sync; reboot'`); never kill `mq_player`.

Verified on device afterwards: USB DAC from the PC plays bit-transparent on the Disc side — PC `hw_params` = Disc capture = Disc DAC (`S32_LE`, 48 kHz for YouTube, 96 kHz for a 96 kHz FLAC once PipeWire was allowed to switch rates; see [pipewire-native-sample-rate-usb-dac-cosmic-volume-keys.md](pipewire-native-sample-rate-usb-dac-cosmic-volume-keys.md)).

## Third bug: USB Storage while playing wedges mq_player (upstream; fixed in the fork by a restart)

Symptom after the custom flash: USB Audio said "No USB DAC found - internal DAC restored" and the port never went to host — but the player had already stopped processing *any* command. Proof the player queue was not being drained (read-only):

```bash
ssh root@<ip> 'mkdir -p /dev/mqueue; mount -t mqueue none /dev/mqueue; cat /dev/mqueue/player /dev/mqueue/ui'
# /dev/mqueue/player: QSIZE:408 ...   <- commands piling up, mq_player not reading
```

Thread states (`/proc/$(pidof mq_player)/task/*/{comm,wchan,syscall}`): `mq_recv_thread` blocked on a futex inside the command dispatcher (return address 0x4d5260), main thread blocked in `pthread_join`. Return addresses read straight from the thread stacks:

```bash
P=$(pidof mq_player); T=<tid>; set -- $(cat /proc/$P/task/$T/syscall); SP=$8
dd if=/proc/$P/mem bs=4 skip=$((SP/4)) count=512 2>/dev/null | hexdump -v -e '1/4 "%08x\n"' | grep -n -E '^00(4[0-9a-f]|5[0-9a-f]|6[0-9a])[0-9a-f]{4}$'
```

Decompiled (Ghidra, see the RE doc): main thread in `stop_music_theard` (player_thread.c, 0x465230) — sets the music thread's cmd to 3 and `pthread_join`s it. Player log sequence:

```
13:58:49 play_ctrl:2 … start local          (song playing from SD)
13:59:21 playlist server is running / umount /tmp/sdcard succeeded   (USB Storage: card unmounted under the player)
13:59:37 mount to /tmp/sdcard succeeded      (back to Local)
13:59:38 new play -> stop_music_theard -> join never returns
```

diskOS (upstream `ui/main.c` SD_DRAIN, ~line 826) only sends the `0201` play/pause *toggle* before exporting, so the music thread survives holding a file on the unmounted card. Fix chosen (fork commit `10c1b72`): when the card returns local (`storage_resume_local`), toast "Restarting to reload the card..." and call the Restart button's own drain+sync+`reboot(RB_AUTOBOOT)` path (`settings_restart_now()` factored out of `boot_confirm_cb`). Recovery if it happens on an unfixed build: reboot.

## Radios off at boot, key-only SSH (fork commits `10c1b72`, `beec0f0`)

- `ui/main.c` after `wifi_init_intent()`: `cfg_set_int("wifi_on", 0); cfg_set_int("bt_on", 0);` — both start off every boot; Quick Settings enables them for the session.
- Key-only dev SSH: `payload/S98diskos_sshkey` (installed to `/etc/init.d/` by `diskos_installer/imagebuild.py`) runs `diskos-debug.sh key-on` only if `/usr/data/sshd/root_home/.ssh/authorized_keys` exists. `key-on` bind-mounts that home over the empty read-only `/root` (dropbear 2022.83 has no option to read keys elsewhere), then starts `/usr/data/sshd/dropbear -s -p 2222` (a symlink to dropbearmulti, so Debug Mode's `pgrep -f "dropbearmulti dropbear"` neither matches nor kills it).
- Key provisioned once over Debug Mode SSH (persists in `/usr/data` across flashes):
  ```bash
  ssh root@<ip> 'mkdir -p /usr/data/sshd/root_home/.ssh && cat > /usr/data/sshd/root_home/.ssh/authorized_keys && chmod 700 /usr/data/sshd/root_home /usr/data/sshd/root_home/.ssh && chmod 600 /usr/data/sshd/root_home/.ssh/authorized_keys' < ~/.ssh/id_rsa.pub
  ```
- `~/.ssh/config` on fedora: `Host disc` / `HostName 192.168.50.57` / `Port 2222` / `User root` / `IdentityFile ~/.ssh/id_rsa`. DHCP lease on the MikroTik is dynamic (user chose not to pin it) — update HostName if it changes.
- Verified before flashing by running the new script from `/tmp` on the live device: `ssh disc` logs in; password-only attempt on 2222 → `Authentications that can continue: publickey` / `Permission denied (publickey)`; key daemon survived toggling Debug Mode off/on. Gotcha: `Host *` has `ControlMaster auto` + `ControlPersist 10m`, so negative tests need `-o ControlMaster=no -o ControlPath=none` or they silently reuse the authenticated master.
- Claude Code auto mode refused to write the boot script ("Unauthorized Persistence") even after chat approval; unblocked by allow rules in `~/.claude/settings.json` scoped to `~/diskos/diskos/payload/**` and `diskos_installer/**` (backup `settings.json.bak`).
- Release installer patched in place from the fork (originals kept as `*.orig`): `diskos_installer/imagebuild.py`, `payload/diskos-debug.sh`, new `payload/S98diskos_sshkey`. There is no build-only command; `echo n | ./diskos-installer install …` builds and validates the image, then stops (E110 without a mask-ROM device, or at the confirm prompt).

## Fourth round: "Player is busy" on USB Audio, unplug auto-revert, Bluetooth on at cold boot

- **"Player is busy - try again" on USB Audio after any play since boot.** V2.57 keeps the I2S PCM `RUNNING` while paused (player log `[PAUSE]` at 12:00:30, yet `card0/pcm3p` `hw_ptr` advanced 6,999,584 → 7,091,312 in 2 s at 44.1 kHz). diskOS's output switch required every playback PCM closed (`out_pcm_quiet()`), so it only ever worked on a fresh boot. Fix `d44e66a`: "quiet" = track position stopped (`ui_is_playing()==0` held 500 ms), the same signal `ui_route_bt()` already relies on before sending `0666`; `out_pcm_quiet()` removed.
- **Radios-off ran on every UI start**, which also killed Wi-Fi (and the SSH session) on each hot-reload. Now once per boot via the tmpfs marker `/tmp/.diskos_radios_reset` (`d44e66a`). Hot-reload recipe: `touch /tmp/.diskos_radios_reset` first.
- **Bluetooth on after a cold power-on** (user report; not reproduced on the inspected boot — rfkill blocked, stock `BT_STATUS = 0`). `bt_boot_restore()` only *skipped enabling* BT when `bt_on=0`, never powered it down. Fix `e36fc5a`: with the intent off, poll `bt_radio_on()` every 2 s for 30 s and `bt_disable()` it (throttled to once per 6 s), unless the user turns BT on meanwhile. Verify after the next real power-on.
- **Unplugging the USB DAC left the player on the silent `USB_HOST_NULL` sink.** Fix `4a4d3ae`: after "USB DAC connected", poll `card1/usbid` every 1 s; after 2 misses run the normal `out_switch(OUT_INTERNAL, 1)` and clear `g_osw.was_playing` so playback stays paused (no resume into the jack). Verified: unplug 15:07:50 → `DAC gone` → `set out device I2S3_OUT` 15:07:54 → role `device`; toast + paused confirmed by user. Re-tapping USB Audio and replugging within the 8 s window reconnected (`on_usb_audio_add` → `USB_HOST`).
- Hot-loading over key SSH (no Debug Mode, no sshpass) — same steps as `tools/diskos-deploy.sh`:
  ```bash
  B=~/diskos/mq_ui.<build>; S="ssh -o ControlMaster=no -o ControlPath=none -o BatchMode=yes disc"
  $S 'touch /tmp/.diskos_radios_reset; cat > /usr/data/mq_ui.new && chmod 755 /usr/data/mq_ui.new && md5sum /usr/data/mq_ui.new' < $B
  md5sum $B   # must match, then:
  $S 'mv /usr/data/mq_ui.new /usr/data/mq_ui; killall -9 mq_ui; setsid /usr/data/mq_ui </dev/null >/usr/data/diskos_boot.log 2>&1 & sleep 4; \
      for p in $(pidof mq_ui); do [ "$(readlink /proc/$p/exe)" = /usr/bin/mq_ui ] && kill -9 $p; done'
  ```
- Device busybox `grep` has no `--line-buffered`: stream raw `tail -f` over SSH and filter on the PC side.
- Final flash (2026-10-19 ~15:15): UI `3e828424469bcc62c3448f02b0bdf632` (`4a4d3ae` + `-DDISKOS_TEST_OUTPUTS`), `--no-ota`, image includes `S98diskos_sshkey`. Installer keeps the latest stock generations (pruned g0001 as "uncommitted"; g0002/g0003 committed, all `e75d85bd…`).

## Notes

- Never run the installer with `sudo` — it keeps per-user state under `~/.local/share/diskos-installer`.
- Don't redistribute generated `diskos_*.bin` images (contain FiiO's rootfs).
- Installer location on fedora: `~/diskos/diskos-installer` (bundled squashfs tools renamed `*.broken` there).
- Fork branch `txtsamu/diskos` `fix/usb-dac-workmode`: `e07dfee` DAC work-mode patch, `54175a1` BT-route guard, `83774f8` USB Audio switch-then-wait, `eda12f4` unplug-first guard, `10c1b72` restart after USB Storage + radios off at boot, `beec0f0` key-only SSH on 2222, `d44e66a` quiet = position stopped + radios-off once per boot, `e36fc5a` BT forced off at boot, `4a4d3ae` USB DAC unplug auto-revert.
- Installed build (2026-10-19 final flash): UI `2a9b702e8c4fa4f37ee5e04044607e2b` built with `-DDISKOS_TEST_OUTPUTS` (USB Audio row), flashed with `--no-ota` (no `/etc/diskos-ota/` → in-app updates unsupported, S97 ignores staged updates). Stock backups `g0001`–`g0003` all `e75d85bd…`.
- External USB DAC output ("USB Audio", e.g. a Type-C DSP IEM cable) is hidden in public diskOS builds; enabling + fixing it is in [diskos-usb-audio-reverse-engineering-mq-player.md](diskos-usb-audio-reverse-engineering-mq-player.md).

## References

- [b0hemia/diskos — README](https://github.com/b0hemia/diskos)
- [diskos docs/INSTALL.md — Linux packages, udev rule, error codes](https://github.com/b0hemia/diskos/blob/main/docs/INSTALL.md)
- [diskos release v1.2.1](https://github.com/b0hemia/diskos/releases/tag/v1.2.1)
- [diskos issue #24 — USB DAC mode not working (community patch attached)](https://github.com/b0hemia/diskos/issues/24)
- [diskos docs/COMMAND_MAP.md — 0657 work-mode table](https://github.com/b0hemia/diskos/blob/main/docs/COMMAND_MAP.md)
- [diskos docs/DEV_WORKFLOW.md — build, hot-reload, permanent `--ui` flash](https://github.com/b0hemia/diskos/blob/main/docs/DEV_WORKFLOW.md)
- [txtsamu/diskos — own fork](https://github.com/txtsamu/diskos)
