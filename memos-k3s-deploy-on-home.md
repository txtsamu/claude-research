---
type: how-to
tags: [memos, memogram, telegram, k3s, kubernetes, home, metallb, truenas-iscsi, sqlite, service-links]
created: 2026-11-07
last_verified: 2026-11-07
status: current
---

# Deploying Memos (usememos/memos) on the home k3s cluster

Memos 26.11.0 as a single-replica Deployment in the `homelab` namespace on `moo@home` (NixOS, single-node k3s, 192.168.50.200). SQLite database on a `truenas-iscsi` PVC, exposed through MetalLB at **192.168.50.244:5230**. The manifest is `~/sessions/2026-11-07-memos-k3s/memos.yaml` (also reproduced below).

## Time estimate
Total about 15 min wall clock (estimate, no precise timing taken). Measured from the pod events: image pull 7 s, PVC provision + iSCSI attach about 13 s, rollout after the fix about 25 s. The first rollout wait timed out at the 240 s limit because of the bug below, which cost about 5 min.

## Steps
1. Context checks (read-only). `ssh moo@home 'kubectl get nodes; kubectl get ns'` shows one node `home`, namespace `homelab`. Apps there are plain manifests applied with `kubectl` (they are not in the `home-nixos` repo, which only owns the host). Copied conventions from the newest app (`gowa`): `strategy: Recreate`, label `spread-group: homelab-app`, pinned image tag, probes, `truenas-iscsi` PVC, Service with annotation `metallb.io/loadBalancerIPs`.
2. Pick a free MetalLB IP. Pool `home-temp-pool` = 192.168.50.240-252. `kubectl get svc -A | grep LoadBalancer` showed 240-243, 245, 247, 249-251 in use, so 244 was free.
3. Pick a version tag (house rule: never `latest`). `gh api repos/usememos/memos/releases/latest --jq .tag_name` gave `26.11.0` (2026-11-01). Confirmed `neosmemo/memos:26.11.0` exists on Docker Hub (`curl https://hub.docker.com/v2/repositories/neosmemo/memos/tags/26.11.0` gave 200).
4. Write the manifest (PVC 5Gi, Deployment, Service). Data dir in the image is `/var/opt/memos`, port 5230, health endpoint `/healthz`.
5. Apply: `scp memos.yaml moo@home:/tmp/ && ssh moo@home 'kubectl apply --dry-run=server -f /tmp/memos.yaml && kubectl apply -f /tmp/memos.yaml && kubectl -n homelab rollout status deploy/memos'`.
6. Verify: `curl -s -o /dev/null -w '%{http_code}\n' http://192.168.50.244:5230/healthz` gave 200.

## The gotcha: Kubernetes service links break `MEMOS_PORT`
First rollout hung at `0/1` with the probes failing (`connection refused`) and the container restarting. Pod log: `Server running on port 0`.

- Memos configures itself from `MEMOS_*` env vars, and the image sets `MEMOS_PORT=5230`.
- Kubernetes injects env vars for every Service in the namespace. A Service named `memos` produces `MEMOS_PORT=tcp://10.43.231.95:5230` (plus `MEMOS_PORT_5230_TCP_*`, `MEMOS_SERVICE_HOST`, ...), which overrides the image default. The value does not parse as a port, so Memos listens on 0 (random).
- Confirmed with `kubectl -n homelab exec deploy/memos -- env | grep ^MEMOS`.
- Fix: `enableServiceLinks: false` in the pod spec. Any app whose env prefix equals its Service name (`<NAME>_PORT`, `<NAME>_HOST`) can hit this. Alternative: name the Service something else.

## Manifest
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata: {name: memos-data, namespace: homelab}
spec:
  accessModes: [ReadWriteOnce]
  resources: {requests: {storage: 5Gi}}
  storageClassName: truenas-iscsi
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: memos, namespace: homelab, labels: {app: memos}}
spec:
  replicas: 1
  selector: {matchLabels: {app: memos}}
  strategy: {type: Recreate}
  template:
    metadata: {labels: {app: memos, spread-group: homelab-app}}
    spec:
      enableServiceLinks: false   # see gotcha above
      containers:
        - name: memos
          image: docker.io/neosmemo/memos:26.11.0
          env: [{name: TZ, value: Asia/Jakarta}]
          ports: [{containerPort: 5230, name: http}]
          livenessProbe:  {httpGet: {path: /healthz, port: http}, initialDelaySeconds: 20, periodSeconds: 30}
          readinessProbe: {httpGet: {path: /healthz, port: http}, initialDelaySeconds: 5, periodSeconds: 10}
          resources: {requests: {cpu: 25m, memory: 64Mi}, limits: {cpu: "1", memory: 512Mi}}
          volumeMounts: [{name: data, mountPath: /var/opt/memos}]
      volumes: [{name: data, persistentVolumeClaim: {claimName: memos-data}}]
---
apiVersion: v1
kind: Service
metadata:
  name: memos
  namespace: homelab
  annotations: {metallb.io/loadBalancerIPs: 192.168.50.244}
spec:
  type: LoadBalancer
  selector: {app: memos}
  ports: [{name: http, port: 5230, targetPort: http}]
```

## Telegram bot (Memogram)
Memos no longer has a built-in Telegram bot. The project's integration is **Memogram** ([usememos/telegram-integration](https://github.com/usememos/telegram-integration)), a separate service that calls the Memos REST API. Bot: `@notesamu_bot` (token checked with `getMe` from home, HTTP ok).

1. Read the repo README: config is env vars `SERVER_ADDR`, `BOT_TOKEN`, optional `ALLOWED_USERNAMES`, `DATA` (token-binding file, holds Memos access tokens, must be persisted). Supports Memos 0.31.x and 26.10.x+ (we run 26.11.0, memogram discovered it at startup).
2. No published container image (Docker Hub `neosmemo/memogram` / `usememos/memogram` return "object not found", workflows only build release artifacts). So: `gh release download 26.10.0 -R usememos/telegram-integration -p memogram_26.10.0_linux_amd64.tar.gz`, extract into its own dir, then a 4-line Containerfile (`FROM cgr.dev/chainguard/static:latest`, `ENV DATA=/data/data.txt`, `COPY memogram /app/memogram`, `USER 65532:65532`, `ENTRYPOINT`) and `podman build -t localhost/memogram:26.10.0`.
3. Import into home's containerd (same pattern as `localhost/vm-bot`, `localhost/route-manager`): `podman save localhost/memogram:26.10.0 | ssh moo@home 'sudo k3s ctr -n k8s.io images import -'` (0.6 s).
4. Token as a Secret, never in a file: `printf '%s' "$TOKEN" | ssh moo@home 'kubectl -n homelab create secret generic memogram --from-file=BOT_TOKEN=/dev/stdin --dry-run=client -o yaml | kubectl apply -f -'`.
5. Deployment `memogram` (manifest `~/sessions/2026-11-07-memos-k3s/memogram.yaml`): `imagePullPolicy: Never`, `SERVER_ADDR=http://memos:5230` (in-cluster Service), `BOT_TOKEN` from the Secret, `DATA=/data/data.txt`, 1Gi `local-path` PVC `memogram-data` with `fsGroup: 65532` (the image runs as UID 65532), `enableServiceLinks: false`, no Service (the bot only makes outbound calls).
6. Verified: log shows `Memogram started` and `instance profile version=26.11.0`.

Usage: create an account in Memos, make a Personal Access Token (Settings > Access Tokens), then send `/start <token>` to the bot. After that text, photos, files, voice and video messages become memos; `/search <words>` searches. Set `ALLOWED_USERNAMES` (Telegram usernames, no `@`, comma separated) to restrict who can use the bot; currently unset.

Maintenance notes: the image is imported only on `home`; if containerd's image store is wiped, rebuild from steps 2-3. Upgrading means a new release tag, rebuild, import, and bump the image tag in the manifest.

## Not done yet
- No `memos.lan` Caddy route / Technitium A record (see the `.lan` DNS notes: every new route needs a manual A record) and no Cloudflare tunnel hostname. Until then it is reachable only at `http://192.168.50.244:5230`.
- First visit to the UI shows the sign-up page: the first account created becomes the admin, so create it right away.
- Backup: the SQLite DB lives only on the iSCSI PVC (`memos-data`); no snapshot/backup job exists for it.

## References
- [usememos/memos releases](https://github.com/usememos/memos/releases) (latest tag 26.11.0)
- [memos `scripts/Dockerfile`](https://github.com/usememos/memos/blob/main/scripts/Dockerfile) (`ENV MEMOS_PORT="5230"`, `EXPOSE 5230`)
- [memos `scripts/entrypoint.sh`](https://github.com/usememos/memos/blob/main/scripts/entrypoint.sh) (data dir `/var/opt/memos`, drops to UID 10001)
- [usememos/telegram-integration (Memogram) README and releases](https://github.com/usememos/telegram-integration)
- [Kubernetes: environment variables / service links](https://kubernetes.io/docs/concepts/services-networking/service/#environment-variables) and the `enableServiceLinks` pod field
