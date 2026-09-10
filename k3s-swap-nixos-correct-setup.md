---
type: how-to
tags: [k3s, kubernetes, swap, nixos, memory, kubelet, home]
created: 2026-09-10
last_verified: 2026-09-10
status: current
---

# Enabling swap on a k3s node correctly (NixOS)

Context: `home` (see [[warp-vm-nixos-migration-plan]]) runs a real, observed memory overcommit — Checkmk flags it CRIT at 157% of physical RAM committed, from running a full k3s control plane + platform layer + 13 apps + ~10 native services on one 16GB box. Swap was added as a host-level OOM safety net.

## The critical gotcha: swap alone breaks k3s

**kubelet refuses to start at all on a node with swap enabled**, unless explicitly told to tolerate it. Adding a swapfile without also telling k3s about it would have broken the entire cluster the moment the config landed — the same "one change, unexpected blast radius" class of mistake as an earlier incident in this same migration (a node-IP change that broke MetalLB without a paired `systemctl restart k3s`).

## What the research actually says about swap + Kubernetes

Two things are simultaneously true and worth being upfront about:

- **The traditional/still-dominant consensus is to disable swap**, including on k3s specifically. Kubernetes' own docs: kubelet won't start with swap present unless overridden. SUSE's k3s community forum, asked directly "should I disable swap memory on K3s?": *"yes you should disable swap on your hosts even with K3s"* — k3s doesn't do this automatically, same guidance as vanilla Kubernetes applies. Stated risks: swap can make eviction decisions less predictable, I/O latency on swapped pages can hit system-critical daemons, and pre-6.3 kernels had a real security gap (memory-backed volume data could land on swap-backed persistent storage; Linux 6.3+ added a `noswap` mount option specifically to close this).
- **This is genuinely shifting.** Kubernetes' `NodeSwap` feature (KEP-2400) — opt-in via a feature gate plus `memorySwapBehavior: LimitedSwap` — is maturing toward stable around the v1.34 release, explicitly for cases like "large memory footprint workloads that only touch a portion of memory at once" and "protect node stability from memory spikes" — close to the actual homelab situation here.

## The choice made: a third position, not either extreme

Rather than either fully disabling swap (the traditional-safe default) or fully opting into `LimitedSwap` (the newer, still-rough-edged feature), this setup does:

- `--kubelet-arg=fail-swap-on=false` — **yes**, lets kubelet start with swap present
- `--kubelet-arg=feature-gates=NodeSwap=true` — **no**, deliberately not set

This keeps kubelet from actively managing per-pod swap cgroup limits (`memory.swap.max`), so pod cgroups aren't deliberately routed to swap — it's host-level headroom for the kernel and non-pod processes, not per-pod swap accounting. **Caveat found while writing this up**: the exact behavior of `fail-swap-on=false` *without* the feature gate isn't crisply documented upstream — Kubernetes' swap-behavior reference page only defines `NoSwap`/`LimitedSwap` in the context of the feature gate being *on*. The reasonable inference (and legacy pre-KEP behavior) is that pod cgroups end up effectively swap-free by default in this configuration, but it wasn't verified against `/sys/fs/cgroup/kubepods.slice/*/memory.swap.max` directly — worth doing if this ever needs to be stated with full confidence rather than "reasonable inference."

## NixOS implementation

`configuration.nix` (the swapfile itself):
```nix
swapDevices = [
  {
    device = "/var/lib/swapfile";
    size = 8 * 1024;  # 8G
  }
];
```

`k3s.nix` (the mandatory pairing — `extraFlags`):
```nix
"--kubelet-arg=fail-swap-on=false"
```

Both landed in the same commit deliberately, since one without the other either does nothing (swapfile with kubelet still refusing swap — actually this isn't quite right either, worth re-checking; the safe assumption going in was "assume they're coupled, verify after") or breaks the cluster outright (the flag without the swapfile is a no-op, but the swapfile without the flag stops kubelet from starting).

`sudo nixos-rebuild switch --flake ...` picks up both — k3s restarts automatically since its systemd unit's flags changed.

## Verification (real, not just "activation succeeded")

```bash
free -h              # Swap: 8.0Gi total, 0B used initially - expected, headroom not yet needed
swapon --show        # /var/lib/swapfile  file  8G  0B  -2
systemctl is-active k3s                                    # active
kubectl get pods -A --no-headers | grep -v Running | grep -v Completed | wc -l   # 0
kubectl get node home -o jsonpath='{.status.addresses}'    # correct IP, node registered fine
```
Then re-checked every app's `.lan` HTTP route returned its normal response code post-restart, to rule out any regression from the k3s bounce itself (matching the general discipline of verifying the *specific* thing a change claims to fix, not a nearby proxy for it).

## References

- [Kubernetes docs — Swap memory management](https://kubernetes.io/docs/concepts/cluster-administration/swap-memory-management/)
- [Kubernetes docs — Linux Node Swap Behaviors](https://kubernetes.io/docs/reference/node/swap-behavior/)
- [Should I disable swap memory on K3s? — SUSE Forums](https://forums.suse.com/t/should-i-disable-swap-memory-on-k3s/42613)
- [k3s-io/k3s#12677 — Swap issues: Pods seem to ignore swap despite NodeSwap enabled](https://github.com/k3s-io/k3s/issues/12677) — evidence the newer `LimitedSwap` path is still rough, part of why it wasn't enabled here
