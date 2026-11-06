#!/usr/bin/env python3
"""Roll the Telegram bot and the script cron jobs back from Evonic/systemd timers to Hermes. Run as root on home.

Order matters (one poller per bot token, and no double cron runs):
  1. Evonic: disable the Telegram channel in its DB, restart evonic (stops the poller), confirm it no longer polls
  2. Hermes .env: put the TELEGRAM_BOT_TOKEN line back (value from .env.pre-telegram-move; nothing else in the file changes)
  3. stop the 8 scheduled-job-*.timer units
  4. restart hermes-gateway, confirm Telegram is connected
  5. hermes cron resume x8, confirm
Never prints the token. Evonic itself, its agents and KBs are left in place.
"""
import json, os, re, subprocess, sys, time

ENV = "/root/.hermes/.env"
BAK = ENV + ".pre-telegram-move"
JOBS = ["8fdeb489eb44", "e023bde2da85", "19a4de80a8f4", "3c8b5d4a784a", "2cc0bc49ffec", "2e735e03ced2", "8b1593485678", "96694a24d519"]
H = "/opt/hermes-venv/bin/hermes"


def sh(*a, **k):
    return subprocess.run(a, capture_output=True, text=True, **k)


def tg_state():
    try:
        return json.load(open("/root/.hermes/gateway_state.json"))["platforms"].get("telegram", {}).get("state", "absent")
    except Exception as e:
        return f"unreadable ({e})"


# 1. Evonic side
code = r'''
import sys
sys.path.insert(0, ".")
from models.db import db
ch = [c for c in db.get_channels("hermes_default") if c.get("name") == "telegram"]
assert ch, "channel missing"
db.update_channel(ch[0]["id"], {"enabled": 0})
print("evonic telegram channel enabled ->", db.get_channel(ch[0]["id"]).get("enabled"))
'''
r = subprocess.run(["runuser", "-u", "evonic", "--", "/opt/evonic-venv/bin/python", "-c", code], cwd="/opt/evonic-source",
                   env=dict(os.environ, HOME="/var/lib/evonic"), capture_output=True, text=True, stdin=subprocess.DEVNULL)
print("\n".join(l for l in (r.stdout + r.stderr).splitlines() if "[INFO]" not in l)[-300:])
assert r.returncode == 0, "could not disable the Evonic channel; stopping before touching Hermes"
t0 = time.strftime("%H:%M:%S")
print("restarting evonic (stops the poller) ...", sh("systemctl", "restart", "evonic").returncode)
for _ in range(60):
    if sh("curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://127.0.0.1:8080/api/health").stdout.strip() == "200":
        break
    time.sleep(1)
time.sleep(6)
log = sh("journalctl", "-u", "evonic", "--since", t0, "--no-pager").stdout
polling = [l for l in log.splitlines() if "connected and polling" in l]
print("evonic still polling Telegram after restart:", bool(polling))
assert not polling, "Evonic is still polling; aborting before Hermes takes the token"

# 2. Hermes .env: restore the token line
tok_line = next((l for l in open(BAK).read().split("\n") if l.startswith("TELEGRAM_BOT_TOKEN=")), None)
assert tok_line and len(tok_line) > 30, "no token line in the backup"
lines = open(ENV).read().split("\n")
out, done = [], 0
for l in lines:
    if l.startswith("# moved to Evonic 2026-11-06"):
        continue
    if l.startswith("#DISABLED_TELEGRAM_BOT_TOKEN="):
        out.append(tok_line); done += 1
    else:
        out.append(l)
assert done == 1, f"expected one disabled token line, found {done}"
st = os.stat(ENV)
tmp = ENV + ".tmp-rollback"
fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, st.st_mode & 0o777)
with os.fdopen(fd, "w") as f:
    f.write("\n".join(out))
os.chown(tmp, st.st_uid, st.st_gid)
os.replace(tmp, ENV)
print("hermes .env: token line restored (mode %s)" % oct(os.stat(ENV).st_mode & 0o777))

# 3. stop the timers (before Hermes resumes the same jobs)
timers = sh("sh", "-c", "systemctl list-units 'scheduled-job-*.timer' --no-legend --plain | awk '{print $1}'").stdout.split()
for t in timers:
    sh("systemctl", "stop", t)
active = sh("sh", "-c", "systemctl list-units 'scheduled-job-*.timer' --state=active --no-legend --plain | wc -l").stdout.strip()
print(f"timers stopped: {len(timers)} | still active: {active}")

# 4. restart Hermes gateway
t1 = time.time()
print("restarting hermes-gateway ...", sh("systemctl", "restart", "hermes-gateway").returncode)
for _ in range(90):
    if tg_state() == "connected":
        break
    time.sleep(2)
print(f"hermes telegram state: {tg_state()} (after {time.time()-t1:.0f}s) | gateway: {sh('systemctl', 'is-active', 'hermes-gateway').stdout.strip()}")

# 5. resume the cron jobs
for j in JOBS:
    print(" ", j, sh(H, "cron", "resume", j).stdout.strip().splitlines()[-1][:80] if True else "")
d = json.load(open("/root/.hermes/cron/jobs.json")); jobs = d["jobs"] if isinstance(d, dict) else d
print("hermes cron enabled:", sum(1 for j in jobs if j.get("enabled")), "of", len(jobs))
print("\nDone. Evonic is still running (Telegram off). Re-migrate later with golive_c_telegram_cutover.py + golive_b_pause_hermes_jobs.sh.")
