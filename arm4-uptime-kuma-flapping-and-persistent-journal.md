---
type: troubleshooting
tags: [arm4, armbian, uptime-kuma, victoriametrics, k3s, journald, armbian-ramlog, cloudflared, technitium, samsung-tv, flapping]
created: 2026-10-29
last_verified: 2026-10-29
status: current
---

# arm4 "disconnects by itself" + Uptime Kuma up/down flapping

Question: arm4 (`root@arm4`, 192.168.50.43) seemed to disconnect by itself, and Uptime Kuma on `home` showed monitors flipping up/down. Checked both hosts read-only, then made one change on arm4 (persistent journal).

## Summary

- **arm4 itself is not the cause.** Its boot ran 2026-09-28 09:00 to 2026-10-29 (about 31 days) with no crash. The 17 Kuma "arm4 down" events from 10-03 to 10-09 have no matching line in arm4's syslog (no kernel, NetworkManager, cloudflared or technitium events inside ±2 min).
- **Kuma "flapping" today = `samsung-tv` monitor only.** HTTP check on `http://192.168.50.31:8001/api/v2/`, added 2026-10-25; the TV is in standby (no ARP reply, `connect EHOSTUNREACH`) about 85% of the day. Expected behaviour.
- **The big Sep/Oct flapping (09-18 to 10-09) hit every ping monitor equally** (about 40-50 status changes each). Messages were `connect ETIMEDOUT` / `write EPIPE` / `Knex: Timeout acquiring a connection`, which a ping monitor does not produce, so this is most likely Kuma's own DB connection (inference, not proven). It stopped on 2026-10-10.
- Only two arm4 down events were real ICMP failures ("Destination Host Unreachable" from 192.168.50.200): 2026-09-19 03:09 (LAN event, 5 monitors at once) and 2026-10-29 08:59:57 (the manual reboot).
- arm4's own weak spots: two 8-9 s eth0 link drops (10-02 19:33, 10-10 13:09, neither caught by Kuma) and cloudflared QUIC timeouts ("no recent network activity", recovers in 10-30 s). The cloudflared stalls did not coincide with any arm4 Kuma down event, so they are upstream/Internet path, not LAN reachability.
- Why this was hard to see: arm4 kept logs in RAM only (`Storage=volatile`, `/var/log` on zram, synced to eMMC once a day at 00:00). Fixed below.

## Host facts

- arm4: ZTE B860H TV box (Amlogic S905), Armbian 25.11 noble, kernel 6.1.66-DBAI, 1.8 GB RAM, eMMC `mmcblk2`, wired eth0 100 Mbps (`meson8b-dwmac`), static 192.168.50.43. Runs Technitium DNS (podman), cloudflared (podman), node-exporter, check-mk-agent, vnstat, chrony. No tailscale/wireguard/fail2ban/ufw. wlan0/wlan1 exist, disconnected; saved profile `wifi-X` has autoconnect on.
- arm4 is the LAN DNS server (Technitium): when it is down, name resolution for clients goes with it.
- No RTC: boot time comes from fake-hwclock then chrony corrects it, so `wtmp`/boot timestamps can be off by about an hour. This produced a bogus "earlier reboot at 07:59" that was really the manual 08:59 reboot.
- `home` (192.168.50.200) runs k3s only (no docker/podman). Uptime Kuma is pod `uptime-kuma-78c44db6f-fz4wq` in ns `homelab` (LB 192.168.50.247:3001, limits 300m CPU / 384Mi, peaked at 372Mi). Its DB is embedded MariaDB, not SQLite (`kuma.db` is 0 bytes). VictoriaMetrics: `vmsingle-victoria-metrics-single-server-0` (:8428, 62 d retention), fed by `vmagent-home`; Kuma `/metrics` is not scraped.

## Steps (in order)

1. **arm4 state** (nothing changed):
   ```bash
   ssh root@arm4 'uptime; last -x reboot shutdown | head; journalctl --list-boots; grep -vE "^\s*#|^\s*$" /etc/systemd/journald.conf'
   ssh root@arm4 'sshd -T | grep -iE "clientalive|tcpkeepalive"; dmesg -T | grep -iE "oom|link|reset|hung|panic"'
   ```
   Found `Storage=volatile`, only the current boot in `--list-boots`, sshd `clientaliveinterval 0`, no OOM/MMC/thermal errors.
2. **Kuma data on home** (read-only SQL inside the pod):
   ```bash
   ssh moo@home 'kubectl -n homelab exec pod/uptime-kuma-78c44db6f-fz4wq -- mariadb -S /app/data/run/mariadb.sock kuma -e "
   SELECT m.name, SUM(s.down), SUM(s.up) FROM stat_daily s JOIN monitor m ON m.id=s.monitor_id GROUP BY m.name;"'
   ```
   `stat_daily` (kept since 2026-08-28) gives per-day counts; the `heartbeat` table only keeps status changes. Heartbeat times are UTC; local is WIB (UTC+7).
   Totals since 08-28 (down checks, 1 check = 60 s ping): fedora 1977 (mostly one ~30 h outage on 09-28/29), samsung-tv 832 (88% down, standby), arm4 78, arm3 59, px1 58, mikrotik 55, arm1 55, nas 52, arm2 50, pihole 47. Since 10-10 only four blips: fedora 10-11 and 10-24, pihole 10-23, arm4 10-29.
3. **VictoriaMetrics** (blackbox probes only exist from 2026-10-28 14:41 UTC because the exporter and vmagent restarted): checked blackbox `probe_success` and node-exporter for `home` and arm4 across the last 7 days: no simultaneous drops, 0 failed scrapes, eth0 RX drops on home peaked at 0.66 pkt/s. The only arm4 probe drop was at 02:00 UTC on 10-29 (the manual reboot).
4. **Correlating arm4 Kuma down events with arm4 logs.** Exported arm4's down heartbeats (query `heartbeat` for `status<>1`, add 7 h), then for each of the 17 events in 10-03..10-09 pulled syslog ±2 min from `/var/log.hdd/syslog.4.gz` and `syslog.3.gz` (syslog on arm4 only spans 09-27 to 10-29 00:00; 09-19..09-23 events and the 8 h before today's reboot have no logs). Result: windows contained only `rngd`/`CRON` lines. Gotcha: `date -d "$d $t -2 min"` parses `-2` as a timezone offset; use epoch arithmetic (`date -d @$((ep-120))`) and `TZ=Asia/Jakarta`.
5. **Persistent journal on arm4** (the one change). Armbian's ramlog script already supports it: it expects a real directory `/var/log.hdd/journal` on the eMMC and symlinks `/var/log/journal` to it. Here `/var/log.hdd/journal` was a symlink pointing to itself (dated 2025-09-13), which broke that.
   ```bash
   ssh root@arm4 '
   cp -a /etc/systemd/journald.conf /etc/systemd/journald.conf.bak-20261029
   sed -i "s/^Storage=volatile/Storage=persistent/" /etc/systemd/journald.conf
   rm /var/log.hdd/journal                       # the self-referencing symlink
   install -d -m 2755 -o root -g systemd-journal /var/log.hdd/journal
   ln -s /var/log.hdd/journal /var/log/journal   # ramlog does this itself at boot
   systemctl restart systemd-journald; journalctl --flush'
   ```
   Verified live: `/var/log.hdd/journal/<machine-id>/system.journal` is written on mmcblk2p2, cap stays `SystemMaxUse=20M`. Armbian already orders journald after `armbian-ramlog.service` (`/usr/lib/systemd/system/systemd-journald.service.d/override.conf`). I also added a redundant ordering drop-in `/etc/systemd/system/systemd-journal-flush.service.d/ramlog.conf` (harmless; can be removed).
   - **Open issue:** `armbian-ramlog write` ends with `journalctl --relinquish-var`, which sends journald back to RAM after every daily sync (`/etc/cron.daily/armbian-ram-logging`) and logrotate. A `*/5 * * * * root journalctl --flush` cron in `/etc/cron.d/journal-persist` would undo that; the cron write was blocked by the auto-mode classifier and is awaiting the user's decision. Not yet tested across a reboot.

## Dead ends / ruled out

- Oracle-style idle reclamation: not applicable, this is a LAN box (no DMI, no cloud-init).
- OOM, MMC/I/O errors, thermal throttling, ext4 errors, watchdog/panic: none in retained logs. Memory 403 Mi used, disk 48%, 43 C.
- Client SSH keepalive: `~/.ssh/config` already has `ServerAliveInterval 60` / `ServerAliveCountMax 3` for `Host *`, so no change was needed.
- Network-wide event on home: none in 7 days.

## Suggested next steps

- Samsung TV monitor: pause it, silence its notifications, or use a long-interval/high-retry check.
- Ping monitors: retries 2-3 with a 20-30 s retry interval and an explicit timeout (currently retries 0, timeout 0, so one lost packet = down).
- Raise Kuma memory limit from 384Mi to 512-768Mi (peak 372Mi).
- Scrape Kuma `/metrics` into VictoriaMetrics for later correlation; alert on `node_network_carrier_changes_total` and uptime resets.
- Security: the cloudflared tunnel token is visible in the process arguments of the container (`ps`); consider rotating it and passing it via a file or env var.
- arm4: try another cable/switch port and check the 5 V supply if link drops or stalls continue.

## Update 2026-10-29 (later): arm4 DNS (port 53) is broken by stale Pi-hole CNI DNAT rules

Found while preparing monitoring: VictoriaMetrics blackbox `probe_success{job="blackbox-dns",name="technitium-arm4"}` is **0 for the whole retained window (~20 h, probe takes the full 5 s timeout)**, while ICMP, SSH and the web UI (5380) are fine; the other Technitium servers (home, arm1, arm3) are healthy. Kuma has no DNS monitor, so nothing alerted.

Diagnosis (all read-only):
```bash
dig +time=3 +tries=1 @192.168.50.43 cloudflare.com A      # timeout over UDP and TCP, from the PC and from arm4 itself
ss -ulnp "sport = :53"; ss -ltnp "sport = :53"             # dotnet is listening, Recv-Q 0, no listen drops
iptables -S INPUT                                          # LAN is accepted, firewall is not the cause
iptables -t nat -S | grep -E "dport (53|8080|8443)"        # <-- the cause
```
The nat table has `CNI-DN-512c6e...` rules DNATing tcp/udp 53, 8080->80, 8443->443 to `10.89.1.3`, a leftover of an old `pi-hole_default` podman network. They are saved in `/etc/iptables/rules.v4` (dated 2026-05-07) and restored by `netfilter-persistent` on every boot. Technitium now runs with `Network=host`, so PREROUTING sends LAN DNS traffic to a nonexistent address. The web UI on 5380 is not in the stale rules, which is why it still works. A DNS client with arm4 in its resolver list waits for the timeout before falling back, which looks like a flaky connection.

Status: **fixed** (see the next section).

Also done in this update: `/etc/cron.d/journal-persist` (`*/5 * * * * root journalctl --flush`) installed on arm4 after the user approved it. Tested: after a forced `armbian-ramlog write` (which relinquishes `/var`), a `journalctl --flush` put new lines back in `/var/log.hdd/journal`.

Side notes: the Technitium admin password is in plain text in the Quadlet file `/etc/containers/systemd/technitium.container` (`DNS_SERVER_ADMIN_PASSWORD`) and shows in the generated unit; consider a podman secret. No vmalert/Alertmanager exists on home; Kuma already has a default Telegram notification (@txtcybr_bot) attached to all ping monitors. `vm-bot` (`homelab/vm-bot`) is a command bot with no inbound port, so it cannot receive pushed alerts as is.

## DNS fix applied 2026-10-29 and network config review

Fix (user approved). Only the Pi-hole leftovers (pattern `512c6e089d98ab8b48026|10\.89\.1\.`) were removed; the cloudflared CNI rules were left alone. Live rules were deleted one by one (not a full `iptables-restore`, which would have wiped the rules of the running containers), then the saved file was filtered the same way and validated first:
```bash
cp -a /etc/iptables/rules.v4 /root/rules.v4.bak-20261029; iptables-save > /root/iptables-live-before-20261029.txt
PAT="512c6e089d98ab8b48026|10\.89\.1\."
delmatch(){ t=$1; c=$2; while :; do n=$(iptables -t $t -S $c | grep "^-A" | grep -nE "$PAT" | head -1 | cut -d: -f1); [ -z "$n" ] && break; iptables -t $t -D $c $n; done; }
delmatch nat CNI-HOSTPORT-DNAT; delmatch nat POSTROUTING; delmatch filter CNI-FORWARD
for ch in CNI-DN-512c6e089d98ab8b48026 CNI-512c6e089d98ab8b48026b8a; do iptables -t nat -F $ch; iptables -t nat -X $ch; done
grep -vE "$PAT" /etc/iptables/rules.v4 > /root/rules.v4.new && iptables-restore --test < /root/rules.v4.new && install -m 644 /root/rules.v4.new /etc/iptables/rules.v4
```
Result: `dig @192.168.50.43 cloudflare.com` answers over UDP and TCP; the VictoriaMetrics probe went from `probe_success=0` / 5.0 s to `1` / 2 ms. Rollback: `cp /root/rules.v4.bak-20261029 /etc/iptables/rules.v4` and `iptables-restore < /root/iptables-live-before-20261029.txt` (reloads everything, so restart the containers afterwards). Not tested across a reboot.

Network config review of arm4 (read-only):
- Static IP 192.168.50.43/24 via NetworkManager (netplan renderer NM), DNS 192.168.50.200/.42/.40/1.1.1.1, eth0 100 Mbps full, autoneg on. No ethtool/dispatcher scripts, nothing rewrites the network at runtime. IPv6 has only link-local (v6 forwarding is on, so RAs are ignored); harmless.
- `wifi-X` profile has autoconnect on for `wlan0`/`wlan1` (currently disconnected). If Wi-Fi ever came up it would add a second default route; consider `nmcli con mod wifi-X connection.autoconnect no`.
- The check-mk agent (`check-mk-agent-async.service`, loop every 60 s, plus socket on 6556) is read-only (grep for `ip link set`, `iptables`, `sysctl -w`, `ethtool -s` found nothing). The socket has accepted 0 connections since boot: the Checkmk server (once at 192.168.50.221:5000 on home k3s) no longer exists as a deployment, so the agent is orphaned. `cekping-agent` runs on home, not arm4.
- Conflicting sysctl: `/etc/sysctl.d/60-quic-tuning.conf` asks for `net.core.rmem_max/wmem_max = 16 MiB`, but `/etc/sysctl.d/99-sysctl.conf` loads later and sets 4 MiB / 1 MiB. cloudflared logs `failed to increase send buffer size (wanted: 7168 kiB, got 2048 kiB)`. A plausible contributor to the QUIC "no recent network activity" stalls (not proven). Also `kernel.hung_task_timeout_secs = 0` disables hung-task detection.
- Stale leftovers still in `rules.v4` and live: CNI rules for `10.89.0.5` (cloudflared now has `10.89.0.2`), plus an unused podman network `pi-hole_default`. Harmless cruft.
- INPUT chain: accepts established, loopback and `192.168.50.0/24`, drops everything else (counter 14 packets of about 36 bytes after 1.5 h; source not identified, no tcpdump installed).

## Follow-up changes 2026-10-29 (all user-approved)

**arm4**
- QUIC buffers: `/etc/sysctl.d/99-sysctl.conf` is a symlink to `/etc/sysctl.conf`, which `sysctl --system` loads last, so a drop-in file does not win. Edited `net.core.rmem_max`/`wmem_max` in `/etc/sysctl.conf` to 8388608 (backup `/root/sysctl.conf.bak-20261029`), then `systemctl restart cloudflared.service`; the `failed to increase send buffer size (wanted 7168 kiB, got 2048 kiB)` warning is gone. Dead end: first tried `/etc/sysctl.d/99-zz-quic.conf`; it applied with `sysctl -p` but my own `sysctl --system` check reverted it.
- `nmcli con mod wifi-X connection.autoconnect no`.
- check-mk agent removed (`systemctl disable --now check-mk-agent.socket check-mk-agent-async.service cmk-agent-ctl-daemon.service; apt-get remove --purge -y check-mk-agent`).

**check-mk agent removal on other hosts.** First confirmed the Checkmk server is gone (no Checkmk objects on k3s, `192.168.50.221:5000` dead, the agent socket on arm4 had 0 accepted connections). Dry-ran `apt-get -s remove --purge check-mk-agent` on each Debian host (only that package would go), then removed it on arm1 (.40), arm3 (.42), arm4 (.43), px1 (.30: also `cmk-agent-ctl-daemon`), and this PC (`dnf remove check-mk-agent`). TrueNAS (`nas`): it was a plain `docker run` container, `docker stop/rm checkmk-agent` + `docker rmi checkmk-agent:2.3.0p49` (node-exporter and smartctl-exporter containers kept). Not done: arm2 (192.168.50.41) does not answer ping/ssh from this PC although Kuma on home reaches it; `home` (NixOS) only has the declarative leftovers `/usr/bin/check_mk_agent` and `/etc/check_mk` from the Nix store, nothing running, left for the NixOS config.

**Uptime Kuma (home).** Added four monitors, all notifying "Telegram @txtcybr_bot": `arm4 ping 20s` (id 62, retries 2), `arm4 ssh 22` (63, TCP), `arm4 dns (technitium)` (64, A query for cloudflare.com against 192.168.50.43), `arm4 technitium web 5380` (65, HTTP). There is no API without the admin login, so they were inserted straight into the embedded MariaDB by cloning existing rows (`CREATE TEMPORARY TABLE t AS SELECT * FROM monitor WHERE id=9; UPDATE t SET id=62, ...; INSERT INTO monitor SELECT * FROM t;` plus `monitor_notification` rows), after `mariadb-dump` to `~/kuma-db-backup-20261029.sql` on home. Kuma only loads monitors at startup: `kubectl -n homelab scale deploy/uptime-kuma --replicas=0`, wait for the pod to go, then `--replicas=1` (strategy is `Recreate`; scaling avoids two pods on the same data). All four came up healthy within a minute. Rollback: restore the dump or `DELETE FROM monitor WHERE id>=62` (+ `monitor_notification`) and restart.

**Alerting on home (namespace `homelab`, manifests in `~/alerting/` on home).** vmalert (`victoriametrics/vmalert:v1.151.0`) and Alertmanager (`prom/alertmanager:v0.28.1`, runs 0.34.1) with a Telegram receiver that reads the bot token from the existing `vm-bot` Secret as a file (`bot_token_file`), so no token was copied. Rules (ConfigMap `vmalert-rules`): Arm4Down, Arm4NodeExporterDown, Arm4Rebooted, Arm4LinkFlap, Arm4DnsDown, Arm4TechnitiumWebDown, Arm4HighMemory, Arm4DiskFull, HostNodeExporterDown, TechnitiumDnsDown. None firing at deploy time; a test alert was delivered (Alertmanager counted 1 Telegram notification, 0 failures). Alertmanager storage is an `emptyDir`, so silences are lost on pod restart. Rollback: `kubectl -n homelab delete deploy vmalert alertmanager; kubectl -n homelab delete svc vmalert alertmanager; kubectl -n homelab delete cm vmalert-rules alertmanager-config`.

