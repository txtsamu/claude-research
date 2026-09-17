---
type: how-to
tags: [kubewall, kubernetes, k3s, dashboard, helm, caddy, technitium, dns, home, rancher-alternative]
created: 2026-09-17
last_verified: 2026-09-17
status: current
---

# Deploying kubewall as a lighter k8s dashboard than Rancher, at `kwall.lan`

## Goal

`home`'s k3s cluster was carrying full Rancher (core + Fleet + CAPI/rancher-turtles)
just to get a dashboard for a single-node homelab cluster — see
[[home-k8s-resource-rightsizing-victoriametrics]] for the resource context that
prompted looking at alternatives. Wanted something reachable the same way
(`*.lan` behind Caddy, from any device on the LAN) but much lighter. Rancher
itself was decommissioned right after — see
[[rancher-full-decommission-k3s-home]].

## Alternatives considered

- **Official `kubernetes/dashboard`** — archived/retired January 2026;
  Kubernetes SIG UI now officially recommends Headlamp as the successor. Not
  a viable pick going forward.
- **Headlamp** (CNCF, official successor) — single in-cluster pod, RBAC-aware,
  plugin-extensible, also ships as a desktop app/browser extension. Solid
  choice, but its default UI didn't land well aesthetically for this use.
- **Lens/OpenLens, k9s, Aptakube, K8Studio** — desktop/terminal tools with
  zero cluster-side footprint (connect via kubeconfig from a workstation).
  Aptakube in particular was praised in a 2026 comparison roundup for native
  (non-Electron) polish and multi-cluster tabs. Ruled out for this specific
  need only because none of them give a shared web URL reachable from any
  device on the LAN the way `rancher.lan`/`kwall.lan` do — that requires an
  in-cluster web deployment.
- **kubewall** — chosen. See below.

## Why kubewall

- **54MB image**, single static Go binary (`ghcr.io/kubewall/kubewall`),
  Apache-2.0, actively maintained (1938 GitHub stars, image pushed within
  days of this write-up).
- Deployable in-cluster via an official OCI Helm chart, same access pattern
  as Rancher was (Caddy-fronted `*.lan` hostname) — or as a local
  desktop/Docker tool with zero cluster footprint, if ever wanted that way
  instead.
- Built-in AI-powered troubleshooting with pluggable providers, including
  Ollama/LMStudio — can point at a local model instead of needing a cloud
  API key, fitting this homelab's existing local-LLM setup.
- Resource ask is modest: chart defaults to 250m/256Mi requests, 500m/512Mi
  limits, 20Mi PVC for its own data — versus Rancher's combined ~1.6GB of
  images and full cattle-system/Fleet overhead for the same "look at my
  cluster" job.

## Deploy

Helm (nix-packaged, since NixOS has no dynamically-linked binaries by
default) against the k3s kubeconfig:

```bash
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
helm install kubewall oci://ghcr.io/kubewall/charts/kubewall \
  -n kubewall-system --create-namespace \
  --set pvc.storageClass=local-path
```

`--set pvc.storageClass=local-path` because this cluster has **two**
StorageClasses both marked `(default)` (`local-path` and `truenas-iscsi`) —
ambiguous default, so pin it explicitly rather than relying on which one
wins.

The chart serves **HTTPS with a self-signed cert on :8443** (README: *"With
helm kubewall runs on port 8443 with self-signed certificates"*), same as
Rancher did — so the Caddy route needs `insecure_skip_verify`, not a plain
HTTP proxy.

Get the Service ClusterIP once it's up:
```bash
kubectl get svc -n kubewall-system kubewall -o jsonpath='{.spec.clusterIP}'
```

## Wire up `kwall.lan`

Caddy on `home` runs natively (not in-cluster) but reaches k3s Service
ClusterIPs directly, because kube-proxy's iptables rules apply on the same
host — no NodePort/Ingress needed. Its live config is JSON, readable and
writable through its own admin API on `:2019`, with zero downtime for every
other route on a reload.

### 1. Get the Service ClusterIP

```bash
kubectl get svc -n kubewall-system kubewall -o jsonpath='{.spec.clusterIP}'
# -> 10.43.240.25
```

### 2. Pull the live Caddy config and add a route + logger for it

```bash
curl -s localhost:2019/config/ > /tmp/caddy_config_full.json
```

Edited it with a small Python script rather than hand-editing JSON (the
config is one big blob — `apps.http.servers.srv0.routes[]` for routes,
`srv0.logs.logger_names` + top-level `logging.logs` for per-host access
logs):

```python
import json
d = json.load(open('/tmp/caddy_config_full.json'))
srv0 = d['apps']['http']['servers']['srv0']

new_route = {
  'handle': [{
    'handler': 'subroute',
    'routes': [{
      'handle': [{
        'handler': 'reverse_proxy',
        'headers': {'request': {'set': {'Host': ['{http.request.host}']}}},
        'transport': {'protocol': 'http', 'tls': {'insecure_skip_verify': True}},
        'upstreams': [{'dial': '10.43.240.25:8443'}]
      }]
    }]
  }],
  'match': [{'host': ['kwall.lan']}],
  'terminal': True
}
srv0['routes'].append(new_route)

srv0['logs']['logger_names']['kwall.lan'] = ['log17']   # next unused logN
d['logging']['logs']['log17'] = {
  'include': ['http.log.access.log17'],
  'writer': {'filename': '/var/log/caddy/access-kwall.lan.log', 'output': 'file'}
}
json.dump(d, open('/tmp/caddy_config_new.json', 'w'))
```

`transport.tls.insecure_skip_verify` is needed because kubewall serves
self-signed HTTPS on :8443 (see above) — for a plain-HTTP backend like
`perses.lan` (:8080), that whole `transport` key is omitted.

### 3. Push it live and verify

```bash
curl -X POST "localhost:2019/load" -H "Content-Type: application/json" \
  --data-binary @/tmp/caddy_config_new.json
# -> HTTP 200, no restart, no downtime for other routes

curl -sk --resolve kwall.lan:443:127.0.0.1 https://kwall.lan/ -o /dev/null -w "%{http_code}\n"
# -> 200
curl -sk --resolve perses.lan:443:127.0.0.1 https://perses.lan/ -o /dev/null -w "%{http_code}\n"
# -> 200  (sanity check: an unrelated existing route still works)
```

### 4. Add the DNS record

Technitium's admin REST API is on `:5380`. Logged in once with the admin
password to mint a **dedicated, named, non-expiring API token** instead of
reusing the raw password for every future call (so it's independently
revocable later without touching the actual login password):

```bash
TOKEN=$(curl -s "http://127.0.0.1:5380/api/user/login?user=admin&pass=<admin-password>&includeInfo=false" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['token'])")

curl -s "http://127.0.0.1:5380/api/user/createToken?token=$TOKEN&user=admin&tokenName=claude-code-dns-mgmt"
# -> {"token": "<dedicated-token>", ...}
```

Then, using that dedicated token for the actual record (and for every DNS
change from then on):

```bash
curl -s "http://127.0.0.1:5380/api/zones/records/add?token=<dedicated-token>&domain=kwall.lan&zone=lan&type=A&ipAddress=192.168.50.200&ttl=3600"
```

Record is always `<name>.lan -> home's own IP` (`192.168.50.200`), not the
backend's ClusterIP — Caddy is what terminates the hostname and proxies
onward, so DNS only ever needs to find Caddy.

### 5. Final verification

```bash
dig +short kwall.lan @192.168.50.200        # -> 192.168.50.200
curl -sk https://kwall.lan/ -o /dev/null -w "%{http_code}\n"   # -> 200, from any LAN device
```

The dedicated Technitium token (and this same recipe, generalized) is also
saved to agent memory for reuse on the next `*.lan` service — see
`caddy-dns-lan-domain-pattern` / `technitium-dns-api-token` if using an
agent with access to that memory store — but the steps above are complete
and standalone on their own.

## References

- [kubewall/kubewall](https://github.com/kubewall/kubewall) — repo, README (Helm/Docker/Homebrew/Snap install paths, port 8443 self-signed TLS note)
- [kubewall Helm chart values.yaml](https://raw.githubusercontent.com/kubewall/kubewall/main/charts/kubewall/values.yaml) and [service.yaml](https://raw.githubusercontent.com/kubewall/kubewall/main/charts/kubewall/templates/service.yaml) — default resources, PVC, TLS/ingress config
- [From Kubernetes Dashboard to Headlamp: Understanding the Transition](https://kubernetes.io/blog/2026/06/01/dashboard-to-headlamp/) — official confirmation kubernetes-dashboard is archived, Headlamp is the SIG UI successor
- [The Best Kubernetes Dashboards in 2026 (radarhq.io)](https://radarhq.io/blog/best-kubernetes-dashboards-2026) — comparison roundup, source of the Aptakube "native app, excellent multi-cluster tabs" assessment
- [Kubernetes Dashboard Alternatives in 2026 (DEV Community)](https://dev.to/alexandrev/kubernetes-dashboard-alternatives-in-2026-best-web-ui-options-after-official-retirement-4e02) and [Kubernetes Dashboard Is Archived: 9 Alternatives (2026)](https://alexandre-vazquez.com/kubernetes-dashboard-alternatives-2026/) — broader alternatives survey (Skooner, Kubevious, K8Studio, etc.)
