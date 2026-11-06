---
type: how-to
tags: [memos, k3s, kubernetes, home, metallb, truenas-iscsi, sqlite, service-links]
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

## Not done yet
- No `memos.lan` Caddy route / Technitium A record (see the `.lan` DNS notes: every new route needs a manual A record) and no Cloudflare tunnel hostname. Until then it is reachable only at `http://192.168.50.244:5230`.
- First visit to the UI shows the sign-up page: the first account created becomes the admin, so create it right away.
- Backup: the SQLite DB lives only on the iSCSI PVC (`memos-data`); no snapshot/backup job exists for it.

## References
- [usememos/memos releases](https://github.com/usememos/memos/releases) (latest tag 26.11.0)
- [memos `scripts/Dockerfile`](https://github.com/usememos/memos/blob/main/scripts/Dockerfile) (`ENV MEMOS_PORT="5230"`, `EXPOSE 5230`)
- [memos `scripts/entrypoint.sh`](https://github.com/usememos/memos/blob/main/scripts/entrypoint.sh) (data dir `/var/opt/memos`, drops to UID 10001)
- [Kubernetes: environment variables / service links](https://kubernetes.io/docs/concepts/services-networking/service/#environment-variables) and the `enableServiceLinks` pod field
