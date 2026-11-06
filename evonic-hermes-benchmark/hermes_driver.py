"""Run one benchmark task through Hermes Agent, sandboxed, on the host `home`.

Isolation (all enforced by systemd, per run):
  - runs as the unprivileged user `nobody`; fixture dir is chowned to nobody for the run, back to the caller afterwards
  - ProtectSystem=strict, ProtectHome=yes, PrivateTmp=yes, NoNewPrivileges=yes; only the task workdir and a state dir are writable
  - fresh HERMES_HOME per run (no memory, sessions or skills carried over) and --safe-mode: no user config, no AGENTS.md/memory,
    no plugins, no MCP servers (production Hermes has TrueNAS/Proxmox/MikroTik/Cloudflare MCP tools; none are reachable here)
  - the provider API key is handed over as a root-only systemd credential holding ONLY that key, never the whole .env

Tools enabled: terminal + file only, to match Evonic's bash + file tools.
Same model as production Hermes: deepseek-v4.1-flash via opencode-go.

Interface:  run_task(prompt, workdir, timeout_s) -> dict   (same keys as evonic_driver.run_task)
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
import uuid
from pathlib import Path

HERMES_BIN = "/opt/hermes-venv/bin/hermes"
MODEL = os.environ.get("BENCH_MODEL", "deepseek-v4.1-flash")
PROVIDER = os.environ.get("BENCH_PROVIDER", "opencode-go")
KEY_ENV = "OPENCODE_GO_API_KEY"
CRED_FILE = "/run/bench/opencode_key"
MAX_TURNS = int(os.environ.get("BENCH_MAX_TURNS", "40"))
TOOLSETS = os.environ.get("HERMES_BENCH_TOOLSETS", "terminal,file")
RUN_USER = "nobody"
RUN_GROUP = "nogroup"
FIXTURE_OWNER = f"{RUN_USER}:{RUN_GROUP}"


def _sudo(*args, **kw):
    return subprocess.run(["sudo", "-n", *args], capture_output=True, text=True, **kw)


def prepare_key() -> None:
    """Create /run/bench/opencode_key (root:root 0600, tmpfs) containing only the provider key. Prints nothing."""
    code = (
        "import os,re;v=None\n"
        "for l in open('/root/.hermes/.env'):\n"
        "    m=re.match(r'^%s=(.*)$'%'" + KEY_ENV + "',l.strip())\n"
        "    if m: v=m.group(1).strip().strip('\"').strip(\"'\")\n"
        "assert v,'key not found'\n"
        "os.makedirs('/run/bench',mode=0o700,exist_ok=True)\n"
        "fd=os.open('" + CRED_FILE + "',os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600);os.write(fd,v.encode());os.close(fd)\n"
    )
    r = _sudo("python3", "-c", code)
    if r.returncode:
        raise RuntimeError("could not prepare credential: " + r.stderr[-200:])


def cleanup_key() -> None:
    _sudo("rm", "-rf", "/run/bench")


def own_fixture(workdir: str) -> None:
    _sudo("chown", "-R", FIXTURE_OWNER, workdir)


def release_fixture(workdir: str) -> None:
    _sudo("chown", "-R", f"{os.getuid()}:{os.getgid()}", workdir)


def _parse_stream(text: str) -> dict:
    """Best-effort parse of --format stream-json (JSONL). Returns counts; unknown schema degrades to zeros."""
    tool_names, final, turns = [], "", 0
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        t = str(ev.get("type") or ev.get("event") or "")
        if "tool" in t and ("call" in t or "start" in t or "use" in t):
            tool_names.append(str(ev.get("name") or ev.get("tool") or ev.get("tool_name") or "?"))
        if t in ("assistant", "message", "final", "result", "assistant_message"):
            c = ev.get("content") or ev.get("text") or ev.get("message") or ev.get("result")
            if isinstance(c, str) and c.strip():
                final = c
        if t in ("turn", "api_call", "llm_request"):
            turns += 1
    return {"tool_names": tool_names, "final": final, "turns": turns}


def run_task(prompt: str, workdir: str, timeout_s: int = 600) -> dict:
    run_id = uuid.uuid4().hex[:10]
    workdir = str(Path(workdir).resolve())
    prompt_file = f"{workdir}/../.prompt-{run_id}.txt"
    Path(prompt_file).write_text(prompt)
    os.chmod(prompt_file, 0o644)
    state = f"hermes-bench/{run_id}"
    # The wrapper runs inside the sandbox as nobody.
    wrapper = (
        f"set -e; export {KEY_ENV}=\"$(cat \"$CREDENTIALS_DIRECTORY/key\")\"; "
        f"export HERMES_HOME=\"/var/lib/hermes-bench/{run_id}/home\"; mkdir -p \"$HERMES_HOME\"; "
        f"exec {HERMES_BIN} --usage-file /var/lib/hermes-bench/{run_id}/usage.json chat --safe-mode --provider {PROVIDER} -m {MODEL} -t {TOOLSETS} --yolo "
        f"--max-turns {MAX_TURNS} --in {shlex.quote(workdir)} "
        f"--query-file {shlex.quote(prompt_file)} --oneshot -Q --format stream-json"
    )
    unit = f"hbench-{run_id}"
    cmd = [
        "sudo", "-n", "systemd-run", "--quiet", "--wait", "--collect", "--pipe", f"--unit={unit}",
        "-p", f"User={RUN_USER}", "-p", f"Group={RUN_GROUP}",
        "-p", "ProtectSystem=strict", "-p", "ProtectHome=yes", "-p", "PrivateTmp=yes", "-p", "NoNewPrivileges=yes",
        "-p", "StateDirectory=hermes-bench", "-p", f"ReadWritePaths={workdir}",
        "-p", f"LoadCredential=key:{CRED_FILE}", "-p", f"WorkingDirectory={workdir}",
        "-p", "Environment=PATH=/run/current-system/sw/bin", "-p", f"Environment=HOME=/var/lib/hermes-bench/{run_id}",
        "-p", f"RuntimeMaxSec={timeout_s + 30}", "-p", "MemoryMax=2G", "-p", "TasksMax=256",
        "/bin/sh", "-c", wrapper,
    ]
    own_fixture(workdir)
    t0 = time.time()
    error = None
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s + 60)
        out, err, rc = p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired as e:
        out, err, rc = (e.stdout or ""), (e.stderr or ""), 124
        error = "driver timeout"
        _sudo("systemctl", "stop", unit + ".service")
    wall = time.time() - t0
    release_fixture(workdir)

    # read + remove the per-run state
    usage = {}
    u = _sudo("cat", f"/var/lib/hermes-bench/{run_id}/usage.json")
    if u.returncode == 0 and u.stdout.strip():
        try:
            usage = json.loads(u.stdout)
        except Exception:
            usage = {"raw": u.stdout[:300]}
    _sudo("rm", "-rf", f"/var/lib/hermes-bench/{run_id}")
    try:
        os.unlink(prompt_file)
    except OSError:
        pass

    parsed = _parse_stream(out)
    if rc not in (0,) and not error:
        error = f"hermes exit {rc}: {(err or out)[-300:]}"

    def num(*keys):
        for k in keys:
            v = usage.get(k)
            if isinstance(v, (int, float)):
                return int(v)
        return None

    return {
        "final_text": parsed["final"] or out[-2000:],
        "wall_seconds": round(wall, 2),
        "tool_calls": len(parsed["tool_names"]),
        "tool_names": parsed["tool_names"],
        "turns": parsed["turns"] or num("api_calls", "requests", "turns"),
        "tokens_in": num("input_tokens", "prompt_tokens", "tokens_in"),
        "tokens_out": num("output_tokens", "completion_tokens", "tokens_out"),
        "usage_raw": usage,
        "error": error,
        "raw_stream_tail": out[-1500:],
    }
