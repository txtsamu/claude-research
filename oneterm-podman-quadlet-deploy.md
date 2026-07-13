---
type: how-to
tags: [oneterm, podman, quadlet, systemd, deployment]
created: 2026-06-26
last_verified: 2026-06-26
status: current
---

# Deploying OneTerm with Podman Quadlets

**Date:** 2026-06-26  
**Host:** homelab (Rocky Linux 9, podman 5.x, systemd 252)  
**Goal:** Run the full OneTerm stack (UI + API + guacd + ACL + MySQL + Redis) as systemd-managed podman containers using quadlets.

---

## 1. What are podman quadlets?

Quadlets are `.container`, `.pod`, `.network`, and `.volume` files placed in `/etc/containers/systemd/`. On `systemctl daemon-reload`, the podman quadlet generator transforms them into `.service` units. This gives you full systemd dependency management, restart policies, and journald logging with zero Docker Compose dependency.

The generator lives at:
```
/usr/lib/systemd/system-generators/podman-system-generator
```

Validate a unit without reloading:
```bash
/usr/lib/systemd/system-generators/podman-system-generator --dryrun 2>&1 | grep -A5 "yourunit"
```

---

## 2. Stack overview

OneTerm requires six containers:

| Service | Image | Purpose |
|---------|-------|---------|
| `oneterm-mysql` | mysql:8.2.0 | Persistent storage |
| `oneterm-redis` | redis:7.2.3 | Session cache |
| `oneterm-acl` | veops/acl-api:2.2 | ACL/auth service |
| `oneterm-guacd` | veops/oneterm-guacd:1.5.4 | Guacamole RDP/VNC daemon |
| `oneterm-api` | veops/oneterm-api:v25.9.1 | Go backend |
| `oneterm-ui` | veops/oneterm-ui:v25.9.1 | nginx + Vue SPA |

All six share a pod (`oneterm.pod`) so they communicate via localhost — no network aliases or service discovery needed.

---

## 3. Pod file

`/etc/containers/systemd/oneterm.pod`:

```ini
[Unit]
Description=OneTerm bastion host pod
Before=oneterm-mysql.service oneterm-redis.service oneterm-guacd.service oneterm-acl.service oneterm-api.service oneterm-ui.service

[Pod]
PodName=oneterm
PublishPort=8666:80
PublishPort=2222:2222
AddHost=mysql:127.0.0.1
AddHost=redis:127.0.0.1

[Install]
WantedBy=multi-user.target
```

`AddHost` injects `/etc/hosts` entries inside every container in the pod — the backend config uses hostnames like `mysql` and `redis`, so this wires them to localhost within the shared network namespace.

---

## 4. Container files

### MySQL

`/etc/containers/systemd/oneterm-mysql.container`:

```ini
[Unit]
Description=OneTerm MySQL
After=oneterm-pod.service

[Container]
ContainerName=oneterm-mysql
Image=registry.cn-hangzhou.aliyuncs.com/veops/mysql:8.2.0
Pod=oneterm.pod
Volume=/opt/oneterm/mysql-data:/var/lib/mysql:Z
Volume=/opt/oneterm/mysqld.cnf:/etc/mysql/conf.d/mysqld.cnf:z,ro
Volume=/opt/oneterm/mysql-init/1-create-users.sql:/docker-entrypoint-initdb.d/1-create-users.sql:z,ro
Volume=/opt/oneterm/mysql-init/2-acl.sql:/docker-entrypoint-initdb.d/2-acl.sql:z,ro
Environment=TZ=Asia/Jakarta MYSQL_ROOT_PASSWORD=123456 MYSQL_DATABASE=oneterm
Exec=--character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci

[Service]
Restart=always

[Install]
WantedBy=multi-user.target
```

### Redis

```ini
[Unit]
Description=OneTerm Redis
After=oneterm-pod.service

[Container]
ContainerName=oneterm-redis
Image=registry.cn-hangzhou.aliyuncs.com/veops/redis:7.2.3
Pod=oneterm.pod
Environment=TZ=Asia/Jakarta

[Service]
Restart=always

[Install]
WantedBy=multi-user.target
```

### ACL API

The ACL service runs init tasks on first boot (db-setup, seed data). Use a startup script mounted as a volume:

```ini
[Container]
ContainerName=oneterm-acl
Image=registry.cn-hangzhou.aliyuncs.com/veops/acl-api:2.2
Pod=oneterm.pod
Volume=/opt/oneterm/acl.env:/data/apps/acl/.env:z,ro
Volume=/opt/oneterm/acl-start.sh:/acl-start.sh:z,ro
Environment=TZ=Asia/Jakarta SYSTEM_DEFAULT_LANGUAGE=en-US
Exec=/bin/sh /acl-start.sh
```

### Guacd

```ini
[Container]
ContainerName=oneterm-guacd
Image=registry.cn-hangzhou.aliyuncs.com/veops/oneterm-guacd:1.5.4
Pod=oneterm.pod
Volume=/opt/oneterm/replay:/replay:Z
Volume=/opt/oneterm/rdp:/rdp:Z
User=root
```

### API

```ini
[Container]
ContainerName=oneterm-api
Image=registry.cn-hangzhou.aliyuncs.com/veops/oneterm-api:v25.9.1
Pod=oneterm.pod
Volume=/opt/oneterm/replay:/replay:Z
Volume=/opt/oneterm/rdp:/rdp:Z
Volume=/opt/oneterm/config.yaml:/oneterm/config.yaml:z,ro
Environment=ONETERM_RDP_DRIVE_PATH=/rdp
Exec=./server config.yaml
```

### UI (nginx)

The upstream image's nginx config is a template — it uses `envsubst` to substitute `$ONETERM_API_HOST`, `$ACL_API_HOST`, and `$NGINX_PORT` at container start. Mount a startup script to do this:

```ini
[Container]
ContainerName=oneterm-ui
Image=registry.cn-hangzhou.aliyuncs.com/veops/oneterm-ui:v25.9.1
Pod=oneterm.pod
Volume=/opt/oneterm/nginx.conf.example:/etc/nginx/conf.d/nginx.oneterm.conf.example:z,ro
Volume=/opt/oneterm/ui-start.sh:/ui-start.sh:z,ro
Environment=TZ=Asia/Jakarta ONETERM_API_HOST=127.0.0.1:8888 ACL_API_HOST=127.0.0.1:5000 NGINX_PORT=80
Exec=/bin/sh /ui-start.sh
```

Since all containers share the pod's localhost, `ONETERM_API_HOST=127.0.0.1:8888` works.

---

## 5. Start the stack

```bash
systemctl daemon-reload
systemctl start oneterm-mysql.service oneterm-redis.service
systemctl start oneterm-acl.service oneterm-guacd.service
systemctl start oneterm-api.service
systemctl start oneterm-ui.service
```

Check everything is running:
```bash
podman ps --pod --format "{{.Names}} {{.Status}} {{.Image}}"
```

---

## 6. Swapping in a locally built image

When you build a custom image with `podman build`, referencing it in a quadlet as `localhost/myimage:tag` causes a pull attempt against `https://localhost/v2/` — which fails. The fix is `Pull=never`:

```ini
[Container]
Image=localhost/oneterm-ui:dark
Pull=never
```

**Validation gotcha:** `PullPolicy=never` is not a valid quadlet key (that's a Docker Compose concept). The correct quadlet key is `Pull=never`. Validate with the dry-run generator before reloading:

```bash
/usr/lib/systemd/system-generators/podman-system-generator --dryrun 2>&1 | grep -i "error\|unsupported"
```

After editing a quadlet file, always run `systemctl daemon-reload` before `systemctl restart`. If a unit ends up in `not-found` state after a failed start, `daemon-reload` again to re-register it.

---

## 7. Building the custom dark-mode UI image

The upstream `Dockerfile` uses `node:16.20.0-alpine`. Two engine compatibility issues arise:

| Problem | Cause | Fix |
|---------|-------|-----|
| `node-releases@2.0.50` requires node >=18 | Node 16 too old | Switch to `node:18-alpine` |
| `@achrinza/node-ipc@9.2.2` requires node 8/10/12/14/16/17 | Node 18 too new for that dep | Add `--ignore-engines` to yarn install |

Final working Dockerfile builder stage:

```dockerfile
FROM node:18-alpine AS builder
WORKDIR /oneterm-ui
COPY . .
RUN yarn config set registry https://registry.npmmirror.com/
RUN yarn install --ignore-engines
RUN yarn build

FROM nginx:alpine
COPY --from=0 /oneterm-ui/dist /etc/nginx/html
RUN mv /etc/nginx/conf.d/default.conf /etc/nginx/conf.d/default.conf.bak
```

Build and tag:
```bash
podman build -t localhost/oneterm-ui:dark ./oneterm-ui/
```

Then swap the quadlet image reference and restart the service — no other containers are affected.

---

## 8. Useful commands

```bash
# View logs for a specific container
journalctl -eu oneterm-ui.service -f

# Check all oneterm container states
podman ps --pod --format "{{.Names}} {{.Status}}" | grep oneterm

# Restart just the UI (e.g. after an image rebuild)
systemctl restart oneterm-ui.service

# Validate quadlet file without reloading
/usr/lib/systemd/system-generators/podman-system-generator --dryrun 2>&1

# List generated unit content for a specific container
/usr/lib/systemd/system-generators/podman-system-generator --dryrun 2>&1 | grep -A 20 "oneterm-ui.service"
```
