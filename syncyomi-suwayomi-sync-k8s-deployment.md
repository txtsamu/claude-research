---
type: how-to
tags: [syncyomi, suwayomi, kubernetes, kubectl, mihon, manga, dns, tls, hostaliases]
created: 2026-08-31
last_verified: 2026-08-31
status: current
---

# SyncYomi v1.3.0 on Kubernetes, and getting Suwayomi's built-in sync working

[SyncYomi](https://github.com/syncyomi/syncyomi) is a self-hosted server
that syncs manga reading progress/library across devices for
TachiyomiSY-family reader apps (Mihon included). It's a separate concern
from Suwayomi — Suwayomi is the manga-*source* server your reader app
pulls chapters from; SyncYomi syncs *reading progress*. They don't talk to
each other by default, but Suwayomi-Server has since grown its own native
SyncYomi client, exposed right in its web UI's Sync settings — that's
what this doc is actually about wiring up.

## Deployment (`homelab` namespace, alongside the existing `suwayomi` app)

No documented env-var config; the binary only takes `--config <path>` and
reads/writes `config.toml` in that directory. Default `host = "127.0.0.1"`
in that file would make it unreachable from a k8s Service, so a
`ConfigMap` pre-seeds the file rather than letting first-run generate the
wrong default:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: syncyomi-config
  namespace: homelab
data:
  config.toml: |
    host = "0.0.0.0"
    port = 8282
    logLevel = "INFO"
    checkForUpdates = true
    sessionSecret = "<generated>"
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: syncyomi-data
  namespace: homelab
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: truenas-iscsi
  resources:
    requests:
      storage: 1Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: syncyomi
  namespace: homelab
  annotations:
    keel.sh/policy: minor
    keel.sh/trigger: poll
    keel.sh/pollSchedule: "@every 1h"
spec:
  replicas: 1
  selector: {matchLabels: {app: syncyomi}}
  strategy: {type: Recreate}
  template:
    metadata:
      labels: {app: syncyomi, spread-group: homelab-app}
    spec:
      containers:
        - name: syncyomi
          image: ghcr.io/syncyomi/syncyomi:v1.3.0
          args: ["--config", "/config"]
          ports: [{containerPort: 8282}]
          resources:
            requests: {cpu: 50m, memory: 128Mi}
            limits: {cpu: 500m, memory: 512Mi}
          volumeMounts:
            - {name: data, mountPath: /config}
            - {name: config, mountPath: /config/config.toml, subPath: config.toml}
      volumes:
        - {name: data, persistentVolumeClaim: {claimName: syncyomi-data}}
        - {name: config, configMap: {name: syncyomi-config}}
---
apiVersion: v1
kind: Service
metadata: {name: syncyomi, namespace: homelab}
spec:
  type: LoadBalancer
  selector: {app: syncyomi}
  ports: [{port: 8282, targetPort: 8282}]
```

`ConfigMap` `subPath` mount for just `config.toml`, PVC for the rest of
`/config` — lets the app's SQLite DB and sync-history files persist
normally on the PVC while `config.toml` itself stays declarative/git-able,
with no init-container needed.

The one gap in the docs worth noting for next time: the full `config.toml`
schema (all keys, defaults, comments) isn't published anywhere findable —
easiest way to get it is to run the image once against a throwaway
volume and read back what it generates:
```bash
podman run -d --name syncyomi-gen -v /tmp/syncyomi-test:/config:Z ghcr.io/syncyomi/syncyomi:v1.3.0 --config /config
sleep 6 && cat /tmp/syncyomi-test/config.toml
podman rm -f syncyomi-gen && rm -rf /tmp/syncyomi-test
```

MetalLB assigned `192.168.50.237`. DNS record (`syncyomi.lan → 192.168.50.200`,
i.e. through Caddy) added identically across all 4 Technitium nodes — see
[technitium-dns-3node-cluster-deployment.md](technitium-dns-3node-cluster-deployment.md).
Caddy route:
```caddyfile
syncyomi.lan {
	tls internal
	reverse_proxy 192.168.50.237:8282
}
```

## Wiring it into Suwayomi: two real bugs, in sequence

### Bug 1 — Suwayomi's pod can't resolve `.lan` names at all

Suwayomi's `Deployment` has a deliberate DNS override:
```yaml
dnsPolicy: None
dnsConfig:
  nameservers: ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
```
This makes the pod bypass CoreDNS (and by extension the node's own
resolver, and Technitium) entirely — it only ever queries those three
public resolvers, for everything. Presumably set up to guarantee reliable
resolution of external manga-source domains regardless of in-cluster DNS
health at the time. Whatever the original reason, it also means the pod
has zero path to resolve any internal `.lan` name — Suwayomi's "Start
sync" against `https://syncyomi.lan` failed with a generic
`java.io.IOException: syncyomi.lan` (Android's/Java's typical
name-resolution-failure wrapper).

**Fix, without touching the existing override** (didn't know its original
justification, so left it alone rather than risk regressing whatever it
was protecting against): added a `hostAliases` entry — resolved via
`/etc/hosts` inside the pod, which is consulted *before* any DNS lookup
happens, so it works regardless of `dnsPolicy`/custom nameservers:
```bash
kubectl patch deployment suwayomi -n homelab --type=json -p \
  '[{"op":"add","path":"/spec/template/spec/hostAliases","value":[{"ip":"192.168.50.200","hostnames":["syncyomi.lan"]}]}]'
```
(Deployment uses `strategy: Recreate`, so this patch triggers a full pod
recreation — brief downtime, acceptable for this app.) Verified:
```bash
kubectl exec -n homelab <suwayomi-pod> -c suwayomi -- cat /etc/hosts   # shows the alias
kubectl exec -n homelab <suwayomi-pod> -c suwayomi -- curl -sk -o /dev/null -w "%{http_code}" https://syncyomi.lan   # 200
```

### Bug 2 — TLS trust: Java doesn't trust Caddy's local CA

Once reachable, "Start sync" still failed, now with a genuinely different
error:
```
(certificate_unknown) PKIX path building failed: SunCertPathBuilderException:
unable to find valid certification path to requested target
```
`curl -k` (used to verify Bug 1's fix) ignores certificate errors
entirely; Suwayomi's actual Java/Kotlin HTTP client does real PKIX
validation and has no knowledge of Caddy's `tls internal` self-signed
local CA — different failure mode than the earlier reachability problem,
easy to conflate if you stop checking logs after the first fix "works."

**Fix**: sidestep TLS for this internal pod-to-pod call entirely, rather
than trying to get Caddy's CA into the JVM's trust store (would need a
custom trust-store volume mount, fragile against image updates). In
Suwayomi's web UI, **SyncYomi host** set to the SyncYomi Service's plain
HTTP LoadBalancer address directly:
```
http://192.168.50.237:8282
```
instead of `https://syncyomi.lan`. No cert involved, no DNS override
involved (raw IP) — works regardless of both prior issues.

## Getting the client (Mihon) side working

SyncYomi/Suwayomi's server-side sync and a reader app's own sync are
separate connections to the same SyncYomi backend, not chained through
each other:
1. In SyncYomi's own web UI (`https://syncyomi.lan` from a normal
   browser, or Suwayomi's proxy of it): Settings → API Keys → generate one.
2. In Mihon (or Suwayomi's web UI, same settings surface): Settings →
   Sync → SyncYomi — host + API key, per-device.
3. Sync then triggers either automatically (interval-based, configurable)
   or manually via "Start sync" / "Sync now" in that same screen — there
   is no server-side trigger; SyncYomi itself is a passive server that
   only responds to client-initiated `PUT`/`GET` calls, never pushes or
   schedules anything on its own.
