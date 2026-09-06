---
type: how-to
tags: [netbird, podman, quadlet, auto-update, vpz, pangolin, technitium]
created: 2026-09-06
last_verified: 2026-09-06
status: current
---

# Updating NetBird and rolling out `podman-auto-update` across all quadlets on vpz

## NetBird client + server update

Client (apt-managed, official repo):

```bash
sudo apt-get install -y --only-upgrade netbird   # 0.78.0 -> 0.78.1
```

Server is the **combined container** (`netbirdio/netbird-server:latest`, Podman
quadlet, `Management + Signal + Relay + STUN` in one process) — no version pin, so
"updating" means pulling fresh and recreating:

```bash
sudo podman pull docker.io/netbirdio/netbird-server:latest
sudo podman pull docker.io/netbirdio/dashboard:latest
sudo systemctl restart netbird-server.service netbird-dashboard.service
```

Confirmed clean via `podman logs netbird-server` — look for
`management server version 0.78.1` in the boot log and normal STUN/Signal/Relay
listener lines, no crash loop.

Noticed (not fixed, flagging for later): the `netbird-traefik` quadlet is still
pinned to `traefik:v3.6` even though `v3.7` was already sitting locally pulled from
an earlier session — version drift, not urgent since v3.6 still works, but worth
aligning with `pangolin-traefik`'s v3.7 eventually.

## Rolling out podman-auto-update to every quadlet

Inventory on vpz (rootful Podman, `/etc/containers/systemd/*.container`): 8
containers — `technitium-dns` (only one that already had the label),
`k8s-proxy-squid`, `netbird-traefik`, `netbird-server`, `netbird-dashboard`,
`pangolin` (app), `gerbil`, `pangolin-traefik`.

Add `AutoUpdate=registry` under `[Container]` in each `.container` file:

```bash
for f in pangolin-traefik pangolin-app pangolin-gerbil k8s-proxy-squid netbird-dashboard netbird-traefik netbird-server; do
  sudo sed -i '/^\[Container\]/a AutoUpdate=registry' /etc/containers/systemd/$f.container
done
```

**The label only takes effect on the running container at (re)creation time** — just
editing the quadlet file and `daemon-reload` is not enough, the container has to be
recreated:

```bash
sudo systemctl daemon-reload
# independent services, any order:
sudo systemctl restart k8s-proxy-squid netbird-traefik netbird-server netbird-dashboard
# pangolin stack has real interdependencies (gerbil and pangolin-traefik share a
# netns) — restart in this order or pangolin-traefik ends up attached to a stale netns:
sudo systemctl restart pangolin-app
sudo systemctl restart pangolin-gerbil
sudo systemctl restart pangolin-traefik
```

Verify the label actually landed on each running container (not just in the quadlet
file):

```bash
sudo podman inspect --format '{{.Name}}: {{index .Config.Labels "io.containers.autoupdate"}}' $(sudo podman ps -q)
```

Enable the timer (systemd default: daily, randomized delay):

```bash
sudo systemctl enable --now podman-auto-update.timer
sudo podman auto-update --dry-run   # sanity check which units/images it picked up
```

The dry-run's `UPDATED` column showing `pending` rather than `true`/`false` for a
few containers turned out to just mean "hasn't checked yet" for containers freshly
recreated in the same session — running a real `sudo podman auto-update` immediately
confirmed the mechanism actually works: it found genuinely stale images for
`pangolin`, `gerbil`, and `pangolin-traefik` (all three were running older cached
images despite my earlier restart, since a plain `systemctl restart` doesn't force a
registry pull — only `podman auto-update` or an explicit `podman pull` does), pulled
fresh ones, recreated the containers, and everything came back healthy
(`pangolin` reports `healthy`, both `vpn.<PERSONAL_DOMAIN>` and
`tun.<PERSONAL_DOMAIN>` returned 200 afterward).

## Caveat: version-pinned images don't "auto-update" to newer versions

`technitium-dns` (`:15.4.0`) and both traefik containers (`:v3.6`/`:v3.7`) are
pinned to specific tags. `AutoUpdate=registry` only re-pulls if the registry
publishes a **new digest under that same tag** — it will never bump you to a newer
version tag on its own. That's a deliberate stability/hands-off tradeoff; switching
those to `:latest` would need a separate decision.
