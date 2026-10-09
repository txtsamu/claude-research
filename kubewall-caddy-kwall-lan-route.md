---
type: troubleshooting
tags: [kubewall, caddy, nixos, home, k3s, tls, dns, kwall-lan]
created: 2026-10-09
last_verified: 2026-10-09
status: current
---

# kwall.lan unreachable: kubewall had DNS but no Caddy route

## Symptom

`kwall.lan` resolved but wasn't usable:

```
$ getent hosts kwall.lan
192.168.50.200  kwall.lan
$ curl -sI http://kwall.lan
HTTP/1.1 308 Permanent Redirect
Location: https://kwall.lan/
Server: Caddy
$ curl -skv https://kwall.lan
* TLSv1.3 (IN), TLS alert, internal error (592)
* TLS connect error: error:0A000438:SSL routines::tlsv1 alert internal error
```

DNS pointed at home (192.168.50.200) and Caddy answered on :80 with its automatic HTTP->HTTPS redirect, but the TLS handshake failed.

## Diagnosis

A `tlsv1 alert internal error` from Caddy means it has no site block (so no certificate) for that name. Confirmed by reading the live config on home:

```bash
ssh moo@home 'sudo ls /etc/caddy'              # only: caddy_config
ssh moo@home 'sudo cat /etc/caddy/caddy_config'  # no kwall.lan block
```

So the DNS record existed but the Caddy route didn't. This is the "every new `.lan` route needs both a Caddy route and a DNS record" rule.

Dead ends / things that cost time:

- `/etc/caddy/Caddyfile` does not exist on home; the NixOS module renders the config to `/etc/caddy/caddy_config`.
- `kubectl` is not installed on home or on fedora. Use `sudo k3s kubectl` on home. home runs k3s itself (it has the `10.42.0.x` pod network), and that is where kubewall lives.
- SSH to `warp.ssamu.id` was refused with "REMOTE HOST IDENTIFICATION HAS CHANGED". Not needed here, since the cluster is on home; left alone rather than bypassed.

## Finding the backend

```bash
ssh moo@home 'sudo k3s kubectl get deploy,svc,pods -A -o wide | grep -i kubewall'
# kubewall-system  deployment.apps/kubewall  1/1  ...  ghcr.io/kubewall/kubewall:0.0.23
# kubewall-system  service/kubewall  ClusterIP  10.43.240.25  8443/TCP
# kubewall-system  pod/kubewall-...  1/1 Running  (on home)
```

Is 8443 plain HTTP or TLS? Probe from home (kube-proxy rules apply node-wide, so the host can reach ClusterIPs, same as the existing `perses.lan` route):

```bash
ssh moo@home 'curl -s  -o /dev/null -w "http %{http_code}\n"  http://10.43.240.25:8443/   # 400
               curl -sk -o /dev/null -w "https %{http_code}\n" https://10.43.240.25:8443/'  # 200
```

It serves TLS itself, so it belongs in `tlsUpstreams` (Host passthrough, cert check skipped), not `httpUpstreams`.

## Fix

home's config is built straight from `github:txtsamu/home-nixos` (no checkout on the host), so the change goes through a PR. Caddy sites are generated from two maps in `hosts/home/proxy.nix`.

```bash
gh repo clone txtsamu/home-nixos && cd home-nixos
git checkout -b caddy-kwall-lan
# add to tlsUpstreams in hosts/home/proxy.nix:
#   "kwall.lan" = "https://10.43.240.25:8443";
git commit -am "proxy: add kwall.lan route to kubewall"
git push -u origin caddy-kwall-lan
gh pr create ...        # PR #6
gh pr checks 6 -R txtsamu/home-nixos   # wait for CI (nix flake check) to pass
gh pr merge 6 -R txtsamu/home-nixos --squash --delete-branch
ssh moo@home 'sudo nixos-rebuild switch --flake github:txtsamu/home-nixos#home --refresh'
```

The rebuild output ended with `reloading the following units: caddy.service`, i.e. Caddy was reloaded in place.

Before changing home's config, check for open PRs first (`gh pr list -R txtsamu/home-nixos`); only the flake.lock bot PR #5 was open.

## Verification

```bash
curl -sk -o /dev/null -w 'https %{http_code}\n' https://kwall.lan/   # https 200
```

The certificate comes from Caddy's internal CA (`local_certs` / `tls internal`), like the other `.lan` sites.

## Caveats

- The ClusterIP `10.43.240.25` is stable for the life of the Service but changes if the Service is deleted and recreated. If `kwall.lan` starts returning 502 after a kubewall redeploy, re-check it with the `get svc` command above and update `proxy.nix`.
- `nix` is not installed on fedora, so `nix fmt` was not run locally; CI's nixfmt check passed.

## Related

- [kubewall-lighter-rancher-dashboard-deploy.md](kubewall-lighter-rancher-dashboard-deploy.md) — original kubewall deployment
- [home-nixos-merge-and-deploy-prs-2-and-4.md](home-nixos-merge-and-deploy-prs-2-and-4.md) — the PR/deploy flow used here
- PR: https://github.com/txtsamu/home-nixos/pull/6
