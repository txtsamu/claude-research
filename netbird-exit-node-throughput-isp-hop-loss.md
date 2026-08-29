---
type: investigation
tags: [netbird, wireguard, throughput, packet-loss, isp, mtr, iperf3, exit-node]
created: 2026-08-30
last_verified: 2026-08-30
status: current
---

# NetBird exit-node throughput bottleneck: not CPU, not this stack — ISP-internal packet loss

## Context

After confirming the self-hosted NetBird deployment
([netbird-selfhosted-podman-quadlet-setup.md](netbird-selfhosted-podman-quadlet-setup.md))
worked — mesh P2P connectivity solid, exit node functionally correct —
suspected the `wg-bypass` VM (2 vCPU) might be too weak to push real
throughput through the tunnel, echoing an earlier finding that the
MikroTik's own CPU capped a different WireGuard path at ~110Mbps against a
~850Mbps real line speed. Set out to measure it properly rather than
assume.

## Method

Installed `iperf3` on both `vpz` and the `wg-bypass` VM. Ran three
comparisons, each with a fresh one-shot `iperf3 -s -1` server on `vpz`:

1. **Tunnel path** — client on the VM against `vpz`'s NetBird IP
   (`100.68.54.91`), forcing traffic over `wt0`.
2. **"Direct" path, first attempt — invalid.** Client against `vpz`'s
   public IP. Result looked nearly identical to the tunnel test, which
   didn't make sense — turned out the VM's exit-node route (`Exit Node
   (vpz)`, selected while testing the deployment doc above) was still
   active, so **all** outbound traffic including this "direct" test was
   still exiting via `wt0` first, looping out through `vpz` and back in
   again on its public IP. `iperf3 -c` confirmed this: `local
   100.68.42.244` (the NetBird IP) instead of the VM's real LAN IP.
   Deselected the exit-node route (`netbird routes deselect "Exit Node
   (vpz)"`) and re-ran for a real baseline.
3. **Direct path, corrected** — same public-IP target, exit node
   deselected. `local 192.168.50.57` confirmed this time — genuinely
   bypasses NetBird entirely, still transits the MikroTik as gateway/NAT
   as normal.

CPU was snapshotted (`top`/`mpstat`) on `vpz`, the `wg-bypass` VM, and the
MikroTik itself (`/system resource print`) during live transfers, to rule
compute in or out before chasing anything else.

## Results

| Test | Throughput | Retransmits (10s) | Notes |
|---|---|---|---|
| Tunnel (`wt0`, corrected baseline available) | 40–49 Mbits/sec | 1049–2224 | Cwnd repeatedly collapsed to 1–95 KB |
| Direct (corrected, no tunnel) | 121 Mbits/sec | 2360 | Still through MikroTik NAT/forward |

CPU during transfer, all three hops:
- `wg-bypass` VM: **0–9% used**, ~90–100% idle
- `vpz`: **0–10% used** (one `sy` spike to 10%, otherwise idle)
- MikroTik: **7–8% `cpu-load`** (`/system resource print`, sampled twice
  mid-transfer) — nowhere near saturated even under the tunnel test

Interface error/drop counters, all clean:
- MikroTik `ether1` (WAN): 0 rx-drop/tx-drop/rx-error/tx-error
- `vpz` `ens3`: 0 across the board
- (`wg-bypass` VM's `wt0` interface itself showed 752 TX drops out of
  245,050 packets — a local queueing symptom, not the root cause; see
  below)

**Conclusion at this point: not CPU-bound anywhere in the stack, and no
device we control is dropping packets on its own interface.** That pushed
the investigation upstream, off our own infrastructure.

## Root cause: ISP-internal hop loss

Ran `mtr` (both ICMP and UDP, 30 cycles each) from the `wg-bypass` VM to
`vpz`'s public IP:

```
 7.|-- 175.184.238.144           20.0%    30   16.7  16.4  15.4  18.5   0.6   (UDP trace)
 7.|-- 175.184.238.144           23.3%    30   15.8  16.0  15.2  16.8   0.5   (ICMP trace)
```

Every hop before it (through two CGNAT hops, `100.64.x.x`/`100.69.x.x` —
confirming this ISP double/carrier-NATs its own customers) shows 0% loss.
Every hop after it, through international peering (Equinix Singapore) and
on to the destination, is also clean (0–6.7%, the last-hop number being
typical ICMP-deprioritization noise, not real loss). One single router,
deep inside the ISP's own backbone, is consistently dropping roughly 1 in 5
packets — for both UDP and ICMP alike, ruling out anything WireGuard- or
NetBird-specific about the loss itself.

**This one hop fully explains both throughput numbers.** With ~18ms RTT
and ~20% loss, TCP's congestion window gets slashed on essentially every
RTT — matches the collapsing-cwnd pattern seen directly in the `iperf3`
output for both the tunnel and (to a lesser extent, being a single
unencapsulated flow) the "direct" test.

**Revisits the earlier "MikroTik CPU bottleneck" finding.** That
conclusion (~110Mbps cap on a different WireGuard path, attributed to the
MikroTik's weak MIPS CPU) was never re-checked against actual `cpu-load`
readings under load at the time. Given this session's direct measurement
showed only 7-8% MikroTik CPU while still capped and lossy, it's plausible
the earlier finding was actually the same class of ISP-side loss
misdiagnosed as a compute limit — the retransmission overhead from real
packet loss can produce a throughput ceiling that looks like a rate/compute
cap without a hop-by-hop trace to tell them apart. Not re-verified against
that original path directly; noted here as a reason to be skeptical of that
older conclusion if it comes up again.

## What this doesn't explain

The 752 TX drops on the VM's own `wt0` interface (out of 245k packets,
~0.3%) remain unexplained by the ISP-hop finding alone — could be a local
qdisc/backpressure symptom *from* the same underlying loss (WireGuard
retrying into a queue that's already congested downstream) rather than an
independent problem. Not investigated further since it's a small fraction
next to the ISP hop's 20%, and the whole exit-node-throughput effort was
deprioritized (see below) before it became worth chasing.

## Outcome

Nothing in this stack (NetBird, Podman/Traefik, the `wg-bypass` VM, or the
MikroTik) needs fixing — the bottleneck lives inside the ISP's own network,
upstream of anything self-hosted here. Decided not to pursue this further
for now (no ISP ticket filed, no further path testing at different times of
day) — the household-wide routing goal this was originally in service of
had already been abandoned in favor of narrower NetBird use (see the
"Current state" section of the deployment doc), which doesn't depend on
squeezing more throughput out of the exit node specifically.

Cleanup done after testing: `wg-bypass` VM's exit-node route reverted to
its pre-test `Not Selected` state, temporary `iperf3` firewall opening on
`vpz` (port 5201/tcp) removed and persisted, no test processes left
running.

## Reusable technique

When a tunnel/VPN throughput number looks capped and CPU on every hop is
idle, don't stop at "must be network limits, nothing to check" — an `mtr`
(both ICMP *and* UDP, since some networks treat them differently) from one
tunnel endpoint to the other's *public* IP, run alongside the tunnel test,
localizes loss to a specific hop in a few minutes and settles the "is it
compute or is it the path" question definitively. Also worth remembering:
**check what route/policy is currently active on the test device before
trusting a "direct" baseline** — an exit-node route left selected from
a previous test silently routed the first "direct" attempt through the
same tunnel being measured, producing a falsely tunnel-like result.
