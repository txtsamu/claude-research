"""Evonic driver for the benchmark runner on `home` (same run_task interface as hermes_driver).

Evonic runs as the `evonic` system user (systemd-sandboxed). The fixture dir is chowned to that user for the run and back
afterwards, exactly like hermes_driver does for `nobody`, so file-permission semantics are the same for both agents.
Needs the Evonic venv interpreter (requests): /opt/evonic-venv/bin/python bench.py ...
"""
import os, subprocess

os.environ.setdefault("EVONIC_URL", "http://127.0.0.1:8080")
os.environ.setdefault("EVONIC_ROOT", "/var/lib/evonic")      # agents/ is a symlink target of the checkout
os.environ.setdefault("EVONIC_AGENT_ID", "bench")
os.environ.setdefault("EVONIC_MOCK_URL", "")                   # no mock cross-check against the real provider
_pw = "/srv/bench/evonic_password"
if "EVONIC_PASSWORD" not in os.environ and os.path.exists(_pw):
    os.environ["EVONIC_PASSWORD"] = open(_pw).read().strip()

import evonic_driver as ed   # noqa: E402  (reads env at import)

OWNER = "evonic:evonic"


def _sudo(*a):
    return subprocess.run(["sudo", "-n", *a], capture_output=True, text=True)


def run_task(prompt, workdir, timeout_s=600):
    _sudo("chown", "-R", OWNER, workdir)
    try:
        r = ed.run_task(prompt, workdir, timeout_s)
    finally:
        _sudo("chown", "-R", f"{os.getuid()}:{os.getgid()}", workdir)
    tc = r.get("tool_calls")
    names = tc.get("names", []) if isinstance(tc, dict) else []
    r["tool_calls"] = tc.get("count", len(names)) if isinstance(tc, dict) else tc
    r["tool_names"] = names
    return r
