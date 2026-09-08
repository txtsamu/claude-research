---
type: how-to
tags: [checkmk, truenas, scale, docker, containers, monitoring, package-management-blocked]
created: 2026-09-09
last_verified: 2026-09-09
status: current
---

# Getting real host-level checkmk metrics on an appliance that blocks package installs (TrueNAS SCALE)

Follow-up to [checkmk-k8s-deployment-monitor-lan.md](checkmk-k8s-deployment-monitor-lan.md),
which left `nas` unmonitored because TrueNAS SCALE hard-blocks
`apt`/`dpkg`:
```
Package management tools are disabled on TrueNAS appliances.
```
This documents actually getting a working, **real-host-accurate** checkmk
agent running there via TrueNAS's own supported Docker/Apps subsystem
instead — plus a genuinely non-obvious footgun in checkmk's own agent
script that silently defeats the whole point if you don't know about it.

## Step 1: enable the Apps/Docker subsystem

Not enabled by default — `docker.service` was `disabled`/`inactive`, no
pool assigned:
```bash
midclt call docker.config
# {"pool": null, "dataset": null, ...}
```
Only one pool existed (`data`, 4.2TB free — same pool backing the
cluster's `truenas-iscsi` PVCs). Enabled it:
```bash
midclt call docker.update '{"pool": "data"}'   # returns a job id
midclt call core.job_wait <job-id> --job        # wait for it
# → creates data/ix-apps dataset, starts docker.service
```
**Worth weighing before doing this on a shared/loaded NAS**: this adds a
permanently-running Docker daemon + a new dataset to a pool that may
already be under memory pressure from other duties (ARC, iSCSI/SCST —
see `truenas-scst-arc-memory-backup-timeout.md`). Confirmed with the user
before doing this rather than assuming it was fine.

## Step 2: don't use a prebuilt community image — build your own from the real agent package

Searched for an existing "checkmk agent in a container" image first
(there's no official one from Checkmk itself for this use case — their
own Docker docs are about monitoring *other* containers from a
host-installed agent, not running the agent *as* a container to monitor
its host):
- `eeacms/check-mk-agent` — ships a genuinely ancient agent
  (`check_mk_agent-2.10p10`, several major versions behind ours) with no
  host-mount setup at all — it would monitor the tiny container itself,
  not the real appliance.
- `sam01/checkmk-agent-docker` (Codeberg) — a build recipe, not a
  published image; would need trusting and building an unfamiliar
  third-party Dockerfile.

Built a minimal one instead, using the **exact same agent package
version already deployed fleet-wide** (`2.3.0p49`), pulled straight from
the checkmk site's own package server rather than any external source:

```dockerfile
FROM debian:bookworm-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends xinetd curl ca-certificates procps && \
    rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /tmp/check-mk-agent.deb \
      "http://<checkmk-loadbalancer-ip>:5000/cmk/check_mk/agents/check-mk-agent_2.3.0p49-1_all.deb" && \
    dpkg -i /tmp/check-mk-agent.deb || true && \
    rm -f /tmp/check-mk-agent.deb
# ^ the .deb's own postinst detects "systemd not found" in a plain
#   container and deploys its own correct /etc/xinetd.d/check-mk-agent
#   automatically -- don't add a second, redundant xinetd service block
#   for port 6556, it'll conflict with the one the package already wrote.

EXPOSE 6556
CMD ["/bin/sh", "-c", "rm -f /.dockerenv; exec /usr/sbin/xinetd -dontfork"]
```
(the `rm -f /.dockerenv` in `CMD` is the critical bit — explained below;
it must run on every container start, not just once at build time.)

Build and run, sharing the real host's PID/network namespaces so the
agent actually inspects the appliance rather than the container:
```bash
docker build -f checkmk-agent.Dockerfile -t checkmk-agent:2.3.0p49 .
docker run -d --name checkmk-agent --restart unless-stopped \
  --privileged --pid host --network host --cgroupns host \
  checkmk-agent:2.3.0p49
```

## Step 3: the real bug — checkmk's agent silently swaps to container-scoped metrics

First run (without the `/.dockerenv` fix) produced a running agent that
answered on port 6556 fine, but with the **wrong sections**:
```
<<<docker_container_mem_cgroupv2>>>
<<<docker_container_cpu_cgroupv2>>>
<<<docker_container_diskstat_cgroupv2>>>
```
instead of the normal `<<<mem>>>`, `<<<cpu>>>`, `<<<df_v2>>>`. No
`<<<mem>>>`/`<<<cpu>>>`/`<<<df>>>` sections at all — checkmk would show
"Docker container" services (reporting the tiny container's own cgroup
limits) instead of real host `Memory`/`CPU load` services. `--cgroupns
host` alone did **not** fix this (tried it, no change in emitted
sections).

**Actual cause**: the agent script's container-detection is a simple
check for the presence of `/.dockerenv` — a marker file Docker
unconditionally drops into every container's root filesystem, completely
unrelated to which namespaces are shared. It exists regardless of
`--pid=host`/`--network=host`/`--cgroupns=host`, so all of that
correctly gave the process real host visibility, but the agent script
never got that far — it saw the marker and deliberately branched to
"report container stats" logic instead, by design (that's the *correct*
behavior for someone using it to monitor an actual container's resource
limits; it's just the wrong behavior for the "use a container purely as
a delivery vehicle to reach an appliance's real host metrics" use case).

**Fix**: delete `/.dockerenv` — Docker recreates it fresh on every
container start, so it has to be removed as part of the startup command,
not just once:
```bash
CMD ["/bin/sh", "-c", "rm -f /.dockerenv; exec /usr/sbin/xinetd -dontfork"]
```
Confirmed this flips the agent over to real `<<<mem>>>`/`<<<cpu>>>`
sections immediately, with values verified to exactly match the real
host (`free`/`uptime`/`load average` run directly via SSH matched the
agent's reported `MemTotal`/load average/uptime seconds precisely).

## What's real vs. what's still container-scoped after the fix

Confirmed accurate (matches the real appliance exactly, checked
side-by-side against `free -h` / `uptime` / `cat /proc/loadavg` run
directly on the host):
- `<<<mem>>>` — `MemTotal` etc.
- `<<<cpu>>>` — load average
- `<<<uptime>>>` — real host boot-relative uptime (2364120s ≈ 27 days,
  matched `uptime`'s "up 27 days, 8:40" exactly)
- `<<<ps_lnx>>>` — real host process tree (PID 1 = host's actual
  `/sbin/init`, correct elapsed times) — this one works via `--pid=host`
  alone regardless of the `/.dockerenv` issue, since it's driven by the
  shared PID namespace, not the container-detection branch.

**Still container-scoped, not fixed by this**: `<<<df_v2>>>` (filesystem
usage) only lists the container's own overlay root and whatever bind
mounts were added — it does **not** see the appliance's real ZFS pools
(`boot-pool`, `data`) at all, since ZFS isn't visible/mountable inside a
generic Debian container without the `zfs`/`zpool` userspace tools and
kernel module access wired in specifically, which wasn't attempted here.
For real storage/pool-level monitoring on this host, TrueNAS's own web
UI/API or SNMP would be the better source — not chased further this
session, host CPU/RAM was the actual ask.

## Result

```bash
curl -sk -u cmkadmin:<pw> -X POST "$BASE/domain-types/host_config/collections/all" \
  -d '{"host_name":"nas","folder":"/","attributes":{"ipaddress":"192.168.50.10","tag_agent":"cmk-agent"}}'
# bulk-discovery-start + activate-changes as usual
```
12 services discovered, including real `Memory`, `CPU utilization`,
`CPU load`, `Uptime`, `Disk IO SUMMARY`, two network `Interface` services
— on par with every other host in the fleet for the metrics that
actually matter (compute), with the filesystem-visibility caveat above
noted for anyone monitoring storage specifically.
