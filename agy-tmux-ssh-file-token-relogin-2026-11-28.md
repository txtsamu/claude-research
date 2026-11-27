---
type: troubleshooting
tags: [antigravity, agy, tmux, ssh, keyring, oauth, token-storage, fedora, cosmic]
created: 2026-11-28
last_verified: 2026-11-28
status: current
---

# AGY asks for a fresh login inside tmux but not on the desktop

Running `agy` from the COSMIC desktop terminal worked with the saved login. Running the same binary inside tmux printed an OAuth URL and `Waiting for authentication`. Same user, same `HOME`, same keyring daemon. The cause is not a broken credential: AGY deliberately switches to **file-based token storage when it detects an SSH session**, and the tmux server had inherited `SSH_*` variables from the SSH login that started it.

## Time estimate

About 10 minutes total for diagnosis and verification.

- Reproducing the failure/tmux probes: 20 to 30 seconds each (the failed run prints the login URL immediately, then waits up to 60 seconds).
- The successful probe returned in a few seconds.
- No builds, downloads or reboots involved. Figures are measured from the probe timestamps, except the total which is approximate.

## Symptom

```console
$ agy --print "reply with OK"        # desktop terminal
OK

$ tmux new-session -d -s probe 'agy --print "reply with OK" > /tmp/agy.out 2>&1'
$ cat /tmp/agy.out
Authentication required. Please visit the URL to log in:
  https://accounts.google.com/o/oauth2/auth?...
Waiting for authentication (timeout 60s)...
Or, paste the authorization code here and press Enter:
```

The same thing happened when the tmux pane was opened from the local desktop, because the long-lived tmux server keeps the environment it was born with.

## Quick answer

Check AGY's own log. Two different storage backends are visible:

```console
$ grep -h -E 'Using file-based token storage|ChainedAuth: authenticated via keyring' \
    ~/.gemini/antigravity-cli/log/cli-*.log | tail -4
I1128 04:29:56 ... composite_token_storage.go:135] Using file-based token storage because SSH session detected
I1128 04:29:14 ... auth.go:157] ChainedAuth: authenticated via keyring (effective: keyring)
I1128 04:28:19 ... composite_token_storage.go:135] Using file-based token storage because SSH session detected
I1128 04:28:06 ... auth.go:157] ChainedAuth: authenticated via keyring (effective: keyring)
```

The keyring run is the desktop shell. The file-based run is tmux.

## Diagnosis

Confirmed environment and version first. Both terminals used the same binary and same home:

```console
$ which agy && agy --version
/home/moo/.local/bin/agy
1.5.18

$ printf '%s\n' "$HOME"
/home/moo
```

The tmux server's global environment contains the SSH markers, even though the current terminal may be a local desktop window:

```console
$ tmux show-environment -g | grep -E 'SSH_|XDG_SESSION_TYPE'
SSH_CLIENT=<client-ip> <port> 22
SSH_CONNECTION=<client-ip> <port> <server-ip> 22
SSH_TTY=/dev/pts/2
XDG_SESSION_TYPE=tty
```

Meanwhile the desktop shell that works has no `SSH_*` variables and runs under the COSMIC Wayland session (`XDG_CURRENT_DESKTOP=COSMIC`, `XDG_SESSION_TYPE=wayland`).

The saved credential is in the login keyring and is perfectly readable. The login collection is unlocked, and the AGY entry is present:

```console
$ busctl --user get-property org.freedesktop.secrets \
    /org/freedesktop/secrets/collection/login \
    org.freedesktop.Secret.Collection Locked
b false

$ gdbus call --session --dest org.freedesktop.secrets --object-path /org/freedesktop/secrets \
    --method org.freedesktop.Secret.Service.SearchItems '{}'
# one of the returned items, via Properties.GetAll:
# Label: "Password for 'antigravity' on 'gemini'"
# Attributes: service=gemini, username=antigravity
```

So the token was never missing. AGY simply was not looking at it.

### Which variables trigger it

Probes inside the same tmux server, each unsetting one variable before launching AGY:

| Unset | Result |
|---|---|
| `SSH_CONNECTION` only | still asked for login |
| `SSH_CLIENT` only | still asked for login |
| `SSH_TTY` only | still asked for login |
| all three | `OK`, and the log flipped to `ChainedAuth: authenticated via keyring` |

`TMUX` stays set in all cases, so the trigger is the SSH markers, not tmux detection. AGY treats any remaining SSH marker as "this is a remote session."

Probe used (replace the unset list as needed):

```console
$ tmux new-session -d -s agyprobe \
    'unset SSH_CONNECTION SSH_CLIENT SSH_TTY; agy --print "reply with OK" > /tmp/agy-probe.out 2>&1; echo exit=$? >> /tmp/agy-probe.out'
$ sleep 10; cat /tmp/agy-probe.out
OK
exit=0
```

## Why AGY does this

The log string is literal: `Using file-based token storage because SSH session detected`. Local sessions use the OS keyring (gnome-keyring via the Secret Service on Linux). SSH sessions get a separate, file-based store and a separate browser-plus-code login. That is a deliberate split, not a bug: a remote login should not silently read the desktop keyring's token, and a token copied over SSH should not be able to impersonate the local desktop session.

tmux is just the messenger. Its server environment is frozen at server start. Here the server was started from an SSH login, so every new pane, and every attach from the desktop, carries `SSH_CONNECTION`, `SSH_CLIENT` and `SSH_TTY` for the life of that server.

## Fixes

### Option A: sign in once inside tmux (supported path)

Run `agy` in the tmux pane, open the printed URL in the browser on the machine you are sitting at, complete the Google sign-in, and paste the alphanumeric code back into the waiting prompt. AGY then stores that credential in its file-based store, so later runs in SSH/tmux sessions find it. This keeps the remote/local separation AGY intends.

I did not complete this exchange during diagnosis, so I have not verified the exact file path or that it survives an AGY upgrade. See *Not verified* below.

### Option B: strip the SSH markers from tmux (workaround)

This makes tmux look local so AGY uses the keyring credential:

```console
tmux set-environment -gu SSH_CONNECTION
tmux set-environment -gu SSH_CLIENT
tmux set-environment -gu SSH_TTY
```

New panes inherit the cleaned global environment. Existing panes keep the old environment, so in each already-open shell run:

```console
unset SSH_CONNECTION SSH_CLIENT SSH_TTY
```

Then verify the log line on the next run:

```console
agy --print "reply with OK"
grep -h 'ChainedAuth' ~/.gemini/antigravity-cli/log/cli-*.log | tail -1
```

Trade-off: this lies to every program in that tmux server about being on an SSH session. Most tools do not care, but anything that keys behaviour off `SSH_CONNECTION` will now think it is local.

### Option C: restart tmux from the desktop

`tmux kill-server`, then start tmux from a local desktop terminal. The new server has no SSH markers. This destroys the current session, so only do it when nothing important is running. If sessions need to survive, combine with tmux-resurrect or similar.

## Gotchas

- Attaching to an old tmux server from the desktop does not change the server's environment. The variables come from whoever started the server, not from the current client.
- `tmux set-environment -g -u` does not retroactively alter running shells. Unset in the pane, or open a new pane.
- Unsetting a single SSH variable is not enough. All of `SSH_CONNECTION`, `SSH_CLIENT` and `SSH_TTY` must be gone in the probe here.
- The keyring entry is labelled `Password for 'antigravity' on 'gemini'`, stored in the `login` collection. A missing entry would be a different failure (real logout or wiped keyring), but this case had the entry present and unlocked.
- Diagnostics live in `~/.gemini/antigravity-cli/log/cli-*.log` on this install (AGY 1.5.18). The path and message text may change in later versions.

## Not verified

- The exact on-disk path of AGY's file-based token store, and whether it is encrypted at rest. I did not complete the browser/code login, so no file was created.
- Whether the file-based token survives an AGY update or a change of `credential-user-scope` (`~/.config/antigravity/credential-user-scope`).
- Whether `screen` or `zellij` behave identically. They should if they inherit the same SSH variables, but that was not tested.
- Google's current CLI auth documentation page content; the mechanism was proven from the local binary and logs, with the linked blog as corroboration.

Related: [[opencode-hermes-default-model-opencode-go-2026-11-27]], [[home-directory-audit-2026-11-28]]

## References

- [Why AGY Asks You to Log In Again over SSH and tmux (Smolkin.org, 2026-11-12)](https://www.smolkin.org/blog/2026/11/why-agy-asks-to-log-in-over-ssh-and-tmux.html): shows the same `Using file-based token storage because SSH session detected` log line and the separate SSH login flow.
- [Antigravity CLI install and authentication docs](https://antigravity.google/docs/install?tab=cli): describes local keyring sign-in versus the SSH authorization flow (linked by the blog; not re-read in this session).
