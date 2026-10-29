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
