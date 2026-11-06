#!/usr/bin/env python3
"""Step A (root on home, AFTER the timers are deployed): fill the two root-only files the scheduled-job timers read.

  /var/lib/scheduled-jobs/telegram-bot-token   <- TELEGRAM_BOT_TOKEN from /root/.hermes/.env
  /var/lib/scheduled-jobs/chat-ids             <- main=<TELEGRAM_HOME_CHANNEL>, other=<origin chat of the camofox-auto-update job>

Nothing is printed except lengths/aliases. Both files end up root:root 0600.
"""
import json, os, re, sys

tok = home = None
for l in open("/root/.hermes/.env"):
    m = re.match(r"^(TELEGRAM_BOT_TOKEN|TELEGRAM_HOME_CHANNEL)=(.*)$", l.strip())
    if m:
        v = m.group(2).strip().strip("\"'")
        if m.group(1) == "TELEGRAM_BOT_TOKEN":
            tok = v
        else:
            home = v
other = None
jobs = json.load(open("/root/.hermes/cron/jobs.json"))
for j in (jobs["jobs"] if isinstance(jobs, dict) else jobs):
    if j["id"] == "3c8b5d4a784a":   # camofox-auto-update: delivers to a different chat than the rest
        other = str((j.get("origin") or {}).get("chat_id") or "")
assert tok and re.fullmatch(r"\d+:[A-Za-z0-9_-]{30,}", tok), "bot token missing or malformed"
assert home and re.fullmatch(r"-?\d+", home), "home channel missing"
assert other and re.fullmatch(r"-?\d+", other), "other chat missing"

d = "/var/lib/scheduled-jobs"
os.makedirs(d, mode=0o700, exist_ok=True)

def put(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chown(path, 0, 0)
    os.chmod(path, 0o600)

put(f"{d}/telegram-bot-token", tok)
put(f"{d}/chat-ids", f"main={home}\nother={other}\n")
for p in ("telegram-bot-token", "chat-ids"):
    st = os.stat(f"{d}/{p}")
    print(f"{p}: {st.st_size} bytes, mode {oct(st.st_mode & 0o777)}, owner {st.st_uid}:{st.st_gid}")
print("aliases:", [l.split("=")[0] for l in open(f"{d}/chat-ids").read().split()])
