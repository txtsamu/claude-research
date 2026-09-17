---
type: how-to
tags: [rancher, fleet, rancher-turtles, capi, k3s, kubernetes, cleanup, home, caddy, technitium]
created: 2026-09-17
last_verified: 2026-09-17
status: current
---

# Fully decommissioning Rancher from `home`'s k3s cluster

## Why

Replaced Rancher's dashboard with kubewall (see
[[kubewall-lighter-rancher-dashboard-deploy]]) and no longer wanted Rancher
running at all — not just the dashboard, but Fleet, CAPI/rancher-turtles,
and every namespace/CRD/webhook it created, fully removed and verified, not
just `helm uninstall`'d and left with orphaned state.

## Why not just `helm uninstall`

Rancher creates a large number of CRDs, CRD instances, and namespaces that
a Helm release delete does **not** clean up — confirmed via the official
docs (*"Simply deleting the Helm release... is not sufficient... Rancher
creates a whole bunch of Custom Resource Definitions (CRDs)... which DO NOT
get removed when deleting the Rancher Helm release"*). The recommended path
is Rancher's own `rancher-cleanup` tool, run as a one-shot Kubernetes Job
with `cluster-admin`.

## Preflight checks (before running anything destructive)

The cleanup script also deletes cluster-wide CRDs for `monitoring.coreos.com`
(Prometheus Operator's ServiceMonitor/PodMonitor etc.), `gatekeeper.sh`
(OPA), and `istio.io` if present — none of those are Rancher's own, they're
shared CRD groups other tools use too. Checked none of that would collide
with this cluster's actual monitoring stack (VictoriaMetrics) before running
anything:

```bash
kubectl get crd | grep -iE "monitoring.coreos.com|gatekeeper.sh|istio.io|cluster.x-k8s.io|cattle.io"
kubectl get servicemonitors.monitoring.coreos.com,podmonitors.monitoring.coreos.com -A
kubectl get ns local && kubectl get all -n local
```

Results: no `monitoring.coreos.com`/`gatekeeper.sh`/`istio.io` CRDs existed
at all (this cluster's VictoriaMetrics isn't deployed via Prometheus
Operator, so nothing here uses those CRD groups) — the script's deletion of
them would be a no-op. `cluster.x-k8s.io` CRDs did exist (from
rancher-turtles/CAPI) but with zero real instances (`kubectl get
clusters.cluster.x-k8s.io` → "No resources found" — confirmed separately
while researching whether rancher-turtles itself was safe to remove, before
deciding to remove all of Rancher instead). Namespace `local` — Rancher's
own bookkeeping namespace for its "local" cluster — was completely empty.
Clear to proceed.

## Procedure

### 1. Deploy the official cleanup job

```bash
curl -s "https://raw.githubusercontent.com/rancher/rancher-cleanup/main/deploy/rancher-cleanup.yaml" -o /tmp/rancher-cleanup.yaml
kubectl create -f /tmp/rancher-cleanup.yaml
```

This creates a `ServiceAccount` + `cluster-admin` `ClusterRoleBinding` +
a `Job` (`cleanup-job`, namespace `kube-system`) running
`rancher/rancher-cleanup:latest` with `args: ["force"]` (skips the
interactive `y/n` prompt, which has no stdin to answer inside a Job anyway).

Watch it:
```bash
kubectl -n kube-system logs -l job-name=cleanup-job -f
```
Took **14 minutes** end to end on this cluster. Reading the script itself
first (`cleanup.sh` from the same repo) before running it showed exactly
what it does, in order: kill Rancher's own controllers first (so nothing
recreates resources mid-cleanup) → delete every `cattle.io`/`rancher-
monitoring`/`gatekeeper`/`istio`/`capi`-matching admission webhook
(critical — a leftover webhook here is what causes the classic "cluster
returns webhook errors on every kubectl request" failure mode) → delete
ClusterRoles/ClusterRoleBindings by label/name-prefix → bulk-delete a fixed
list of "data" CRDs → delete APIServices → walk every namespaced/
cluster-scoped `cattle.io` resource individually, clearing finalizers first
(`kubectl patch -p '{"metadata":{"finalizers":null}}' --type=merge`) before
deleting it, which is exactly the step a manual cleanup usually forgets and
ends up with namespaces stuck `Terminating` forever → finally delete the
Rancher/Fleet/CAPI/Turtles namespaces themselves (`local cattle-system
cattle-impersonation-system cattle-global-data cattle-global-nt
cattle-provisioning-capi-system cattle-turtles-system cattle-capi-system`
plus the Fleet namespaces `cattle-fleet-clusters-system
cattle-fleet-local-system cattle-fleet-system fleet-default fleet-local
fleet-system`) → delete the remaining CRDs by group.

### 2. Verify

```bash
curl -s "https://raw.githubusercontent.com/rancher/rancher-cleanup/main/deploy/verify.yaml" -o /tmp/verify.yaml
# (ServiceAccount/ClusterRoleBinding already exist from step 1 — extract just the Job)
python3 -c "
import yaml
docs = list(yaml.safe_load_all(open('/tmp/verify.yaml')))
job = [d for d in docs if d and d.get('kind')=='Job'][0]
yaml.dump(job, open('/tmp/verify-job-only.yaml','w'))
"
kubectl create -f /tmp/verify-job-only.yaml
kubectl -n kube-system logs -l job-name=verify-job
```
Per the tool's own README, output should be empty besides deprecation
warnings. Got: 8 harmless `the server doesn't have a resource type
"podsecuritypolicy"` errors (PSP API doesn't exist on k8s 1.25+, this
cluster runs k3s 1.35.7 — `verify.sh` still probes for it unconditionally),
one `v1 Endpoints is deprecated` warning, and one bare line
`etcdsnapshotfiles.k3s.cattle.io` — traced that last one to `verify.sh`'s
own last two lines, which build an unfiltered comma-joined list of
`api-resources` type *names* matching `cattle.io` (unlike every other check
in the script, these two specifically don't `grep -v k3s.cattle.io`) — it's
k3s's own required CRD name being echoed as a string, not a `kubectl get`
result showing an actual leftover object. Confirmed clean.

### 3. Gotchas the tool itself didn't catch

**Two Rancher namespaces newer than the script's hardcoded list.** After
verify came back clean, `kubectl get ns` still showed
`cattle-local-user-passwords` and `cattle-ui-plugin-system` — both
Rancher-created, neither in the script's `CATTLE_NAMESPACES`/
`TOOLS_NAMESPACES`/`FLEET_NAMESPACES` lists (the community script predates
whatever Rancher version introduced these). Checked they were already empty
(just the auto-injected `kube-root-ca.crt` configmap every namespace gets)
and deleted directly:
```bash
kubectl get all,secrets,configmaps -n cattle-local-user-passwords
kubectl get all,secrets,configmaps -n cattle-ui-plugin-system
kubectl delete ns cattle-local-user-passwords cattle-ui-plugin-system --timeout=30s
```
**Lesson**: always run `kubectl get ns | grep -i cattle` (or `rancher`)
manually after the script finishes, regardless of Rancher version — don't
trust the hardcoded namespace list to be exhaustive for a newer release.

**One orphaned `Terminating` pod.** `kubectl get pods -A` showed a
`fleet-controller-*` pod stuck `Terminating` in `cattle-fleet-system` a full
12 minutes after the job finished — but `kubectl get ns
cattle-fleet-system` already returned `NotFound`. The namespace was fully
gone; this was just a leftover kubelet-side pod object from the bulk
deletion racing with container termination (one of its 3 containers,
`fleet-agentmanagement`, was crash-looping/back-off right as the delete
hit). Force-cleared it:
```bash
kubectl delete pod -n cattle-fleet-system fleet-controller-<hash> --grace-period=0 --force
```

### 4. Remove the Caddy route and DNS record

Reversed the exact setup from [[kubewall-lighter-rancher-dashboard-deploy]]:
pulled Caddy's live config (`curl localhost:2019/config/`), removed the
`rancher.lan` entry from `apps.http.servers.srv0.routes[]` and its matching
`logger_names`/`logging.logs` entry, pushed it back
(`POST localhost:2019/load`), then deleted the DNS record using the
dedicated Technitium API token:
```bash
curl -s "http://127.0.0.1:5380/api/zones/records/delete?token=<dedicated-token>&domain=rancher.lan&zone=lan&type=A&ipAddress=192.168.50.200"
```
Verified `rancher.lan` now fails to connect while `kwall.lan`/`perses.lan`
still return 200.

### 5. Prune the now-actually-unused container images

**Pitfall hit twice in the same session**: comparing `crictl images`
against `kubectl get pods -o jsonpath=...image` by exact string match gives
false positives, because pod specs use Docker Hub's short form
(`mariadb:11`, `rancher/turtles:v0.27.1`) while `crictl` reports the fully
canonical form (`docker.io/library/mariadb:11`,
`docker.io/rancher/turtles:v0.27.1`) — same image, different string. A
naive diff flags dozens of genuinely-in-use images (couchdb, nextcloud,
redis, rancher/turtles itself while it was still running) as "unused." Fix:
canonicalize before comparing — no `/` → prepend `docker.io/library/`;
exactly one `/` and the first segment isn't already `docker.io` and has no
dot in it → prepend `docker.io/`; already `docker.io/<name>` with no further
`/` → also add the `docker.io/library/<name>` form. Only trust the
diff *after* that normalization:
```python
def canonical_forms(ref):
    forms = {ref}
    if '/' not in ref:
        forms.add('docker.io/library/' + ref)
    else:
        head, rest = ref.split('/', 1)
        if head == 'docker.io' and '/' not in rest:
            forms.add('docker.io/library/' + rest)
        elif '.' not in head and ':' not in head and head != 'docker.io':
            forms.add('docker.io/' + ref)
    return forms
```
After Rancher's pods were actually gone (not before — that's the point of
re-checking post-decommission rather than trusting the earlier live-cluster
image audit), the corrected diff showed exactly 11 images, all
`docker.io/rancher/*` (rancher, rancher-agent, rancher-cleanup, fleet,
fleet-agent, cluster-api-controller, turtles, rancher-webhook,
system-upgrade-controller, and two `mirrored-*` base images), 1.85GB total —
removed with:
```bash
kubectl get pods -A -o jsonpath='{range .items[*]}{range .spec.initContainers[*]}{.image}{"\n"}{end}{range .spec.containers[*]}{.image}{"\n"}{end}{end}' | sort -u > /tmp/used.txt
# (build canonical-forms set from /tmp/used.txt, diff against `crictl images -o json`, then:)
crictl rmi <image-id>   # once per unused id; retry any that don't report "Deleted:" the first time
```
`docker.io/rancher/local-path-provisioner`, `mirrored-coredns-coredns`, and
`mirrored-metrics-server` remain — those are Rancher-org-published mirrors
of core k3s dependencies (default storage provisioner, CoreDNS, metrics-
server), unrelated to the Rancher *app* itself, correctly left alone.

## Results

| | Before | After |
|---|---|---|
| Namespaces | 27 | 9 |
| Pods | 41 | 30 |
| Node CPU limit overcommit | 238% | 213% |
| Node memory limit overcommit | 110% | 90% |
| Root disk used | 64G (69%) | 55G (60%) |

`homelab` namespace apps (immich, nextcloud, forgejo, perses,
victoria-metrics, etc.) were unaffected throughout — none of them are in any
Rancher/Fleet/CAPI namespace, and the preflight check confirmed none of
them depend on a CRD group the cleanup script touches.

## References

- [rancher/rancher-cleanup](https://github.com/rancher/rancher-cleanup) — the tool used: [README](https://raw.githubusercontent.com/rancher/rancher-cleanup/main/README.md), [cleanup.sh](https://raw.githubusercontent.com/rancher/rancher-cleanup/main/cleanup.sh), [verify.sh](https://raw.githubusercontent.com/rancher/rancher-cleanup/main/verify.sh), [deploy manifests](https://github.com/rancher/rancher-cleanup/tree/master/deploy)
- [Rancher is No Longer Needed (SUSE Rancher Manager FAQ)](https://ranchermanager.docs.rancher.com/faq/rancher-is-no-longer-needed) — official confirmation that `rancher-cleanup` is the recommended removal path, not a manual Helm uninstall
- [How to remove Rancher from a Kubernetes cluster (Verifa)](https://verifa.io/blog/remove-rancher-from-kubernetes-cluster/index.html) — independent walkthrough corroborating the same procedure
- [rancherlabs/support-tools](https://github.com/rancherlabs/support-tools) — broader Rancher support-tools collection `rancher-cleanup` is now split out from
