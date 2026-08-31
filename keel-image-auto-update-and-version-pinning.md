---
type: how-to
tags: [keel, kubernetes, kubectl, image-updates, semver, homelab]
created: 2026-08-31
last_verified: 2026-08-31
status: current
---

# Keel: automatic, semver-aware image updates for the homelab cluster

Prompted by realizing none of the `homelab` namespace's ~17 apps auto-update
despite most being tagged `:latest` — a common misconception:
`imagePullPolicy: Always` only re-pulls on the *next pod (re)start* (crash,
node move, manual rollout), not continuously on a running pod. A healthy
pod sitting untouched for a week is still running whatever image it pulled
a week ago, tag notwithstanding.

## Why Keel over the alternatives

- A CronJob doing `kubectl rollout restart` on a schedule: cheap, but blind
  — restarts even when there's no new image, and can't distinguish "no
  update available" from "update failed."
- ArgoCD/Flux image automation: only worth it running actual GitOps for
  this cluster, which this homelab doesn't.
- **Keel**: k8s-native, watches registries, triggers a rollout only when
  the image digest genuinely changes, supports semver-aware policies
  (`patch`/`minor`/`major`) instead of just floating-tag tracking.

## Install
```bash
helm repo add keel https://charts.keel.sh
helm repo update
kubectl create namespace keel
helm upgrade --install keel keel/keel -n keel --set helmProvider.enabled=false --wait --timeout 3m
```

## Policy: `minor` on every tracked deployment
```bash
kubectl annotate deployment/<name> -n homelab \
  keel.sh/policy=minor \
  keel.sh/trigger=poll \
  keel.sh/pollSchedule="@every 1h" \
  --overwrite
```
`minor` auto-applies patch + minor bumps, never a major version — keeps
schema/breaking-change risk manual. Applied to every app in `homelab`
(including `oneterm`'s 6-container pod) plus `bookstack-db`.

## The real work: pinning `:latest`/`:stable`/floating tags to actual versions first

Keel can only track forward from a real semver tag — it can't "bump" a
floating tag like `:latest`. So the bulk of the effort was resolving each
app's *actual currently-running* version and its true latest stable
release, then rewriting the image tag before adding the Keel annotation.

**Never trust a registry's default tag-list ordering** — this caught two
real near-misses:
- **Immich**: GHCR's `tags/list` (unsorted, paginated) topped out at
  `v1.91.1` on the visible page. The pod's own `/api/server/version`
  endpoint reported `v3.1.0` already running. Cross-checked against
  GitHub's Releases API (`/repos/<owner>/<repo>/releases/latest`, which
  *is* authoritative) — confirmed `v3.1.0` was in fact current stable.
  Pinning to the registry-listing "latest" would have been a two-major
  version downgrade.
- **Suwayomi**: same registry-listing problem — GHCR unsorted list
  suggested `v2.1.1999` was newest; GitHub Releases API showed the real
  latest was `v2.3.2243`.

**Method that held up**: for any project with a GitHub (or Codeberg)
repo, use the platform's own Releases API as ground truth
(`api.github.com/repos/<owner>/<repo>/releases/latest`,
`codeberg.org/api/v1/repos/<owner>/<repo>/tags`), then verify the
resolved tag actually exists as a pullable image before touching any
deployment:
```bash
token=$(curl -s "https://ghcr.io/token?service=ghcr.io&scope=repository:<owner>/<repo>:pull" | jq -r .token)
curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $token" \
  "https://ghcr.io/v2/<owner>/<repo>/manifests/<resolved-tag>"   # expect 200
```

### Final pinned versions
| App | Pinned to |
|---|---|
| bookstack / mariadb | 26.05.4 / 11.8.8 |
| forgejo / its postgres | 16.0.3 / 16.15-alpine |
| grafana | 13.0.2 |
| immich (server / redis) | v3.1.0 / 9.1.1 |
| nextcloud (app / db / redis) | 33.0.8-apache / 16.15-alpine / 7.4.11-alpine |
| couchdb, crawl4ai, copyparty, jellyfin, openwebui, suwayomi, flaresolverr, uptime-kuma | 3.5.2, 0.9.2, 1.20.21, 10.11.11, 0.11.1, v2.3.2243, v3.5.0, 2.5.3 |
| oneterm's 6 containers | already had real version tags — Keel tracking added, no tag change needed |

**Skipped from version-pinning** (upstream doesn't publish real semver,
nothing for Keel to track meaningfully):
- Immich's bundled postgres fork (`14-vectorchord0.4.3-pgvectors0.2.0`) —
  custom composite tag tightly coupled to Immich's own compatibility
  matrix; left untouched, excluded from Keel.
- `oneterm-ui:dark` — a private image with a theme-variant tag, not a
  version; GHCR listing also needs its own auth to even inspect.
- `searxng` — publishes CalVer+git-hash tags
  (`2026.8.29-d226b78bc`), not semver; left on `:latest`, unmanaged.

## A real regression caught live: `cekping-agent`

Pinning to its actual latest release (`1.0.0`, a private
`ghcr.io/awandataindonesia/cekping-agent` image) crash-looped it —
```
Error: PINGVE_SERVER and PINGVE_TOKEN environment variables are required.
```
The `1.0.0` release added a hard-required env-var check that the
`:latest` build it replaced apparently didn't have. Rolled back to
`:latest` immediately and pulled it out of Keel tracking, since fixing it
properly needs the two missing env vars (values not known at the time).
**Lesson generalized**: after pinning/updating any app, actually check
the pod came up healthy before moving to the next one — don't batch
blind. This is exactly what caught it (rollout status checked
immediately after applying all the `kubectl set image` calls, not
assumed).

## Verification pattern used throughout
```bash
kubectl get deployments -n homelab -o wide | awk '{print $1, $2, $3, $4}'   # READY/UP-TO-DATE/AVAILABLE
kubectl get pods -n homelab --field-selector=status.phase!=Running | grep -v Completed
```
Two benign, expected transients seen along the way, not real problems:
- `FailedAttachVolume: Multi-Attach error` on an RWO PVC during a rolling
  update — self-resolves once the old pod fully terminates and releases
  the volume.
- Slow `ContainerCreating` on `openwebui` specifically — its image bundles
  ML dependencies, genuinely large pull, not a fault.
