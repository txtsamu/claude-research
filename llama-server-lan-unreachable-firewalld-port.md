---
type: troubleshooting
tags: [llama-server, openwebui, firewalld, fedora, networking, k3s]
created: 2026-09-18
last_verified: 2026-09-21
status: current
---

# OpenWebUI couldn't reach a llama-server instance that worked fine locally

Follow-up to [bonsai-27b-prismml-ternary-gguf-deploy.md](bonsai-27b-prismml-ternary-gguf-deploy.md). After starting `llama-server` bound to `0.0.0.0:8083` on `fedora` (192.168.50.20), OpenWebUI (running in `home`'s k3s cluster, 192.168.50.200) didn't show the new model even after refreshing.

## Symptom

`curl http://127.0.0.1:8083/v1/models` from `fedora` itself worked fine. OpenWebUI's own pod logs (`kubectl logs -n homelab openwebui-<pod> --tail=80`) showed the real problem:

```
ERROR | open_webui.routers.openai:send_get_request:117 - Connection error: Cannot connect to host 192.168.50.20:8083 ssl:default [Connect call failed ('192.168.50.20', 8083)]
```

A connection to that exact URL/port already existed in OpenWebUI's config (`GET /openai/config` showed `192.168.50.20:8083` at index 2, `connection_type: local, auth_type: none` — leftover from earlier work on this same port) — the connection didn't need to be *added*, it just couldn't be *reached*.

## Root cause

`fedora`'s `firewalld` only had specific ports open to the LAN:

```
$ sudo firewall-cmd --list-ports
3389/tcp 6556/tcp 6742/tcp 8000/tcp 8081/tcp 8811/tcp 8812/tcp
```

`8083/tcp` was not among them. `localhost` traffic bypasses firewalld entirely (loopback isn't filtered), which is why the connection worked from `fedora` itself but nowhere else — a classic "works on my machine, not from the network" trap when testing only via `curl 127.0.0.1`.

## Fix

```bash
sudo firewall-cmd --add-port=8083/tcp --permanent
sudo firewall-cmd --reload
```

## Verification

From `home` (the actual host running the OpenWebUI pod, not just `fedora`):

```
$ ssh home "curl -s -m 5 -o /dev/null -w 'HTTP %{http_code}\n' http://192.168.50.20:8083/health"
HTTP 200
```

Model then appeared in OpenWebUI's model dropdown without any config change on the OpenWebUI side.

## Key lesson

When a locally-served API "isn't showing up" in a client running on a different host, check the *serving* host's firewall before touching the *client's* config — `curl 127.0.0.1` proving connectivity proves nothing about reachability from elsewhere. Worth checking `firewall-cmd --list-ports` any time a new llama-server/service is stood up on a new port on this host; the open-port list is a manually maintained allowlist, not automatic.
