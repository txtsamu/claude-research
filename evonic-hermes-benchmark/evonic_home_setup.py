"""One-time lean-benchmark configuration of Evonic on `home`. Run AS THE evonic USER with cwd=/opt/evonic-source:
   runuser -u evonic -- env HOME=/var/lib/evonic BENCH_KEY=... ADMIN_PW=... /opt/evonic-venv/bin/python evonic_home_setup.py
The API key and admin password come from the environment (never argv). Settings mirror the validated mock run
(driver-evonic/setup_instance.sh, step 6): all optional LLM-calling features off so only the core agent loop is measured."""
import os, sys
sys.path.insert(0, os.getcwd())
from werkzeug.security import generate_password_hash
from backend.setup import _update_env_var
from models.db import db

MODEL_ID = os.environ.get("BENCH_MODEL_ID", "deepseek-v4.1-flash")
BASE_URL = os.environ.get("BENCH_BASE_URL", "https://opencode.ai/zen/go/v1")
AGENT_ID = "bench"
WORK = "/srv/bench/work"
key, pw = os.environ["BENCH_KEY"], os.environ["ADMIN_PW"]

env = os.path.join(os.getcwd(), ".env")
for k, v in {
    "ADMIN_PASSWORD_HASH": generate_password_hash(pw, method="pbkdf2:sha256"),
    "EVONIC_MEMORY_ENGINE": "fts5", "EVOMEM_KB_ORGANIZER": "off", "ACTIVE_CONTEXT_MODE": "off", "TWO_PASS_ENABLED": "0",
    "EVONIC_SESSION_ARCHIVE": "1", "LLM_API_LOG_ENABLED": "0", "LLM_TIMEOUT": "120", "EVONIC_TIMEZONE": "UTC",
}.items():
    _update_env_var(env, k, v)

if not db.get_model_by_id(MODEL_ID):
    db.create_model({"id": MODEL_ID, "name": "deepseek-v4.1-flash (opencode-go)", "type": "chat", "provider": "openai",
                     "model_name": MODEL_ID, "api_key": key, "base_url": BASE_URL, "is_default": 0})
with db._connect() as c:
    c.execute("UPDATE llm_models SET is_default = CASE WHEN id = ? THEN 1 ELSE 0 END", (MODEL_ID,)); c.commit()

if not db.get_agent(AGENT_ID):
    sys.exit("agent 'bench' missing: run `./evonic agent add bench --name 'Bench Agent' --model <model>` first")
db.update_agent(AGENT_ID, {
    "workspace": WORK, "sandbox_enabled": 0, "model_id": MODEL_ID, "safety_checker_enabled": 0, "enable_agent_state": 0,
    "always_execute": 1, "message_buffer_seconds": 0, "outbound_buffer_seconds": 0, "send_intermediate_responses": 0,
    "inject_datetime": 0, "inject_agent_id": 0, "message_wrapper_enabled": 0, "summarize_threshold": 1000, "summarize_tail": 5,
    "enable_cmp": 0, "tool_compression_enabled": 0, "disable_turn_prefetch": 1, "disable_parallel_tool_execution": 1,
    "builtin_tools_enabled": 0, "agent_messaging_enabled": 0, "ask_user_enabled": 0, "artifacts_enabled": 0,
    "vision_enabled": 0, "attachments_enabled": 0, "bash_exec_enabled": 0, "memory_engine": "fts5", "kb_organizer_mode": "off",
    "help_enabled": 0,
})
db.set_agent_tools(AGENT_ID, ["bash", "read_file", "write_file", "str_replace", "patch"])
db.set_agent_skills(AGENT_ID, [])
for k, v in {"task_classifier_enabled": "0", "two_pass_enabled": "0", "max_concurrent_llm_global": "1",
             "long_running_guard_enabled": "0", "root_fs_scan_guard_enabled": "0"}.items():
    db.set_setting(k, v)
a = db.get_agent(AGENT_ID)
print("configured:", {k: a[k] for k in ("id", "workspace", "sandbox_enabled", "model_id", "kb_organizer_mode", "memory_engine")}, db.get_agent_tools(AGENT_ID))
