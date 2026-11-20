#!/usr/bin/env sh
# TRIBUNAL AI companion launcher for macOS / Linux (the Windows launcher is start-companion.ps1).
# Starts the console in the background and records its PID in data/companion.pid.
# Port: 8081 by default, or the next free port when that one is busy. A port set in companion.local.json
# ({"port": 8181}) or TRIBUNAL_PORT is used as given and never moved. The address printed below is the real one.
set -e
cd "$(dirname "$0")"
mkdir -p data
if [ -n "$PYTHON" ]; then PY="$PYTHON"; elif [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
if [ -f data/companion.pid ] && kill -0 "$(cat data/companion.pid)" 2>/dev/null; then
  echo "Tribunal AI companion already running: http://127.0.0.1:$("$PY" -m core.companion_config)  (PID $(cat data/companion.pid))"
  exit 0
fi
: >data/companion.log                    # emptied here, so the loop below never reads a previous run's address
nohup "$PY" companion_server.py >>data/companion.log 2>data/companion.err &
PID=$!
echo "$PID" >data/companion.pid
# The server prints its address once it listens; it exits at once when it cannot start or is already running.
i=0
while [ "$i" -lt 40 ]; do
  URL="$(sed -n 's/.*Tribunal AI console \(http:\/\/127\.0\.0\.1:[0-9]*\).*/\1/p' data/companion.log 2>/dev/null | head -n 1)"
  if [ -n "$URL" ]; then
    NOTE="$(grep 'in use by another program' data/companion.log 2>/dev/null | head -n 1 || true)"
    [ -n "$NOTE" ] && echo "$NOTE"
    echo "Tribunal AI companion: $URL  (PID $PID)"
    exit 0
  fi
  if ! kill -0 "$PID" 2>/dev/null; then
    [ "$(cat data/companion.pid 2>/dev/null)" = "$PID" ] && rm -f data/companion.pid   # only our own record
    if grep -q "already running" data/companion.log 2>/dev/null; then
      grep "already running" data/companion.log | head -n 1
      exit 0
    fi
    echo "Tribunal AI companion failed to start:" >&2
    tail -n 3 data/companion.err >&2
    exit 1
  fi
  i=$((i + 1))
  sleep 0.5
done
echo "Tribunal AI companion started (PID $PID) but has not reported ready yet; see data/companion.log" >&2
exit 1
