---
type: how-to
tags: [mikrotik, routeros, backup, github, git, security]
created: 2026-09-19
last_verified: 2026-09-21
status: current
---

# Backing up MikroTik config to a private GitHub repo, without leaking credentials

RouterOS offers two very different backup formats — only one of them is safe to put in git, even a private repo.

## The two formats

**`/export`** — a text RouterOS script that recreates the config. **Masks passwords/secrets by default.** Confirmed on this router: `grep -iE "password="` across a fresh export returned nothing, and `/ppp secret` entries show `add name=vpn` with no password field at all.

**`/system backup save`** — a binary snapshot. **Not masked.** It's not password-protected unless you explicitly pass `password=...` to the save command, and MikroTik's own docs are clear that a plain binary backup contains full recoverable credential material. This is the one that actually restores a router byte-for-byte (RSA host keys, some binary state `/export` can't represent) — but it's also the one you do not want sitting in git history, private repo or not (repos get forked, made-public by accident, tokens leak).

## Steps

```bash
# 1. Masked text export — safe to commit
sshpass -p '<MIKROTIK_PASSWORD>' ssh admin@192.168.50.1 "/export" > mikrotik-backup-$(date +%Y%m%d-%H%M%S).rsc

# 2. Binary backup — for local disaster-recovery use only, never committed
sshpass -p '<MIKROTIK_PASSWORD>' ssh admin@192.168.50.1 "/system backup save name=mikrotik-backup-<ts>"
sshpass -p '<MIKROTIK_PASSWORD>' scp admin@192.168.50.1:mikrotik-backup-<ts>.backup ./
sshpass -p '<MIKROTIK_PASSWORD>' ssh admin@192.168.50.1 "/file remove mikrotik-backup-<ts>.backup"  # see flash-space note below
```

```
# .gitignore
*.backup
```

```bash
git init && git add . && git commit -m "..."
gh repo create <name> --private --source=. --remote=origin --push
```

## Flash storage is tiny — clean up after yourself

This particular router (hEX S / RB760iGS) has only **16MB total flash**, and was down to **4.9MB free** before this backup. The binary backup file itself was small (43.3KiB) so there was no real risk here, but on a router this storage-constrained, always check size before creating a backup file on-box, and remove it immediately after copying it off (`/file remove`) rather than leaving it sitting on the router — a config mistake or a larger board's `.backup` could otherwise fill the remaining flash and cause its own outage.

## Password auth over SSH without a TTY prompt

`sshpass -p '<password>' ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no admin@<router-ip> "<command>"` — needed here because the router's admin account uses password auth and the existing `~/.ssh/config` `mikrotik` host entry has no key configured. `-o PubkeyAuthentication=no` avoids wasting a round-trip offering keys the router doesn't have registered before falling back to password.
