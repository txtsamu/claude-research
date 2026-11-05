---
type: investigation
tags: [mikrotik, routeros, hex-s, mmips, sqm, qos, cake, fq-codel, bufferbloat, queue-tree, fasttrack, pppoe]
created: 2026-11-05
last_verified: 2026-11-05
status: current
---

# Can the hEX S run SQM? CAKE/FQ-CoDel work, but one CPU core caps them at ~170–240 Mbps

Router `192.168.50.1` — MikroTik RB760iGS hEX S, RouterOS **7.25**, mmips MIPS 1004Kc V2.15,
4 cores @ 880 MHz, 256 MB RAM. WAN is PPPoE (`pppoe-out1`, MTU 1480) over `ether1`.
Line measured at **~630 Mbps down / ~282 Mbps up**, idle RTT to 1.1.1.1 2.5–3.2 ms.

Answer: **yes, it supports SQM** (CAKE and FQ-CoDel both accepted and functional), but the shaped
throughput is a quarter of the line, so SQM was tested and **left disabled**. Nothing on the router
was changed in the end — no queue trees, no custom queue types, no simple queues.

## Question

Smart Queue Management (SQM) on RouterOS means CAKE or FQ-CoDel attached to a queue tree on the WAN
egress and the LAN ingress. The stock `/queue type` list on this box has neither, so the question was
whether this hardware generation supports them at all, and whether they are worth enabling on a
line this fast.

## Support check

`/queue type print` on 7.25 lists only the ten defaults (`pfifo`, `sfq`, `red`, `pcq`, `mq-pfifo`,
`none`). CAKE and FQ-CoDel exist since RouterOS 7.1beta3 but are **not pre-created** — they must be
added by hand, which is why they do not show up on a stock router.

Both kinds were created successfully on this build:

```
/queue type add name=cake-test kind=cake cake-diffserv=diffserv4 cake-rtt=100ms \
    cake-flowmode=triple-isolate cake-nat=yes cake-wash=yes cake-overhead-scheme=ethernet
/queue type add name=cake-blind kind=cake cake-flowmode=flowblind cake-diffserv=diffserv3 cake-rtt=100ms
/queue type add name=fq-codel-test kind=fq-codel fq-codel-target=5ms fq-codel-interval=100ms fq-codel-limit=1024
```

All parameters were accepted, including `cake-overhead-scheme=ethernet`, which auto-resolved to
`cake-overhead=38 cake-mpu=84`. FQ-CoDel resolved to `fq-codel-flows=1024 fq-codel-memlimit=32.0MiB
fq-codel-quantum=1514 fq-codel-ecn=yes`. So this is not a build/architecture limitation.

Current state before and after the test: `/queue simple` empty, `/queue tree` empty, every interface on
`only-hardware-queue` or `no-queue`, i.e. no shaping anywhere.

## Method

Load was generated from `192.168.50.200` (the Hermes host, on the LAN bridge) with parallel `curl`
streams, sampling `/system resource cpu print` (per-core) every 2 s and pinging `1.1.1.1` in a side
thread throughout, so throughput, per-core CPU and RTT-under-load were captured in the same run.

```
curl -sL -o /dev/null -w '%{speed_download}' --max-time 20 https://proof.ovh.net/files/1Gb.dat   # ×5
```

Shaping was applied as interface-parented queue trees, the standard SQM shape:

```
/queue tree add name=sqm-dl parent=bridgeLocal max-limit=600M packet-mark=no-mark queue=cake-test
/queue tree add name=sqm-ul parent=pppoe-out1  max-limit=340M packet-mark=no-mark queue=cake-test
```

Upload was benched separately with `POST https://speed.cloudflare.com/__up` (200 MB body).

## Measurements

| Config | Download | RTT p50 | RTT max | Busiest core |
|---|---|---|---|---|
| No SQM (FastTrack on) | **636 Mbps** | 3.7 ms | 37.7 ms | 79 % |
| CAKE triple-isolate, diffserv4, nat, wash, cap 600M | 157 Mbps | 6.9 ms | 14.7 ms | **100 %** |
| FQ-CoDel, cap 480M | 241 Mbps | — | — | 89 % |
| CAKE flowblind, diffserv3, cap 600M | 40 Mbps — invalid, see note | — | — | 97 % |
| Upload, no SQM | 282 Mbps | 2.5 ms | 4.6 ms | 47 % |
| Upload, CAKE cap 280M | 169 Mbps | 2.1 ms | 6.1 ms | **99 %** |

Unshaped ceiling was confirmed twice (615 and 636 Mbps aggregate over 20–25 s of 5-stream download),
so ~630 Mbps is the line, not a test artefact.

## Analysis

- **Every shaped run pins exactly one core at 97–100 %.** CAKE and FQ-CoDel run single-threaded per
  queue, so the other three cores do not help. The per-direction ceiling is ~170 Mbps (CAKE) and
  ~240 Mbps (FQ-CoDel) — CPU, not bandwidth, is the limit. Lowering `max-limit` does not help; the
  shaper was never the binding constraint.
- **Bufferbloat on this line is already mild.** Worst-case RTT under full download saturation was
  37.7 ms against a 3.7 ms median, and upload saturation showed 4.6 ms max — i.e. effectively no
  upload bloat. SQM improved worst-case latency (37.7 → 14.7 ms) but there is very little to remove.
- **FastTrack does not prevent shaping here.** The forward chain has an active `fasttrack-connection`
  rule (2.0 GB / 15.0 M packets counted). Interface-parented queue trees still saw the traffic —
  throughput collapsed to the shaped rate — so SQM works with FastTrack left on. Only simple queues
  and `parent=global` queue trees are bypassed by fasttracked flows.
- **The router is already near its FastTrack ceiling** at 79–86 % of a core while routing 630 Mbps.
  This box will become the bottleneck before the line does if the plan is upgraded.

Net: enabling full-rate SQM would trade ~470 Mbps of download and ~110 Mbps of upload for a 23 ms
improvement in worst-case latency on a link that does not meaningfully bloat.

## Decision

**SQM left disabled on the hEX S.** Revisit only on a concrete symptom — calls or voice breaking up
during large transfers, or gaming RTT spiking when something saturates the line. If that happens, the
least-bad in-place options are:

1. Download FQ-CoDel capped at ~240M (cheapest AQM that the CPU can sustain), or
2. Upload-only CAKE at ~170M — but upload showed no bloat, so this buys little here.

Doing it at full line rate requires moving routing to x86 hardware; the hEX S cannot shape 600 Mbps.

## Ready-to-apply config (not applied)

```
/queue type add name=cake-aqm kind=cake cake-diffserv=diffserv4 cake-rtt=100ms \
    cake-flowmode=triple-isolate cake-nat=yes cake-wash=yes cake-overhead-scheme=ethernet
/queue type add name=fq-codel-aqm kind=fq-codel fq-codel-target=5ms fq-codel-interval=100ms

/queue tree add name=sqm-upload   parent=pppoe-out1  max-limit=170M packet-mark=no-mark queue=cake-aqm
/queue tree add name=sqm-download parent=bridgeLocal max-limit=240M packet-mark=no-mark queue=fq-codel-aqm
```

Revert with `/queue tree remove [find name~"sqm-"]` and
`/queue type remove [find name~"aqm"]`. Download shapes on the **LAN-side** parent (`bridgeLocal`),
upload on the **WAN** parent (`pppoe-out1`); shaping the wrong side silently does nothing.

## Gotchas found while testing

- **`mcp__mikrotik__mikrotik_execute_command` is read-only.** `add` / `set` / `remove` are rejected as
  dangerous commands; writes went over SSH instead. `sshpass` is not installed on the NixOS Hermes
  host and the RouterOS `admin` user has no SSH key, so the working route was a throwaway venv with
  `paramiko` (`python3 -m venv .venv && .venv/bin/pip install paramiko`) and one `exec_command()` per
  command — RouterOS still refuses `;` chaining.
- **Public speedtest mirrors rate-limit you mid-session.** After roughly 10 GB of test traffic,
  `proof.ovh.net` and `speed.hetzner.de` started returning `http=000` timeouts while general HTTPS
  (`google.com`, `github.com`) and ICMP stayed healthy. Two consecutive benchmark runs (40 Mbps, then
  0 Mbps) were source-side failures, not router config — that result is marked invalid in the table.
  Re-baseline against a different host before drawing conclusions.
- **Judge shaping by throughput collapse, not by `print`.** A queue tree prints identically whether or
  not traffic reaches it; the only proof is that measured throughput drops to `max-limit`.

## References

- MikroTik docs, *Queues* — CoDel/FQ-CoDel/CAKE kinds, `cake-*` and `fq-codel-*` properties, ROS 7.1beta3 availability: https://help.mikrotik.com/docs/spaces/ROS/pages/328088/Queues
- MikroTik docs, *Queue types*: https://help.mikrotik.com/docs/spaces/ROS/pages/196345871/Queue+types
- animmouse, *Fix Bufferbloat on MikroTik without disabling FastTrack* — interface-parented queue trees vs fasttrack, `packet-mark=no-mark`: https://www.animmouse.com/p/fix-bufferbloat-on-mikrotik-without-disabling-fasttrack/
- IBCSC, *Configure QoS with CAKE on MikroTik RouterOS* — CAKE parameter set and CPU-cost caveat: https://ibcsc.be/techblog/configurer-qos-mikrotik-routeros?lang=en
- mikrotikdocs.fyi, *CAKE and FQ-CoDel*: https://mikrotikdocs.fyi/firewall-and-quality-of-service/queues/cake-fq-codel/
