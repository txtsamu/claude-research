#!/usr/bin/env bash
# Start the mock LLM (127.0.0.1:18081) and the isolated Evonic copy (127.0.0.1:18080) in the background.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN="$DIR/evonic-run"
PORT="${EVONIC_PORT:-18080}"
MOCK_PORT="${MOCK_PORT:-18081}"
mkdir -p "$DIR/logs"

if ! curl -fsS "http://127.0.0.1:$MOCK_PORT/health" >/dev/null 2>&1; then
  nohup "$DIR/venv/bin/python" -I "$DIR/mock_llm.py" --port "$MOCK_PORT" --log "$DIR/logs/mock_requests.jsonl" \
      >"$DIR/logs/mock.out" 2>&1 &
  echo $! > "$DIR/logs/mock.pid"
fi

export HOME="$DIR/home"        # never touch the real home / ~/.config
cd "$RUN"
./evonic start -d </dev/null   # daemon: app.py in its own session, PID in evonic-run/run/evonic.pid, log run/server.log

for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && curl -fsS "http://127.0.0.1:$MOCK_PORT/health" >/dev/null 2>&1; then
    echo "ready: evonic http://127.0.0.1:$PORT  mock http://127.0.0.1:$MOCK_PORT/v1"; exit 0
  fi
  sleep 1
done
echo "evonic did not become healthy; see $RUN/run/server.log" >&2; exit 1
