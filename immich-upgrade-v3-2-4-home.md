---
type: how-to
tags: [immich, kubernetes, k3s, home, upgrade, postgres, kubectl]
created: 2026-10-02
last_verified: 2026-10-02
status: current
---

# Immich v3.2.2 → v3.2.4 on k3s (`home`)

A patch upgrade that reused the recipe in [immich-upgrade-k8s-home.md](immich-upgrade-k8s-home.md) unchanged. Immich is `deployment/immich` in namespace `homelab`: one pod with `server`, `postgres` and `redis` containers (no separate ML pod). It is applied with plain kubectl and is **not** managed by the home-nixos flake, so there is no flake change or PR for an image bump.

## Steps

1. Find the current and latest versions. Current: `ghcr.io/immich-app/immich-server:v3.2.2`. Latest stable: v3.2.4 (v3.2.3 was skipped upstream; v3.3.0-rc.* are prereleases and were ignored). Notes for v3.2.4: a memory-leak fix via a dependency update plus one mobile fix, no breaking changes. The v3.2.4 compose file uses the same DB and cache images as the live deployment (postgres `14-vectorchord0.4.3-pgvectors0.2.0`, valkey `9.1.2`), so only the server image changes.
   ```bash
   ssh moo@home 'kubectl -n homelab get deploy immich -o jsonpath="{.spec.template.spec.containers[*].image}"'
   ```
2. Confirm Immich's own nightly dump exists (`upload/backups`, newest `immich-db-backup-20261002T020000-v3.2.2-pg14.19.sql.gz`, 622 MB), then take a manual dump on `home`:
   ```bash
   ssh moo@home 'mkdir -p ~/immich-backups && kubectl -n homelab exec deploy/immich -c postgres -- pg_dump -U postgres -d immich --clean --if-exists | gzip > ~/immich-backups/immich-pre-v3.2.4-20261002T125429-v3.2.2.sql.gz && gzip -t ~/immich-backups/immich-pre-v3.2.4-*.sql.gz'
   ```
   Result: 619 MB, `gzip -t` OK, 30 GB free on `/`.
3. Upgrade and watch the rollout (Recreate strategy, so about a minute of downtime):
   ```bash
   ssh moo@home 'kubectl -n homelab set image deployment/immich server=ghcr.io/immich-app/immich-server:v3.2.4 && kubectl -n homelab rollout status deployment/immich --timeout=500s'
   ```
4. Verify:
   ```bash
   ssh moo@home 'kubectl -n homelab get pods | grep immich; curl -s http://192.168.50.251:2283/api/server/version; curl -s http://192.168.50.251:2283/api/server/ping'
   ```
   Result: pod 3/3 Running, 0 restarts; version `{"major":3,"minor":2,"patch":4,"prerelease":null}`; ping `pong`. The server log showed migrations running and finishing, "No schema drift detected", and no errors. One harmless warning: `LegacyRouteConverter: Unsupported route path "/api/*"`. This checks the MetalLB IP directly, not the `.lan` route.

## Rollback

`kubectl -n homelab set image deployment/immich server=ghcr.io/immich-app/immich-server:v3.2.2`. If the DB schema moved, restore the dump above. Patch releases here ran migrations without drift.

## Notes

- The manual dump lives at `/home/moo/immich-backups/` on `home` and is not cleaned up automatically.
- This was done by a subagent, and the parent session re-verified the image, pod state, version endpoint and backup file afterward.
- The agent's evomem search timed out, so no extra context came from there.
