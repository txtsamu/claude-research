#!/usr/bin/env python3
"""Benchmark driver for Evonic: send one prompt to the benchmark agent over the HTTP API
and return timing / tool / token metrics as a dict (or JSON file).

    python evonic_driver.py --prompt-file p.txt --workdir /tmp/w1 --timeout 600 --out result.json

    from evonic_driver import run_task
    r = run_task("Create a file hello.txt with content hi", "/tmp/w1", 600)

How it works (see README.md for the full write-up)
  * auth:  Evonic uses a Flask session cookie (POST /login, form field `password`) plus a
           double-submit CSRF token (cookie `csrf_token` echoed in header X-CSRF-Token on every
           non-GET).  There are no API keys / bearer tokens for /api/agents/*.
  * rate limit: POST /api/agents/<id>/chat is the "chat" tier = 10 req/min, not configurable.
           On HTTP 429 {"error":"rate_limit_exceeded","retry_after":N} we sleep and retry
           (the wait counts against the task timeout but NOT against `wall_seconds`' agent time;
           it is reported separately as `rate_limit_wait_seconds`).
  * isolation: every task uses a brand-new `user_id` => brand-new chat session (own history,
           own execution backend).  The agent's `workspace` (cwd of bash, root of the file tools)
           is re-pointed to `workdir` with PUT /api/agents/<id> {"workspace": workdir} before the
           chat starts.  One agent, tasks strictly sequential.
  * metrics: tool calls from the chat response `tool_trace`/`timeline`; LLM requests + tokens from
           the per-session byte-exact LLM trace written by Evonic (EVONIC_SESSION_ARCHIVE=1 ->
           <root>/agents/<agent>/llm_traces/<session>.jsonl, field `usage` copied from the
           provider's response).  Optional cross-check against the mock server's own request log.
"""
import argparse
import json
import os
import sys
import time
import uuid

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
IDLE_WAIT_S = 300
DEFAULTS = {
    "base_url": os.environ.get("EVONIC_URL", "http://127.0.0.1:18080"),
    "password": os.environ.get("EVONIC_PASSWORD", "<THROWAWAY_LOCAL_PASSWORD>"),
    "agent_id": os.environ.get("EVONIC_AGENT_ID", "bench"),
    "root": os.environ.get("EVONIC_ROOT", os.path.join(HERE, "evonic-run")),
    "mock_url": os.environ.get("EVONIC_MOCK_URL", "http://127.0.0.1:18081"),  # "" disables cross-check
}


class _Api:
    """Thin authenticated client: session cookie + CSRF header + 429 backoff."""

    def __init__(self, base_url, password):
        self.base = base_url.rstrip("/")
        self.password = password
        self.s = requests.Session()
        self.rate_wait = 0.0
        self.logged_in = False

    def login(self):
        self.s = requests.Session()
        self.s.get(self.base + "/login", timeout=15)  # primes csrf_token cookie
        r = self.s.post(self.base + "/login", data={"password": self.password, "next": "/"},
                        allow_redirects=False, timeout=15)
        if r.status_code != 302 or "session" not in self.s.cookies:
            raise RuntimeError(f"login failed: HTTP {r.status_code} {r.text[:200]!r}")
        self.logged_in = True

    def _csrf(self):
        tok = ""
        for c in self.s.cookies:  # may hold >1 csrf_token cookie (pre/post login); take the newest
            if c.name == "csrf_token":
                tok = c.value
        return tok

    def request(self, method, path, deadline=None, **kw):
        """deadline: [absolute time.time()] mutable one-item list. The read timeout of each attempt is
        derived from it, and every 429 back-off extends it (rate-limit sleeps are not agent time)."""
        if not self.logged_in:
            self.login()
        relogged = False
        while True:
            headers = dict(kw.get("headers") or {})
            if method != "GET":
                headers["X-CSRF-Token"] = self._csrf()
            kw2 = dict(kw, headers=headers)
            if deadline is not None:
                kw2["timeout"] = (10, max(1.0, deadline[0] - time.time()))
            r = self.s.request(method, self.base + path, **kw2)
            if r.status_code == 401 and not relogged:
                relogged = True
                self.login()
                continue
            if r.status_code == 429:
                try:
                    wait = float(r.json().get("retry_after") or r.headers.get("Retry-After") or 5)
                except Exception:
                    wait = 5.0
                wait += 0.5
                if self.rate_wait + wait > 600:
                    return r  # caller reports the 429
                time.sleep(wait)
                self.rate_wait += wait
                if deadline is not None:
                    deadline[0] += wait
                continue
            return r


def _read_trace(root, agent_id, session_id):
    fn = session_id[len(agent_id) + 1:] if session_id.startswith(agent_id + "-") else session_id
    path = os.path.join(root, "agents", agent_id, "llm_traces", fn + ".jsonl")
    recs = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        recs.append(json.loads(line))
                    except ValueError:
                        pass
    except FileNotFoundError:
        return None, path
    except PermissionError:
        # service state is owned by the evonic user on `home`; read it through sudo
        import subprocess
        r = subprocess.run(["sudo", "-n", "cat", path], capture_output=True, text=True)
        if r.returncode:
            return None, path
        for line in r.stdout.splitlines():
            line = line.strip()
            if line:
                try:
                    recs.append(json.loads(line))
                except ValueError:
                    pass
    return recs, path


def _trace_metrics(recs):
    tin = tout = 0
    est = False
    names = []
    for r in recs:
        u = r.get("usage") or {}
        p, c = u.get("prompt_tokens"), u.get("completion_tokens")
        if not p and not c:
            est = True
        tin += int(p or 0)
        tout += int(c or 0)
        msg = ((((r.get("response") or {}).get("choices") or [{}])[0]).get("message")) or {}
        for tc in msg.get("tool_calls") or []:
            names.append((tc.get("function") or {}).get("name"))
    return {"turns": len(recs), "tokens_in": tin, "tokens_out": tout,
            "tokens_missing_usage": est, "trace_tool_names": names}


def _mock_snapshot(mock_url):
    if not mock_url:
        return None
    try:
        return requests.get(mock_url.rstrip("/") + "/mock/requests", timeout=5).json()["requests"]
    except Exception:
        return None


def _tool_names_from_response(data):
    tt = data.get("tool_trace") or []
    names = [t.get("tool") or t.get("name") for t in tt if isinstance(t, dict)]
    names = [n for n in names if n]
    if not names:
        names = [e.get("tool") for e in (data.get("timeline") or [])
                 if isinstance(e, dict) and e.get("type") == "tool_call" and e.get("tool")]
    return names


def run_task(prompt, workdir, timeout_s, base_url=None, password=None, agent_id=None,
             root=None, mock_url=None, _api=[None]):
    """Run one task in a fresh Evonic chat session; never raises (errors go in `error`).

    Returns dict: final_text, wall_seconds, tool_calls{count,names}, turns, tokens_in, tokens_out,
    error, plus diagnostics (session_id, user_id, workdir, tokens_source, tokens_missing_usage,
    rate_limit_wait_seconds, crosscheck).
    """
    base_url = base_url or DEFAULTS["base_url"]
    password = password or DEFAULTS["password"]
    agent_id = agent_id or DEFAULTS["agent_id"]
    root = root or DEFAULTS["root"]
    mock_url = DEFAULTS["mock_url"] if mock_url is None else mock_url
    workdir = os.path.abspath(workdir)
    os.makedirs(workdir, exist_ok=True)

    api = _api[0]
    if api is None or api.base != base_url.rstrip("/"):
        api = _api[0] = _Api(base_url, password)
    api.rate_wait = 0.0

    out = {"final_text": "", "wall_seconds": None, "tool_calls": {"count": 0, "names": []},
           "turns": 0, "tokens_in": None, "tokens_out": None, "error": None,
           "workdir": workdir, "agent_id": agent_id, "user_id": None, "session_id": None,
           "tokens_source": None, "tokens_missing_usage": None, "rate_limit_wait_seconds": 0.0,
           "timed_out": False, "pre_task_idle_wait_seconds": None, "crosscheck": None}
    t_start = time.time()
    deadline = [t_start + timeout_s]
    mock_before = _mock_snapshot(mock_url)
    try:
        # 1) make sure the agent is idle (previous timed-out task could still be unwinding)
        t_idle = time.time()
        if not _wait_idle(api, agent_id, IDLE_WAIT_S):
            raise RuntimeError(f"agent still busy after {IDLE_WAIT_S}s (previous task not finished)")
        out["pre_task_idle_wait_seconds"] = round(time.time() - t_idle, 3)
        # 2) point the agent's workspace at workdir (cwd for bash, root for file tools)
        r = api.request("PUT", f"/api/agents/{agent_id}", json={"workspace": workdir, "message_buffer_seconds": 0},
                        timeout=30)  # buffer>0 makes POST /chat return {"buffered":true} immediately (async)
        if r.status_code != 200:
            raise RuntimeError(f"set workspace: HTTP {r.status_code} {r.text[:200]}")
        # 3) fresh session = fresh user_id
        user_id = "bench-" + uuid.uuid4().hex[:12]
        out["user_id"] = user_id
        r = api.request("GET", f"/api/agents/{agent_id}/chat/session", params={"user_id": user_id}, timeout=30)
        r.raise_for_status()
        session_id = r.json()["session_id"]
        out["session_id"] = session_id

        # 4) the synchronous chat call; the clock for wall_seconds starts here
        t_chat = time.time()
        deadline[0] = t_chat + timeout_s
        try:
            r = api.request("POST", f"/api/agents/{agent_id}/chat", deadline=deadline,
                            json={"message": prompt, "user_id": user_id})
            out["wall_seconds"] = round(time.time() - t_chat - api.rate_wait, 3)
            if r.status_code == 429:
                out["error"] = "rate_limit_exceeded (gave up: retry would exceed timeout)"
            elif r.status_code != 200:
                out["error"] = f"HTTP {r.status_code}: {r.text[:300]}"
            else:
                data = r.json()
                if data.get("buffered") or data.get("injected"):
                    out["error"] = f"message was buffered/injected rather than processed: {data}"
                out["final_text"] = data.get("response") or ""
                names = _tool_names_from_response(data)
                out["tool_calls"] = {"count": len(names), "names": names}
                if data.get("error"):
                    out["error"] = "agent_error: " + (out["final_text"] or "")[:300]
        except requests.exceptions.Timeout:
            out["wall_seconds"] = round(time.time() - t_chat - api.rate_wait, 3)
            out["timed_out"] = True
            out["error"] = f"timeout after {timeout_s}s"
            try:  # ask Evonic to abort the turn so it cannot leak into the next task
                api.request("POST", f"/api/sessions/{session_id}/stop", timeout=10)
            except Exception:
                pass
            # NOTE: an LLM request already in flight cannot be cancelled; the next run_task() waits
            # (pre_task_idle_wait_seconds) until the agent is idle again.
        out["rate_limit_wait_seconds"] = round(api.rate_wait, 3)

        # 5) per-request LLM usage from Evonic's own trace of this session
        recs, tpath = _read_trace(root, agent_id, session_id)
        if recs is None and out["timed_out"]:
            out.update(turns=0, tokens_in=0, tokens_out=0,
                       tokens_source="no completed LLM call recorded (timed out while the first request was in flight; its usage is unknown)")
        elif recs is None:
            out["tokens_source"] = f"unavailable (no trace file {tpath}; was EVONIC_SESSION_ARCHIVE=1 set?)"
        else:
            m = _trace_metrics(recs)
            out.update(turns=m["turns"], tokens_in=m["tokens_in"], tokens_out=m["tokens_out"],
                       tokens_missing_usage=m["tokens_missing_usage"],
                       tokens_source="evonic llm_traces (provider usage)")
            if out["tool_calls"]["count"] == 0 and m["trace_tool_names"]:
                out["tool_calls"] = {"count": len(m["trace_tool_names"]), "names": m["trace_tool_names"]}
                out["tool_calls"]["source"] = "llm_traces (requested by model)"
    except Exception as e:  # noqa: BLE001
        out["error"] = (out["error"] + " | " if out["error"] else "") + f"{type(e).__name__}: {e}"
    if out["wall_seconds"] is None:
        out["wall_seconds"] = round(time.time() - t_start, 3)

    # 6) optional cross-check: how many requests did the (mock) provider actually receive
    after = _mock_snapshot(mock_url)
    if mock_before is not None and after is not None:
        seen = after[len(mock_before):] if len(after) >= len(mock_before) else after
        out["crosscheck"] = {"provider_requests": len(seen),
                             "provider_prompt_tokens": sum(x["usage"]["prompt_tokens"] for x in seen),
                             "provider_completion_tokens": sum(x["usage"]["completion_tokens"] for x in seen),
                             "provider_kinds": [x["kind"] for x in seen]}
    return out


def _wait_idle(api, agent_id, max_s):
    end = time.time() + max_s
    while time.time() < end:
        try:
            r = api.request("GET", f"/api/agents/{agent_id}/busy", timeout=10)
            if r.status_code == 200 and not r.json().get("busy"):
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--agent-id", default=None)
    ap.add_argument("--root", default=None, help="evonic install dir (for llm_traces)")
    ap.add_argument("--mock-url", default=None, help="'' to disable the mock cross-check")
    a = ap.parse_args(argv)
    with open(a.prompt_file, encoding="utf-8") as f:
        prompt = f.read().strip()
    res = run_task(prompt, a.workdir, a.timeout, base_url=a.base_url, agent_id=a.agent_id,
                   root=a.root, mock_url=a.mock_url)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2, ensure_ascii=False)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if not res["error"] else 1


if __name__ == "__main__":
    sys.exit(main())
