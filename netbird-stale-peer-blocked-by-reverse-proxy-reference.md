---
type: troubleshooting
tags: [netbird, self-hosted, reverse-proxy, peer-management, vpz, home, warp-vm]
created: 2026-09-10
last_verified: 2026-09-10
status: current
---

# NetBird: stale peer can't be deleted — "in use by proxy"

## Symptom

After decommissioning `warp-vm` (see [[warp-vm-nixos-migration-plan]]), its NetBird peer (`warp.netbird.selfhosted`) was left stuck permanently "Connecting" in the dashboard and detailed status output — expected, since the box is off and will never answer again. Deleting it from the self-hosted NetBird dashboard failed:

```
Code 412: Peer daeg57p852oc73evkhgg is in use by proxy daei529852oc73aq8v3g
Request ID: daguhup852oc73ar9ha0
```

## Root cause

This self-hosted NetBird deployment has the **Reverse Proxy Service** feature enabled (see [[netbird-reverse-proxy-k3s-forward-filter-drop]] for the original setup) — a NetBird object type that lets a peer act as a reverse-proxy entry point for other resources. `warp-vm`'s peer object was still referenced by a stale/disconnected proxy object from before the migration, and NetBird's management API enforces referential integrity: a peer can't be deleted while something still points at it, even if that something is itself dead.

## Fix

The self-hosted `netbird-server` image ships an `admin` CLI with limited peer/proxy management helpers (run inside its container, on the box hosting the NetBird management stack — `vpz` in this setup):

```bash
sudo podman exec netbird-server /go/bin/netbird-server admin --help
# admin proxy --help
#   disconnect-all   Force-mark all reverse proxy instances as disconnected
```

There's no scoped "delete/disconnect just this one proxy" command — only a blunt `disconnect-all`, which affects *every* reverse proxy instance on the account, not just the stale one. It requires an interactive typed confirmation, which needs piping in non-interactively over SSH:

```bash
echo "disconnect all proxies" | sudo podman exec -i netbird-server \
  /go/bin/netbird-server admin proxy disconnect-all --config /etc/netbird/config.yaml
```

Real gotchas hit along the way:
- The container name assumption mattered: `docker exec netbird-server` failed with "no such container" even though `docker ps`-style output had been seen for it earlier — the deployment actually runs under **Podman**, not Docker, despite the container being named identically; `sudo podman exec` worked.
- The config path isn't `/etc/netbird/management.json` (a reasonable first guess) — it's `/etc/netbird/config.yaml`, found via `find / -iname '*.json' -o -iname '*.yaml'` inside the container.
- Only *currently connected* proxy instances get affected — `disconnect-all` reported "Force-marked 1 of 1 reverse proxy instance(s) as disconnected," which was the one live, working proxy (a `nextcloud` route), not necessarily the same stale reference blocking the peer deletion. It resolved the block anyway — confirmed by successfully deleting the stale `warp` peer from the dashboard immediately after.

## Blast radius / what to watch for

`disconnect-all` is genuinely blunt — it affects *every* reverse proxy instance on the account, including ones actively in production use. In this case only one other proxy existed (the already-verified `nextcloud` route), and it was expected to self-reconnect on its own next heartbeat without intervention, which it did. On a deployment with several active reverse-proxy routes, expect all of them to need a moment to reconnect after running this — not something to run casually if there are many in active use, and per the tool's own warning, best done "during a maintenance window."

## References

None — diagnosed and fixed via the `netbird-server` container's own bundled `admin` CLI (`--help` output), not external web research.
