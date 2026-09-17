---
type: troubleshooting
tags: [agenix, nixos, technitium, secrets, home]
created: 2026-09-18
last_verified: 2026-09-18
status: current
---

# Fixing a stale agenix secret without ever decrypting the old value

Context: `home` (see [[warp-vm-nixos-migration-plan]]) has had a known,
recurring gotcha since the T19 cutover — the agenix-managed
`technitium-admin-password` secret does not match Technitium's real, live
admin password. It bit twice: once during the T19 cutover itself, and
again when adding the `perses.lan` DNS record, both times requiring the
user to supply the real password (`<TECHNITIUM_ADMIN_PASSWORD>`) out of band before the
Technitium admin UI could be used. This doc is the actual fix.

## Root cause

`hosts/home/dns.nix` (T3, txtsamu/claude-research#11) wires
`technitium-admin-password` in as an `EnvironmentFile` for
`technitium-dns-server`, expecting `DNS_SERVER_ADMIN_PASSWORD=...`. That
env var is only read by the underlying binary **on first-run bootstrap** —
if an auth database already exists, it's ignored.

`home`'s Technitium data directory was never bootstrapped fresh. Per T3's
own notes, `warp-vm`'s existing `/var/lib/technitium-dns-server` data
(zones, auth db, blocklists) was copied in wholesale after first boot and
chowned to the dynamic UID, specifically to preserve existing DNS records.
That means the *real* admin credential live in the auth db has always been
whatever `warp-vm`'s original database already had — completely
independent of whatever password got encrypted into the T3-era agenix
secret. The secret was truthful about nothing from the moment it was
created; the mismatch just hadn't surfaced yet.

## The fix — no decryption of the old value required

Re-encrypting an agenix secret normally means `agenix -e <file> -i
/etc/ssh/ssh_host_ed25519_key`, which decrypts the existing value into
`$EDITOR` first — and per `secrets/secrets.nix`'s own comment, that
requires the host's *private* SSH key, which only ever lives on `home`
itself. But none of that is actually necessary here: **age encryption is
asymmetric — encrypting a new value only needs the recipient's public
key**, which is already sitting in plaintext in `secrets/secrets.nix`:

```nix
let
  home = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICuMl1a2ZkqmctvGNjASFAYSzrSWyDWwxcCBdF51lnXn";
in
```

So the whole fix runs from any machine with the plain `age` CLI installed
— no SSH to `home`, no private key, no need to ever see (or overwrite
blind) the old ciphertext:

```bash
HOME_PUBKEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICuMl1a2ZkqmctvGNjASFAYSzrSWyDWwxcCBdF51lnXn"
umask 077
TMPFILE=$(mktemp)
printf 'DNS_SERVER_ADMIN_PASSWORD=<TECHNITIUM_ADMIN_PASSWORD>\n' > "$TMPFILE"
age -r "$HOME_PUBKEY" -o secrets/technitium-admin-password.age "$TMPFILE"
shred -u "$TMPFILE"   # don't leave the plaintext sitting on disk
```

`file secrets/technitium-admin-password.age` confirms the same format as
every other working secret in the repo (`age encrypted file, ssh-ed25519
recipient`) — good enough sanity check without needing to decrypt
anything to compare.

## Deploying it

The local checkout of `home-nixos` is the source of truth (git remote,
matches `origin/main`); the copy that lives at `/home/moo/home-nixos` on
`home` itself is a plain rsync target, not a git clone, and there's no
local `nix` install to run `--target-host` deploys from this machine — so
the actual deploy shape is: rsync the repo over, then rebuild on `home`
itself.

```bash
rsync -az --delete --exclude='.git' /home/moo/home-nixos/ home:/home/moo/home-nixos/
ssh home "cd /home/moo/home-nixos && sudo nixos-rebuild switch --flake .#home --refresh"
```

Activation output confirms agenix picked up the new ciphertext and
rotated to a fresh generation:

```
[agenix] creating new generation in /run/agenix.d/30
decrypting '.../technitium-admin-password.age' to '/run/agenix.d/30/technitium-admin-password...'
[agenix] symlinking new secrets to /run/agenix (generation 30)...
[agenix] removing old secrets (generation 29)...
```

Verification, again without ever printing the actual password value:

```bash
sudo stat -c '%a %U:%G %s bytes' /run/agenix/technitium-admin-password
# 400 root:root 40 bytes

sudo grep -c '^DNS_SERVER_ADMIN_PASSWORD=' /run/agenix/technitium-admin-password
# 1 — confirms the key name landed, without revealing the value

systemctl is-active technitium-dns-server
# active
```

## What this fix does and doesn't change

- **Does**: makes the encrypted secret truthful. Any future secret
  rotation, disaster-recovery rebuild, or fresh-bootstrap scenario now
  starts from the real password instead of a stale pre-migration one.
- **Doesn't**: change Technitium's live runtime behavior at all — its
  auth database was already bootstrapped before this fix landed, and
  `DNS_SERVER_ADMIN_PASSWORD` is only consulted on first-run. The admin
  password you log in with today is unchanged; only the *secret file's
  claim about what that password is* was wrong before, and is now
  correct.
- **Out of scope**: `home` is one of several independent Technitium
  nodes (see
  [[technitium-dns-3node-cluster-deployment]]) — `arm1`, `arm3`, and
  `vpz` each keep their own independent config and were not touched by
  this fix. If any of those ever drift the same way, the same
  no-decrypt-needed technique applies wherever they're wired through
  agenix (none currently are).

## References

- No web research needed for this one — root cause and fix were both
  derived directly from this repo's own prior tickets
  (`hosts/home/dns.nix`, `hosts/home/secrets.nix`,
  `secrets/secrets.nix`) and standard `age`/agenix asymmetric-encryption
  semantics, not from a fresh search.
