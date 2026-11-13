---
type: how-to
tags: [fedora, dnf, rpm, prisma-access-browser, palo-alto-networks, talon, enterprise-browser, gpg, bcc, ebpf]
created: 2026-11-13
last_verified: 2026-11-13
status: current
---

# Installing Prisma Access Browser (ex-Talon) on Fedora 43

## Context

Machine: `fedora` workstation, Fedora 43 Workstation Edition, `x86_64`, kernel `7.2.15-100.fc43.x86_64`, Wayland session.
No git repo involved: this was a host provisioning task on the local desktop.
Request: "install this" pointing at a `releases.talon-sec.com` appcast URL.

## What the URL actually is

```
https://releases.talon-sec.com/api/v1/appcast.xml?appid={dfef2477-...}&platform=linux_rpm&architecture=x64&channel=stable
```

That is a **Sparkle update feed**, not an installer. It returns RSS XML listing every stable build, each `<item>` carrying an `enclosure url` pointing at the real `.rpm` (with a 169 to 177 MB payload). Current head at install time: `157.19.6.79`.

The product is Prisma Access Browser, the enterprise Chromium fork formerly sold as Talon; Palo Alto Networks acquired Talon and folded the browser into Prisma SASE. Everything is still served from `talon-sec.com` domains.

## Install path chosen: signed DNF repo

Palo Alto documents three Linux paths: the `curl | sudo bash` script, a manual one-off `.rpm`, and a DNF/APT repository. The repo is the only one that verifies package signatures on every install and upgrade, so that is what went in.

```bash
sudo tee /etc/yum.repos.d/prisma-access-browser.repo >/dev/null <<'EOF'
[prisma-access-browser]
name=prisma-access-browser
baseurl=https://updates.talon-sec.com/linux/prisma-access-browser/rpm/stable/x86_64
enabled=1
gpgcheck=1
repo_gpgcheck=0
gpgkey=https://updates.talon-sec.com/linux/prisma-access-browser/linux_signing_key.pub
EOF
sudo rpm --import https://updates.talon-sec.com/linux/prisma-access-browser/linux_signing_key.pub
sudo dnf clean all
sudo dnf install -y prisma-access-browser-stable
```

`repo_gpgcheck=0` because the repo metadata itself (`repomd.xml`) is not signed; only the packages are. Package `gpgcheck=1` is what matters here.

## Verification (real output)

Installed version and package identity:

```
$ rpm -q prisma-access-browser-stable
prisma-access-browser-stable-157.19.6.79-1.x86_64
```

Signature check on the downloaded package (`dnf download` then `rpm -Kv`):

```
prisma-access-browser-stable-157.19.6.79-1.x86_64.rpm:
    Header OpenPGP V4 RSA/SHA512 signature, key fingerprint: 50ad129e9687023e085c68e18f8b8dd2f5f7c303: OK
    Header SHA256 digest: OK
    Payload SHA256 digest: OK
```

Imported key is the matching one:

```
pub   rsa4096 2025-03-12 [SCEA]
      50AD 129E 9687 023E 085C  68E1 8F8B 8DD2 F5F7 C303
uid   Palo Alto Networks, Inc. (Prisma Access Browser) <dl-browser-team@paloaltonetworks.com>
```

Footprint and files:

```
$ du -sh /opt/paloaltonetworks/pab
472M
$ ls /usr/share/applications | grep -i prisma
com.paloaltonetworks.PrismaAccessBrowser.desktop
prisma-access-browser.desktop
```

`/opt/paloaltonetworks/pab/chrome-sandbox` is installed setuid root (`-rwsr-xr-x`), which the Chromium sandbox needs.

Protection service after the fix below:

```
$ systemctl is-active pab-protection.service
active
$ sudo journalctl -u pab-protection.service -n 3
Loading eBPF program: protector_filter_lsm.c
BPF LSM detected: LSM hooks attached automatically
```

## Gotchas

**The `%post` scriptlet is written for Debian.** It printed:

```
Error: BCC (BPF Compiler Collection) Python module not available.
The protection service requires BCC. Install with:
  apt-get install python3-bpfcc bpfcc-tools linux-headers-$(uname -r)
```

`pab-protection.service` then crash-looped with `ModuleNotFoundError: No module named 'bcc'`. The Fedora equivalent is a single package:

```bash
sudo dnf install -y python3-bcc
```

`bpfcc-tools` does not exist on Fedora 43 under that name, so copying the `apt` line verbatim fails with `No match for argument: bpfcc-tools`. `bcc-tools` is the Fedora package name and got pulled in as a dep anyway.

**A stale MD5 on the docs page.** The docs claim `install.sh` is `eaeb2552cdffe5842debb6c8b7f5cffd`; the file actually served was `c21a98d3a389648cd3250bde7a45dbda`. Read as: the doc page was last updated Nov 2 2026 and the script has changed since. Do not treat that hash as a verification gate, and do not `curl | sudo bash` on the strength of it. Downloading it first and reading it showed a benign script that resolves the latest RPM from the release manager and runs `dnf install` on it.

**A scriptlet key import failed harmlessly.**

```
error: can't create transaction lock on /usr/lib/sysimage/rpm/.rpm.lock
error: /tmp/prismabrowser.sig.9yqUP6: key 1 import failed.
```

The package's `%post` tries to import a key into the RPM database while the RPM transaction still holds the lock. The system-wide key was imported manually beforehand and the package signature checked OK, so this is cosmetic, but it means the browser's own internal updater signature key may not be present. Repo-based `dnf upgrade` covers updates regardless.

**The appcast URL is not a download link.** Handing that URL to a browser or `wget -O file.rpm` gives you XML. Use `https://releases.talon-sec.com/api/v1/latest?...&redirect=true` for a direct payload, or the repo.

**Licensing gate is the real blocker, not the install.** Per Palo Alto prerequisites: requires *Prisma Access with Prisma Browser bundle license* or a *Prisma Browser standalone license*, plus SSO sign-in to a tenant. The binary installs fine on an unlicensed machine, but first launch cannot get past the sign-in/unenrollment screen. Fedora 41+ is supported; Fedora 43 is inside that window.

## Not verified

- Never launched the GUI to a working signed-in session. `/opt/paloaltonetworks/pab/prisma-access-browser --version` is a blocked switch: the browser strips `--version` and launches the full UI, which then hung for 120 s in a non-interactive shell. Launch it from the app menu instead.
- No tenant/licence was available, so the sign-in flow and policy sync are untested end to end.
- Whether the repo path auto-upgrades cleanly (`dnf upgrade`) across a major version was not exercised.

## Uninstall and cleanup (same day)

The package's removal is incomplete. Its `%preun` deletes the systemd unit, but the repo file, the imported signing key, `/opt/paloaltonetworks`, `/var/log/pab` and `/etc/default/prisma-access-browser` all survive `dnf remove`. Full sweep:

```bash
sudo systemctl disable --now pab-protection.service
sudo dnf remove -y prisma-access-browser-stable
sudo rm -f /etc/yum.repos.d/prisma-access-browser.repo
sudo rm -f /etc/default/prisma-access-browser
sudo rmdir /opt/paloaltonetworks /var/log/pab
sudo rpmkeys --delete 50ad129e9687023e085c68e18f8b8dd2f5f7c303
sudo dnf clean all
```

`/etc/default/prisma-access-browser` contained only `repo_add_once="true"`, so it is scriptlet litter, not configuration worth keeping. The BCC workaround also came out, since nothing else on the box wanted it:

```bash
sudo dnf remove -y python3-bcc   # also takes llvm20-libs, compiler-rt20, clang20-resource-files: 317 MiB
```

Post-removal verification:

```
$ rpm -qa | grep -iE 'prisma|paloalto|talon|bcc'
(nothing)
$ systemctl list-unit-files | grep -i pab
(nothing)
$ sudo find / -xdev \( -iname '*prisma-access*' -o -iname '*paloaltonetworks*' \)
(nothing)
```

`journalctl` still holds 63 historical lines from the crash-looping protector service. They are log history, not files, and age out on their own.

## Second sweep: user-level leftovers (later same day)

`dnf remove` never touches the per-user browser profile, so a follow-up "uninstall and clean up leftover files" request found the package already gone but 289 MB of user data still on disk:

```
$ du -sh "$HOME/.config/Palo Alto Networks" "$HOME/.cache/Palo Alto Networks"
257M    /home/moo/.config/Palo Alto Networks
32M     /home/moo/.cache/Palo Alto Networks
$ ls ~/.cache/libdnf5/ | grep prisma
prisma-access-browser-1b17910d51609d01
prisma-access-browser-f2a7aa2133ee3c0f
```

The 257 MB profile held a Chromium tree (`Default/Bookmarks`, `History`, `Login Data`, extensions under `Default/Extensions/gdhaibkimkeghllnpodfpoamchapggea`). It was safe to drop: 0 bookmarks, 43 history rows, all from the failed sign-in attempts.

```bash
rm -rf "$HOME/.config/Palo Alto Networks" "$HOME/.cache/Palo Alto Networks"
rm -rf "$HOME"/.cache/libdnf5/prisma-access-browser-*
```

Also removed a 16K Firefox `localStorage` entry for `docs.paloaltonetworks.com` (`~/.mozilla/firefox/<profile>/storage/default/https+++docs.paloaltonetworks.com`), a trace of reading the install docs, not part of the app.

Final state, both user and system wide:

```
$ find "$HOME" -xdev \( -iname '*prisma-access*' -o -iname '*paloaltonetworks*' -o -iname '*palo alto networks*' \) \
    -not -path '*/claude-research/*' -not -path '*/sessions/*' -not -path '*/node_modules/*'
(nothing)
$ sudo find / -xdev \( -iname '*prisma-access*' -o -iname '*paloaltonetworks*' -o -iname 'pab-protection*' \)
(nothing)
$ rpm -qa | grep -iE 'prisma|paloalto|talon'
(nothing)
```

Only `journalctl -u pab-protection.service` history remains (91 lines after the second launch attempt). Deleting it would need `journalctl --vacuum-time`, which is not worth nuking unrelated logs for.

## Related

- [[cosmic-de-install-fedora43]]
- [[fedora-perf-audit-openrgb-i2c-dup-scan]]
- [[flameshot-shortcut-cosmic-fedora43]]
