---
type: how-to
tags: [infrastructure, forgejo, kubernetes, kube-ovn, talos, networking, egress, homelab]
created: 2026-08-27
last_verified: 2026-08-30
status: unresolved
---

# homelab-vm → Talos/k8s migration discovery, and an unresolved Kube-OVN egress bug

**Date:** 2026-08-27
**Trigger:** Restarted a stopped Forgejo instance on `homelab-vm` (this host) as part of routine mirror-sync maintenance, assuming it was the real `git.<PERSONAL_DOMAIN>`. It wasn't.

---

## 1. Infrastructure discovery: homelab-vm is decommissioned

This host (`homelab-vm`, 192.168.50.80, where all Claude Code sessions in this
project have been running) was **fully decommissioned as of 2026-08-25** —
confirmed via a commit on the real `claude-research` repo itself:
`"homelab-vm fully decommissioned: everything moved to warp-vm"`.

Everything moved to a **Talos Linux Kubernetes cluster**, reachable via SSH
jump host `warp` (`ssh warp`, per `~/.ssh/config` — proxies through
`cloudflared access ssh`):

```
ts-master01   192.168.50.91   control-plane
ts-master02   192.168.50.92   control-plane
ts-master03   192.168.50.93   control-plane
ts-worker01   192.168.50.94   worker
ts-worker02   192.168.50.95   worker
ts-worker03   192.168.50.96   worker
```
- OS: Talos v1.13.9 (immutable, API-only — **no SSH to nodes**, only `kubectl`
  or `talosctl`)
- Kubernetes v1.36.3
- CNI: **Kube-OVN** (OVS 3.5.5, `br-int` + `ovn0` internal port + geneve
  tunnels between nodes, no separate `br-external`)
- Everything that used to live on homelab-vm's Podman Quadlets now runs as
  k8s deployments in the `homelab` namespace: forgejo, immich, nextcloud,
  grafana, jellyfin, openwebui, searxng, uptime-kuma, copyparty, suwayomi,
  oneterm, bookstack, couchdb, crawl4ai, and more. Plus cert-manager, rancher,
  fleet, metallb, a registry mirror namespace, and democratic-csi.

**`warp`'s ssh config entry**: `HostName warp.<PERSONAL_DOMAIN>`, `User moo`,
`ProxyCommand cloudflared access ssh --hostname %h` — not itself a cluster
node, just a bastion with `kubectl` configured.

## 2. The stale decoy: a leftover Podman Forgejo on homelab-vm

`homelab-vm` still had a Podman-Quadlet-deployed Forgejo (`forgejo-app`,
`forgejo-db`, host network, web on :3500) — **configured with the same
`FORGEJO__server__DOMAIN=git.<PERSONAL_DOMAIN>`** as the real one, but completely
disconnected from actual DNS/tunnel routing. It had been stopped (clean
`SIGTERM`, not a crash — host itself never rebooted, up since Aug 12) since
2026-08-24 ~16:50 WIB, most likely by `podman-auto-update.timer` doing an
image update and the container just never restarting afterward (auto-update
stops aren't covered by `Restart=on-failure`, that only fires on crashes).

**I found this stopped instance, assumed it was the real thing, and
restarted it.** Every `mirror-sync` API call I made across this entire
session (rounds 1-6 of the Gemma/Qwen/Ornith model doc, this doc's own
first push attempt) hit this decoy — not the real `git.<PERSONAL_DOMAIN>`. No data
was lost (GitHub, the actual `git push origin` target, was correct the
whole time) but the Forgejo mirror was stale on the real instance for the
whole session until manually re-triggered from `warp`.

**Action item, not yet done:** stop/remove this leftover Podman Forgejo on
homelab-vm (`sudo systemctl stop forgejo-app forgejo-db forgejo-pod`) to
prevent this exact confusion from happening again. Left running for now in
case something still depends on it.

**Lesson:** when a service's local instance responds and looks configured
correctly, that's not proof it's the one actually serving production traffic
— check the real endpoint (DNS/tunnel/LoadBalancer) matches, not just that
*a* local instance with matching config exists and answers.

## 3. Real Forgejo location

- k8s Deployment `forgejo-app` / `forgejo-db`, namespace `homelab`, on
  `ts-worker03` (currently)
- Service: `LoadBalancer`, cluster IP `10.100.208.93`, **external IP
  `192.168.50.231`** (MetalLB), ports `3500` (web) / `2223` (git ssh)
- Reachable directly at `http://192.168.50.231:3500` from the `warp` bastion
  (or presumably anywhere on the LAN) — doesn't require going through the
  Cloudflare tunnel for internal access/scripting
- Public URL `https://git.<PERSONAL_DOMAIN>` presumably routes to this via Cloudflare
  Tunnel → MetalLB IP (not independently re-verified this session)
- To generate an admin token for API use:
  ```bash
  kubectl exec -n homelab deploy/forgejo-app -- su-exec git \
    forgejo admin user generate-access-token -c /data/gitea/conf/app.ini \
    -u samu -t <token-name> --scopes write:repository --raw
  ```
  (note `su-exec git`, not `-u git` like the old podman `exec` flag — this
  is a plain `kubectl exec`, the user-switch has to happen inside the
  command itself)

## 4. Unresolved: Kube-OVN pod-network egress to the internet fails ~94% of the time

### Symptom

Forgejo's GitHub pull-mirror silently stopped updating after the migration
(mirror timestamp advanced on each sync attempt, content did not). Traced
to: **pods on this cluster mostly cannot reach the public internet.**
`kubectl exec <pod> -- curl https://github.com` times out on ~16 of 17
attempts tested; DNS resolution works fine (that's internal, via CoreDNS).

### What's confirmed working (ruled out as causes)

| Layer | Check | Result |
|---|---|---|
| Node network | `hostNetwork: true` pod → github.com | **200 OK**, every time |
| Node routing | `ip_forward=1`, `rp_filter=0`, correct default route via `eth0` | fine |
| NetworkPolicy | `kubectl get networkpolicy -n homelab` | none exist |
| iptables `nat` table | `OVN-POSTROUTING` → `OVN-MASQUERADE` chains | structurally correct, real packet counts |
| iptables `filter` FORWARD | default ACCEPT, real traffic (362K pkts/72MB) already forwarded from pod subnet | fine |
| OVN chassis/port-bindings | `ovn-sbctl show` — all 6 nodes correctly registered, hostnames match, no stale entries | fine |
| OVN logical router route | `ovn-nbctl lr-route-list` — `0.0.0.0/0 → 100.64.0.1` (join subnet gateway) | correct |
| Kernel NAT/conntrack modules | `ovs-appctl dpctl/dump-conntrack` shows real, working conntrack entries (geneve tunnels, node↔pod traffic) | **works fine for other traffic** — rules out missing Talos kernel module theory from Kube-OVN's official Talos-install docs |
| `kubectl-ko trace` (OVN's own pipeline simulator) | traced a pod→github.com TCP packet | **shows success** — full pipeline resolves to `ct(commit,zone=13,...,nat(src)) → output`, not a drop |

### The actual failure signature

Live-captured with `conntrack -L` + `ovs-appctl dpctl/dump-conntrack`
polled during real connection attempts (client pod + privileged
hostNetwork monitor pod, same node):

- **16 of 17 attempts**: curl times out (`exit 28`), and **no conntrack
  entry ever appears** for the attempted connection, in either the OVS
  datapath table or the kernel netfilter table. The packet vanishes with
  zero trace at any inspectable layer.
- **1 of 17 attempts**: completely normal lifecycle — conntrack shows
  `ESTABLISHED` (both the pod-facing entry, zone=16, and the NAT'd
  node-facing entry) for several seconds, then a clean `CLOSE`. Full
  success, real HTTP-capable connection.

This is **not** a binary "broken vs. working" — it's a severe intermittent
failure (~6% success rate) with two completely distinct behaviors (either
perfect success or total silence, nothing in between/partial). That rules
out simple misconfiguration (would be consistently broken) and points at
something timing/resource/race-related: possibly OVS flow-cache population
for "cold" (never-seen-before) destination IPs, a conntrack zone allocation
limit, or a Kube-OVN/OVS internal race specific to first-packet handling.
The one success happened shortly after an unrelated `kubectl-ko trace` run,
which may have incidentally warmed some flow/cache entry — circumstantial,
not confirmed.

### What wasn't tried (deliberately, given risk)

- No live cluster networking config was changed. Everything above is
  read-only diagnosis (`kubectl exec`, `ovs-vsctl show`, `ovn-nbctl`,
  `ovn-sbctl`, `conntrack -L`, packet traces). Modifying NAT/conntrack
  zone config, OVS bridge mappings, or Kube-OVN CRDs on a live cluster
  carries real risk of breaking other traffic and wasn't attempted without
  the user's explicit go-ahead on a specific fix (which was never reached
  — investigation stopped at diagnosis, no confirmed root cause to act on).
- Web search (Kube-OVN GitHub issues, official docs, FAQ) did not surface
  an exact match for this specific signature (intermittent silent-drop with
  zero conntrack trace on failure, perfect lifecycle on rare success). The
  closest related issues were about asymmetric return traffic on other
  cloud providers (Hetzner) and generic NAT/conntrack kernel-version
  mismatches — informative but not a direct hit.

### Recommended next steps (not yet done)

1. Take this diagnostic trail to Kube-OVN's GitHub issues or Discord — the
   specific signature (94% silent-drop-zero-trace, 6% perfect success) is
   distinctive enough that maintainers may recognize it immediately.
2. If reproducing for a bug report: the test harness used here was two pods
   on the same node (`nodeName` pinned) — one `hostNetwork: true` privileged
   `nicolaka/netshoot` pod running `conntrack -L` / `ovs-appctl
   dpctl/dump-conntrack` in a poll loop, one plain pod-network
   `curlimages/curl` pod issuing repeated `curl -m 5` attempts to a fixed
   external IP (bypassing DNS to isolate the variable, used
   `-H "Host: github.com" -k` against `20.205.243.166` directly).
3. Consider filing with Kube-OVN's `env-check` / `diagnose` subcommands of
   `kubectl-ko` (found at `/kube-ovn/kubectl-ko` inside
   `kube-ovn-controller` pods) — `diagnose all` was tried but hit an RBAC
   permission error partway through on an unrelated serviceaccounts check;
   worth re-running with elevated permissions or investigating just the
   parts that did complete.
4. Two of three `ovn-central` replicas (`2cdqh`, `djq6b`) fail to serve
   their local `ovnsb_db.sock` via direct `ovn-sbctl` exec (only `5jftt`,
   on `ts-master03`, responds) — investigated as a possible cause but the
   error logs are stale (from initial cluster bootstrap on Aug 23), so
   likely unrelated to this bug. Still worth fixing independently since a
   degraded 3-node Raft cluster running effectively as 1-of-3 is its own
   latent risk.

## 5. Useful commands for next time

```bash
# Access the cluster
ssh warp   # bastion with kubectl configured, not a cluster node itself

# Find Forgejo
kubectl get pods -n homelab | grep forgejo
kubectl get svc forgejo-app -n homelab   # LoadBalancer external IP

# Generate an admin API token
kubectl exec -n homelab deploy/forgejo-app -- su-exec git \
  forgejo admin user generate-access-token -c /data/gitea/conf/app.ini \
  -u samu -t <name> --scopes write:repository --raw

# Trigger a mirror sync manually (from warp, hits the real instance directly)
curl -s -X POST http://192.168.50.231:3500/api/v1/repos/samu/claude-research/mirror-sync \
  -H "Authorization: token <token>"

# Kube-OVN diagnostics
kubectl exec -n kube-system deploy/kube-ovn-controller -- /kube-ovn/kubectl-ko trace \
  <namespace>/<pod-name> <target-ip> tcp <port>
kubectl exec -n kube-system <ovs-ovn-pod-on-node> -- ovs-vsctl show
kubectl exec -n kube-system <ovn-central-pod> -- ovn-sbctl show   # try all 3 replicas, only some may respond
kubectl exec -n kube-system <ovs-ovn-pod-on-node> -- ovs-appctl dpctl/dump-conntrack

# Test pod pinned to a specific node (for isolating node-specific issues)
kubectl run test --image=curlimages/curl -n homelab \
  --overrides='{"spec":{"nodeName":"<node>"}}' --command -- sleep 60
```

## 6. Stale local memory that needs correcting

The pre-existing memory entries `mem-network-*` (network topology) and
`mem-homelab-vm-*` describe homelab-vm as the live, active host — both are
now outdated as of 2026-08-25. See the accompanying memory update for the
corrected picture (superseding entries, not deleting the history).
