#!/bin/sh
# Run as root on home. Imports /srv/migrate/portable/*.json into Evonic as the evonic user, then syncs each KB index.
set -u
SRC=/srv/migrate/portable
DST=/var/lib/evonic/import
install -d -m 0700 -o evonic -g evonic "$DST"
cp "$SRC"/hermes_*.json "$DST"/ && chown evonic:evonic "$DST"/hermes_*.json && chmod 600 "$DST"/hermes_*.json
cd /opt/evonic-source || exit 1
EV="runuser -u evonic -- env HOME=/var/lib/evonic"
for f in "$DST"/hermes_*.json; do
  id=$(basename "$f" .json)
  echo "== import $id"
  $EV ./evonic agent import "$f" --id "$id" --yes </dev/null 2>&1 | grep -E "imported|Error|Warning" | head -3
done
echo; echo "== sync KB indexes"
for f in "$DST"/hermes_*.json; do
  id=$(basename "$f" .json)
  $EV /opt/evonic-venv/bin/python - "$id" <<'PY' 2>&1 | tail -1
import sys
sys.path.insert(0, ".")
from backend.agent_runtime.evomem_client import sync, is_available
aid = sys.argv[1]
print(aid, "evomem available:", is_available(), "| sync ->", sync(aid))
PY
done
echo; $EV ./evonic agent list </dev/null 2>&1 | grep -E "hermes_|ID " | head -20
