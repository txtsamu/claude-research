---
type: how-to
tags: [rancher, kubernetes, talos, k3s, migration, cert-manager, metallb, caddy, cattle-system]
created: 2026-09-06
last_verified: 2026-09-06
status: current — migrated, old Talos-side rancher scaled to 0
---

# Migrating Rancher from Talos to k3s (same day as [[talos-to-k3s-migration-warp]])

## Context

Following the `homelab` namespace migration to k3s on warp, Rancher itself (running
on the Talos cluster in `cattle-system`, managing that cluster as its own `local`)
needed to move too, ahead of decommissioning Talos.

## First: check whether a fresh install or a full backup/restore is warranted

Inspected the existing Rancher install before deciding:

```bash
kubectl --context=talos get clusters.provisioning.cattle.io -A   # only "local" — no other managed/imported clusters
kubectl --context=talos get users.management.cattle.io           # just the default admin, no other local users
kubectl --context=talos get authconfigs.management.cattle.io     # only "local" enabled, no SSO/LDAP configured
kubectl --context=talos get globalroles.management.cattle.io -o custom-columns=NAME:.metadata.name,BUILTIN:.builtin | grep -v true  # no custom roles
kubectl --context=talos get clusterrepos.catalog.cattle.io        # only the 3 default catalog repos
kubectl --context=talos get features.management.cattle.io -o custom-columns=NAME:.metadata.name,VALUE:.spec.value  # all nil (default)
```

Result: a near-vanilla install managing only itself, nothing custom. **Fresh install
was the right call** — a full `rancher-backup`/restore cycle would have been
overkill for recreating essentially the default admin user.

## Install

`helm get values rancher -n cattle-system` on Talos first, to replicate the exact
config. Rancher's chart needs cert-manager present even with `ingress.enabled=false`:

```bash
helm -n cert-manager install cert-manager jetstack/cert-manager --version 1.21.1 --set crds.enabled=true
```

```bash
helm -n cattle-system install rancher rancher-latest/rancher --version 2.15.1 \
  --set hostname=rancher.192.168.50.220.nip.io \
  --set bootstrapPassword="<REDACTED - reused Talos's original, so the login didn't change>" \
  --set ingress.enabled=false \
  --set replicas=1 \
  --set resources.limits.cpu=2000m --set resources.limits.memory=3Gi \
  --set resources.requests.cpu=250m --set resources.requests.memory=1Gi \
  --set startupProbe.failureThreshold=30
```

Deviated from the original Talos config in one place: `replicas=1` instead of `2` —
single k3s node, so a second replica buys zero HA, just doubles resource use.

`ingress.enabled=false` means Rancher terminates its own TLS directly on a bare
`LoadBalancer` Service — no cert-manager Certificate object involved for the main
UI/API path, cert-manager is only needed as a chart dependency (e.g. the
rancher-webhook's internal certs).

## Cutover

Same MetalLB pool as the homelab apps (Rancher's own service already lived at
`192.168.50.220`, inside that same pool) — same reuse-the-IP pattern:

```bash
kubectl --context=talos -n cattle-system delete svc rancher
kubectl --context=k3s -n cattle-system patch svc rancher --type=merge \
  -p '{"metadata":{"annotations":{"metallb.io/loadBalancerIPs":"192.168.50.220"}},"spec":{"type":"LoadBalancer"}}'
kubectl --context=talos -n cattle-system scale deploy rancher rancher-webhook --replicas=0
```

**Consequence of reusing the IP: Caddy's `rancher.lan` route on warp
(`/root/caddy/Caddyfile`, `reverse_proxy https://192.168.50.220`) needed zero
changes** — same pattern as the Cloudflare tunnel needing no changes for the app
migration. Verified end-to-end (`curl -k https://rancher.lan/ping` → `pong`) after
cutover.

k3s auto-registered itself as Rancher's new `local` cluster immediately —
`kubectl --context=k3s get clusters.provisioning.cattle.io` showed it `READY=true`
within ~2 minutes of the fresh install (self-managing behavior is inherent, no
explicit import step).

## Verification

- `management server version 0.78.1`-equivalent output in `rancher` pod logs = clean
  boot (no CRD/webhook install errors).
- `https://rancher.lan/ping` → `pong` through the unmodified Caddy route.
- Login with the reused bootstrap password worked immediately — same credentials as
  before the migration.

## Notes on secrets

The bootstrap password and TrueNAS-style API keys referenced in this migration are
not reproduced here — see [[talos-to-k3s-migration-warp]] for where the real
democratic-csi credential lives.
