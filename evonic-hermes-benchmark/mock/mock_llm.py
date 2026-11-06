#!/usr/bin/env python3
"""Mock OpenAI-compatible LLM server for proving the Evonic benchmark plumbing.

No network, no API key, no cost.  Stdlib only.

Endpoints
  GET  /v1/models
  POST /v1/chat/completions   (non-stream and stream=true, incl. stream_options.include_usage)
  GET  /health
  GET  /mock/requests         (JSON list of every request seen, for call counting)

Scripted behaviour (decided from the LAST user message + whether a tool result
already follows it):

  1. "create/write/make a file <path> with content <text>"
       -> turn 1: tool_call write_file {file_path, content}   (or bash printf if
          the prompt mentions bash/shell/command, or write_file is not offered)
       -> turn 2 (after the tool result): final text "Done: created <path> ..."
  2. "run (the) command: <cmd>"  (or `<cmd>` in backticks after "run")
       -> turn 1: tool_call bash {script: <cmd>}; turn 2: final text.
  3. anything else -> plain text answer, no tool call.
       "what is A + B" is answered with the sum, otherwise "MOCK-ANSWER: ...".

Directive anywhere in the prompt:  [mock:delay=SECONDS]  sleeps before replying
(used for the timeout test).  Applies to the first reply for that prompt only
(the delay is skipped once a tool result follows).

Every request is appended to --log (JSONL) with timing, stream flag, message and
tool counts, the first 80 chars of the system prompt, what was answered and the
usage that was reported.  That log is the ground truth for "how many LLM
requests did the platform make", including hidden helper calls.
"""
import argparse
import json
import math
import re
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL_ID = "mock-model"
LOCK = threading.Lock()
LOG_PATH = None
SEEN = []  # in-memory copy of the log (bounded)

FILE_RE = re.compile(
    r"(?:create|write|make|save)\s+(?:a\s+|the\s+)?(?:new\s+)?(?:text\s+)?file\s+"
    r"(?:named\s+|called\s+|at\s+|path\s+)?[`'\"\u201c\u201d]?(?P<path>[\w./\-]+?)[`'\"\u201c\u201d]?[,]?\s+"
    r"(?:with|containing|that\s+contains)\s+(?:the\s+)?"
    r"(?:(?:exact\s+)?(?:content|contents|text)\s*:?\s*)?(?P<content>.+)",
    re.I | re.S,
)
CMD_RE = re.compile(r"run\s+(?:the\s+)?(?:shell\s+)?(?:command|cmd)\s*:?\s*(?P<cmd>.+)", re.I | re.S)
MATH_RE = re.compile(r"what\s+is\s+(-?\d+)\s*\+\s*(-?\d+)", re.I)
DELAY_RE = re.compile(r"\[mock:delay=(\d+(?:\.\d+)?)\]")


def est_tokens(text):
    return max(1, math.ceil(len(text) / 4)) if text else 0


def content_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


QUOTES = "\"'`\u201c\u201d\u201e\u2018\u2019"  # Evonic rewrites " and ' to curly quotes in user text


def strip_quotes(s):
    s = s.strip().rstrip(".").strip()
    if len(s) >= 2 and s[0] in QUOTES and s[-1] in QUOTES:
        return s[1:-1]
    return s


def prompt_tokens_of(body):
    total = 0
    for m in body.get("messages", []):
        total += 4 + est_tokens(content_text(m.get("content")))
        for tc in m.get("tool_calls") or []:
            total += est_tokens(json.dumps(tc.get("function", {})))
    if body.get("tools"):
        total += est_tokens(json.dumps(body["tools"]))
    return total


def extract_user_prompt(text):
    """Evonic may wrap user text in a preference/metadata wrapper; keep the whole
    thing, the regexes search inside it."""
    return text


def decide(body):
    """Return dict: {text} or {tool: name, args: {...}}, plus 'delay' and 'kind'."""
    msgs = body.get("messages", [])
    tools = {t.get("function", {}).get("name") for t in body.get("tools") or []}
    last_user_idx = max((i for i, m in enumerate(msgs) if m.get("role") == "user"), default=-1)
    if last_user_idx < 0:
        return {"text": "MOCK-ANSWER: (no user message)", "kind": "plain"}
    prompt = extract_user_prompt(content_text(msgs[last_user_idx].get("content")))
    after = msgs[last_user_idx + 1:]
    tool_results = [m for m in after if m.get("role") == "tool"]
    delay = 0.0
    dm = DELAY_RE.search(prompt)
    if dm and not tool_results:
        delay = float(dm.group(1))

    # Only the agent loop sends tools; helper calls (summaries etc.) do not.
    if tool_results:
        last = content_text(tool_results[-1].get("content"))[:160].replace("\n", " ")
        return {"text": f"Done. Tool result received ({last}).", "kind": "final_after_tool",
                "delay": delay}

    fm = FILE_RE.search(prompt)
    if fm and tools:
        path = fm.group("path")
        content = strip_quotes(fm.group("content").strip().split("\n\n[")[0])
        use_bash = bool(re.search(r"\b(bash|shell|command)\b", prompt, re.I)) or "write_file" not in tools
        if use_bash and "bash" in tools:
            script = f"printf '%s' {json.dumps(content)} > {json.dumps(path)}"
            return {"tool": "bash", "args": {"script": script}, "delay": delay, "kind": "tool_bash"}
        if "write_file" in tools:
            return {"tool": "write_file", "args": {"file_path": path, "content": content},
                    "delay": delay, "kind": "tool_write_file"}
    cm = CMD_RE.search(prompt)
    if cm and "bash" in tools:
        cmd = cm.group("cmd").strip().split("\n")[0]
        cmd = strip_quotes(cmd)
        return {"tool": "bash", "args": {"script": cmd}, "delay": delay, "kind": "tool_bash"}
    mm = MATH_RE.search(prompt)
    if mm:
        return {"text": f"{int(mm.group(1)) + int(mm.group(2))}", "kind": "plain", "delay": delay}
    return {"text": "MOCK-ANSWER: no tool needed. " + prompt.strip().replace("\n", " ")[:80],
            "kind": "plain", "delay": delay}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):  # quiet
        pass

    def _json(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.rstrip("/") in ("/v1/models", "/models"):
            return self._json(200, {"object": "list", "data": [
                {"id": MODEL_ID, "object": "model", "created": 0, "owned_by": "mock"}]})
        if self.path == "/health":
            return self._json(200, {"ok": True})
        if self.path == "/mock/requests":
            with LOCK:
                return self._json(200, {"requests": list(SEEN)})
        self._json(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            body = json.loads(raw)
        except Exception:
            return self._json(400, {"error": {"message": "bad json"}})
        if not self.path.rstrip("/").endswith("/chat/completions"):
            return self._json(404, {"error": {"message": "unknown endpoint"}})

        t0 = time.time()
        d = decide(body)
        stream = bool(body.get("stream"))
        p_tok = prompt_tokens_of(body)
        if "tool" in d:
            args_json = json.dumps(d["args"])
            c_tok = est_tokens(d["tool"] + args_json)
        else:
            c_tok = est_tokens(d["text"])
        usage = {"prompt_tokens": p_tok, "completion_tokens": c_tok, "total_tokens": p_tok + c_tok}
        cid = "chatcmpl-" + uuid.uuid4().hex[:24]
        sysmsg = next((content_text(m.get("content")) for m in body.get("messages", [])
                       if m.get("role") == "system"), "")
        rec = {"ts": t0, "stream": stream, "model": body.get("model"),
               "n_messages": len(body.get("messages", [])), "n_tools": len(body.get("tools") or []),
               "tool_names": sorted({t.get("function", {}).get("name") for t in body.get("tools") or []}),
               "system_head": sysmsg[:80], "kind": d["kind"],
               "tool": d.get("tool"), "usage": usage}
        with LOCK:
            rec["seq"] = len(SEEN) + 1
            SEEN.append(rec)
            if len(SEEN) > 5000:
                del SEEN[:1000]
            if LOG_PATH:
                with open(LOG_PATH, "a") as f:
                    f.write(json.dumps(rec) + "\n")

        if d.get("delay"):
            time.sleep(d["delay"])
        try:
            if stream:
                self._stream(d, cid, usage, bool((body.get("stream_options") or {}).get("include_usage")))
            else:
                msg = {"role": "assistant", "content": None if "tool" in d else d["text"]}
                if "tool" in d:
                    msg["tool_calls"] = [{"id": "call_" + uuid.uuid4().hex[:12], "type": "function",
                                          "function": {"name": d["tool"], "arguments": json.dumps(d["args"])}}]
                self._json(200, {"id": cid, "object": "chat.completion", "created": int(t0),
                                 "model": body.get("model") or MODEL_ID,
                                 "choices": [{"index": 0, "message": msg,
                                              "finish_reason": "tool_calls" if "tool" in d else "stop"}],
                                 "usage": usage})
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _sse(self, obj):
        data = ("data: " + (obj if isinstance(obj, str) else json.dumps(obj)) + "\n\n").encode()
        self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
        self.wfile.flush()

    def _stream(self, d, cid, usage, include_usage):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        base = {"id": cid, "object": "chat.completion.chunk", "created": int(time.time()), "model": MODEL_ID}

        def chunk(delta, finish=None):
            return dict(base, choices=[{"index": 0, "delta": delta, "finish_reason": finish}])

        self._sse(chunk({"role": "assistant", "content": ""}))
        if "tool" in d:
            args_json = json.dumps(d["args"])
            half = max(1, len(args_json) // 2)
            self._sse(chunk({"tool_calls": [{"index": 0, "id": "call_" + uuid.uuid4().hex[:12],
                                             "type": "function",
                                             "function": {"name": d["tool"], "arguments": args_json[:half]}}]}))
            self._sse(chunk({"tool_calls": [{"index": 0, "function": {"arguments": args_json[half:]}}]}))
            self._sse(chunk({}, "tool_calls"))
        else:
            words = re.findall(r"\S+\s*", d["text"]) or [""]
            for w in words:
                self._sse(chunk({"content": w}))
            self._sse(chunk({}, "stop"))
        if include_usage:
            self._sse(dict(base, choices=[], usage=usage))
        self._sse("[DONE]")
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()


def main():
    global LOG_PATH
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=18081)
    ap.add_argument("--log", default="mock_requests.jsonl")
    a = ap.parse_args()
    LOG_PATH = a.log
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.daemon_threads = True
    print(f"mock LLM on http://{a.host}:{a.port}/v1 (log: {a.log})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
