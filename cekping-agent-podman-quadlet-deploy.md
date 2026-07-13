---
type: how-to
tags: [podman, quadlet, systemd, deployment]
created: 2026-07-11
last_verified: 2026-07-11
status: current
---

# Deploying Cekping Agent with a Podman Quadlet

**Date:** 2026-07-11
**Host:** homelab (podman, systemd, rootful quadlets in `/etc/containers/systemd/`)
**Goal:** Convert a one-off `podman run -d ...` command into a systemd-managed quadlet service.

---

## 1. Starting point

The deployment was requested as a plain `podman run` command:

```bash
podman run -d \
  --name cekping-agent \
  --network host \
  --pull always \
  --cap-add=NET_RAW \
  --env CEKPING_SERVER=cekping.id:50051 \
  --env CEKPING_TOKEN="<TOKEN>" \
  --env CEKPING_SECURE=true \
  ghcr.io/awandataindonesia/cekping-agent:latest
```

Turning this into a quadlet gets you systemd-managed restarts, journald logging, and automatic start-on-boot without a Docker Compose-style wrapper.

---

## 2. Mapping `podman run` flags to quadlet keys

| `podman run` flag | Quadlet key |
|---|---|
| `--name` | `ContainerName=` |
| `--network host` | `Network=host` |
| `--pull always` | `AutoUpdate=registry` (podman auto-update, checks registry digest on `podman auto-update` runs) |
| `--cap-add=NET_RAW` | `AddCapability=NET_RAW` |
| `--env KEY=VAL` | `Environment=KEY=VAL` (one per line, or space-separated on one line) |
| (image) | `Image=` |

Note `AutoUpdate=registry` isn't a literal 1:1 substitute for `--pull always` — `--pull always` re-checks on every container start, while `AutoUpdate=registry` is checked whenever `podman auto-update` runs (typically a systemd timer). For a long-running daemon service this is the more idiomatic quadlet equivalent.

---

## 3. The container file

`/etc/containers/systemd/cekping-agent.container`:

```ini
[Unit]
Description=Cekping Agent
After=network-online.target

[Container]
AutoUpdate=registry
Image=ghcr.io/awandataindonesia/cekping-agent:latest
ContainerName=cekping-agent
Network=host
AddCapability=NET_RAW
Environment=CEKPING_SERVER=cekping.id:50051
Environment=CEKPING_TOKEN=<CEKPING_TOKEN>
Environment=CEKPING_SECURE=true

[Service]
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Replace `<CEKPING_TOKEN>` with the real token. Since it's a secret, consider keeping it out of a world-readable quadlet file — see section 6.

---

## 4. Starting the service

```bash
systemctl daemon-reload
systemctl start cekping-agent.service
systemctl status cekping-agent.service --no-pager
```

**Gotcha:** don't run `systemctl enable` on a quadlet-generated unit — it fails with:

```
Failed to enable unit: Unit /run/systemd/generator/cekping-agent.service is transient or generated.
```

This is expected. Quadlet units are generated fresh from the `.container` file on every `daemon-reload`, so `WantedBy=multi-user.target` in the `[Install]` section already handles start-on-boot — there's nothing to separately "enable." Just `daemon-reload` + `start`.

---

## 5. Verifying

```bash
systemctl status cekping-agent.service --no-pager -l
journalctl -eu cekping-agent.service -f
```

Confirm the app logs show it connecting to the configured server (in this case `cekping.id:50051`).

---

## 6. Handling the secret token

Putting a real token in `/etc/containers/systemd/*.container` is fine for local homelab use (root-only readable, not committed anywhere), but if you want to avoid it living in that file at all, options are:

- `Environment=CEKPING_TOKEN=%d/... ` isn't applicable here (no systemd credential support needed for a simple case)
- An `EnvironmentFile=/opt/cekping/cekping.env` line instead of inline `Environment=`, keeping the token in a separate file with tighter permissions (`chmod 600`)
- A secrets manager (`podman secret create` + `Secret=` quadlet key) if this needs to scale beyond one host

For this deployment, inline `Environment=` was used for simplicity since the quadlet directory is root-only.

---

## 7. Useful commands

```bash
# View logs
journalctl -eu cekping-agent.service -f

# Restart after editing the quadlet
systemctl daemon-reload
systemctl restart cekping-agent.service

# Check container is actually running under podman
podman ps --filter name=cekping-agent
```
