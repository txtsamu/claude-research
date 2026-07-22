---
type: troubleshooting
tags: [ssh, armbian, motd, arm-cluster, dns]
created: 2026-07-22
last_verified: 2026-07-22
status: current
---

# ARM cluster: slow SSH logins caused by armbian-motd WAN-IP lookup

## Symptom

`ssh arm1` / `arm2` / `arm3` / `arm4` took noticeably longer than a LAN SSH login should — 1.4s to 6.7s to run a trivial remote command, worst on arm3 (6.7s).

Hosts (from `/etc/hosts`):

```
192.168.50.40  arm1
192.168.50.41  arm2
192.168.50.42  arm3
192.168.50.43  arm4
```

## Diagnosis

`ssh -vvv` showed the handshake, KEX, and pubkey auth all completing in milliseconds. The entire delay sat between the client sending `SSH2_MSG_CHANNEL_OPEN` (start of interactive session) and the server's open confirmation — i.e. server-side work that happens *after* auth succeeds but *before* the shell/command starts. That's the classic signature of PAM/session-setup overhead (MOTD generation, `pam_systemd`, etc.), not an SSH protocol or crypto issue.

Timed `run-parts /etc/update-motd.d/` directly on arm3: 5.5s — matched the observed SSH delay almost exactly. Timing each script individually pinned it to one file:

```
/etc/update-motd.d/10-armbian-header: 4.9s   <-- culprit
/etc/update-motd.d/30-armbian-sysinfo: 0.3s
(everything else: <0.2s)
```

`10-armbian-header` is Armbian's stock login-banner script. It calls two functions to show your WAN IP in the banner:

```bash
function get_wan_address() {
    curl --connect-timeout 2 -s http://whatismyip.akamai.com/ | sed -E 's/(.[0-9]+){2}$/.***.***/'
}
function get_wan6_address() {
    curl --connect-timeout 2 -s http://whatismyip.akamai.com/ | sed -E 's/(.[0-9]+){2}$/.***.***/'
}
```

Two curl calls, each with a 2s connect-timeout, run on **every login** (invoked via PAM's session phase, which runs `run-parts /etc/update-motd.d/`). When outbound DNS/routing to `whatismyip.akamai.com` is slow or broken — arm3's case, `curl` returned `http_code=000` (total failure) after ~2s per call — that's ~4-5s added to every single SSH session.

Cross-checked all four nodes:

| host | curl to whatismyip.akamai.com | motd header script time | total ssh time (before fix) |
|---|---|---|---|
| arm1 | 200, 0.06s | fast (other scripts dominate: `20-ip-info` 0.46s, sysinfo 0.31s) | 1.4s |
| arm2 | 200, 0.14s | 1.3s (RTT-bound, no timeout) | 3.2s |
| arm3 | 000 (fail), 2.0s | 5.0s (both v4+v6 calls time out) | 6.7s |
| arm4 | 000 (fail), 0.04s (fast DNS fail) | 1.0s | 2.7s |

All four are Armbian and all run this script — arm3 is just the one whose outbound path to that specific host is actually broken (consistent with lingering post-power-outage network flakiness noted elsewhere in this homelab's history), so it pays the full timeout on both calls.

## Fix

Blackholed the lookup target in `/etc/hosts` on all four nodes so `curl` fails instantly (connection refused) instead of waiting out a DNS/connect timeout:

```sh
echo '127.0.0.1 whatismyip.akamai.com' >> /etc/hosts
```

Did **not** edit `/etc/update-motd.d/10-armbian-header` directly — the file carries an explicit "DO NOT EDIT, changes lost on BSP update" header, and Armbian does rewrite it on package updates. The `/etc/hosts` blackhole survives that.

## Result

```
arm3: 6.7s -> 2.7s   (the real fix — was blocked on the timeout)
arm1: 1.4s -> 1.4s   (unchanged, was never blocked on this curl)
arm2: 3.2s -> 2.8s   (marginal — curl already succeeded fast, RTT is RTT)
arm4: 2.7s -> 2.6s   (marginal — curl already failed fast via DNS NXDOMAIN)
```

Residual ~1-1.6s on arm1/2/4 comes from other `update-motd.d` scripts (mainly `30-armbian-sysinfo`, ~0.3-0.4s) plus normal SSH/PAM overhead — not chased further, diminishing returns.

## If this recurs / generalizing

If SSH to any Armbian box feels slow, don't reach for `UseDNS no` or GSSAPI config first (both are common generic "slow SSH" advice but weren't the cause here — auth was already fast). Instead:

```sh
ssh <host> "for f in /etc/update-motd.d/*; do s=\$(date +%s.%N); \"\$f\" >/dev/null 2>&1; e=\$(date +%s.%N); echo \"\$f: \$(echo \"\$e - \$s\" | bc)s\"; done"
```

This isolates which specific motd script is slow in one shot.
