---
type: troubleshooting
tags: [light-agent, vm-bot, telegram, gbrgb, hidraw, udev, uaccess, fedora, cosmic-greeter, systemd-user, rgb]
created: 2026-11-28
last_verified: 2026-11-28
status: current
---

# Telegram `/light` failed with ECONNREFUSED 192.168.50.20:8099 — moved checkout + hidraw owned by the greeter

**Host:** Fedora 43 desktop, `192.168.50.20`. Bot `vm-bot` runs in k3s on `home` (`192.168.50.200`)
and calls a small HTTP agent on this PC, which shells out to `gbrgb` on `/dev/hidraw3`
(Gigabyte IT5701, USB `048d:5702`). Background:
[[gigabyte-b650m-k-argb-fan-no-light-openrgb-gbrgb]] and
[[telegram-bot-proxmox-windows-vm-power]].

## Symptom

```
Failed: connect ECONNREFUSED 192.168.50.20:8099
```

Nothing was listening. Two independent breakages had stacked up, so fixing only one would still
have failed.

## Diagnosis, in order

```bash
hostname -I                       # 192.168.50.20 -> we are on the right machine
systemctl --user status light-agent --no-pager -l
ss -ltnp | grep 8099              # empty
```

The unit was `failed`, exit code 2:

```
× light-agent.service - Telegram light agent (sets the PC RGB light through gbrgb)
     Active: failed (Result: exit-code) since Sat 2026-11-28 01:21:57 WIB
    Process: 2364 ExecStart=/usr/bin/python3 /home/moo/vm-bot/light-agent/light_agent.py (code=exited, status=2)
```

```bash
journalctl --user -u light-agent -n 50 --no-pager
```

```
python3[1838]: /usr/bin/python3: can't open file '/home/moo/vm-bot/light-agent/light_agent.py': [Errno 2] No such file or directory
```

**Cause 1: the checkout moved.** The home directory was reorganised on 2026-11-27
(see [[home-directory-reorg-projects-logs-probes-2026-11-27]]); the repo now lives at
`/home/moo/projects/vm-bot`. The user unit still had `%h/vm-bot/light-agent/light_agent.py`.
Restart-on-failure kept retrying, hit the rate limit after 5 tries, and stayed dead.

After repairing the path the service started but every request returned
`502 {"ok": false, "message": "gbrgb failed: TimeoutExpired"}`. The agent's own 20 s subprocess
timeout fired because `gbrgb` was in its 30 × 1 s `open_with_retry` loop.

```bash
ls -l /dev/hidraw*
# crw-rw----+ 1 root root 241, 3 ... /dev/hidraw3
getfacl -p /dev/hidraw3
# user::rw-
# user:cosmic-greeter:rw-      <-- not moo
```

```bash
loginctl list-sessions --no-pager
# c1  961 cosmic-greeter seat0  1802 greeter tty1 ...
# (no moo session on seat0)
gbrgb info
# controller not available
```

**Cause 2: the seat had no logged-in user.** `60-openrgb.rules` only adds `TAG+="uaccess"`, so
the hidraw ACL follows whoever holds seat0. The PC had booted at 01:21 and was still sitting at
the COSMIC login screen, so the ACL went to `cosmic-greeter`. Root worked (`sudo gbrgb info`),
which is why the boot-time `gbrgb.service` still applied the saved colour and the fan looked fine
while Telegram control was dead. This is the login-screen gotcha already noted in
[[gigabyte-b650m-k-argb-fan-no-light-openrgb-gbrgb]], now made permanent.

## Fix

1. Point the user unit at the real checkout, and update the copy in the repo so a reinstall does
   not reintroduce the bug:

   ```bash
   cp ~/.config/systemd/user/light-agent.service /tmp/opencode/light-agent.service.bak
   sed -i 's|%h/vm-bot/light-agent/light_agent.py|%h/projects/vm-bot/light-agent/light_agent.py|' \
     ~/.config/systemd/user/light-agent.service
   systemctl --user daemon-reload
   systemctl --user reset-failed light-agent
   systemctl --user restart light-agent
   ```

   Repo change (`txtsamu/vm-bot`, `main`, commit `fb9a3fa`): same one-line `ExecStart` update in
   `light-agent/light-agent.service`, pushed.

2. Give `moo` permanent access to the controller by **ownership**, not by ACL:

   ```bash
   sudo tee /etc/udev/rules.d/61-gbrgb-hidraw-moo.rules >/dev/null <<'E'
   # Make the Gigabyte RGB Fusion 2 controller writable by moo regardless of who holds seat0.
   # 60-openrgb.rules only adds TAG+="uaccess", which follows the seat user (cosmic-greeter at the
   # login screen), so the light-agent got EACCES and /light timed out. Owner is not touched by uaccess.
   SUBSYSTEM=="hidraw", ATTRS{idVendor}=="048d", ATTRS{idProduct}=="5702", OWNER="moo", GROUP="moo", MODE="0600"
   E
   sudo udevadm control --reload-rules
   sudo udevadm trigger --action=change --subsystem-match=hidraw
   ```

   **Dead end, do not repeat:** a `RUN+="/usr/bin/setfacl -m u:moo:rw /dev/%k"` rule does not
   survive. The `uaccess` handling rewrites the node ACL after the rule runs and the `moo` entry
   disappears again (verified with `getfacl` after `udevadm trigger`). Owning the node works
   because `uaccess` only manages ACL entries.

3. Verify, as the agent does it (POST only; GET returns 501):

   ```bash
   . ~/.config/light-agent/env
   curl -s -w '\n<http %{http_code}>\n' -X POST \
     -H "Authorization: Bearer $LIGHT_AGENT_TOKEN" -H 'content-type: application/json' \
     -d '{"action":"set","color":"ff00ff"}' http://192.168.50.20:8099/light
   # {"ok": true, "message": "ok"}
   # <http 200>
   ```

   Mode call also verified: `{"action":"mode","mode":"breathing","color":"ff00ff","speed":4}` → 200.

## Verification (real output)

```
$ ss -ltnp | grep 8099
LISTEN 0 5 192.168.50.20:8099 0.0.0.0:* users:(("python3",pid=6842,fd=3))

$ ls -l /dev/hidraw3
crw-------+ 1 moo moo 241, 3 Nov 28 03:07 /dev/hidraw3

$ gbrgb info
hidraw        : /dev/hidraw3
product       : IT5701-GIGABYTE V4.0.26.2
fw version    : 4.0.26.2
support flags : 0x00  (bit0 = keep-lighting 0x47, bit1 = 0x48)

$ ssh home 'timeout 3 bash -c "</dev/tcp/192.168.50.20/8099" && echo open'
open

$ ssh home 'sudo k3s kubectl -n homelab get deploy vm-bot'
NAME     READY   UP-TO-DATE   AVAILABLE   AGE
vm-bot   1/1     1          1           49d
```

Light changed on the fan, and the firewalld rich rules for port 8099 were untouched.

## Gotchas

- The bot speaks **POST** to `/light` only. Testing with `curl http://.../light` gives
  `501 Unsupported method ('GET')`, which looks like an agent bug but is expected.
- `TimeoutExpired` from the agent means `gbrgb` never got the device; check the hidraw ACL/owner
  before blaming the controller.
- A user service dies at the login screen by design (no user session), but the root-run
  `gbrgb.service` still restores the last colour at boot, so the light can look healthy while
  control is broken.
- The uid `cosmic-greeter` owning the device is normal when nobody is logged in graphically.

## Time estimate

Total wall clock: about 8 minutes (03:00 to 03:08, from shell timestamps). Steps: diagnosis ~3 min,
unit path fix and restart under 1 min, udev rule plus the failed ACL attempt ~2 min, end-to-end
verification ~2 min. All figures are measured.

## Not verified

- Survival across a reboot. The udev rule is on disk and `udevadm trigger` proved the ownership
  applies to the current node, but no reboot was performed.
- Whether logging in as `moo` on seat0 still works with `OWNER="moo"`. It should (same user), but
  the graphical session was never started.
- Why the PC was still at the greeter at 01:21. No failed system units (`systemctl --failed`
  empty), so this looks like a normal "nobody logged in", not a broken display manager.

## References

No external sources were used. The diagnosis came from the on-box logs and from
[[gigabyte-b650m-k-argb-fan-no-light-openrgb-gbrgb]], which documents the packet-level setup,
the `uaccess` behaviour and the login-screen caveat.
