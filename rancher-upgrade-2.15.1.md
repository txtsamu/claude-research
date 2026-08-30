---
type: how-to
tags: [rancher, helm, kubernetes, upgrade, cattle-system, security]
created: 2026-08-30
last_verified: 2026-08-30
status: current
---

# Rancher Helm upgrade: v2.15.0 → v2.15.1

Routine patch upgrade, `cattle-system` namespace, Talos cluster.

## Checked first

```bash
helm list -n cattle-system            # confirm current release/chart version
helm repo update
helm search repo rancher-latest/rancher --versions   # latest available
helm get values rancher -n cattle-system              # preserve exact existing config
```

Existing values (`bootstrapPassword`, `hostname`,
`ingress.enabled: false`, `replicas: 2`) — small, easy to pass through
explicitly on upgrade rather than relying on `--reuse-values` (avoids any
surprise from a values-schema change between chart versions).

Read the [official release notes](https://github.com/rancher/rancher/releases/tag/v2.15.1)
before upgrading rather than assuming "patch = trivial" — this one had real
substance: 5 security fixes (SAML assertion replay across multi-replica
deployments — directly relevant here, since this deployment runs
`replicas: 2`; project-secrets disclosure across clusters; token listing
via crafted label selectors; a GlobalRole RBAC lockout bug; a Norman API
identity-mutation issue) plus a Fleet Helm-template vulnerability. No
breaking changes for this bump.

Also confirmed prerequisites: Helm `3.21.4` (well above the documented
3.18+ requirement) and `cert-manager v1.21.1` already installed and
compatible.

## Upgrade

```bash
helm upgrade rancher rancher-latest/rancher -n cattle-system --version 2.15.1 \
  --set bootstrapPassword=<existing value> \
  --set hostname=<existing value> \
  --set ingress.enabled=false \
  --set replicas=2 \
  --wait --timeout 5m
```

Gotcha: if driving this over SSH with a wrapper `timeout` shorter than
Helm's own `--wait --timeout`, the local wrapper can cut the client off
before Helm finishes waiting — the upgrade itself still completes
server-side regardless (Helm submits the change to the API server
immediately; `--wait` just blocks the *client* until rollout finishes).
Check actual rollout status separately rather than trusting the client
exit code alone:
```bash
kubectl rollout status deployment/rancher -n cattle-system --timeout=150s
```

## Verification

```bash
helm list -n cattle-system                          # revision bumped, chart 2.15.1
kubectl exec -n cattle-system deploy/rancher -- rancher --version
curl -sk -o /dev/null -w "%{http_code}\n" https://<rancher-hostname>/
kubectl get pods -n cattle-system                    # rancher-webhook untouched
```

A `helm-operation-*` job pod spins up automatically right after any
Helm-driven change to Rancher — that's Rancher's own internal
chart-reconciliation job, normal and self-cleaning, not something the
upgrade itself created incorrectly.
