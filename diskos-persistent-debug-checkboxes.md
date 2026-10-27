---
type: how-to
tags: [diskos, snowsky-disc, debug-mode, ssh, wifi, boot, lvgl, hot-load, podman]
created: 2026-10-27
last_verified: 2026-10-27
status: current
---

# diskOS "Persistent debug": Wi-Fi and SSH come back by themselves after a reboot

Repo `/home/moo/diskos/diskos`, branch `feat/persistent-debug` (from `refactor/outseq`), commit `5ae06f9`. Request: during a debug session every reboot meant re-enabling Wi-Fi and Debug Mode by hand. Companion docs: [[fiio-snowsky-disc-diskos-flash-fedora]] (flash and key-only SSH), [[diskos-ui-architecture-review-output-sequencer-design]] (the `outseq` work this branch sits on).

## What it does

Debug Mode (Settings > System, or the Quick Settings Debug tile) has a "Persistent debug" block with two checkboxes, both off by default:

| Checkbox | cfg key | Effect at boot |
|---|---|---|
| Auto-connect Wi-Fi at boot | `pdbg_wifi` | Wi-Fi intent stays on (`wifi_on=1`); the keepalive starts it and joins a saved network |
| Enable Debug at boot | `pdbg_ssh` | SSH is enabled again with a fresh random password (read it on Debug Mode) |

No password or key is stored beyond the existing `/usr/data/sshd/current_pw`. SSH password is regenerated each boot.

## Why it did not work before (facts read from the code)

- `ui/main.c` (after `wifi_init_intent()`): once per boot (marker `/tmp/.diskos_radios_reset` on tmpfs) it forced `wifi_on=0` and `bt_on=0` ("radios start OFF every boot"). That is what turned Wi-Fi off.
- `ui/wifi.c` V2.57 radio reconcile could also set `wifi_on=0` ("Wi-Fi off: Bluetooth was on") when stock arbitrated that way.
- `ui/debug_ui.c` documented "State is intentionally NOT persisted across reboots", and `enable_dbg()` was welded to its LVGL labels, so it could not run at boot.

## Changes

- `ui/debug_ui.c`: `enable_core()` (widget-free enable: random password, `crypt` hash, `diskos-debug.sh ssh-on <hash>` and `serial-on`, then trust the real state); `enable_dbg()` is now a thin wrapper; `debug_boot_restore()` (skips when dropbear is already running or the shadow overlay is mounted, so a UI restart does not rotate the password); two `lv_checkbox`es (`pdbg_checkbox()`), layout moved up and the button is 190x44.
- `ui/main.c`: `wifi_on` is set to `pdbg_wifi ? 1 : 0` in the once-per-boot reset; a one-shot `lv_timer` 6 s after startup calls `debug_boot_restore()` when `pdbg_ssh` is set.
- `ui/wifi.c`: the reconcile's `wifi_reco_decide(...)` is skipped while `pdbg_wifi` is set.
- `ui/screens.h`: `debug_boot_restore()` declaration.

## Build and deploy (no Docker on the box: podman with the existing builder image)

```bash
cd /home/moo/diskos/diskos/ui
podman run --rm --userns=keep-id -v "$PWD:/src:Z" localhost/diskos-ui-builder:latest \
  sh -c 'make CROSS=$CROSS EXTRA_CFLAGS=-DDISKOS_TEST_OUTPUTS'     # the flag keeps the USB Audio/SPDIF test rows
# deploy over the key-only SSH daemon (Host disc, 192.168.50.57:2222): a copy of tools/diskos-deploy.sh with
#   SSH=(ssh -o ConnectTimeout=8) and "root@$IP" -> "disc"  (no password needed)
```

A UI hot-load only lasts until the next reboot (the flashed `mq_ui` returns). So the new behaviour only survives a reboot once the build is flashed; the boot path was tested without rebooting by clearing the marker and restarting the UI (below).

## Test on the device (boot path without a reboot)

```bash
ssh disc '/usr/project/diskos-debug.sh ssh-off; printf "pdbg_wifi=1\npdbg_ssh=1\n" >> /usr/data/diskos.conf;
          rm -f /tmp/.diskos_radios_reset /usr/data/sshd/current_pw'
# redeploy/restart mq_ui, wait ~14 s
ssh disc '/usr/project/diskos-debug.sh status; ls -l /usr/data/sshd/current_pw; grep "persistent debug" /usr/data/diskos_boot.log'
#  -> SSH=on, new current_pw, "persistent debug: SSH enabled at boot"
# Wi-Fi half: put wifi_on=0 in diskos.conf, clear the marker, restart the UI
#  -> wifi_on back to 1, wlan0 keeps its IP
ssh disc 'sed -i "/^pdbg_/d" /usr/data/diskos.conf'                   # restore afterwards
```

Result: both halves worked. Not done: a real reboot with this build flashed; looking at the Debug Mode screen (the layout was placed by arithmetic for the 360x360 round panel, never seen); a run without `pdbg_wifi` set (it would switch Wi-Fi off and cut the SSH link).

## Follow-up in the same session

Working Mode picker (`ui/modes.c`, commit `1891442`): the USB Audio row (test-outputs builds only) now sits directly under Local Playback. Display order only: `lv_obj_move_to_index(g_row[ROW_USB_AUDIO], 1)` after the rows are built, because the row index is the mode id for `ui_set_source_mode`, `SWITCH_MSG`, `shown_mode` and the selected marks. Reordering the `MODES[]` table instead would have shifted every id.

## Notes

- Security: with `pdbg_ssh` on, root password SSH over Wi-Fi is up on every boot until Disable is pressed. The file header comment in `debug_ui.c` says so. Key-only SSH on port 2222 (`S98diskos_sshkey`) is separate and unaffected by ssh-on/off.
- The USB Storage return path restarts the Disc by design (`storage_resume_local`, `main.c`), which also drops a hot-loaded build.
