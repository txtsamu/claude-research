cd /opt/evonic-source
for id in default audio critic dev device diskos finance net ops research uiux; do
  runuser -u evonic -- env HOME=/var/lib/evonic EVOMEM_BINARY=/run/current-system/sw/bin/evomem EVONIC_SKIP_EVOMEM_UPDATE_CHECK=1 /opt/evonic-venv/bin/python - hermes_$id <<'PY' 2>&1 | grep -E "^hermes_|Traceback|Error" | head -3
import sys
sys.path.insert(0, ".")
from backend.agent_runtime.evomem_client import sync, init_evomem, is_available
aid = sys.argv[1]
print(aid, "available:", is_available(), "| sync ->", sync(aid))
PY
done
