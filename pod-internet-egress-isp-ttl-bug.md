---
type: troubleshooting
tags: [talos, kubernetes, kube-ovn, flannel, cni, mikrotik, routeros, ttl, networking, homelab-vm, fasttrack, tls, warp-vm]
created: 2026-08-24
last_verified: 2026-08-30
status: current
---

# Pods couldn't reach the internet — root cause was an ISP TTL issue, not Kubernetes

A single symptom ("pods can't reach the internet") led through a 4+ hour systematic investigation across Talos, Flannel, a full CNI migration to Kube-OVN, and finally down to the physical WAN edge — where the actual cause turned out to be one hop upstream of everything Kubernetes-related. Documenting the full methodology here because the elimination process is the reusable part, not just the fix.

## Symptom

Pods could resolve DNS and reach LAN destinations fine, but any pod trying to reach a real internet host (`1.1.1.1`, `8.8.8.8`, `registry-1.docker.io`, etc.) over TCP would hang and eventually time out. `kubectl top`, LoadBalancer IPs (MetalLB), Rancher, storage (`democratic-csi`) — everything cluster-internal worked perfectly. Only pod→internet traffic was affected.

## Investigation timeline

### 1. Ruled out Flannel-specific causes first

Checked and eliminated, one at a time, directly on a Talos node (not by assumption):
- Masquerade/NAT rule correctness (`iptables -t nat -L FLANNEL-POSTRTG -n -v`) — correct, actively matching packets
- `FORWARD` chain filtering — wide open, `ACCEPT` on everything
- `net.bridge.bridge-nf-call-iptables` sysctl — correctly `1`
- `rp_filter` — correctly `0` on all relevant interfaces
- TCP checksum offload / GRO on the node's NIC — tested disabling live via `ethtool`, no change
- MTU on the VXLAN interfaces — correctly `1450`/`1500` (textbook-correct VXLAN overhead accounting)
- A full `kube-flannel` daemonset restart — no change (ruled out stale state)

**The decisive test at this stage**: a `hostNetwork: true` pod on the same node reached `1.1.1.1:443` successfully, while a regular pod-network pod on the *identical node* could not. That isolated the problem to the pod-network delivery path specifically — but see below, this conclusion turned out to be a half-truth (see "the real lesson" at the end).

A packet capture (`talosctl pcap`) at this point showed something that looked like a smoking gun: outbound SYN leaves fine, a reply SYN-ACK genuinely reaches the node's connection tracking (`SYN_RECV` state), but the reply never reaches the pod. The reply packet's `ttl` was `1`. This looked exactly like a spoofed/injected packet from something one hop away — **this interpretation was wrong**, see below.

### 2. Migrated the CNI from Flannel to Kube-OVN

Based on the (still partially correct — see conclusion) theory that this was a Flannel-specific NAT/conntrack bug, migrated the cluster's CNI to Kube-OVN, reasoning that a completely different NAT implementation (OVS/OpenFlow-based, not iptables-based) would sidestep whatever the flannel-specific issue was. Chose Kube-OVN over OVN-Kubernetes specifically because:
- Kube-OVN implements its gateway function in software (policy-route/ipset/iptables) rather than requiring a dedicated physical NIC bound to the OVS bridge — critical given every node here has exactly one NIC already carrying the Talos API, Kubernetes API, and the control-plane VIP
- Kube-OVN has an official, vendor-endorsed Talos install path (Sidero Labs publicly announced Kube-OVN + Talos + KubeVirt compatibility); OVN-Kubernetes only has informal community workarounds on Talos
- Kube-OVN ships `ENABLE_KEEP_VM_IP`/`ENABLE_LIVE_MIGRATION_OPTIMIZE` as default chart values — relevant since KubeVirt is a stated future goal for this cluster

Real gotchas hit doing this migration (all fixed, all still relevant if this is ever repeated):
1. **`siderolabs/openvswitch` is not a real Talos extension.** An earlier web search result was misread as confirming this existed; it does not, on any Talos version tested (checked v1.9.x through v1.13.9 directly against the Image Factory API, all `400 Bad Request: extension not available`). This cost one wasted `talosctl upgrade` attempt. The actual truth: **OVS kernel support is already compiled directly into the Talos kernel** (`CONFIG_OPENVSWITCH=y`, confirmed via `talosctl read /proc/config.gz`) — no extension needed at all. Kube-OVN's `DISABLE_MODULES_MANAGEMENT=true` chart value exists specifically because of this — it tells Kube-OVN's install scripts not to try loading kernel modules themselves.
2. **Helm's `--set` treats commas as list separators.** `--set MASTER_NODES="node1,node2,node3"` silently mis-parses. Needed escaped commas: `--set MASTER_NODES='node1\,node2\,node3'`.
3. **The chart's `MASTER_NODES` value needs actual IP addresses, not Kubernetes node names**, despite an official quick-start example implying otherwise. The chart passes it verbatim into a `NODE_IPS` env var with zero name-to-IP resolution — using node names crashes every `ovn-central` replica (`ERROR! host ip 192.168.50.92 not in env NODE_IPS ts-master01,ts-master02,ts-master03`).
4. **A stuck rolling update after fixing #3.** New (correct) and old (broken/crash-looping) `ovn-central` replicas can deadlock: the new pod needs its 2 peers healthy to join the OVN raft cluster and become `Ready`, but the rollout won't replace the old peers until the new pod is `Ready`. Fix: `kubectl scale rs <old-replicaset> --replicas=0` to force full cutover instead of a gradual rolling replace.
5. **Kube-OVN's `ovn0`/join-subnet interface confused kubelet's node-IP auto-detection.** Every node's Kubernetes `InternalIP` silently became `100.64.0.x` (Kube-OVN's internal join CIDR) instead of the real LAN IP, breaking `kubectl logs`/`exec` and anything scraping nodes by IP. Fixed with an explicit Talos machine config pin:
   ```yaml
   machine:
     kubelet:
       nodeIP:
         validSubnets:
           - 192.168.50.0/24
   ```
6. Talos's default `pod-security.kubernetes.io/enforce=baseline` policy blocks `NET_RAW` capability additions — same pattern hit earlier with `democratic-csi`/MetalLB.

**After all of this, the CNI migration completed successfully and Kube-OVN is healthy — but pod-to-internet traffic still failed, with the identical symptom.**

### 3. The pivotal test: reproduced on bare metal, no Kubernetes at all

This is the test that actually cracked it. Created a plain Linux network namespace directly on the Proxmox host (`px1`) — no VM, no container, no CNI, no Talos, nothing Kubernetes-related — with a veth pair and a standard `iptables MASQUERADE` rule:

```sh
ip netns add snattest
ip link add veth-host type veth peer name veth-ns
ip link set veth-ns netns snattest
ip addr add 10.99.99.1/24 dev veth-host && ip link set veth-host up
ip netns exec snattest ip addr add 10.99.99.2/24 dev veth-ns
ip netns exec snattest ip link set veth-ns up
ip netns exec snattest ip link set lo up
ip netns exec snattest ip route add default via 10.99.99.1
sysctl -w net.ipv4.ip_forward=1
iptables -t nat -A POSTROUTING -s 10.99.99.0/24 -o vmbr0 -j MASQUERADE
iptables -A FORWARD -s 10.99.99.0/24 -j ACCEPT
iptables -A FORWARD -d 10.99.99.0/24 -j ACCEPT

ip netns exec snattest nc -zvw5 1.1.1.1 443   # timed out -- identical symptom
```

(Note: the outbound interface for the MASQUERADE rule needs to be `vmbr0`, not the underlying physical NIC `eno1` — once a NIC is a bridge member, routing decisions happen on the bridge, not the raw member interface. Got this wrong on the first attempt; the rule silently never matched.)

**This reproduced the exact same failure with zero Kubernetes, zero virtualization guest, zero CNI involved.** That conclusively ruled out Talos, Flannel, Kube-OVN, and virtio-net/KVM as the cause. The problem was in the Proxmox host's own kernel path, or upstream of it.

### 4. Chasing a wrong theory: "spoofed packets"

At this point, a packet capture on `px1`'s physical NIC (`eno1`) during the SNAT test showed a genuine-looking reply SYN-ACK from `1.1.1.1`, but with `ttl=1, id=0`. This looked exactly like a locally-injected/spoofed packet (very low TTL, `id=0` is a common lazy-spoofing artifact), so the investigation briefly went looking for a device on the LAN segment impersonating `1.1.1.1`.

**This was the wrong interpretation**, caught by a simple sanity check that should have happened earlier: a completely normal, successful ping from `px1`'s own real IP to `1.1.1.1` *also* showed `ttl=1`, with 0% packet loss and perfectly normal latency. Checking a second and third unrelated destination (`8.8.4.4`, `example.com`) showed the identical `ttl=1` on every single reply, regardless of provider. **A `ttl=1` reply is not evidence of spoofing if it's happening for every destination uniformly — it means something in the path is rewriting or has always delivered traffic with an abnormally low TTL, full stop.**

### 5. Found the actual source: captured raw on the WAN interface, before any local processing

Used RouterOS's own packet sniffer directly on the Mikrotik's WAN-facing interface (`ether1`) to capture traffic as it physically arrives from the ISP modem, before *any* local processing (routing, NAT, firewall, mangle) touches it:

```
1.1.1.1 > 192.168.1.34: ICMP echo reply ... ttl 2
```

**`ttl=2` was already present on the raw packet, at the absolute network edge, before the Mikrotik does anything to it at all.** This is not a RouterOS FastTrack artifact either (checked and ruled out: FastTrack only accelerates already-established connections on the `forward` chain — it never touches the first packet of a new connection, which is exactly what was captured, and the sniffer capture point is before FastTrack or any other chain runs regardless).

**Conclusion: the ISP (or the ISP-provided modem in front of the Mikrotik) delivers replies with an already near-exhausted TTL.** Single-hop delivery (a device receiving a reply addressed directly to itself) survives fine on a budget of 1-2. Any additional internal hop — SNAT reverse + forward into a netns, a pod, a container, anything — needs at least one more hop of TTL budget than is available, and the packet legitimately expires per RFC 1812 (a compliant router is *required* to decrement TTL and discard-with-ICMP-time-exceeded at 0 — this was correct kernel behavior the whole time, not a bug in Talos, Flannel, Kube-OVN, or the Proxmox host).

## The real lesson: it was never actually "pod-network vs host-network"

This reframes the earlier "flannel-specific" conclusion from step 1: `hostNetwork` traffic worked not because pod-network delivery was broken, but because `hostNetwork` traffic to a self-terminating process needs **zero** additional internal hops after the packet already survived the trip from the ISP. Pod-network traffic needs at least one more. The number of hops needed, not the CNI or virtualization layer, was the actual variable the whole time. This is worth remembering for any future case with this shape: **before concluding "X subsystem is broken," check whether the same test succeeds or fails purely as a function of hop count, independent of which subsystem is doing the forwarding.**

## Fix

One `change-ttl` mangle rule on the Mikrotik, resetting TTL on all WAN-inbound traffic to a normal value before it's forwarded anywhere downstream:

```
/ip firewall mangle add chain=prerouting in-interface=ether1 action=change-ttl new-ttl=set:64 passthrough=yes comment="Fix ISP low incoming TTL"
```

This is the standard, well-documented technique for this exact class of problem (see [MikroTik forum discussion](https://forum.mikrotik.com/viewtopic.php?t=171672)). Rewriting at the network edge means every downstream host, VM, and pod sees a normal TTL — no changes needed anywhere else.

## Verification

- `ping` from `px1` to `1.1.1.1`: `ttl=1` → `ttl=63` after the fix
- The bare-metal SNAT/netns reproduction from step 3: now connects successfully to both `1.1.1.1:443` and `8.8.8.8:443`
- A pod inside the Kube-OVN cluster: successfully connects to both `1.1.1.1:443` and `8.8.8.8:443`
- The `docker-mirror`/`ghcr-mirror` registry-mirror pods, which had been crash-looping the entire session (`panic: dial tcp registry-1.docker.io: i/o timeout`) with dozens of restarts, immediately came up `1/1 Running` and started serving (`HTTP 200` on `/v2/`)

## Along the way: found and fixed a second, unrelated router issue

While investigating, found that a mangle rule policy-routing *all* LAN traffic toward a Cloudflare WARP VPN table (`0.0.0.0/0 via 192.168.50.200`, comment: "route ALL LAN internet traffic via .200") was pointing at a route that was disabled/non-functional — meaning the WARP VPN wasn't actually providing the intended privacy routing for any device on the LAN except the one explicitly bypassed (`warp-bypass` address-list, containing only the WARP VPN host itself). This rule was deleted. It was **not** the cause of the TTL issue (confirmed: the low TTL was present raw on the wire before this rule or any other Mikrotik processing ran), but it was a real, separate misconfiguration meaning WARP-based VPN routing hadn't been working as intended. Revisiting the WARP setup (why the route was disabled, whether to re-enable it with the mangle rule properly scoped) is a separate follow-up, not done as part of this investigation.

## Key findings / methodology notes

- **When a "the CNI must be broken" theory doesn't fully resolve the symptom after actually fixing/replacing the CNI, that's a strong signal the theory was wrong, not that the fix was incomplete.** The Kube-OVN migration was real, useful work (better fit for this cluster's KubeVirt future either way) — but it didn't fix the actual bug, because the bug was never in the CNI.
- **Reproduce on the simplest possible substrate before chasing complex-layer theories.** A 10-line bare-metal network-namespace test with a single `iptables` rule was more diagnostic than hours of in-cluster debugging, and took a few minutes to set up.
- **A suspicious-looking packet characteristic (very low TTL) needs a baseline comparison before being treated as evidence of something adversarial.** Checking what a *known-good* successful request looks like on the same path would have caught the "ttl=1 is just how this network replies" explanation much earlier.
- **Capture as close to the actual source of a symptom as your tooling allows.** The decisive capture was on the router's raw WAN interface, upstream of every layer that had been the focus of debugging for hours.
- Container image pulls (`docker.io`, `ghcr.io`, etc.) were unaffected by this bug throughout the whole investigation, which was itself a clue in hindsight: `containerd` pulls images via the **host's** network namespace, not the pod network — zero extra hops, same as any other single-hop traffic.

## Update 2026-08-30: the fix above only protected the *first packet* of each connection — FastTrack was silently undoing it for everything after

Six days after the fix above was applied and verified, the identical class of symptom resurfaced, discovered indirectly: Suwayomi (a manga reader running in this same cluster) started failing to fetch its extension catalog from GitHub with `SocketTimeoutException`/`StreamResetException`. Initial suspicion fell on a newly-built SOCKS proxy setup (unrelated work from the same session) — disabling that proxy helped partially but didn't fully fix it, which was the signal that something deeper was still wrong.

### Re-diagnosis, this time isolating exactly which phase of a connection was slow

`curl`'s per-phase timing (`time_connect`/`time_appconnect`/`time_total`) against a pod in this same cluster showed a very specific split:

```
dns=0.000040 connect=0.004777 tls=9.280577 total=10.749287
```

- **Raw TCP handshake: ~5ms.** Fast, healthy.
- **TLS handshake specifically: ~9.3 seconds.** Every time, against multiple destinations (`1.1.1.1`, `9.9.9.9`), regardless of TLS version or cipher-suite count (forcing a smaller TLS 1.2 ClientHello didn't help — ruling out a packet-fragmentation/MTU theory that fit the symptom shape at first glance).
- **Plain HTTP (no TLS) to the same destination: ~1.1 seconds total.** Fast. This was the decisive test — it proved the problem was specific to TLS's back-and-forth, not a generic "pod egress is just slow" characteristic, and not encryption/entropy-related (`/proc/sys/kernel/random/entropy_avail` was a healthy `256`, ruling out CSPRNG starvation).

### The actual packet capture

A privileged `hostNetwork: true` pod on the *same node* as the test pod, running `tcpdump -i eth0 -n -v` during a slow request, showed the real signature — inconsistent TTL within a single TCP flow:

```
1.1.1.1.443 > <node>.<port>: Flags [S.] ... ttl 63     <- SYN-ACK, correctly fixed
1.1.1.1.443 > <node>.<port>: Flags [.]  ... ttl 1      <- next packet, NOT fixed
1.1.1.1.443 > <node>.<port>: Flags [P.] ... ttl 1      <- NOT fixed
...
1.1.1.1.443 > <node>.<port>: Flags [.]  ... ttl 63     <- fixed again, briefly
1.1.1.1.443 > <node>.<port>: Flags [.]  ... ttl 1      <- NOT fixed
```

The *same flow*, same 4-tuple, flips between the fixed value (`63` — the router's `set:64` mangle rule minus one hop) and the raw broken ISP value (`1`) packet by packet. A single connection cannot see the ISP suddenly change its behaviour mid-stream — this had to be something on the router applying the fix inconsistently.

### Root cause: RouterOS FastTrack bypasses mangle for established connections

Checked the router's `/ip firewall filter` and found a long-standing, heavily-used rule:

```
chain=forward action=fasttrack-connection connection-state=established,related
```

51.6 million packets matched. **FastTrack's entire purpose is to skip the full netfilter pipeline — including mangle — for packets belonging to an already-established connection**, routing them through an accelerated path instead. The original fix (`change-ttl` in `chain=prerouting`) only ever ran against the *first* packet or two of a connection, before conntrack promoted it to FastTrack-eligible. Everything after that point — the bulk of a TLS handshake (`ServerHello` + certificate chain, several KB, many packets), any file download, anything beyond a trivial single-packet exchange — reverted to the ISP's raw, broken TTL and started dying again exactly as before the original fix, just now intermittently and only for larger/longer exchanges instead of universally.

This also explains why the original fix's verification (`ping`, a `nc`/`curl` connectivity check, a few registry-mirror pods) never caught it: those are either ICMP (not subject to the same `established,related` TCP fasttrack path in the same way) or complete within the pre-FastTrack window.

### Fix: exempt WAN-inbound connections from FastTrack specifically, rather than disabling it

FastTrack is genuinely load-bearing for this router (weak MIPS CPU, documented elsewhere in this repo) — disabling it globally to fix a WAN-specific problem would be a bad trade. Instead, mark only the connections that need the TTL fix, and exclude those from FastTrack eligibility, leaving FastTrack fully intact for LAN-to-LAN traffic (which was never affected by this bug in the first place):

```
/ip firewall mangle add chain=prerouting in-interface=ether1 \
    action=mark-connection new-connection-mark=wan-inbound-no-fasttrack \
    passthrough=yes comment="Mark WAN-inbound conns to exempt from FastTrack (preserves TTL fix)" \
    place-before=[find comment="Fix ISP low incoming TTL"]

/ip firewall filter set [find comment="FastTrack LAN traffic"] \
    connection-mark=!wan-inbound-no-fasttrack
```

The mark-connection rule must run *before* the `change-ttl` rule (same `chain=prerouting`, both matching `in-interface=ether1`) so every WAN-inbound connection is tagged from its very first packet, before FastTrack's `chain=forward` rule ever gets a chance to evaluate it.

### Verification

- Fresh connections from a cluster pod to `1.1.1.1`/`9.9.9.9`, TLS handshake: **9.3s → 30-40ms**, consistent across repeated runs.
- The exact Keiyoushi extension-catalog fetch that started this investigation (`https://github.com/keiyoushi/extensions/raw/repo/index.pb`): **timeout → 69ms, HTTP 302**.
- LAN-to-LAN latency (MikroTik → a LAN host) unaffected: sub-millisecond, `ttl=64`, FastTrack still firing normally for that traffic.
- Existing already-established connections at the time of the fix don't retroactively benefit (connection tracking state persists) — only new connections after the fix was applied are covered. Not an issue in practice since TCP connections are short-lived relative to this being a one-time router config change.

### Revised key lesson

**A fix verified against a connection's first packet or two is not verified against that connection's full lifetime.** FastTrack (or any conntrack-based acceleration path) can silently exempt "established" traffic from mangle/filter processing that a fix depends on, without any error, warning, or obviously broken behaviour on the first exchange. The tell here was inconsistent TTL *within a single flow* — worth specifically checking for on any future "intermittent, only for larger exchanges" symptom on a router using connection-tracking acceleration.

This also explains an earlier same-session observation that never got its own write-up: pods reaching an external HTTP proxy consistently showed several seconds of latency on new connections, provisionally chalked up in conversation to "pod network egress is just inherently slow for new connections." That provisional explanation was never verified against packet captures and should be treated as superseded by this finding, not as an independently-confirmed separate characteristic.

Note this is a different phenomenon from the [netbird-exit-node-throughput-isp-hop-loss.md](netbird-exit-node-throughput-isp-hop-loss.md) investigation (real, independently-confirmed ~20% packet loss at a specific ISP backbone hop on the `wg-bypass` VM ↔ `vpz` NetBird tunnel) — that one is unrelated to this FastTrack/TTL bug and its conclusion stands as-is.
