#!/usr/bin/env python3
"""Run as root on home. Stages the Telegram channel on agent hermes_default, DISABLED (nothing polls yet).

Reads TELEGRAM_BOT_TOKEN / TELEGRAM_ALLOWED_USERS from /root/.hermes/.env, passes them to Evonic's DB layer through the
environment of the evonic user (never argv, never printed). Also calls Telegram getMe / getWebhookInfo, which are read-only
and do not conflict with the poller that Hermes currently runs.
"""
import json, os, re, subprocess, sys, urllib.request

env_file = "/root/.hermes/.env"
vals = {}
for line in open(env_file):
    m = re.match(r"^(TELEGRAM_BOT_TOKEN|TELEGRAM_ALLOWED_USERS)=(.*)$", line.strip())
    if m:
        vals[m.group(1)] = m.group(2).strip().strip("\"'")
token, allowed = vals.get("TELEGRAM_BOT_TOKEN", ""), [x.strip() for x in vals.get("TELEGRAM_ALLOWED_USERS", "").split(",") if x.strip()]
assert token and allowed, "token or allowed users missing"

def tg(method):
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}", timeout=20) as r:
        return json.load(r)["result"]

me = tg("getMe")
wh = tg("getWebhookInfo")
print("bot:", {k: me.get(k) for k in ("id", "username", "first_name", "can_join_groups")})
print("webhook url set:", bool(wh.get("url")), "| pending updates:", wh.get("pending_update_count"), "| last error:", wh.get("last_error_message"))

# Display names Hermes already knows for these chats (jobs.json origins), so Evonic does not ask users for their name.
names = {}
try:
    jobs = json.load(open("/root/.hermes/cron/jobs.json"))
    jobs = jobs["jobs"] if isinstance(jobs, dict) else jobs
    for j in jobs:
        o = j.get("origin") or {}
        if o.get("chat_id") and o.get("chat_name"):
            names[str(o["chat_id"])] = o["chat_name"]
except Exception:
    pass

code = r'''
import json, os, sys
sys.path.insert(0, ".")
from models.db import db
tok, allowed, names = os.environ["TG_TOKEN"], json.loads(os.environ["TG_ALLOWED"]), json.loads(os.environ["TG_NAMES"])
agent = "hermes_default"
assert db.get_agent(agent), "agent missing"
existing = [c for c in db.get_channels(agent) if c.get("name") == "telegram"]
if existing:
    print("channel already exists:", existing[0]["id"], "enabled:", existing[0].get("enabled"))
    sys.exit(0)
cfg = {"mode": "restricted", "bot_token": tok, "allowed_users": allowed,
       "user_names": {u: names[u] for u in allowed if u in names}}
cid = db.create_channel({"agent_id": agent, "type": "telegram", "name": "telegram", "config": cfg, "enabled": False})
ch = db.get_channel(cid)
c = ch["config"] if isinstance(ch["config"], dict) else json.loads(ch["config"])
print("staged channel", cid, "| enabled:", ch.get("enabled"), "| mode:", c.get("mode"), "| allowed:", len(c.get("allowed_users", [])), "| named:", len(c.get("user_names", {})), "| token stored:", bool(c.get("bot_token")))
'''
e = dict(os.environ, HOME="/var/lib/evonic", TG_TOKEN=token, TG_ALLOWED=json.dumps(allowed), TG_NAMES=json.dumps(names))
r = subprocess.run(["runuser", "-u", "evonic", "--", "/opt/evonic-venv/bin/python", "-c", code], cwd="/opt/evonic-source", env=e,
                   capture_output=True, text=True, stdin=subprocess.DEVNULL)
out = (r.stdout + r.stderr).replace(token, "<BOT_TOKEN>")
print("\n".join(l for l in out.splitlines() if "[INFO]" not in l)[-900:])
sys.exit(r.returncode)
