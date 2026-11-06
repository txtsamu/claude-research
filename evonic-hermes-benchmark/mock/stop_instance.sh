#!/usr/bin/env bash
# Stop Evonic (via its own CLI) and the mock LLM.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export HOME="$DIR/home"
( cd "$DIR/evonic-run" && ./evonic stop </dev/null ) || true
if [ -f "$DIR/logs/mock.pid" ]; then kill "$(cat "$DIR/logs/mock.pid")" 2>/dev/null || true; rm -f "$DIR/logs/mock.pid"; fi
