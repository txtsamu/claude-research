#!/usr/bin/env python3
"""Step C (root on home): move the Telegram bot from Hermes to Evonic.

 1. back up /root/.hermes/.env
 2. comment out TELEGRAM_BOT_TOKEN in it (atomic rewrite, same owner/mode); nothing else in the file changes
 3. restart hermes-gateway and confirm it no longer connects to Telegram
 4. enable the staged Evonic channel (DB) and restart evonic; confirm it is polling and no token-conflict is logged

ROLLBACK (also printed at the end):
   cp -p /root/.hermes/.env.pre-telegram-move /root/.hermes/.env && systemctl restart hermes-gateway
   (Evonic side) runuser -u evonic -- ... update_channel(<id>, {"enabled": 0}) ; systemctl restart evonic

Never prints the token.
"""
import json, os, re, shutil, subprocess, sys, time

ENV = "/root/.hermes/.env"
BAK = ENV + ".pre-telegram-move"


def sh(*a, **k):
    return subprocess.run(a, capture_output=True, text=True, **k)


def gw_telegram_state():
    try:
        d = json.load(open("/root/.hermes/gateway_state.json"))
        return (d.get("platforms") or {}).get("telegram", {}).get("state", "absent")
    except Exception as e:
        return f"unreadable ({e})"


# --- 1+2: Hermes side
if not os.path.exists(BAK):
    shutil.copy2(ENV, BAK)
    os.chmod(BAK, 0o600)
print("backup:", BAK, oct(os.stat(BAK).st_mode & 0o777))
lines = open(ENV).read().split("\n")
changed = 0
for i, l in enumerate(lines):
    if re.match(r"^TELEGRAM_BOT_TOKEN=", l):
        lines[i] = "# moved to Evonic 2026-11-06 (backup: .env.pre-telegram-move)\n#DISABLED_" + l.split("=", 1)[0] + "="
        changed += 1
assert changed == 1, f"expected exactly one TELEGRAM_BOT_TOKEN line, found {changed}"
st = os.stat(ENV)
tmp = ENV + ".tmp-migrate"
fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, st.st_mode & 0o777)
with os.fdopen(fd, "w") as f:
    f.write("\n".join(lines))
os.chown(tmp, st.st_uid, st.st_gid)
os.replace(tmp, ENV)
print("hermes .env: token line disabled (value removed from the active line)")

# --- 3: restart Hermes gateway
t0 = time.time()
print("restarting hermes-gateway ...", sh("systemctl", "restart", "hermes-gateway").returncode)
for _ in range(60):
    if sh("systemctl", "is-active", "hermes-gateway").stdout.strip() == "active":
        break
    time.sleep(1)
time.sleep(20)  # let the platforms connect
print(f"hermes-gateway active after {time.time()-t0:.0f}s | telegram platform state: {gw_telegram_state()}")

# --- 4: Evonic side
code = r'''
import sys
sys.path.insert(0, ".")
from models.db import db
ch = [c for c in db.get_channels("hermes_default") if c.get("name") == "telegram"]
assert ch, "staged channel missing"
db.update_channel(ch[0]["id"], {"enabled": 1})
print("channel", ch[0]["id"], "enabled ->", db.get_channel(ch[0]["id"]).get("enabled"))
'''
r = subprocess.run(["runuser", "-u", "evonic", "--", "/opt/evonic-venv/bin/python", "-c", code], cwd="/opt/evonic-source",
                   env=dict(os.environ, HOME="/var/lib/evonic"), capture_output=True, text=True, stdin=subprocess.DEVNULL)
print("\n".join(l for l in (r.stdout + r.stderr).splitlines() if "[INFO]" not in l)[-400:])
assert r.returncode == 0
print("restarting evonic ...", sh("systemctl", "restart", "evonic").returncode)
for _ in range(60):
    if sh("curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://127.0.0.1:8080/api/health").stdout.strip() == "200":
        break
    time.sleep(1)
time.sleep(15)
log = sh("journalctl", "-u", "evonic", "--since", "-2min", "--no-pager").stdout
tok = ""
for l in open(ENV + ".pre-telegram-move"):
    m = re.match(r"^TELEGRAM_BOT_TOKEN=(.*)$", l.strip())
    if m:
        tok = m.group(1).strip().strip("\"'")
log = log.replace(tok, "<BOT_TOKEN>") if tok else log
hits = [l for l in log.splitlines() if re.search(r"[Tt]elegram", l)]
print("--- evonic log lines mentioning telegram (last 2 min):")
print("\n".join(h[-170:] for h in hits[-8:]) or "(none)")
conflict = [l for l in hits if re.search(r"conflict|terminated by other", l, re.I)]
print("token conflict logged:", bool(conflict), "| polling logged:", any("polling" in l for l in hits))
print("\nROLLBACK: cp -p %s %s && systemctl restart hermes-gateway   # then disable the Evonic channel + restart evonic" % (BAK, ENV))
