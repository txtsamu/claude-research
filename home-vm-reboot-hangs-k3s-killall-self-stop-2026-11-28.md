---
type: troubleshooting
tags: [home, proxmox, px1, k3s, systemd, shutdown, reboot, deadlock, nixos, k3s-killall, preStop]
created: 2026-11-28
last_verified: 2026-11-28
status: current
---

# `home` VM comes back up healthy, but its shutdown hangs in `k3s-killall.sh` stopping its own cleanup unit

**Host:** `home`, NixOS 26.05 (Yarara), kernel 6.18.60, VM 102 on Proxmox node `px1` (16 GB, 8 vCPU)
**Question asked:** did `moo@home` reboot properly?
**Short answer:** it is up and healthy now, but it did **not** complete the reboot on its own. The guest hung during shutdown at 02:52:20, and the VM was hard-stopped (`qmstop`) and restarted from `px1` at 02:54:32/02:54:37.

## Timeline (all WIB, 2026-11-28)

| Time | Event | Evidence |
|---|---|---|
| 02:50 | `moo` logs in from `192.168.50.20` | `last -x` |
| 02:52:20 | Guest shutdown begins; last journal line is `systemctl stop k3s-shutdown-cleanup.service` from `k3s-killall.sh` | `journalctl -b -1` tail |
| 02:54:32 | `qmstop:102:root@pam` on `px1`, completes in 1 s | `/var/log/pve/tasks/index`, `pvedaemon` journal |
| 02:54:37 | `qmstart:102:root@pam` | same |
| 02:54:50 | New boot, kernel starts | `journalctl --list-boots`, `who -b` |
| 02:55+ | `systemctl is-system-running` = `running`, 0 failed units | guest checks |

There is no `shutdown system down` record in `wtmp` for the 02:52 cycle, unlike the clean 2026-11-07 shutdown. The guest was killed mid-shutdown rather than finishing it.

## Current health (verified after the restart)

```
$ ssh home 'hostname; uptime; who -b; systemctl is-system-running'
home
 02:57:13  up   0:02,  0 users,  load average: 2.61, 1.42, 0.54
         system boot  2026-11-28 02:54
running
```

- `systemctl --failed` → `0 loaded units listed`.
- `k3s kubectl get nodes` → `home Ready control-plane 79d v1.35.8+k3s1`.
- `k3s kubectl get pods -A --field-selector=status.phase!=Running` → only one `Completed` pod (`homelab/curlt`), no failures.
- Listening: `sshd:22`, Technitium DNS `:53`, Caddy `:80/:443`, k3s `:6443`, `node_exporter:9100`, `cloudflared`, `tailscaled`/`tailcat`, `evomem:7700`, `headroom:8787`, `proxmox-mcp-plugin:8811`.
- Only error-level lines in the new boot are benign: `snd_hda_intel ... no codecs found` and `sm-notify ... sm.bak: No such file or directory`.

So the **post-restart state is fine**. The problem is the shutdown path.

## Root cause: the cleanup unit stops itself through `k3s-killall.sh`

`/home/moo/home-nixos/hosts/home/k3s.nix` defines `systemd.services.k3s-shutdown-cleanup` with:

```nix
TimeoutStopSec = 240;
preStop = ''
  ...
  k3s-killall.sh || true
  ...
'';
```

`k3s-killall.sh` (the k3s package wrapper) does:

```sh
for service in /etc/systemd/system/k3s*.service; do
    [ -s $service ] && systemctl stop $(basename $service)
done
```

That glob matches the cleanup unit itself:

```
/etc/systemd/system/k3s-shutdown-cleanup.service -> /nix/store/...-unit-k3s-shutdown-cleanup.service/...
```

So `ExecStop` of `k3s-shutdown-cleanup.service` runs a script that asks systemd to stop `k3s-shutdown-cleanup.service`. The stop job is already in progress (running this very `ExecStop`), and `systemctl stop` waits for that job to finish. The job cannot finish until the script returns. Circular wait, broken only by `TimeoutStopSec=240` (or by the operator hard-stopping the VM first, which is what happened here after ~132 s).

The previous boot's journal tail shows exactly the loop, ending on the self-stop:

```
02:52:20 home k3s-shutdown-cleanup-pre-stop[1817576]: + systemctl stop k3s.service
02:52:20 home k3s-shutdown-cleanup-pre-stop[1817578]: ++ basename /etc/systemd/system/k3s-shutdown-cleanup.service
02:52:20 home k3s-shutdown-cleanup-pre-stop[1817576]: + systemctl stop k3s-shutdown-cleanup.service
```

Nothing after that until the hard stop.

## Fix (not applied yet)

Rename the unit so it no longer matches `k3s*.service`, for example:

```nix
systemd.services.kube-shutdown-cleanup = {
  ...
  before = [ "k3s.service" ];
  ...
};
```

The unit name is arbitrary; `before = [ "k3s.service" ]` still gives the same ordering. Then `k3s-killall.sh` will stop only `k3s.service` and `k3s-image-prune.service`, and the preStop script can exit normally.

Alternatives, in order of preference:

1. Rename the unit (above). Cleanest, no copy of upstream logic.
2. Drop the `k3s-killall.sh` call and keep only the shim/iscsi cleanup already written in the script. Loses k3s's own unmount/CNI cleanup.
3. Lower `TimeoutStopSec` to e.g. 60. Only shortens the hang; does not fix it.

Do **not** test this with a plain `systemctl stop k3s-shutdown-cleanup.service` on the live node: that kills every pod, which is exactly what the `restartIfChanged = false` / `stopIfChanged = false` comments are guarding against. Test with an actual reboot.

## Side findings

- **Stale SSH host key on `px1`.** `ssh 192.168.50.200` from `px1` fails with `REMOTE HOST IDENTIFICATION HAS CHANGED` (offending key at `/root/.ssh/known_hosts:45`). The guest's current ED25519 key is dated `2026-09-09`, so this is an old entry from before a reinstall, not a new key from this boot. Fix on `px1`: `ssh-keygen -f /root/.ssh/known_hosts -R 192.168.50.200`.
- **`home` has no DNS A record.** `nslookup home.ssamu.id 192.168.50.200` returns `No answer`, so `ssh moo@home` from `px1` fails at name resolution. From the workstation, `~/.ssh/config` maps `Host home` → `192.168.50.200`, which is why `ssh home` works there.
- The VM was started with `qmstart`, and the guest agent answered immediately, so the hard stop did not corrupt the root filesystem (`ext4` on `/dev/sda2`, mounted rw).

## Time estimate

| Step | Time |
|---|---|
| SSH to `px1`, check VM status and task log | ~1 min |
| Guest health checks via `qm guest exec` and `ssh home` | ~3 min |
| Read `k3s.nix`, `k3s-killall.sh`, correlate journal | ~2 min |
| **Total** | **~6 min** (measured wall clock, 02:55 to 03:01) |

## Related

- [[hermes-gateway-restart-deferred-runtime-draining-2026-11-11]] (other `home` systemd stop/start behaviour)
- [[tiny11core-windows-vm-proxmox-px1]] (px1 VM operations)
