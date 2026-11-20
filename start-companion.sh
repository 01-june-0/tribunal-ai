#!/usr/bin/env sh
# AI DEV DIRECTOR companion launcher for macOS / Linux (the Windows launcher is start-companion.ps1).
# Starts the console in the background and records its PID in data/companion.pid.
# Port: companion.json, overridden by companion.local.json (e.g. {"port": 8181} when 8081 is taken).
set -e
cd "$(dirname "$0")"
mkdir -p data
if [ -f data/companion.pid ] && kill -0 "$(cat data/companion.pid)" 2>/dev/null; then
  echo "AI DEV companion already running (PID $(cat data/companion.pid))"
  exit 0
fi
if [ -n "$PYTHON" ]; then PY="$PYTHON"; elif [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
PORT="$("$PY" -m core.companion_config)"
nohup "$PY" companion_server.py >data/companion.log 2>data/companion.err &
PID=$!
echo "$PID" >data/companion.pid
# The server exits at once when the port is taken; report that instead of a success line.
i=0
while [ "$i" -lt 20 ]; do
  if ! kill -0 "$PID" 2>/dev/null; then
    rm -f data/companion.pid
    echo "AI DEV companion failed to start on port $PORT:" >&2
    tail -n 3 data/companion.err >&2
    echo "If the port is in use, put {\"port\": 8181} in companion.local.json." >&2
    exit 1
  fi
  if grep -q "http://127.0.0.1:$PORT" data/companion.log 2>/dev/null; then
    echo "AI DEV companion: http://127.0.0.1:$PORT  (PID $PID)"
    exit 0
  fi
  i=$((i + 1))
  sleep 0.5
done
echo "AI DEV companion started (PID $PID) but has not reported ready yet; see data/companion.log" >&2
exit 1
