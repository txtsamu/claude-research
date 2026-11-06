#!/bin/sh
# Step B (root on home): pause the 8 Hermes script jobs that now run as systemd timers. Reversible: `hermes cron resume <id>`.
H=/opt/hermes-venv/bin/hermes
cp -p /root/.hermes/cron/jobs.json /root/.hermes/cron/jobs.json.pre-timers-2026-11-06
for id in 8fdeb489eb44 e023bde2da85 19a4de80a8f4 3c8b5d4a784a 2cc0bc49ffec 2e735e03ced2 8b1593485678 96694a24d519; do
  printf '%s: ' $id; $H cron pause $id 2>&1 | tail -1 | cut -c1-100
done
echo; echo "== states after pausing:"
python3 - <<'PY'
import json
d = json.load(open("/root/.hermes/cron/jobs.json")); jobs = d["jobs"] if isinstance(d, dict) else d
for j in jobs:
    print(f"{j['id'][:12]} {j['name'][:34]:34s} enabled={j.get('enabled')} state={j.get('state') or j.get('status') or '-'}")
PY
