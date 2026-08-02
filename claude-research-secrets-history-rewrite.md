---
type: troubleshooting
tags: [git, secrets, git-filter-repo, github, security, privacy]
created: 2026-08-03
last_verified: 2026-08-03
status: current
---

# Scrubbing a leaked hostname/username/password from claude-research's git history

## Symptom

A just-pushed tutorial commit (`vpd-ssh-cloudflared-slow-connect.md`) contained a real cloudflared Access hostname and VPS username in plaintext. Since the commit was already on GitHub, editing the file forward wouldn't remove it — the original values would still be visible in the commit history.

A full audit of the *entire* history (not just the flagged commit) turned up more that had gone unnoticed:
- The same personal domain's subdomains in an older, already-pushed doc.
- A literal database root password in an early revision of another doc (`oneterm-podman-quadlet-deploy.md`) — the password had since been manually redacted in a *later* commit, but the plaintext value was still sitting in the earlier commit's history, recoverable via `git log -p`.
- A `TZ=<real timezone>` line (reveals approximate location) repeated across several docs.

**Lesson: a single flagged leak is rarely the only one.** Once you know you need to rewrite history, audit the whole repo for the same class of problem before doing it, since a rewrite is expensive to redo. (Note: the real values aren't reproduced in this write-up on purpose — see the Secrets policy below. Examples in this doc use fake placeholders like `vpn.example.com` / `deploy7821` / `hunter2`.)

## Diagnosis: audit the full history, not just the working tree

`git log <pattern>` on its own only searches commit messages. To find a string that ever appeared in file *content*, across every commit reachable from every ref:

```sh
git log --all -p | grep -inE 'pattern1|pattern2|...'
```

Useful variants used here:

```sh
# All subdomains of a domain, anywhere in history
git log --all -p | grep -oE '[a-z0-9._-]+\.example\.com' | sort -u

# Any non-private-range IPv4 address ever committed
git log --all -p | grep -oE '\b([0-9]{1,3}\.){3}[0-9]{1,3}\b' | sort -u \
  | grep -vE '^(192\.168\.|10\.|127\.|172\.(1[6-9]|2[0-9]|3[01])\.)'

# Email addresses (also catches package/extension IDs as false positives — check each hit)
git log --all -p | grep -oiE '[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}' | sort -u

# Which commits ever introduced/removed a given string (pickaxe search)
git log --all --oneline -S'search-string' -- .
```

`git log --all --format="%an <%ae>"` also shows every author identity ever used — useful to distinguish "this is just normal commit-authorship metadata" (not a leak — GitHub already shows this) from "this is leaked file content."

## Fix: `git filter-repo --replace-text`

`git filter-repo` (not the deprecated `git filter-branch`) rewrites every commit's blobs to strip the target strings. Install:

```sh
pip3 install --user git-filter-repo
```

It refuses to run on your working repo directly (safety feature) — operate on a disposable clone:

```sh
# Full backup first, always
tar czf ~/repo-backup-$(date +%Y%m%d-%H%M%S).tar.gz /path/to/repo

# Fresh clone to do the actual rewrite in
git clone /path/to/repo /path/to/repo-filtered
cd /path/to/repo-filtered
```

Replacement rules go in a plain text file, one `old==>new` per line (values below are illustrative, not the real ones that were actually redacted):

```
vpn.example.com==><VPN_HOSTNAME>
cloud.example.com==><NEXTCLOUD_HOSTNAME>
deploy7821==><VPS_USER>
MYSQL_ROOT_PASSWORD=hunter2==>MYSQL_ROOT_PASSWORD=<MYSQL_ROOT_PASSWORD>
TZ=America/Chicago==>TZ=<YOUR_TZ>
```

```sh
git filter-repo --replace-text replacements.txt --force
```

This rewrites every commit that ever contained any of those strings, giving each a new hash, and repacks the repo. It also removes the `origin` remote as a safety measure (deliberate — forces you to re-add it and re-confirm before pushing anywhere).

**Gotcha: a commit whose entire diff becomes a no-op gets pruned.** Here, an earlier commit's sole purpose was manually redacting the same database password later on. Once filter-repo redacted it at the point of *introduction* instead, that follow-up commit's diff became empty and filter-repo silently dropped it (24 commits → 23). This is correct behavior, not data loss — diff the before/after commit lists (`git log --oneline --reverse`) to confirm *why* a commit disappeared before assuming something broke.

## Verify before pushing — twice

Don't trust the rewrite blindly. Re-run the full-history grep inside the filtered clone:

```sh
git log --all -p | grep -inE 'pattern1|pattern2|...'   # must be empty
```

Then push, and verify independently with a *fresh clone straight from the remote* (not just re-checking the local repo you just pushed from — see gotcha below for why that distinction matters):

```sh
git remote add origin <url>
git push --force origin master

git clone --quiet <url> /tmp/verify-clone
cd /tmp/verify-clone && git log --all -p | grep -inE 'pattern1|pattern2|...'   # must be empty
rm -rf /tmp/verify-clone
```

Finally, replace the old working copy with the filtered one (after backing up):

```sh
mv /path/to/repo /path/to/repo-old-presecretsscrub
mv /path/to/repo-filtered /path/to/repo
```

## Gotcha: `git commit --amend` does not restage working-tree edits

Before reaching for the full `filter-repo` rewrite, the first attempt was to fix just the single latest (tip) commit with `git commit --amend`, since it was the most recently pushed one. That surfaced a real mistake worth flagging:

1. `git add -A` staged a file.
2. The file was edited *again* afterward (fixing a typo/mistake in the same content).
3. `git commit --amend --no-edit` was run — **without** re-running `git add`.

`git commit --amend` (without `-a`) commits whatever is currently in the **index**, not the working tree. Since the index still held the pre-fix version from step 1, the amended commit silently contained the *stale* content — in this case, briefly re-leaking the same hostname into a README "example" line that was meant to demonstrate the fix.

This is exactly the kind of mistake a full-history audit catches (it re-scans actual git content, not the working tree you assume is authoritative) but a spot-check of "does the working tree look right?" would have missed. **Always re-stage after any post-`git add` edit, or use `git commit --amend -a`, or run `git diff --cached` immediately before the amend to see exactly what will be committed.**

## Result

Full history rewrite is genuinely destructive — every commit hash in the repo changes, which breaks any existing clones/forks — so it's only worth it when something is actually leaked and already pushed publicly. For a leak caught *before* pushing, a normal `git reset`/re-commit is enough. For anything after pushing, amending only the tip commit is not sufficient by itself unless you've also confirmed (via the full-history grep above) that the leak never appeared in any earlier commit.

Pre-rewrite backups (tarball + renamed old repo directory) were kept locally on request rather than deleted immediately — worth doing by default until you're confident the rewritten history is what you wanted, since a rewrite can't be undone once the backups are gone.
