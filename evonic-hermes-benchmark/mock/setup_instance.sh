#!/usr/bin/env bash
# Reproducible, non-interactive setup of an ISOLATED Evonic instance for benchmarking.
#
#   ./setup_instance.sh            # full setup (idempotent: re-running re-syncs config only)
#   EVONIC_SRC=/path/to/clone ./setup_instance.sh
#
# Layout (all under this script's directory):
#   venv/            python venv shared by the instance and the driver
#   evonic-run/      COPY of the read-only reference clone (state lives here: DB, agents/, .env, logs/)
#   home/            fake $HOME used when the server runs (nothing touches the real ~/.config)
#   scratch/         default agent workspace (the driver switches it per task)
#
# Nothing here uses a real LLM key. The only network use is `pip install`.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${EVONIC_SRC:-$DIR/../evonic}"
RUN="$DIR/evonic-run"
PORT="${EVONIC_PORT:-18080}"
MOCK_PORT="${MOCK_PORT:-18081}"
ADMIN_PASSWORD="${EVONIC_ADMIN_PASSWORD:-<THROWAWAY_LOCAL_PASSWORD>}"   # throwaway, local only
AGENT_ID="${EVONIC_AGENT_ID:-bench}"
MODEL_ID="${EVONIC_MODEL_ID:-mock-model}"
PY="${PYTHON:-python3}"

mkdir -p "$DIR/home" "$DIR/scratch" "$DIR/results"

echo "[1/6] copy reference clone -> $RUN (excluding .git, state dirs)"
rsync -a --delete \
  --exclude '.git' --exclude '/.env' --exclude '/venv' --exclude '/.venv' \
  --exclude '/shared' --exclude '/agents' --exclude '/logs' --exclude '/run' --exclude '/data' \
  "$SRC"/ "$RUN"/

echo "[2/6] venv + requirements"
[ -x "$DIR/venv/bin/python" ] || "$PY" -m venv "$DIR/venv"
"$DIR/venv/bin/pip" install -q --upgrade pip
"$DIR/venv/bin/pip" install -q -r "$RUN/requirements.txt"
ln -sfn "$DIR/venv" "$RUN/venv"      # ./evonic wrapper looks for $SCRIPT_DIR/venv

# Everything below runs with HOME redirected so no state can land in the real home.
export HOME="$DIR/home"
cd "$RUN"
VPY="$DIR/venv/bin/python"

echo "[3/6] .env (instance config)"
touch .env && chmod 600 .env
"$VPY" -I - "$RUN" "$PORT" "$ADMIN_PASSWORD" <<'PYEOF'
import sys
run, port, pw = sys.argv[1:4]
sys.path.insert(0, run)
from werkzeug.security import generate_password_hash
from backend.setup import _update_env_var     # same helper `./evonic pass` uses
env = run + "/.env"
settings = {
    # --- network / auth ---
    "HOST": "127.0.0.1",
    "PORT": port,
    "DEBUG": "0",
    # session cookie has the Secure flag by default -> requests would not send it over http://
    "FORCE_INSECURE_COOKIES": "1",
    # same hash method `./evonic pass` writes (pbkdf2:sha256)
    "ADMIN_PASSWORD_HASH": generate_password_hash(pw, method="pbkdf2:sha256"),
    # --- keep extra LLM calls / background work off ---
    "EVONIC_MEMORY_ENGINE": "fts5",        # no evomem binary / embeddings
    "EVOMEM_KB_ORGANIZER": "off",          # no KB-filing LLM calls
    "ACTIVE_CONTEXT_MODE": "off",          # no context-projection side effects
    "TWO_PASS_ENABLED": "0",
    # --- measurement ---
    "EVONIC_SESSION_ARCHIVE": "1",         # makes agents/<id>/llm_traces/<session>.jsonl (per-call usage)
    "LLM_API_LOG_ENABLED": "0",
    "LLM_TIMEOUT": "120",
    "EVONIC_TIMEZONE": "UTC",
}
for k, v in settings.items():
    _update_env_var(env, k, v)
print("  wrote", len(settings), "keys to .env")
PYEOF

echo "[4/6] ./evonic setup --non-interactive  (creates super agent + placeholder openrouter model, no key)"
if [ -f shared/db/evonic.db ] && "$VPY" -I -c "
import sys; sys.path.insert(0,'.')
from models.db import db; sys.exit(0 if db.has_super_agent() else 1)"; then
  echo "  already set up"
else
  ./evonic setup --non-interactive </dev/null
fi

echo "[5/6] mock model + benchmark agent via ./evonic CLI"
./evonic model add "$MODEL_ID" --name "Mock LLM" --provider openai --api-key mock \
    --base-url "http://127.0.0.1:$MOCK_PORT/v1" </dev/null || echo "  (model exists)"
./evonic agent add "$AGENT_ID" --name "Bench Agent" --description "Benchmark agent" \
    --model "$MODEL_ID" </dev/null || echo "  (agent exists)"

echo "[6/6] benchmark agent + global settings (CLI cannot set these -> models.db API)"
"$VPY" -I - "$RUN" "$AGENT_ID" "$MODEL_ID" "$DIR/scratch" <<'PYEOF'
import sys
run, agent_id, model_id, scratch = sys.argv[1:5]
sys.path.insert(0, run)
import os; os.chdir(run)
from models.db import db

# Make the mock the global default model too (so helper calls never reach another provider).
with db._connect() as c:
    c.execute("UPDATE llm_models SET is_default = CASE WHEN id = ? THEN 1 ELSE 0 END", (model_id,))
    c.commit()

agent = {
    "workspace": scratch,            # file tools + bash cwd (the driver re-points this per task)
    "sandbox_enabled": 0,            # LocalBackend: host subprocess, no Docker
    "model_id": model_id,
    "safety_checker_enabled": 0,     # skip the HMADS/Decim safety pipeline (may do extra work/LLM)
    "enable_agent_state": 0,         # no plan/execute state machine
    "always_execute": 1,
    "message_buffer_seconds": 0,     # no 2s debounce delay before the turn starts
    "outbound_buffer_seconds": 0,
    "send_intermediate_responses": 0,
    "inject_datetime": 0,
    "inject_agent_id": 0,
    "message_wrapper_enabled": 0,    # do not wrap user text
    "summarize_threshold": 1000,     # effectively never summarize (summarizer = extra LLM call)
    "summarize_tail": 5,
    "enable_cmp": 0,                 # context-management plugin off
    "tool_compression_enabled": 0,   # do not rewrite tool output
    "disable_turn_prefetch": 1,
    "disable_parallel_tool_execution": 1,
    "builtin_tools_enabled": 0,      # no built-in agent-messaging/ask-user/etc. tools
    "agent_messaging_enabled": 0,
    "ask_user_enabled": 0,
    "artifacts_enabled": 0,
    "vision_enabled": 0,
    "attachments_enabled": 0,
    "bash_exec_enabled": 0,
    "memory_engine": "fts5",
    "kb_organizer_mode": "off",
    "help_enabled": 0,
}
ok = db.update_agent(agent_id, agent)
print("  agent updated:", ok)
db.set_agent_tools(agent_id, ["bash", "read_file", "write_file", "str_replace", "patch"])
db.set_agent_skills(agent_id, [])

# global (app_settings) switches
for k, v in {
    "task_classifier_enabled": "0",   # LLM task classifier off
    "two_pass_enabled": "0",
    "max_concurrent_llm_global": "1",
    "long_running_guard_enabled": "0",
    "root_fs_scan_guard_enabled": "0",
}.items():
    db.set_setting(k, v)
print("  global settings set")
a = db.get_agent(agent_id)
print("  agent:", {k: a[k] for k in ("id", "workspace", "sandbox_enabled", "model_id", "enable_agent_state", "kb_organizer_mode", "memory_engine")})
print("  tools:", db.get_agent_tools(agent_id))
PYEOF

echo "done. Start with: $DIR/start_instance.sh"
