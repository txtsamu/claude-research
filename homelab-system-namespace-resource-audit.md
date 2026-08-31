---
type: how-to
tags: [kubernetes, resource-limits, cert-manager, metallb, fleet, capi, democratic-csi, snapshot-controller, rancher, homelab]
created: 2026-08-31
last_verified: 2026-08-31
status: current
---

# Resource requests/limits for system-namespace controllers (cert-manager, metallb, fleet/capi, democratic-csi, snapshot-controller)

Companion to [homelab-cluster-memory-limits-audit.md](homelab-cluster-memory-limits-audit.md)
(2026-08-30), which covered the `homelab` namespace only. This pass
covered everything *outside* `homelab` — turned out most `homelab` apps
were already well-sized from that earlier audit; the real gap was system
plumbing that had never been touched.

## Method

```sh
kubectl get deploy -A -o json > /tmp/all_deploy.json   # then parsed with python for requests/limits per container
```
Found 8 deployments (14 containers) with **`NONE`/`NONE`** — no
`resources` block at all: `cert-manager`, `cert-manager-cainjector`,
`cert-manager-webhook`, `metallb-controller`, `snapshot-controller`,
`rancher-webhook`, `capi-controller-manager`, `fleet-agent`,
`fleet-controller` (×3 containers), `gitjob`, `helmops`,
`democratic-csi-controller` (×6 sidecar containers).

`rancher` itself was also in this list (see
[rancher-startup-probe-cpu-throttle-restart-loop.md](rancher-startup-probe-cpu-throttle-restart-loop.md)
for that one specifically — same audit, but big enough to need its own
doc after it broke).

## Sizing sources

Researched official docs where they existed, sized off actual observed
usage (`kubectl top pods -A --containers`) elsewhere:

| Component | Source |
|---|---|
| cert-manager (all 3) | [cert-manager.io best-practice docs](https://cert-manager.io/docs/installation/best-practice/) |
| metallb-controller | community-documented production baseline |
| snapshot-controller | [kubernetes-csi.github.io](https://kubernetes-csi.github.io/docs/snapshot-controller.html), scaled down to match ~15Mi/pod actual usage (official example is 128Mi/512Mi, generous for this workload) |
| fleet-controller | [Fleet's own resource-limits docs](https://fleet.rancher.io/how-tos-for-operators/resource-limits) — official example is 768Mi request/8Gi limit, **way** oversized for this cluster's real ~90Mi usage; scaled down accordingly |
| gitjob/helmops/fleet-agent/capi-controller-manager/rancher-webhook/democratic-csi sidecars | no official numbers found anywhere — sized purely off observed usage (18-53Mi each) with generous CPU headroom (a direct lesson from the Rancher incident above) |

## Applied (exact commands)

One deployment at a time, `kubectl rollout status` gate between each
before moving to the next (all system components here are steady-state
low-CPU controllers, not CPU-burst-at-startup like Rancher — none of
these hit the startup-probe issue):

```sh
kubectl set resources deployment/cert-manager -n cert-manager --containers=cert-manager-controller --requests=cpu=50m,memory=64Mi --limits=cpu=500m,memory=256Mi
kubectl set resources deployment/cert-manager-cainjector -n cert-manager --containers=cert-manager-cainjector --requests=cpu=25m,memory=64Mi --limits=cpu=250m,memory=256Mi
kubectl set resources deployment/cert-manager-webhook -n cert-manager --containers=cert-manager-webhook --requests=cpu=25m,memory=48Mi --limits=cpu=250m,memory=128Mi

kubectl set resources deployment/metallb-controller -n metallb-system --containers=controller --requests=cpu=100m,memory=128Mi --limits=cpu=200m,memory=256Mi

kubectl set resources deployment/snapshot-controller -n kube-system --containers=snapshot-controller --requests=cpu=50m,memory=64Mi --limits=cpu=500m,memory=256Mi

kubectl set resources deployment/rancher-webhook -n cattle-system --containers=rancher-webhook --requests=cpu=25m,memory=96Mi --limits=cpu=500m,memory=256Mi

kubectl set resources deployment/capi-controller-manager -n cattle-capi-system --containers=manager --requests=cpu=50m,memory=64Mi --limits=cpu=500m,memory=256Mi

kubectl set resources deployment/fleet-agent -n cattle-fleet-local-system --containers=fleet-agent --requests=cpu=20m,memory=64Mi --limits=cpu=500m,memory=256Mi

kubectl set resources deployment/fleet-controller -n cattle-fleet-system --containers=fleet-controller --requests=cpu=50m,memory=128Mi --limits=cpu=1000m,memory=512Mi
kubectl set resources deployment/fleet-controller -n cattle-fleet-system --containers=fleet-cleanup --requests=cpu=20m,memory=32Mi --limits=cpu=500m,memory=128Mi
kubectl set resources deployment/fleet-controller -n cattle-fleet-system --containers=fleet-agentmanagement --requests=cpu=20m,memory=32Mi --limits=cpu=500m,memory=128Mi

kubectl set resources deployment/gitjob -n cattle-fleet-system --containers=gitjob --requests=cpu=20m,memory=32Mi --limits=cpu=500m,memory=256Mi
kubectl set resources deployment/helmops -n cattle-fleet-system --containers=helmops --requests=cpu=20m,memory=32Mi --limits=cpu=500m,memory=256Mi

kubectl set resources deployment/democratic-csi-controller -n democratic-csi --containers=external-attacher --requests=cpu=10m,memory=32Mi --limits=cpu=200m,memory=128Mi
kubectl set resources deployment/democratic-csi-controller -n democratic-csi --containers=external-provisioner --requests=cpu=10m,memory=32Mi --limits=cpu=200m,memory=128Mi
kubectl set resources deployment/democratic-csi-controller -n democratic-csi --containers=external-resizer --requests=cpu=10m,memory=32Mi --limits=cpu=200m,memory=128Mi
kubectl set resources deployment/democratic-csi-controller -n democratic-csi --containers=external-snapshotter --requests=cpu=10m,memory=32Mi --limits=cpu=200m,memory=128Mi
kubectl set resources deployment/democratic-csi-controller -n democratic-csi --containers=csi-driver --requests=cpu=20m,memory=64Mi --limits=cpu=300m,memory=256Mi
kubectl set resources deployment/democratic-csi-controller -n democratic-csi --containers=csi-proxy --requests=cpu=10m,memory=32Mi --limits=cpu=200m,memory=128Mi
```

`kubectl set resources` triggers a rolling update automatically (changes
the pod template) — no separate `kubectl rollout restart` needed.

## Follow-up: 5 `homelab` containers still under-declared

While re-checking `kubectl top --containers` against the earlier audit's
numbers, found 5 containers now running *at or above* their own declared
memory `request` (same root symptom as the original audit, smaller
scale — real usage had drifted past the request since 2026-08-30):

| Container | Request (before) | Actual usage | New request |
|---|---|---|---|
| `suwayomi/suwayomi` | 512Mi | 730Mi (143%) | 768Mi |
| `openwebui/openwebui` | 768Mi | 700Mi (91%) | 896Mi |
| `immich/server` | 1Gi | 1000Mi (98%) | 1536Mi |
| `crawl4ai` | 320Mi | 326Mi (102%) | 384Mi |
| `immich/redis` | 256Mi | 300Mi (117%) | 384Mi |

Limits untouched (all had comfortable headroom already). Applied the same
way:
```sh
kubectl set resources deployment/suwayomi -n homelab --containers=suwayomi --requests=cpu=200m,memory=768Mi
kubectl set resources deployment/openwebui -n homelab --containers=openwebui --requests=cpu=100m,memory=896Mi
kubectl set resources deployment/immich -n homelab --containers=server --requests=cpu=200m,memory=1536Mi
kubectl set resources deployment/crawl4ai -n homelab --containers=crawl4ai --requests=cpu=100m,memory=384Mi
kubectl set resources deployment/immich -n homelab --containers=redis --requests=cpu=50m,memory=384Mi
```

**Gotcha**: `openwebui`'s rollout hit a 90s `kubectl rollout status`
timeout — not a real failure, just a `FailedAttachVolume` "Multi-Attach
error" transiently logged while the RWO PVC handed off from the
old pod to the new one (normal for iSCSI/`democratic-csi`-backed
volumes on reschedule), followed by a genuinely slow image pull. Gave it
a longer timeout (180s) and it completed cleanly — check `kubectl
describe pod` events before assuming a timeout means something broke.

## Result

All 12 system deployments + 5 homelab containers updated, all rollouts
clean, 0 unexpected restarts anywhere. Rancher's dashboard "Reserved vs
Used" memory gap (see the Reserved/Used investigation this same session —
`rancher` alone had zero declared requests despite being the single
biggest consumer) should now track real usage much more closely
cluster-wide, not just for Rancher itself.
