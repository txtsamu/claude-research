---
type: how-to
tags: [immich, kubernetes, k3s, home, upgrade, postgres, valkey, deployment, homelab]
created: 2026-09-27
last_verified: 2026-10-03
status: current
---

# Upgrading Immich (k8s deployment on `home`)

Reusable recipe for bumping the Immich image on the `home` k3s cluster. Last run
**2026-10-02: v3.2.2 → v3.2.4** (clean patch bump; recipe unchanged, see [[immich-upgrade-v3-2-4-home.md]]). Before that, 2026-09-25: v3.2.0 → v3.2.2. See also
[[immich-pgdata-iscsi-lun-resize.md]] and [[immich-bull-queue-leftover-cleanup.md]].

## How this deployment is shaped (matters for the upgrade)

- Namespace `homelab`, `deployment/immich`, **plain `kubectl apply`-managed** —
  NOT Keel/Flux/Argo/Helm (checked annotations: only
  `kubectl.kubernetes.io/last-applied-configuration`). So `kubectl set image`
  is correct and won't be reverted by any GitOps loop.
- **One pod, three containers**: `server` (`ghcr.io/immich-app/immich-server`),
  `postgres` (`ghcr.io/immich-app/postgres:14-vectorchord0.4.3-pgvectors0.2.0`),
  `redis` (`valkey/valkey:9.1.2`). No separate machine-learning deployment.
- **Update strategy = `Recreate`** — critical: `db-data`, `redis-data`,
  `model-cache` are **ReadWriteOnce** PVCs. With RollingUpdate the new pod can't
  mount the RWO volumes while the old pod holds them → stuck rollout. `Recreate`
  terminates the old pod first, so it's safe. (`upload`/`photos-nfs` are RWX NFS.)
- No source manifest exists on `home` or the fedora box — the live deployment is
  the only copy. If a manifest repo is ever reintroduced, bump the image there too.
- Service is a MetalLB LoadBalancer at **`192.168.50.251:2283`**.

## Steps

### 1. Find the current + latest version
```bash
ssh moo@home 'kubectl -n homelab get deploy immich \
  -o jsonpath="{range .spec.template.spec.containers[*]}{.name}  {.image}{\"\n\"}{end}"'
```
Latest stable tag (ignore `-rc.*` prereleases) via the GitHub API — note the
GitHub release JSON has control chars in bodies, so parse with `strict=False`:
```bash
python3 - <<'EOF'
import json,urllib.request
req=urllib.request.Request("https://api.github.com/repos/immich-app/immich/releases?per_page=8",
    headers={"User-Agent":"curl","Accept":"application/vnd.github+json"})
for r in json.loads(urllib.request.urlopen(req,timeout=15).read().decode(errors="replace"),strict=False):
    print(("PRE " if r["prerelease"] else "REL "), r["tag_name"], r["published_at"][:10])
EOF
```

### 2. Check the DB/valkey image didn't change for the target version
The postgres image is pinned per release; a major DB image change needs its own
migration. Diff against the target's compose:
```bash
python3 -c "import urllib.request;print(urllib.request.urlopen(urllib.request.Request(
 'https://raw.githubusercontent.com/immich-app/immich/v3.2.2/docker/docker-compose.yml',
 headers={'User-Agent':'curl'})).read().decode(errors='replace'))" | grep -iE 'image:|postgres|valkey'
```
For 3.2.0→3.2.2 the postgres image was **identical**
(`14-vectorchord0.4.3-pgvectors0.2.0`), so only the `server` image moved. If the
postgres image DID change, read the release notes / DB migration guide first.

### 3. Confirm a fresh automatic DB backup exists (safety net)
Immich auto-dumps the DB into the upload volume nightly:
```bash
ssh moo@home 'kubectl -n homelab exec deploy/immich -c server -- \
  sh -c "ls -lt /usr/src/app/upload/backups/ | head -3"'
# -> immich-db-backup-YYYYMMDDT020000-v<ver>-pg14.19.sql.gz  (~620MB)
```

### 4. Bump the server image + watch the Recreate rollout
```bash
ssh moo@home '
kubectl -n homelab set image deployment/immich server=ghcr.io/immich-app/immich-server:v3.2.2
kubectl -n homelab rollout status deployment/immich --timeout=300s'
```
Recreate briefly takes Immich fully down (old pod stops before new starts); the
new ~1.5 GB image pull can take a minute or two — `0 of 1 updated replicas are
available` during the pull is normal.

### 5. Verify: version, clean migrations, health
```bash
# migrations (in the server container log):
ssh moo@home 'kubectl -n homelab logs deploy/immich -c server --tail=40 \
  | grep -iE "migration|schema drift|listening|error"'
# want: "Running migrations" -> "Finished running migrations" -> "No schema drift detected"

# version + ping over the LoadBalancer (the server container has no curl/wget):
curl -s http://192.168.50.251:2283/api/server/version   # -> {"major":3,"minor":2,"patch":2,...}
curl -s http://192.168.50.251:2283/api/server/ping       # -> {"res":"pong"}
```

## Gotchas seen

- **No `curl`/`wget` inside the `server` container** — `exec ... curl` gives
  `exit 7`/`command terminated`. Test the API from the LoadBalancer IP instead,
  or use `kubectl port-forward`.
- **Don't use RollingUpdate** on this deployment (RWO PVC deadlock — see above).
- Immich does **not** support downgrades once forward migrations have run; the
  nightly SQL dump in `upload/backups/` is the rollback path if a major upgrade
  goes wrong (restore into a fresh DB volume).

## References

- [Immich — Upgrading](https://docs.immich.app/install/upgrading/)
- [immich-app/immich Releases](https://github.com/immich-app/immich/releases)
