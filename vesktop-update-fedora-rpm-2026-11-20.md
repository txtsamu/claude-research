---
type: how-to
tags: [vesktop, discord, fedora, rpm, update-alternatives, electron, vencord]
created: 2026-11-20
last_verified: 2026-11-20
status: current
---

# Updating Vesktop on Fedora when it was installed from a GitHub RPM

## Context

Vesktop on the Fedora 43 workstation (`/home/moo`, Wayland session) was at
`vesktop-1.6.9-1.x86_64`, installed straight from the upstream GitHub RPM, not from a
repo or COPR:

```bash
rpm -qf /usr/bin/vesktop          # file /usr/bin/vesktop is not owned by any package
dnf info vesktop | grep -E 'Version|From repo'
# Version         : 1.6.9
# From repository : @commandline
```

`@commandline` means no repo tracks it, so `dnf upgrade` alone will never see a new
version. The update is a manual RPM download. Same class of problem as
[[openrgb-rc3-update-fedora]] (hand-installed unsigned RPM on Fedora).

Upstream's latest at the time was v1.7.0, published 2026-11-19T18:58:58Z.

## Time estimate

| Step | Time | Basis |
|---|---|---|
| Download the 87.4 MiB RPM | ~5 s | measured, `curl` progress showed `Total ... 0:00:05` at ~19 MB/s |
| `dnf upgrade` of the local file | 5 s | measured, `dnf history info` Begin 06:15:37, End 06:15:42 |
| Restore the `/usr/bin/vesktop` link | < 1 s | measured |
| Restart the app and wait for it to come up | ~6 s | measured settle wait; RPC sockets were listening by then |

Whole job is about two minutes of actual work. The clock time in the session was
longer only because the restart waited for a go-ahead.

## Steps

### 1. Confirm the current install has no repo behind it

```bash
rpm -q vesktop
dnf info vesktop | grep -E 'Version|From repo'
dnf repolist --enabled | grep -Ei 'vesktop|copr'
```

Only proceed with a manual RPM if the answer is `@commandline`. If it came from a COPR,
`sudo dnf upgrade vesktop` is the right move instead.

### 2. Get the latest release and its published digest

```bash
curl -fsSL https://api.github.com/repos/Vencord/Vesktop/releases/latest \
  | grep -E '"tag_name"|"name": "vesktop.*rpm"|digest'
```

For v1.7.0 the x86_64 asset was `vesktop-1.7.0.x86_64.rpm`, 91,659,670 bytes, with
`sha256:859e32db6e12345e4a1298effb2282e858ca976e3efb29e95f1a5991a22fd736`.

### 3. Download and verify

```bash
cd /tmp/opencode
curl -fL -o vesktop-1.7.0.x86_64.rpm \
  https://github.com/Vencord/Vesktop/releases/download/v1.7.0/vesktop-1.7.0.x86_64.rpm
sha256sum vesktop-1.7.0.x86_64.rpm
```

Compare the hash with the digest from step 2. This matters more than usual because the
package is not GPG-signed by anything in the local rpmdb.

### 4. Upgrade the package

```bash
sudo dnf upgrade -y --nogpgcheck ./vesktop-1.7.0.x86_64.rpm
```

`--nogpgcheck` suppresses the `skipped OpenPGP checks for 1 package from repository:
@commandline` warning path. The checksum in step 3 is what backs the package here, not a
signature.

### 5. Repair the `/usr/bin/vesktop` link (this is the trap)

The upgrade removes the launcher link. Immediately after `dnf upgrade`:

```bash
vesktop --version                 # /bin/bash: line 1: vesktop: command not found
ls -l /usr/bin/vesktop            # No such file or directory
```

Why: the package drives the launcher through `update-alternatives`. Its `postinstall`
registers the alternative, and its `postuninstall` calls
`update-alternatives --remove vesktop /opt/Vesktop/vesktop`. On an RPM *upgrade*, rpm
runs the new package's `postinstall` first and then the old package's `postuninstall`,
so the removal deletes the link the new version just created. Nothing is broken in
`/opt`; only the link is missing.

Fix it by re-registering the alternative the way the package does, not with a bare
`symlink` (a bare link works, but the next upgrade will treat it as foreign):

```bash
sudo update-alternatives --install /usr/bin/vesktop vesktop /opt/Vesktop/vesktop 100
```

Expected result:

```
lrwxrwxrwx. /etc/alternatives/vesktop -> /opt/Vesktop/vesktop
lrwxrwxrwx. /usr/bin/vesktop -> /etc/alternatives/vesktop
```

### 6. Restart the running app

Replacing files under `/opt` does not change a process that already has them mapped.
The running instance stays on the old code until it is restarted.

```bash
pgrep -x vesktop                  # note the main pid
kill -TERM <main-pid>
pgrep -x vesktop                  # expect nothing left
setsid -f /opt/Vesktop/vesktop >/tmp/opencode/vesktop-relaunch.log 2>&1
```

Do **not** use `pkill -f '/opt/Vesktop/vesktop'` from an interactive shell: the pattern
matches the shell's own command line, so it kills the shell that issued it (observed
exit code 143). Use `pgrep -x vesktop` / `kill -TERM` on the pid, or `pkill -x vesktop`.

## Verification

```bash
rpm -q vesktop                    # vesktop-1.7.0-1.x86_64
vesktop --version                 # Vesktop v1.7.0
pgrep -x vesktop | wc -l          # 8 (main + Electron children)
tail -2 /tmp/opencode/vesktop-relaunch.log
# [RPC:WS] Listening on 6463
# [RPC:IPC] Listening on /run/user/1000/discord-ipc-0
```

The app's own updater line in the launch log reads
`Update for version 1.7.0 is not available (latest version: 1.7.0, downgrade is
disallowed)`, which confirms the running copy considers itself current.

## What was not verified

- Whether Vesktop's in-app updater can ever work on this install. It would have to
  replace files in `/opt` as the user, which needs root, so assume no and keep updating
  by hand.
- Whether the `update-alternatives` link survives the *next* upgrade. Based on the
  scriptlets it will be removed again each time, so step 5 is expected to be needed
  every upgrade. Not yet tested against a real 1.7.x follow-up.
- The GPG key situation in depth. The RPM is unsigned for practical purposes; the
  sha256 from the GitHub release API is the integrity check used.

## References

- [Vesktop v1.7.0 release](https://github.com/Vencord/Vesktop/releases/tag/v1.7.0) (changelog and asset list)
- [Vesktop releases API, latest](https://api.github.com/repos/Vencord/Vesktop/releases/latest) (source of the asset sha256 digests used above)
- [Vesktop release listing](https://github.com/Vencord/Vesktop/releases)
