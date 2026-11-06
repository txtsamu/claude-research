#!/usr/bin/env python3
"""Run as root on home. Stages the 3 Hermes AGENT cron jobs as DISABLED Evonic schedules (session_prompt on a specialist).

They are staged disabled on purpose: they relied on things an Evonic agent does not have (root ssh keys to Proxmox/TrueNAS,
web + camofox tools, write access to /root/hermes-research, a pre-run collector script). Enable one only after deciding how to
provide that. Prompts are copied verbatim from /root/.hermes/cron/jobs.json with a short preface.
"""
import json, os, subprocess, sys

MAP = {  # hermes job id -> (evonic agent, cron kwargs for APScheduler CronTrigger, preface)
    "63555ae355cb": ("hermes_default", {"minute": 0, "hour": 1},
                     "[Migrated from Hermes cron 'Daily Claude session report'. Hermes first ran a collector script and handed you its "
                     "output; Evonic cannot run that script for you, so gather the last 24h of Claude Code sessions yourself if you can, "
                     "otherwise say what is missing.]\n\n"),
    "29925319d926": ("hermes_ops", {"minute": 0, "hour": 4},
                     "[Migrated from Hermes cron 'proxmox-backup-autofix'. Hermes only ran this when a monitor script detected a change, "
                     "and as root with ssh keys to Proxmox and TrueNAS. As an Evonic agent you have no such keys: diagnose what you can "
                     "and report what you could not do.]\n\n"),
    "964315af6df8": ("hermes_research", {"minute": 0, "hour": 4},
                     "[Migrated from Hermes cron 'Daily Hermes efficiency research'. It assumed web, camofox and write access to "
                     "/root/hermes-research, which an Evonic agent lacks; do what is possible with bash and report the gaps.]\n\n"),
}

jobs = json.load(open("/root/.hermes/cron/jobs.json"))
jobs = jobs["jobs"] if isinstance(jobs, dict) else jobs
spec = []
for j in jobs:
    if j["id"] in MAP:
        agent, cron, pre = MAP[j["id"]]
        spec.append({"hid": j["id"], "name": "hermes: " + j["name"], "agent": agent, "cron": cron,
                     "message": pre + (j.get("prompt") or ""), "chat": str((j.get("origin") or {}).get("chat_id") or "")})
assert len(spec) == 3, f"expected 3 jobs, found {len(spec)}"

code = r'''
import json, os, sys, uuid
sys.path.insert(0, ".")
from models.db import db
spec = json.loads(os.environ["SPEC"])
tg = [c for c in db.get_channels("hermes_default") if c.get("name") == "telegram"]
chan = tg[0]["id"] if tg else None
have = {s["name"] for s in db.list_schedules()} if hasattr(db, "list_schedules") else set()
for s in spec:
    if s["name"] in have:
        print("exists:", s["name"]); continue
    sid = str(uuid.uuid4())[:8]
    db.create_schedule(schedule_id=sid, name=s["name"], owner_type="user", owner_id="admin",
                       trigger_type="cron", trigger_config=s["cron"], action_type="session_prompt",
                       action_config={"agent_id": s["agent"], "message": s["message"], "channel_id": chan, "external_user_id": s["chat"]},
                       max_runs=None, metadata={"migrated_from": "hermes cron " + s["hid"], "staged_disabled": True})
    db.update_schedule(sid, enabled=0)
    print("staged (disabled):", sid, s["name"], "->", s["agent"], s["cron"])
'''
e = dict(os.environ, HOME="/var/lib/evonic", SPEC=json.dumps(spec))
r = subprocess.run(["runuser", "-u", "evonic", "--", "/opt/evonic-venv/bin/python", "-c", code], cwd="/opt/evonic-source", env=e,
                   capture_output=True, text=True, stdin=subprocess.DEVNULL)
print("\n".join(l for l in (r.stdout + r.stderr).splitlines() if "[INFO]" not in l)[-1200:])
sys.exit(r.returncode)
