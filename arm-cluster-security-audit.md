---
type: investigation
tags: [security, ssh, arm-cluster, armbian, cloudflared]
created: 2026-07-22
last_verified: 2026-07-22
status: current
---

# ARM cluster (arm1-4): security audit for malicious scripts / data exfiltration

## Why

User asked for a defensive check on arm1-4 (192.168.50.40-43) for malicious scripts, backdoors, or anything that could be stealing data — general due diligence, not triggered by a specific incident.

## Method

Per host, checked: listening sockets and established outbound connections, top CPU/mem processes and anything running from `/tmp` `/dev/shm` `/var/tmp`, all users' crontabs plus `/etc/cron.*`, systemd timers and enabled services (filtered down to non-standard units), `authorized_keys` for every home dir, UID-0 accounts, `sudoers.d`, recently modified files under `/usr/bin` `/usr/sbin` `/usr/local/*` `/etc` (last 14 days), hidden files in tmp dirs, and login history.

## Findings

**Clean:**
- No processes running from `/tmp`, `/dev/shm`, `/var/tmp`.
- No crontab entries for any user; `/etc/cron.d` / `cron.daily` / `cron.weekly` contents are all stock Armbian/Debian package files (timestamps match image build dates, Sep 2025 / Mar 2024).
- No non-standard enabled systemd services — only `armbian-*` stock units, `chrony`, `cloudflared`, `cloudflared-dns` (arm1 only), `warp-svc` (arm2 only, Cloudflare WARP), `vnstat`, `netfilter-persistent`, `openvpn` (installed but inert — `ExecStart=/bin/true`, no active tunnel), `rpcbind`.
- Only `root` has UID 0 on all four boxes. `/etc/sudoers.d` has no custom entries beyond the default README.
- No unexpected recently-modified system binaries (only `/etc/fake-hwclock.data`, which is touched routinely by design).
- Listening ports are all expected: sshd, systemd-resolved stub, rpcbind, cloudflared, and on arm2 the WARP client's local DNS proxy.

**Needed follow-up — `authorized_keys` had unrecognized entries:**

`/root/.ssh/authorized_keys` on all four boxes contains more than the one key currently in use from this machine. Verified fingerprint of the local key (`/root/.ssh/id_rsa.pub`, `SHA256:wk067UfC...`, comment `administrator@WIN-EQ6G9ODFLE0`) matches the primary entry everywhere.

Beyond that:
- `u0_a202@localhost` (`SHA256:EJEGe5IA...`) — present on **all four** boxes. Comment format is a classic Android per-app UID (Termux-style).
- **arm1 only**, seven more: `offic@Admin`, `vamou@LiNeOZ`, `afriansyah@ubusyah`, `btech@btech`, `xeph@DESKTOP-Q0BLUCE`, `ahmadazharrivaldy@DESKTOP-MRV9HH7`, plus commented-out `#manda` `#yasin` `#artur` `#minipc-btech` `#yoshep`.

`sshd` auth logs on arm1 showed **active successful root logins** via several of the extra keys as recently as 2026-07-21 (`afriansyah@ubusyah` ×6, `btech@btech` ×5, `ahmadazharrivaldy@DESKTOP-MRV9HH7` ×3, `offic@Admin` ×2), sourced from arm1's own LAN IP (192.168.50.40). That source pattern is consistent with Cloudflare Tunnel's WARP/private-network routing making a remote login appear LAN-sourced on the target — `cloudflared` here runs in remotely-managed token mode (`cloudflared tunnel run --token ...`), so ingress rules live in the Cloudflare Zero Trust dashboard and aren't visible from the box itself. Could not confirm from the host alone whether SSH is exposed beyond the tunnel's private network.

The username style (Indonesian names) plus the vendor string in `/etc/armbian-image-release` (`VENDOR=DBAI-2K25`, an Amlogic S905X TV-box community build) suggested these boxes were flashed from a shared community image, which was the working hypothesis raised to the user before confirming.

**Resolution:** asked the user directly whether these keys were recognized. **Confirmed legitimate** — known devices/collaborators with intentional shared access, not a backdoor. No keys were removed; `authorized_keys` left untouched on all four hosts.

**Minor hygiene note, not actioned:** `cloudflared` runs with its tunnel token as a literal CLI argument (`--token <jwt>`), visible via `ps`/`/proc` to any local user on the box. This is standard behavior for `cloudflared service install <token>` deployments and not a bug, but worth knowing given more than one person has shell access to these boxes.

## Outcome

No malicious script, exfiltration mechanism, or unauthorized persistence found. The one ambiguous signal (extra SSH keys) turned out to be intentional shared access, confirmed by the user. See also [arm-cluster-ssh-motd-slow.md](arm-cluster-ssh-motd-slow.md) for the unrelated SSH-latency investigation on the same hosts done the same day.

## If re-auditing later

- Re-run the same authorized_keys fingerprint check; treat *new* unrecognized keys/logins appearing after 2026-07-22 as a real signal (this round is a closed baseline, not something to re-litigate).
- The Cloudflare Zero Trust dashboard (ingress rules for this tunnel) was not checked — only visible from the box's local config, which doesn't exist since it's remotely-managed. If SSH exposure ever needs confirming, that has to come from the dashboard, not the host.
